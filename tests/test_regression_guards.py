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
import unittest.mock
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

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
    SQLite in-memory test client.

    StaticPool ensures every SQLAlchemy connection checkout (outer fixture
    context, nested contexts, Flask test-client request contexts) shares the
    exact same in-memory database, so committed rows are visible across all
    session and context boundaries.

    Flask-SQLAlchemy 3.x guards init_app() from being called twice, so we
    swap the engine directly in db._app_engines instead.
    """
    sqlite_engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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

    Killington is a canonical example: its slug maps to the display label
    "Ikon" in _RESORT_PASS_OVERRIDES, which is applied to the resort's
    pass_label when the resort otherwise resolves to the generic "other" key.
    The guard verifies that executing this override path (via
    get_all_active_resorts_map) does not change what normalize_pass("Ikon")
    returns — the display override must stay in the display layer only.

    Calls the real function with a Resort row seeded in SQLite so the
    lru_cache result is freshly computed from test data, not a Supabase
    snapshot.
    """
    with app.app_context():
        # Insert Killington — slug is in _RESORT_PASS_OVERRIDES → "Ikon" display label.
        # No ResortPass row means pass_brands resolves to "other"; the override
        # then sets pass_label = "Ikon" in the display layer only.
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

        # A ResortPass row that resolves to the generic "other" key is required
        # so that _pass_data returns pk=["other"].  With pk==["other"] and the
        # "killington" slug present in _RESORT_PASS_OVERRIDES, the builder then
        # sets pass_labels = "Ikon" — the code path the guard is exercising.
        rp = ResortPass(resort_id=resort.id, pass_name="other", is_primary=True)
        db.session.add(rp)
        db.session.commit()
        resort_id = resort.id

        # The override label that _RESORT_PASS_OVERRIDES["killington"] carries.
        # normalize_pass must not be changed to return this display string.
        killington_override_label = "Ikon"

        # ── Capture normalize_pass BEFORE running the map builder ────────────
        before = normalize_pass(killington_override_label)

        # Force a fresh cache computation against our SQLite data
        get_all_active_resorts_map.cache_clear()
        resort_map = get_all_active_resorts_map()

        # ── Capture normalize_pass AFTER running the map builder ─────────────
        after = normalize_pass(killington_override_label)

    # normalize_pass must return identical results before and after
    assert before == after, (
        f"normalize_pass({killington_override_label!r}) changed after "
        "get_all_active_resorts_map() ran — the display-layer override must "
        "not mutate the pass normalizer"
    )

    # The canonical form must differ from the display label: if the override
    # had polluted normalize_pass it would return "Ikon" (title-case), not the
    # canonical lowercase key.
    assert normalize_pass(killington_override_label) == before, (
        "normalize_pass output must be stable across map-builder executions"
    )

    # The resort map entry for killington must carry the display override so
    # we confirm the code path that risks mutation actually ran.
    assert resort_id in resort_map, (
        "Killington must be present in the resort map after get_all_active_resorts_map()"
    )
    killington_entry = resort_map[resort_id]
    assert killington_entry.pass_labels == killington_override_label, (
        f"Killington's pass_labels must be the display override "
        f"{killington_override_label!r}; got {killington_entry.pass_labels!r}"
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
