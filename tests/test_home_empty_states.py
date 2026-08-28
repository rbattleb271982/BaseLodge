from datetime import datetime
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

from app import app
from conftest import _login, _make_user
from models import DismissedInsightCard, Friend, db


HOME_TEMPLATE = Path("templates/home.html").read_text()
POPULATED_HEADER_TEMPLATE = Path("templates/partials/home/_header.html").read_text()
EMPTY_HEADER_TEMPLATE = Path("templates/partials/home/_header_empty.html").read_text()
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
        id=1,
        user_id=friend_id,
        mountain="Test Peak",
        resort=SimpleNamespace(name="Test Peak"),
        trip_status="planning",
        created_at=now,
        updated_at=now,
    )


def _get_home(client, user_id, *, feed=None, friend_trips=None, availability=None):
    _login(client, user_id)
    feed = feed or []
    friend_trips = friend_trips or []
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=availability or [],
    ), patch(
        "services.ideas_engine.build_destination_feed",
        return_value=(feed, {}, friend_trips),
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ):
        return client.get("/home").get_data(as_text=True)


def _setup_viewer_and_friend():
    viewer = _make_user("viewer")
    friend = _make_user("friend")
    _connect(viewer, friend)
    db.session.commit()
    return viewer.id, friend.id


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
    assert html.index('id="fp-card-title"') < html.index('id="section-happening"')
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


def test_home_header_variants_use_compact_identity_and_preserve_stat_contracts():
    for header_template in (POPULATED_HEADER_TEMPLATE, EMPTY_HEADER_TEMPLATE):
        assert 'class="hc-identity-line"' in header_template
        assert header_template.count("url_for('edit_profile')") == 2
        assert "url_for('select_pass')" in header_template
        assert "hc-identity-separator" in header_template

        assert "stat_trips_url" in header_template
        assert "stat_mountains_url" in header_template
        assert "stat_wishlist_url" in header_template
        assert "hc-stat-tile--link" in header_template


def test_home_header_variants_include_editable_gear_summary_and_pass_summary():
    for header_template in (POPULATED_HEADER_TEMPLATE, EMPTY_HEADER_TEMPLATE):
        assert "partials/home/_section_friend_passes.html" in header_template
        assert "partials/home/_gear_summary.html" in header_template
        assert "Boots:" not in header_template
        assert "Bindings:" not in header_template


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