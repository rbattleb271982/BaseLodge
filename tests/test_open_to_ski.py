from datetime import date, timedelta
from html import unescape

import pytest

import app as app_module
from app import app
from models import db, User, UserAvailability
from services.open_dates import replace_current_availability
from services.open_to_ski import (
    MAX_DISPLAY_RANGES,
    MAX_SELECTED_DAYS,
    OpenToSkiSelectionError,
    build_open_to_ski_page_model,
    group_open_to_ski_dates,
)
from tests.conftest import _login, _make_user, form_post


def _iso(value):
    return value.isoformat()


def _future(days):
    return date.today() + timedelta(days=days)


def _make_owner(label, legacy_dates=None):
    owner = _make_user(label, open_dates=list(legacy_dates or []))
    owner.first_name = "Alex"
    owner.last_name = "PrivateSurname"
    owner.home_state = "PrivateLocation"
    owner.pass_type = "PrivatePass"
    return owner


def test_open_to_ski_requires_authentication(client):
    response = client.get("/open-to-ski")

    assert response.status_code == 302
    assert "/auth" in response.headers["Location"]


def test_open_to_ski_analytics_requires_authentication(client):
    response = client.post("/api/open-to-ski/analytics", json={
        "event": "availability_share_opened",
        "properties": {},
    })

    assert response.status_code in {302, 403}


