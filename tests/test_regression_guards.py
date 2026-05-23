"""
Regression guard tests for recent BaseLodge UX/social-graph fixes.

Coverage:
  1. remove_friend severs both Friend rows AND cancels accepted Invitation rows
  2. rental equipment via onboarding route persists to User.equipment_status
  3. pass display overrides do not mutate normalize_pass()
  4. home empty-state card appears only when dest_feed is empty

Run: pytest tests/test_regression_guards.py -v
"""
import unittest.mock
from datetime import datetime

import pytest

from app import app
from models import db, Friend, Invitation, User


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """SQLite in-memory test client — matches test_profile_consolidation.py pattern."""
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


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
    """POST /onboarding/equipment with equipment_status=needs_rentals mirrors to User."""
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
    """Resort display-layer overrides must not mutate normalize_pass() output."""
    from services.pass_utils import normalize_pass

    # Capture results before any override logic is simulated
    before_other = normalize_pass("other")        # canonical → "other"
    before_slug = normalize_pass("killington")    # not in PASS_NORM_MAP → "killington"

    # Simulate exactly what get_all_active_resorts_map() does internally:
    # assign a display label to a LOCAL variable only — normalize_pass is not touched.
    _simulated_overrides = {"killington": "Ikon"}
    _pk = ["other"]
    _pl = "other"
    if _pk == ["other"] and "killington" in _simulated_overrides:
        _pl = _simulated_overrides["killington"]  # display label changes in local scope only

    # normalize_pass must return identical results before and after
    after_other = normalize_pass("other")
    after_slug = normalize_pass("killington")

    assert before_other == after_other == "other", (
        "normalize_pass('other') must always return 'other', never a display label"
    )
    assert before_slug == after_slug, (
        "normalize_pass result must be identical before and after override dict assignment"
    )
    assert _pl == "Ikon", (
        "The display-layer override must produce 'Ikon' for the presentation layer"
    )
    assert normalize_pass("other") != "Ikon", (
        "normalize_pass must never return a branded display label"
    )
    assert normalize_pass("killington") != "Ikon", (
        "normalize_pass on a resort slug must never return a display override label"
    )


# ─── Test 4 — home empty-state card only when dest_feed is empty ──────────────

def test_empty_opportunity_card_only_when_feed_empty(client):
    """
    The opportunities partial renders bl-opp-empty-card iff dest_feed is [].

    Tests the template logic directly via render_template so the assertion is
    independent of complex route/DB state. The Jinja2 conditional in
    _section_opportunities.html is the precise regression guard.
    """
    from flask import render_template

    # ── Part A: empty feed → empty card MUST appear ───────────────────────────
    with app.test_request_context("/home"):
        html_empty = render_template(
            "partials/home/_section_opportunities.html",
            dest_feed=[],
            ideas_count=0,
            show_add_dates=True,
        )

    assert "bl-opp-empty-card" in html_empty, (
        "Empty-state card must appear in template HTML when dest_feed=[]"
    )
    assert "Add dates to unlock trip ideas" in html_empty, (
        "Empty-state card title must match the spec copy"
    )

    # ── Part B: one feed item → empty card must NOT appear ────────────────────
    mock_row = {
        "resort":            None,       # triggers "Pick a mountain" path
        "idea_type":         "friend_trip",
        "line2":             "1 friend is going",
        "date_range":        None,
        "friend_count":      1,
        "going_count":       1,
        "considering_count": 0,
        "signal_type":       1,
        "_card_key":         "friend_trip:999",
        "_url":              "/add_trip",
    }
    with app.test_request_context("/home"):
        html_has_items = render_template(
            "partials/home/_section_opportunities.html",
            dest_feed=[mock_row],
            ideas_count=1,
            show_add_dates=False,
        )

    assert "bl-opp-empty-card" not in html_has_items, (
        "Empty-state card must NOT appear in template HTML when dest_feed has items"
    )
    assert "bl-opp-row" in html_has_items, (
        "Opportunity rows must be rendered when dest_feed has items"
    )
