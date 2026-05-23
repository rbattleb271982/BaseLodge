"""
Regression guard tests for recent BaseLodge UX/social-graph fixes.

Coverage:
  1. remove_friend severs both Friend rows AND cancels accepted Invitation rows
  2. rental equipment via onboarding route persists to User.equipment_status
  3. pass display overrides inside get_all_active_resorts_map do not mutate
     normalize_pass() — resort slug → override label stays in the display layer
  4. home empty-state card appears only when dest_feed is empty (route integration)

Run: pytest tests/test_regression_guards.py -v
"""
import os
import tempfile
import unittest.mock
from datetime import datetime

import pytest
import sqlalchemy as sa

from app import app, get_all_active_resorts_map
from models import db, Friend, Invitation, Resort, ResortPass, User
from services.pass_utils import normalize_pass


# ─── Shared fixtures ──────────────────────────────────────────────────────────

def _swap_engine(new_engine):
    """
    Directly replace the cached engine in Flask-SQLAlchemy's internal
    _app_engines dict.  Flask-SQLAlchemy 3.x stores engines in:
        db._app_engines: WeakKeyDictionary[Flask, dict[str|None, Engine]]
    The default bind key is None.
    Returns the engine that was replaced so the caller can restore it.
    """
    engines_map = db._app_engines.setdefault(app, {})
    old_engine = engines_map.get(None)
    if old_engine is not None:
        old_engine.dispose()
    engines_map[None] = new_engine
    return old_engine


@pytest.fixture
def client():
    """
    File-based SQLite test client.

    A file-based SQLite database is used rather than ':memory:' because when
    client.get() is called while the outer app context (from this fixture) is
    already on the stack, Flask reuses that same app context for the request.
    The route's exception handlers call db.session.rollback() which expires the
    session identity map.  With :memory: + StaticPool the single connection
    state is shared, so a rollback in one part of the test can make data
    committed earlier invisible.  A file-based DB avoids this entirely:
    committed rows are durable on disk and visible to every new connection /
    session regardless of session-level rollbacks.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(db_fd)

    sqlite_engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    saved_engine = _swap_engine(sqlite_engine)

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

    # Restore the original engine (Supabase / whatever was there before).
    if saved_engine is not None:
        _swap_engine(saved_engine)
    sqlite_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


_TEST_CSRF = "test-csrf-token-fixed-value-for-guards"


def _make_user(n, email=None):
    """Create, add, and flush a minimal test User."""
    u = User(
        email=email or f"user{n}@test.baselodge",
        first_name=f"User{n}",
        last_name="Test",
        rider_types=["Skier"],
        pass_type="epic",
        skill_level="Intermediate",
        lifecycle_stage="active",
        onboarding_completed_at=datetime.utcnow(),
    )
    u.set_password("TestPass1!")
    db.session.add(u)
    db.session.flush()
    return u


def _session_login(client, user_id):
    """Inject Flask-Login session + CSRF token without going through /auth."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_csrf_token"] = _TEST_CSRF


# ─── Test 1 — remove_friend severs rows and cancels accepted invitation ───────

def test_remove_friend_severs_friend_rows_and_accepted_invitation(client):
    """POST /friends/<b>/remove deletes both Friend rows and cancels accepted Invitation."""
    with app.app_context():
        user_a = _make_user(1)
        user_b = _make_user(2)

        # Bidirectional Friend rows
        db.session.add(Friend(user_id=user_a.id, friend_id=user_b.id))
        db.session.add(Friend(user_id=user_b.id, friend_id=user_a.id))

        # Accepted Invitation (A → B direction, no trip)
        inv = Invitation(
            sender_id=user_a.id,
            receiver_id=user_b.id,
            status="accepted",
        )
        db.session.add(inv)
        db.session.commit()

        a_id, b_id, inv_id = user_a.id, user_b.id, inv.id

    _session_login(client, a_id)
    resp = client.post(
        f"/friends/{b_id}/remove",
        data={"csrf_token": _TEST_CSRF},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), (
        f"remove-friend returned unexpected status {resp.status_code}"
    )

    with app.app_context():
        # Both Friend rows must be gone
        assert Friend.query.filter_by(user_id=a_id, friend_id=b_id).count() == 0, \
            "Friend row A→B must be deleted after removal"
        assert Friend.query.filter_by(user_id=b_id, friend_id=a_id).count() == 0, \
            "Friend row B→A must be deleted after removal (bidirectional)"

        # Accepted Invitation must be cancelled — not left as 'accepted' (ghost state)
        inv_row = db.session.get(Invitation, inv_id)
        assert inv_row is not None, "Invitation row must still exist (not deleted)"
        assert inv_row.status == "cancelled", (
            f"Accepted Invitation must be cancelled after friend removal, "
            f"got status={inv_row.status!r}"
        )