def test_open_to_ski_analytics_accepts_only_anonymous_allowlisted_payload(
    client,
    monkeypatch,
):
    with app.app_context():
        owner = _make_owner("ots-analytics")
        db.session.commit()
        owner_id = owner.id
    tracked = []
    monkeypatch.setattr(
        app_module.ph_analytics,
        "track",
        lambda user_id, event, properties: tracked.append(
            (user_id, event, properties)
        ),
    )
    _login(client, owner_id)
    client.get("/open-to-ski")
    with client.session_transaction() as session:
        csrf_token = session["_csrf_token"]

    response = client.post(
        "/api/open-to-ski/analytics",
        json={
            "event": "availability_share_succeeded",
            "properties": {"format": "png", "delivery": "download"},
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 204
    assert tracked == [
        (
            None,
            "availability_share_succeeded",
            {"format": "png", "delivery": "download"},
        )
    ]


def test_open_to_ski_analytics_rejects_private_or_extra_properties(client):
    with app.app_context():
        owner = _make_owner("ots-analytics-private")
        db.session.commit()
        owner_id = owner.id
    _login(client, owner_id)
    client.get("/open-to-ski")
    with client.session_transaction() as session:
        csrf_token = session["_csrf_token"]

    response = client.post(
        "/api/open-to-ski/analytics",
        json={
            "event": "availability_share_failed",
            "properties": {
                "format": "png",
                "delivery": "share",
                "error_code": "share_failed",
                "selected_dates": ["2027-01-03"],
            },
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 400


def test_open_to_ski_uses_only_current_owner_and_ignores_source_override(client):
    owner_day = _future(5)
    other_day = _future(9)
    with app.app_context():
        owner = _make_owner("ots-owner", [_iso(owner_day)])
        other = _make_owner("ots-other", [_iso(other_day)])
        db.session.commit()
        owner_id = owner.id
        other_id = other.id

    _login(client, owner_id)
    response = client.get(f"/open-to-ski?user_id={other_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert _iso(owner_day) in html
    assert _iso(other_day) not in html


def test_open_to_ski_passes_only_explicit_allowlisted_model(client, monkeypatch):
    selected_day = _future(5)
    with app.app_context():
        owner = _make_owner("ots-allowlist", [_iso(selected_day)])
        db.session.commit()
        owner_id = owner.id

    captured = {}

    def fake_render(template_name, **context):
        captured["template_name"] = template_name
        captured["context"] = context
        return "captured"

    monkeypatch.setattr(app_module, "render_template", fake_render)
    _login(client, owner_id)
    response = client.get("/open-to-ski")

    assert response.status_code == 200
    assert captured["template_name"] == "open_to_ski.html"
    assert set(captured["context"]) == {"share"}
    share = captured["context"]["share"]
    assert set(share) == {
        "brand",
        "first_name",
        "eligible_dates",
        "selected_dates",
        "eligible_count",
        "ready",
        "error",
        "availability_changed",
        "max_selected_days",
        "max_display_ranges",
        "selection_notice",
        "card",
        "empty_message",
    }
    assert share["first_name"] == "Alex"
    serialized = repr(share)
    for prohibited in (
        "PrivateSurname",
        "PrivateLocation",
        "PrivatePass",
        "wishlist",
        "trip",
        "email",
        "user_id",
    ):
        assert prohibited not in serialized


def test_review_preselects_canonical_mixed_dates_and_excludes_tombstone_and_past(
    client,
):
    today = date.today()
    legacy_day = _future(5)
    normalized_day = _future(6)
    tombstoned_day = _future(7)
    with app.app_context():
        owner = _make_owner(
            "ots-canonical",
            [_iso(legacy_day), _iso(tombstoned_day), _iso(today - timedelta(days=1))],
        )
        db.session.add_all([
            UserAvailability(user_id=owner.id, date=today, is_available=True),
            UserAvailability(
                user_id=owner.id,
                date=normalized_day,
                is_available=True,
            ),
            UserAvailability(
                user_id=owner.id,
                date=tombstoned_day,
                is_available=False,
            ),
        ])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    html = client.get("/open-to-ski").get_data(as_text=True)

    for expected in (_iso(today), _iso(legacy_day), _iso(normalized_day)):
        assert f'value="{expected}" checked' in html
    assert _iso(tombstoned_day) not in html
    assert _iso(today - timedelta(days=1)) not in html


def test_confirm_allows_deselection_and_builds_ready_4_by_5_preview(client):
    first_day = _future(5)
    omitted_day = _future(6)
    with app.app_context():
        owner = _make_owner(
            "ots-confirm",
            [_iso(first_day), _iso(omitted_day)],
        )
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    assert client.get("/open-to-ski").status_code == 200
    response = form_post(
        client,
        "/open-to-ski",
        data={"selected_dates": [_iso(first_day)]},
    )
    html = unescape(response.get_data(as_text=True))

    assert response.status_code == 200
    assert "Your confirmed preview" in html
    assert 'data-export-width="1080"' in html
    assert 'data-export-height="1350"' in html
    assert 'data-aspect-ratio="4:5"' in html
    assert "Alex" in html
    assert first_day.strftime("%B %-d, %Y") in html
    assert omitted_day.strftime("%B %-d, %Y") not in html
    assert "html2canvas.min.js" in html
    assert "open-to-ski-export.js" in html
    assert "window.__USER__" not in html
    assert "analytics.js" not in html
    assert "/api/activity/heartbeat" not in html
    assert "bl-native.js" not in html
    assert "Alex is open to ski during" in html
    assert "check with me before planning" in html
    assert "static image" in html
    assert "Share image" in html
    assert "Download image" in html


def test_confirmation_rejects_stale_removed_date_and_requires_review(client):
    selected_day = _future(5)
    with app.app_context():
        owner = _make_owner("ots-stale", [_iso(selected_day)])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    assert client.get("/open-to-ski").status_code == 200

    with app.app_context():
        owner = db.session.get(User, owner_id)
        replace_current_availability(owner, [])
        db.session.commit()

    response = form_post(
        client,
        "/open-to-ski",
        data={"selected_dates": [_iso(selected_day)]},
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 409
    assert "Your availability changed" in html
    assert "Your confirmed preview" not in html
    assert _iso(selected_day) not in html


def test_confirmation_rejects_zero_selected_dates(client):
    selected_day = _future(5)
    with app.app_context():
        owner = _make_owner("ots-zero", [_iso(selected_day)])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    client.get("/open-to-ski")
    response = form_post(client, "/open-to-ski", data={})

    assert response.status_code == 400
    assert "Select at least one future date" in response.get_data(as_text=True)


def test_more_than_31_available_days_opens_but_confirmation_is_blocked(client):
    values = [_iso(_future(offset)) for offset in range(1, MAX_SELECTED_DAYS + 2)]
    with app.app_context():
        owner = _make_owner("ots-days-limit", values)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    review = client.get("/open-to-ski")
    assert review.status_code == 200
    assert "Select up to 31" in review.get_data(as_text=True)

    response = form_post(
        client,
        "/open-to-ski",
        data={"selected_dates": values},
    )
    assert response.status_code == 400
    assert "no more than 31 calendar days" in response.get_data(as_text=True)


def test_more_than_12_display_ranges_is_blocked(client):
    values = [
        _iso(_future(1 + offset * 2))
        for offset in range(MAX_DISPLAY_RANGES + 1)
    ]
    with app.app_context():
        owner = _make_owner("ots-range-limit", values)
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    review = client.get("/open-to-ski")
    assert "no more than 12 ranges" in review.get_data(as_text=True)
    response = form_post(
        client,
        "/open-to-ski",
        data={"selected_dates": values},
    )

    assert response.status_code == 400
    assert "no more than 12 ranges" in response.get_data(as_text=True)


def test_empty_availability_returns_add_dates_state(client):
    with app.app_context():
        owner = _make_owner("ots-empty")
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    response = client.get("/open-to-ski")
    html = unescape(response.get_data(as_text=True))

    assert response.status_code == 200
    assert (
        "Choose future dates you're open to ski. Then share them with friends."
        in html
    )
    assert 'href="/add-open-dates"' in html
    assert "Create preview" not in html


def test_grouping_is_chronological_deduplicated_and_preserves_gaps():
    grouped = group_open_to_ski_dates([
        "2027-01-05",
        "2027-01-03",
        "2027-01-04",
        "2027-01-05",
        "2027-01-08",
    ])

    assert grouped["selected_dates"] == [
        "2027-01-03",
        "2027-01-04",
        "2027-01-05",
        "2027-01-08",
    ]
    assert [item["label"] for item in grouped["month_groups"][0]["ranges"]] == [
        "3–5",
        "8",
    ]


def test_grouping_splits_cross_month_and_labels_cross_year_unambiguously():
    grouped = group_open_to_ski_dates([
        "2026-12-31",
        "2027-01-01",
        "2027-01-02",
    ])

    assert [group["label"] for group in grouped["month_groups"]] == [
        "DEC 2026",
        "JAN 2027",
    ]
    assert [
        item["label"]
        for group in grouped["month_groups"]
        for item in group["ranges"]
    ] == ["31", "1–2"]
    assert grouped["period_label"] == "December 2026 — January 2027"


@pytest.mark.parametrize(
    ("values", "density", "column_count"),
    [
        (["2027-01-03"], "sparse", 1),
        (
            ["2027-01-03", "2027-01-05", "2027-01-07", "2027-01-09", "2027-01-11"],
            "normal",
            1,
        ),
        (
            ["2027-01-03", "2027-02-03", "2027-03-03"],
            "compact",
            2,
        ),
        (
            [
                "2027-01-03",
                "2027-02-03",
                "2027-03-03",
                "2027-04-03",
                "2027-05-03",
                "2027-06-03",
            ],
            "dense",
            2,
        ),
    ],
)
def test_density_tiers_are_deterministic(values, density, column_count):
    grouped = group_open_to_ski_dates(values)

    assert grouped["density"] == density
    assert grouped["column_count"] == column_count
    assert sum(len(column) for column in grouped["columns"]) == grouped["month_count"]


def test_grouping_never_silently_truncates_maximum_allowed_days():
    values = [
        _iso(date(2027, 1, 1) + timedelta(days=offset))
        for offset in range(MAX_SELECTED_DAYS)
    ]
    grouped = group_open_to_ski_dates(values)

    assert grouped["selected_count"] == MAX_SELECTED_DAYS
    assert grouped["selected_dates"] == values


def test_grouping_rejects_limits_instead_of_truncating():
    too_many_days = [
        _iso(date(2027, 1, 1) + timedelta(days=offset))
        for offset in range(MAX_SELECTED_DAYS + 1)
    ]
    too_many_ranges = [
        _iso(date(2027, 1, 1) + timedelta(days=offset * 2))
        for offset in range(MAX_DISPLAY_RANGES + 1)
    ]

    with pytest.raises(OpenToSkiSelectionError, match="31 calendar days"):
        group_open_to_ski_dates(too_many_days)
    with pytest.raises(OpenToSkiSelectionError, match="12 ranges"):
        group_open_to_ski_dates(too_many_ranges)


def test_page_model_ready_card_contains_only_allowed_card_fields():
    model = build_open_to_ski_page_model(
        first_name="Alex",
        eligible_values=["2027-01-03"],
        ready=True,
    )

    assert set(model["card"]) == {
        "brand",
        "first_name",
        "headline",
        "period_label",
        "columns",
        "density",
        "column_count",
        "selected_count",
        "range_count",
        "snapshot_label",
        "footer",
        "accessible_summary",
        "export_width",
        "export_height",
        "aspect_ratio",
    }


def test_review_session_stores_only_a_fingerprint(client):
    selected_day = _future(5)
    with app.app_context():
        owner = _make_owner("ots-session", [_iso(selected_day)])
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    client.get("/open-to-ski")
    with client.session_transaction() as session:
        fingerprint = session["open_to_ski_review_fingerprint"]

    assert fingerprint != _iso(selected_day)
    assert len(fingerprint) == 64


def test_rendered_page_does_not_include_prohibited_owner_identity(client):
    selected_day = _future(5)
    with app.app_context():
        owner = _make_owner("ots-rendered-privacy", [_iso(selected_day)])
        owner.last_name = "ForbiddenSurname"
        owner.email = "forbidden-address@example.test"
        db.session.commit()
        owner_id = owner.id

    _login(client, owner_id)
    with client.session_transaction() as session:
        session["_flashes"] = [
            ("message", "Forbidden trip and friend notification"),
        ]
    html = client.get("/open-to-ski").get_data(as_text=True)

    assert "ForbiddenSurname" not in html
    assert "forbidden-address@example.test" not in html
    assert "window.__USER__" not in html
    assert "analytics.js" not in html
    assert "/api/activity/heartbeat" not in html
    assert "bl-native.js" not in html
    assert "Forbidden trip and friend notification" not in html


def test_client_range_count_uses_timezone_independent_calendar_ordinals():
    template = app.jinja_env.get_template("open_to_ski.html")
    source, _, _ = app.jinja_env.loader.get_source(app.jinja_env, template.name)

    assert "Date.UTC(" in source
    assert "value + 'T00:00:00'" not in source


def test_privacy_isolated_template_suppresses_identity_bearing_shell_sections():
    source, _, _ = app.jinja_env.loader.get_source(
        app.jinja_env,
        "open_to_ski.html",
    )

    assert "{% block analytics_head %}" in source
    assert "{% block topbar_right %}" in source
    assert "{% block flash %}{% endblock %}" in source
    assert "{% block bottom_nav %}{% endblock %}" in source


def test_card_height_is_bound_to_its_container_width_at_all_breakpoints():
    source, _, _ = app.jinja_env.loader.get_source(
        app.jinja_env,
        "open_to_ski.html",
    )

    assert "container-type:inline-size" in source
    assert "height:125cqw" in source
    assert "@container (max-width: 400px)" in source
    assert "height:min(calc((100vw" not in source


def test_dense_single_month_keeps_all_12_ranges_in_one_bounded_group():
    values = [
        _iso(date(2027, 1, 1) + timedelta(days=offset * 2))
        for offset in range(MAX_DISPLAY_RANGES)
    ]

    grouped = group_open_to_ski_dates(values)

    assert grouped["density"] == "dense"
    assert grouped["range_count"] == MAX_DISPLAY_RANGES
    assert len(grouped["month_groups"]) == 1
    assert len(grouped["month_groups"][0]["ranges"]) == MAX_DISPLAY_RANGES


def test_compact_single_month_keeps_all_eight_ranges_in_one_bounded_group():
    values = [
        _iso(date(2027, 1, 1) + timedelta(days=offset * 2))
        for offset in range(8)
    ]

    grouped = group_open_to_ski_dates(values)

    assert grouped["density"] == "compact"
    assert grouped["range_count"] == 8
    assert len(grouped["month_groups"]) == 1
    assert len(grouped["month_groups"][0]["ranges"]) == 8


def test_normal_two_month_selection_keeps_all_five_ranges():
    values = [
        "2027-01-01",
        "2027-01-03",
        "2027-01-05",
        "2027-02-01",
        "2027-02-03",
    ]

    grouped = group_open_to_ski_dates(values)

    assert grouped["density"] == "normal"
    assert grouped["range_count"] == 5
    assert sum(
        len(group["ranges"]) for group in grouped["month_groups"]
    ) == 5