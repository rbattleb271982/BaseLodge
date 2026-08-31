from datetime import datetime
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

from app import _build_home_summary, app
from conftest import _login, _make_trip, _make_user
from models import DismissedInsightCard, Friend, db


HOME_TEMPLATE = Path("templates/home.html").read_text()
POPULATED_HEADER_TEMPLATE = Path("templates/partials/home/_header.html").read_text()
EMPTY_HEADER_TEMPLATE = Path("templates/partials/home/_header_empty.html").read_text()
ACTIVITY_TEMPLATE = Path("templates/partials/home/_activity.html").read_text()
HAPPENING_TEMPLATE = Path("templates/partials/home/_section_happening.html").read_text()
OPPORTUNITIES_TEMPLATE = Path("templates/partials/home/_section_opportunities.html").read_text()
PILLS_TEMPLATE = Path("templates/partials/home/_section_pills.html").read_text()
REQUESTS_TEMPLATE = Path("templates/partials/home/_section_requests.html").read_text()


def _fallback_tag(html):
    match = re.search(r'<div id="home-activity-fallback"[^>]*>', html)
    assert match, "Expected the combined Home activity fallback in the DOM"
    return match.group(0)


def _connect(user, friend):
    db.session.add_all([
        Friend(user_id=user.id, friend_id=friend.id),
        Friend(user_id=friend.id, friend_id=user.id),
    ])


def _feed_row(friend_id):
    return {
        "resort_id": None,
        "resort": None,
        "idea_type": "friend_trip",
        "line2": "1 friend is going",
        "date_range": None,
        "friend_count": 1,
        "going_count": 1,
        "considering_count": 0,
        "signal_type": 1,
        "friend_ids": [friend_id],
        "start_date": "2026-01-15",
    }


def _happening_trip(friend_id):
    now = datetime.utcnow()
    return SimpleNamespace(
        trip_id=1,
        attendance_user_id=friend_id,
        mountain="Test Peak",
        resort_name="Test Peak",
        attendance_status="planning",
        created_at=now,
        updated_at=now,
        activity_timestamp=now,
        card_key="happening:1",
    )


def _get_home(client, user_id, *, feed=None, friend_trips=None, availability=None):
    _login(client, user_id)
    feed = feed or []
    friend_trips = friend_trips or []

    def mocked_home_ideas(**_kwargs):
        dismissed = {
            row.card_key
            for row in DismissedInsightCard.query.filter_by(
                user_id=user_id, card_type="opportunity"
            ).all()
        }
        result = []
        for row in feed:
            candidate = dict(row)
            if candidate.get("resort_id"):
                key = f"{candidate['idea_type']}:{candidate['resort_id']}"
            else:
                friend_key = "_".join(
                    str(value)
                    for value in sorted(candidate.get("friend_ids") or [])
                )
                key = (
                    f"{candidate['idea_type']}:{friend_key}:"
                    f"{candidate.get('start_date', 'nodate')}"
                )
            if key not in dismissed:
                candidate["_card_key"] = key
                result.append(candidate)
        return result[:5]

    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=availability or [],
    ), patch(
        "services.ideas_retrieval.get_home_ideas",
        side_effect=mocked_home_ideas,
    ), patch(
        "services.happening.get_happening_candidates",
        return_value=friend_trips,
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ):
        return client.get("/home").get_data(as_text=True)


def _get_home_context(client, user_id):
    captured = {}

    def capture_render(template_name, **context):
        assert template_name == "home.html"
        captured.update(context)
        return "rendered"

    _login(client, user_id)
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=[],
    ), patch(
        "services.ideas_retrieval.get_home_ideas",
        return_value=[],
    ), patch(
        "services.happening.get_happening_candidates",
        return_value=[],
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ), patch(
        "app.get_upcoming_trip_count",
        side_effect=AssertionError("Home must reuse all_upcoming"),
    ) as trip_count, patch(
        "app.render_template",
        side_effect=capture_render,
    ):
        response = client.get("/home")

    assert response.status_code == 200
    trip_count.assert_not_called()
    return captured


def _setup_viewer_and_friend():
    viewer = _make_user("viewer")
    friend = _make_user("friend")
    _connect(viewer, friend)
    db.session.commit()
    return viewer.id, friend.id