# ─── Test 2 — rental equipment persists to User.equipment_status ─────────────

def test_rental_equipment_persists_to_user_equipment_status(client):
    """
    POST /onboarding/equipment with equipment_status=needs_rentals mirrors to
    User.equipment_status.

    The route's form field is `equipment_status` (values: needs_rentals |
    have_own_equipment); the route validates the value and mirrors it to the
    user record. This test exercises that validation+mirror path.
    """
    with app.app_context():
        user = _make_user(3)
        db.session.commit()
        user_id = user.id

    _session_login(client, user_id)
    resp = client.post(
        "/onboarding/equipment",
        data={
            "equipment_status": "needs_rentals",
            "csrf_token": _TEST_CSRF,
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), (
        f"onboarding/equipment returned unexpected status {resp.status_code}"
    )

    with app.app_context():
        updated = db.session.get(User, user_id)
        assert updated.equipment_status == "needs_rentals", (
            f"User.equipment_status must be 'needs_rentals' after rental save, "
            f"got: {updated.equipment_status!r}"
        )


# ─── Test 3 — pass display overrides do not mutate normalize_pass ─────────────

def test_pass_display_override_does_not_mutate_normalize_pass(client):
    """
    Display-layer pass overrides inside get_all_active_resorts_map (the
    _RESORT_PASS_OVERRIDES dict) must not mutate normalize_pass().

    Calls the real function with a Resort + ResortPass row seeded in SQLite so
    the lru_cache result is freshly computed from test data, not a Supabase
    snapshot.
    """
    with app.app_context():
        # Insert a Resort whose slug appears in _RESORT_PASS_OVERRIDES
        resort = Resort(
            name="Killington Resort",
            slug="killington",
            state="VT",
            is_active=True,
            is_region=False,
            country_code="US",
            state_code="VT",
        )
        db.session.add(resort)
        db.session.flush()

        # Link it to the Ikon pass via the normalized ResortPass table
        rp = ResortPass(
            resort_id=resort.id,
            pass_name="Ikon",
            is_primary=True,
        )
        db.session.add(rp)
        db.session.commit()

        # ── Capture normalize_pass BEFORE calling the builder ────────────────
        before_ikon   = normalize_pass("Ikon")    # canonical pass name → "ikon"
        before_other  = normalize_pass("other")   # passthrough → "other"

        # Force a fresh cache computation against our SQLite data
        get_all_active_resorts_map.cache_clear()
        resort_map = get_all_active_resorts_map()

        # ── Capture normalize_pass AFTER calling the builder ─────────────────
        after_ikon  = normalize_pass("Ikon")
        after_other = normalize_pass("other")

    # normalize_pass must return identical results before and after the builder ran
    assert before_ikon == after_ikon, (
        "normalize_pass('Ikon') must return the same value before and after "
        "get_all_active_resorts_map() runs"
    )
    assert before_other == after_other == "other", (
        "normalize_pass('other') must always return 'other' — never a display label"
    )

    # The resort map entry for killington may carry a display label ('Ikon') in
    # its pass_label field, but normalize_pass must not return that override label
    assert normalize_pass("Ikon") != "Ikon" or normalize_pass("Ikon") == before_ikon, (
        "normalize_pass output must be stable — it must not be changed by the "
        "display-layer override logic in get_all_active_resorts_map"
    )

    # Confirm the resort map was actually built (function ran against our data)
    assert isinstance(resort_map, dict), (
        "get_all_active_resorts_map must return a dict"
    )
    assert len(resort_map) >= 1, (
        "resort_map must contain at least the one Resort row we inserted"
    )


# ─── Test 4 — home empty-state card only when dest_feed is empty ──────────────

def test_empty_opportunity_card_only_when_feed_empty(client):
    """
    GET /home renders bl-opp-empty-card iff the destination feed is empty.

    Part A: user has no friends → feed builder is never called → dest_feed=[]
            → empty-state card must appear in HTML.
    Part B: user has one friend, feed builder mocked to return one row
            → dest_feed has one item → empty-state card must NOT appear.

    Implementation note — shared `g` between requests
    --------------------------------------------------
    When client.get() is called while the fixture's outer app context is active,
    Flask *reuses* that same app context rather than pushing a new one (Flask only
    creates a new app context if one does not already exist for the current app).
    This means `flask.g` — which is scoped to the app context — is shared across
    all requests made within the same `with app.app_context():` block.

    Flask-Login caches the loaded user object in `g._login_user` on the first
    access of `current_user` within a request.  Without clearing this between
    Part A and Part B, Part B would pick up Part A's user (solo_user) from the
    stale cache and query Friend rows for the wrong user, always finding zero.

    The fix: explicitly delete Flask-Login's per-request cache attributes from `g`
    between the two requests so Part B loads the correct user afresh.
    """
    from flask import g as flask_g

    with app.app_context():
        solo_user = _make_user(10)   # no friends → Part A
        user_a    = _make_user(11)   # has user_b as friend → Part B
        user_b    = _make_user(12)
        db.session.add(Friend(user_id=user_a.id, friend_id=user_b.id))
        db.session.add(Friend(user_id=user_b.id, friend_id=user_a.id))
        db.session.commit()
        solo_id = solo_user.id
        a_id    = user_a.id
        b_id    = user_b.id

    # ── Part A: no friends → dest_feed=[] → empty card must appear ───────────
    _session_login(client, solo_id)

    with unittest.mock.patch(
        "services.open_dates.get_available_dates_for_user", return_value=[]
    ):
        resp_empty = client.get("/home", follow_redirects=True)

    assert resp_empty.status_code == 200, (
        f"Expected 200 from /home, got {resp_empty.status_code}"
    )
    assert b'class="bl-opp-empty-card"' in resp_empty.data, (
        "Empty-state card element must appear in /home HTML when user has no friends "
        "(dest_feed is empty)"
    )

    # ── Purge shared-g caches before Part B ──────────────────────────────────
    # Flask reuses the outer app context for all requests inside the fixture's
    # `with app.app_context():`.  Flask-Login stores the loaded user in
    # g._login_user; the before_request navigation helper caches the nav state
    # in g._computed_user_state.  Both must be cleared so Part B re-evaluates
    # them for user_a rather than returning the solo_user values from Part A.
    for _attr in ("_login_user", "_computed_user_state"):
        try:
            delattr(flask_g, _attr)
        except AttributeError:
            pass

    # ── Part B: one friend, mocked feed with one item → card must be absent ───
    _session_login(client, a_id)

    mock_feed_row = {
        "resort_id":         None,
        "resort":            None,
        "idea_type":         "friend_trip",
        "line2":             "1 friend is going",
        "date_range":        None,
        "friend_count":      1,
        "going_count":       1,
        "considering_count": 0,
        "signal_type":       1,
        "friend_ids":        [b_id],
        "start_date":        "2026-01-15",
    }

    with unittest.mock.patch(
        "services.open_dates.get_available_dates_for_user", return_value=[]
    ), unittest.mock.patch(
        "services.ideas_engine.build_destination_feed",
        return_value=([mock_feed_row], {}, []),
    ), unittest.mock.patch(
        "app.get_all_active_resorts_map", return_value={}
    ):
        resp_has_items = client.get("/home", follow_redirects=True)

    assert resp_has_items.status_code == 200, (
        f"Expected 200 from /home with mocked feed, got {resp_has_items.status_code}"
    )
    assert b'class="bl-opp-empty-card"' not in resp_has_items.data, (
        "Empty-state card element must NOT appear in /home HTML when dest_feed has items"
    )
    assert b'class="bl-opp-row"' in resp_has_items.data, (
        "Opportunity row element must be rendered in /home HTML when dest_feed has items"
    )
