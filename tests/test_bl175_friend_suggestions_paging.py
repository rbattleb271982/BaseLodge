"""Focused BL-175 bounded Suggested Friends tests."""
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from sqlalchemy import event
from app import app
from models import FriendSuggestion, db
from services.friend_suggestions_paging import (
    SUGGESTIONS_PAGE_SIZE, FriendSuggestionsCursorError,
    count_active_suggestions, load_suggestions_page,
)
from tests.conftest import _login, _make_user

FRIENDS = Path("templates/friends.html").read_text()

def _suggest(recipient, suggested, suggester, *, created=None, expired=False, dismissed=False):
    row = FriendSuggestion(
        recipient_id=recipient.id, suggested_user_id=suggested.id,
        suggester_id=suggester.id,
        created_at=created or datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(days=-1 if expired else 30),
        dismissed_at=datetime.utcnow() if dismissed else None,
    )
    db.session.add(row)
    db.session.flush()
    return row

@pytest.mark.parametrize("count", [0, 1, SUGGESTIONS_PAGE_SIZE, SUGGESTIONS_PAGE_SIZE + 1, 45])
def test_count_and_pages_are_bounded(client, count):
    with app.app_context():
        viewer, suggester = _make_user(f"v-{count}"), _make_user(f"s-{count}")
        for index in range(count):
            _suggest(viewer, _make_user(f"p-{count}-{index}"), suggester,
                     created=datetime.utcnow() - timedelta(minutes=index))
        db.session.commit()
        first = load_suggestions_page(viewer.id)
        assert count_active_suggestions(viewer.id) == count
        assert len(first.rows) == min(count, SUGGESTIONS_PAGE_SIZE)
        if count > SUGGESTIONS_PAGE_SIZE:
            second = load_suggestions_page(viewer.id, first.next_cursor)
            assert not ({r["user"].id for r in first.rows} & {r["user"].id for r in second.rows})

def test_groups_before_limit_and_preserves_latest_order_and_attribution(client):
    with app.app_context():
        viewer = _make_user("group-viewer")
        suggesters = [_make_user(f"sg-{i}") for i in range(3)]
        people = [_make_user(f"person-{i}") for i in range(SUGGESTIONS_PAGE_SIZE + 1)]
        for index, person in enumerate(people):
            _suggest(viewer, person, suggesters[0],
                     created=datetime.utcnow() - timedelta(minutes=index + 10))
        _suggest(viewer, people[0], suggesters[1], created=datetime.utcnow())
        _suggest(viewer, people[0], suggesters[2], created=datetime.utcnow() - timedelta(minutes=1))
        db.session.commit()
        page = load_suggestions_page(viewer.id)
        assert len(page.rows) == SUGGESTIONS_PAGE_SIZE
        assert page.rows[0]["user"].id == people[0].id
        assert page.rows[0]["suggester_ids"] == [suggesters[0].id, suggesters[2].id]
        assert page.rows[0]["suggester_count"] == 3

def test_attribution_hydration_is_bounded_with_many_suggesters(client):
    with app.app_context():
        viewer, person = _make_user("many-v"), _make_user("many-p")
        for index in range(100):
            _suggest(
                viewer, person, _make_user(f"many-s-{index}"),
                created=datetime.utcnow() - timedelta(minutes=100 - index),
            )
        db.session.commit()
        row = load_suggestions_page(viewer.id).rows[0]
        assert len(row["suggester_ids"]) == 2
        assert row["suggester_count"] == 100

def test_expired_dismissed_and_other_recipient_are_excluded(client):
    with app.app_context():
        viewer, other, suggester = _make_user("scope-v"), _make_user("scope-o"), _make_user("scope-s")
        active, expired, dismissed, foreign = [_make_user(f"scope-{x}") for x in "aedf"]
        _suggest(viewer, active, suggester)
        _suggest(viewer, expired, suggester, expired=True)
        _suggest(viewer, dismissed, suggester, dismissed=True)
        _suggest(other, foreign, suggester)
        db.session.commit()
        assert [r["user"].id for r in load_suggestions_page(viewer.id).rows] == [active.id]

def test_cursor_is_signed_and_viewer_scoped(client):
    with app.app_context():
        viewer, other, suggester = _make_user("cursor-v"), _make_user("cursor-o"), _make_user("cursor-s")
        for index in range(SUGGESTIONS_PAGE_SIZE + 1):
            _suggest(viewer, _make_user(f"cursor-p-{index}"), suggester)
        db.session.commit()
        cursor = load_suggestions_page(viewer.id).next_cursor
        with pytest.raises(FriendSuggestionsCursorError):
            load_suggestions_page(other.id, cursor)
        position = len(cursor) // 2
        replacement = "a" if cursor[position] != "a" else "b"
        with pytest.raises(FriendSuggestionsCursorError):
            load_suggestions_page(
                viewer.id, cursor[:position] + replacement + cursor[position + 1:]
            )

def test_initial_html_has_badge_but_no_hydrated_cards(client):
    with app.app_context():
        viewer, suggested, suggester = _make_user("initial-v"), _make_user("initial-p"), _make_user("initial-s")
        _suggest(viewer, suggested, suggester)
        db.session.commit()
        viewer_id, suggested_id = viewer.id, suggested.id
    _login(client, viewer_id)
    body = client.get("/friends").get_data(as_text=True)
    assert f'id="fr-sugg-row-{suggested_id}"' not in body
    assert '>1</span>' in body
    assert "/api/friends/suggestions/page" in body

def test_fragment_endpoint_shape_and_budget_stay_bounded(client):
    with app.app_context():
        viewer, suggester = _make_user("budget-v"), _make_user("budget-s")
        for index in range(100):
            _suggest(viewer, _make_user(f"budget-{index}"), suggester)
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine
    _login(client, viewer_id)
    statements = []
    def record(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get("/api/friends/suggestions/page")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["has_more"] and payload["next_cursor"]
    assert payload["html"].count('class="fr-sugg-row"') == SUGGESTIONS_PAGE_SIZE
    assert len(statements) <= 11

def test_initial_render_budget_does_not_grow_with_suggestion_source(client):
    with app.app_context():
        viewer, suggester = _make_user("initial-budget-v"), _make_user("initial-budget-s")
        for index in range(100):
            _suggest(viewer, _make_user(f"initial-budget-{index}"), suggester)
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine
    _login(client, viewer_id)
    client.get("/friends")  # Prime the invite token and analytics path.
    statements = []
    def record(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get("/friends")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200
    assert 'class="fr-sugg-row"' not in response.get_data(as_text=True)
    assert len(statements) <= 12

def test_client_load_contract_preserves_default_tab_and_directory():
    assert "_frEnsureSuggestionsLoaded();" in FRIENDS
    assert "if (tab === 'suggested') _frEnsureSuggestionsLoaded();" in FRIENDS
    assert "event.target.closest('#fr-sugg-load-more')" in FRIENDS
    assert "existingIds.has(id)" in FRIENDS
    assert "list.appendChild(row)" in FRIENDS
    assert "if (reset && _frSuggestionsLoaded) return;" in FRIENDS
    assert "_frSuggestionsController.abort()" in FRIENDS
    assert "_frFetchDirectory(false)" in FRIENDS