def test_home_summary_assembler_uses_only_resolved_values():
    user = SimpleNamespace(
        id=7,
        display_rider_type="Skier + Snowboarder",
        skill_level="Advanced",
        pass_type="epic,ikon",
        visited_resorts_count=3,
        wish_list_resorts=[11, 12],
    )
    next_trip = SimpleNamespace(id=21, user_id=7)
    gear = {"skier": SimpleNamespace(id=31)}
    pass_counts = {"epic": 2, "ikon": 1, "other": 4}

    summary = _build_home_summary(
        user=user,
        all_upcoming=[next_trip],
        next_trip=next_trip,
        next_trip_friends_going_count=2,
        friend_ids=[8, 9],
        friend_pass_counts=pass_counts,
        home_rider_disciplines=["skier"],
        home_gear_by_discipline=gear,
        home_is_renting=False,
    )

    assert summary == {
        "about_you": {
            "user": user,
            "display_rider_type": "Skier + Snowboarder",
            "skill_level": "Advanced",
            "pass_type": "epic,ikon",
            "rider_disciplines": ["skier"],
            "gear_by_discipline": gear,
            "is_renting": False,
        },
        "activity": {
            "upcoming_trip_count": 1,
            "mountains_visited_count": 3,
            "wishlist_count": 2,
        },
        "friends_passes": {
            "friend_count": 2,
            "counts": pass_counts,
            "other_pass_slugs_url": (
                "indy,mountain_collective,powder_alliance,"
                "freedom,ski_california,other"
            ),
        },
        "next_trip": {
            "trip": next_trip,
            "is_owner": True,
            "friends_going_count": 2,
            "actions": [],
            "action_count": 0,
        },
    }


def test_home_summary_matches_flat_values_and_reuses_loaded_trips(client):
    with app.app_context():
        viewer = _make_user(
            "summary-owner",
            visited_resort_ids=[101, 102],
            wish_list_resorts=[201],
        )
        trip = _make_trip(viewer)
        viewer_id = viewer.id
        trip_id = trip.id
        db.session.commit()

    context = _get_home_context(client, viewer_id)
    summary = context["home_summary"]

    assert summary["about_you"]["user"].id == viewer_id
    assert summary["activity"] == {
        "upcoming_trip_count": 1,
        "mountains_visited_count": 2,
        "wishlist_count": 1,
    }
    assert summary["activity"]["upcoming_trip_count"] == context["stat_trips_total"]
    assert summary["activity"]["mountains_visited_count"] == context["stat_mountains"]
    assert summary["activity"]["wishlist_count"] == context["stat_wishlist"]
    assert summary["friends_passes"]["friend_count"] == context["friend_count"]
    assert summary["friends_passes"]["counts"] == context["friend_pass_counts"]
    assert summary["next_trip"]["trip"].id == trip_id
    assert summary["next_trip"]["is_owner"] is True


def test_home_renders_your_activity_from_shared_summary(client):
    with app.app_context():
        viewer = _make_user(
            "activity-disclosure",
            visited_resort_ids=[101, 102],
            wish_list_resorts=[201],
        )
        _make_trip(viewer)
        viewer_id = viewer.id
        db.session.commit()

    html = _get_home(client, viewer_id)

    assert html.count('id="your-activity"') == 1
    assert "1 trip · 2 mountains visited · 1 wishlist mountain" in html
    assert "Trips" in html
    assert "Mountains Visited" in html
    assert "Wishlist Mountain" in html


def test_empty_home_summary_matches_existing_zero_values(client):
    with app.app_context():
        viewer = _make_user(
            "summary-empty",
            visited_resort_ids=[],
            wish_list_resorts=[],
        )
        viewer.pass_type = "no_pass"
        viewer_id = viewer.id
        db.session.commit()

    context = _get_home_context(client, viewer_id)
    summary = context["home_summary"]

    assert summary["activity"] == {
        "upcoming_trip_count": 0,
        "mountains_visited_count": 0,
        "wishlist_count": 0,
    }
    assert summary["friends_passes"]["friend_count"] == 0
    assert summary["friends_passes"]["counts"] == {
        "epic": 0,
        "ikon": 0,
        "other": 0,
    }
    assert summary["next_trip"] is None


def test_home_hides_empty_activity_sections_and_shows_combined_fallback(client):
    with app.app_context():
        viewer_id, _friend_id = _setup_viewer_and_friend()

    html = _get_home(client, viewer_id)

    assert 'id="section-happening"' not in html
    assert 'id="section-opportunities"' not in html
    assert 'id="home-activity-fallback"' in html
    assert "hidden" not in _fallback_tag(html)
    assert "Add dates to unlock trip ideas" in html
    assert ">Ideas<" not in html


def test_home_shows_ideas_without_happening_when_only_ideas_has_content(client):
    with app.app_context():
        viewer_id, friend_id = _setup_viewer_and_friend()

    html = _get_home(client, viewer_id, feed=[_feed_row(friend_id)])

    assert 'id="section-opportunities"' in html
    assert 'id="section-happening"' not in html
    assert "hidden" in _fallback_tag(html)


def test_home_shows_happening_without_ideas_when_only_happening_has_content(client):
    with app.app_context():
        viewer_id, friend_id = _setup_viewer_and_friend()

    html = _get_home(
        client,
        viewer_id,
        friend_trips=[_happening_trip(friend_id)],
    )

    assert 'id="section-happening"' in html
    assert 'id="section-opportunities"' not in html
    assert "hidden" in _fallback_tag(html)
    assert "Test Peak" in html


def test_home_shows_both_activity_sections_when_both_have_content(client):
    with app.app_context():
        viewer_id, friend_id = _setup_viewer_and_friend()

    html = _get_home(
        client,
        viewer_id,
        feed=[_feed_row(friend_id)],
        friend_trips=[_happening_trip(friend_id)],
    )

    assert 'id="section-happening"' in html
    assert 'id="section-opportunities"' in html
    assert "hidden" in _fallback_tag(html)
    assert html.index('id="friends-passes"') < html.index('id="section-happening"')
    assert html.index('id="section-happening"') < html.index('id="section-opportunities"')
    assert html.index('id="section-opportunities"') < html.index('id="section-pills"')


def test_home_excludes_persisted_dismissals_and_returns_to_combined_fallback(client):
    with app.app_context():
        viewer_id, friend_id = _setup_viewer_and_friend()
        db.session.add(DismissedInsightCard(
            user_id=viewer_id,
            card_type="opportunity",
            card_key=f"friend_trip:{friend_id}:2026-01-15",
        ))
        db.session.commit()

    html = _get_home(client, viewer_id, feed=[_feed_row(friend_id)])

    assert 'id="section-opportunities"' not in html
    assert "hidden" not in _fallback_tag(html)


def test_home_dismissal_reconciles_final_sections_without_reload():
    assert "function syncHomeActivityEmptyState()" in HOME_TEMPLATE
    assert "section.remove();" in HOME_TEMPLATE
    assert "fallback.hidden = hasVisibleActivity;" in HOME_TEMPLATE
    assert "if (card.parentNode) card.remove();" in HOME_TEMPLATE
    assert "syncHomeActivityEmptyState();" in HOME_TEMPLATE
    assert "var homeCsrfToken = {{ csrf_token() | tojson }};" in HOME_TEMPLATE
    assert "fd.append('csrf_token', homeCsrfToken);" in HOME_TEMPLATE


def test_home_dismissal_persists_with_valid_csrf_and_survives_reload(client):
    with app.app_context():
        viewer_id, friend_id = _setup_viewer_and_friend()

    _login(client, viewer_id)
    card_key = f"friend_trip:{friend_id}:2026-01-15"
    response = client.post(
        "/dismiss-insight-card",
        data={
            "card_type": "opportunity",
            "card_key": card_key,
            "csrf_token": "test-csrf-fixed-value-baselodge-regression",
        },
    )
    assert response.status_code == 204

    with app.app_context():
        row = DismissedInsightCard.query.filter_by(
            user_id=viewer_id,
            card_type="opportunity",
            card_key=card_key,
        ).first()
    assert row is not None

    html = _get_home(client, viewer_id, feed=[_feed_row(friend_id)])
    assert 'id="section-opportunities"' not in html
    assert "hidden" not in _fallback_tag(html)


def test_home_dismissal_is_idempotent_for_happening_and_opportunity(client):
    with app.app_context():
        viewer_id, _friend_id = _setup_viewer_and_friend()

    _login(client, viewer_id)
    dismissals = [
        ("happening", "happening:123"),
        ("opportunity", "friend_trip:123:2026-01-15"),
    ]
    for card_type, card_key in dismissals:
        for _ in range(2):
            response = client.post(
                "/dismiss-insight-card",
                data={
                    "card_type": card_type,
                    "card_key": card_key,
                    "csrf_token": "test-csrf-fixed-value-baselodge-regression",
                },
            )
            assert response.status_code == 204

    with app.app_context():
        for card_type, card_key in dismissals:
            assert DismissedInsightCard.query.filter_by(
                user_id=viewer_id,
                card_type=card_type,
                card_key=card_key,
            ).count() == 1


def test_home_header_variants_use_about_you_and_activity_disclosures():
    for header_template in (POPULATED_HEADER_TEMPLATE, EMPTY_HEADER_TEMPLATE):
        assert "partials/home/_about_you_gear.html" in header_template
        assert "partials/home/_activity.html" in header_template
        assert 'class="hc-identity-line"' not in header_template
        assert "partials/home/_gear_summary.html" not in header_template
        assert "hc-stat-band" not in header_template

    assert "stat_trips_url" in ACTIVITY_TEMPLATE
    assert "stat_mountains_url" in ACTIVITY_TEMPLATE
    assert "stat_wishlist_url" in ACTIVITY_TEMPLATE


def test_home_header_variants_include_editable_gear_summary_and_pass_summary():
    for header_template in (POPULATED_HEADER_TEMPLATE, EMPTY_HEADER_TEMPLATE):
        assert "partials/home/_section_friend_passes.html" in header_template
        assert "partials/home/_about_you_gear.html" in header_template
        assert "Boots:" not in header_template
        assert "Bindings:" not in header_template


def test_home_about_you_gear_uses_stacked_single_column_layout():
    assert ".home-about-you-gear__list" in HOME_TEMPLATE
    assert ".home-about-you-gear__row" in HOME_TEMPLATE
    assert "flex-direction: column;" in HOME_TEMPLATE
    about_you_css = HOME_TEMPLATE[
        HOME_TEMPLATE.index(".home-about-you-gear__list"):
        HOME_TEMPLATE.index(".home-activity-metrics")
    ]
    assert "grid-template-columns" not in about_you_css


def test_home_activity_disclosure_uses_summary_counts_and_grammar():
    activity = {
        "upcoming_trip_count": 1,
        "mountains_visited_count": 36,
        "wishlist_count": 1,
    }
    with app.test_request_context():
        html = app.jinja_env.get_template(
            "partials/home/_activity.html"
        ).render(
            home_summary={"activity": activity},
            stat_trips_url="/trips",
            stat_mountains_url="/mountains",
            stat_wishlist_url="/wishlist",
        )

    assert '<details id="your-activity"' in html
    assert 'id="your-activity"' in html.split(">", 1)[0]
    assert "open" not in html.split(">", 1)[0]
    assert "1 trip · 36 mountains visited · 1 wishlist mountain" in html
    assert "Trips" not in html.split("</summary>", 1)[0]
    assert "Trip" in html
    assert "Mountains Visited" in html
    assert "Wishlist Mountain" in html


def test_home_activity_disclosure_renders_zero_values_cleanly():
    activity = {
        "upcoming_trip_count": 0,
        "mountains_visited_count": 0,
        "wishlist_count": 0,
    }
    with app.test_request_context():
        html = app.jinja_env.get_template(
            "partials/home/_activity.html"
        ).render(home_summary={"activity": activity})

    assert "0 trips · 0 mountains visited · 0 wishlist mountains" in html
    assert html.count('class="home-activity-metric__value">0</span>') == 3
    assert "Trips" in html
    assert "Mountains Visited" in html
    assert "Wishlist Mountains" in html


def test_home_uses_scoped_compact_summary_treatment_without_changing_hierarchy():
    assert '<div class="page-container home-page-container">' in HOME_TEMPLATE
    assert ".home-page-container > .hc-card" in HOME_TEMPLATE
    assert ".home-page-container .hc-gear-summary" in HOME_TEMPLATE
    assert ".home-page-container .hc-stat-band" in HOME_TEMPLATE
    assert ".home-page-container .fp-card" in HOME_TEMPLATE

    # The Home-specific treatment must preserve the behavior-critical section
    # IDs used by pill focus, dismissal, and fallback synchronization.
    for section_id in (
        "section-happening",
        "section-opportunities",
        "section-pills",
        "section-requests",
        "home-activity-fallback",
    ):
        section_source = {
            "section-happening": HAPPENING_TEMPLATE,
            "section-opportunities": OPPORTUNITIES_TEMPLATE,
            "section-pills": PILLS_TEMPLATE,
            "section-requests": REQUESTS_TEMPLATE,
            "home-activity-fallback": OPPORTUNITIES_TEMPLATE,
        }[section_id]
        assert f'id="{section_id}"' in section_source

    # The summary remains before primary activity, with controls afterward.
    assert HOME_TEMPLATE.index("partials/home/_header.html") < HOME_TEMPLATE.index(
        "partials/home/_section_happening.html"
    )
    assert HOME_TEMPLATE.index("partials/home/_header_empty.html") < HOME_TEMPLATE.index(
        "partials/home/_section_happening.html"
    )
    assert HOME_TEMPLATE.index("partials/home/_section_happening.html") < HOME_TEMPLATE.index(
        "partials/home/_section_opportunities.html"
    )
    assert HOME_TEMPLATE.index("partials/home/_section_opportunities.html") < HOME_TEMPLATE.index(
        "partials/home/_section_pills.html"
    )


def test_home_keeps_availability_semantics_as_a_lighter_secondary_action():
    assert 'class="bl-pill bl-pill--availability"' in PILLS_TEMPLATE
    assert 'onclick="openAvailSheet()"' in PILLS_TEMPLATE
    assert "bl-pill--availability" in HOME_TEMPLATE