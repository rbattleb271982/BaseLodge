"""
#242 — Trip planning permissions, link URL security, and rate-limit tests.

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import unittest.mock
import pytest
from app import app
from models import db, SkiTripPlanningPost, GuestStatus
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post, json_patch, json_delete,
)


@pytest.fixture
def planning_setup(client):
    with app.app_context():
        resort   = _make_resort()
        owner    = _make_user("owner")
        member   = _make_user("member")
        invited  = _make_user("invited")
        outsider = _make_user("outsider")
        trip = _make_trip(owner, resort=resort)
        _add_participant(trip, member,  GuestStatus.ACCEPTED)
        _add_participant(trip, invited, GuestStatus.INVITED)
        db.session.commit()
        data = {
            "trip_id":    trip.id,
            "owner_id":   owner.id,
            "member_id":  member.id,
            "invited_id": invited.id,
            "outsider_id": outsider.id,
        }
    yield data


def _make_post(client, trip_id, user_id, body="Test body"):
    _login(client, user_id)
    return json_post(client, f"/api/trip/{trip_id}/planning-posts",
                     {"category": "Other", "body": body})


def _insert_post(trip_id, user_id):
    p = SkiTripPlanningPost(
        trip_id=trip_id, user_id=user_id,
        category="Other", body="Original body",
    )
    db.session.add(p)
    db.session.flush()
    return p.id


# ── Planning permissions — create ─────────────────────────────────────────────

def test_owner_can_create_planning_post(client, planning_setup):
    rv = _make_post(client, planning_setup["trip_id"], planning_setup["owner_id"])
    assert rv.status_code == 201
    assert rv.get_json()["ok"] is True


def test_accepted_member_can_create_planning_post(client, planning_setup):
    rv = _make_post(client, planning_setup["trip_id"], planning_setup["member_id"])
    assert rv.status_code == 201


def test_invited_member_cannot_create_planning_post(client, planning_setup):
    rv = _make_post(client, planning_setup["trip_id"], planning_setup["invited_id"])
    assert rv.status_code == 403


def test_non_member_cannot_create_planning_post(client, planning_setup):
    rv = _make_post(client, planning_setup["trip_id"], planning_setup["outsider_id"])
    assert rv.status_code == 403


# ── Planning permissions — edit ───────────────────────────────────────────────

def test_owner_can_edit_own_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["owner_id"])
        db.session.commit()

    _login(client, planning_setup["owner_id"])
    rv = json_patch(client,
                    f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}",
                    {"category": "Other", "body": "Updated"})
    assert rv.status_code == 200


def test_owner_cannot_edit_participant_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["member_id"])
        db.session.commit()

    _login(client, planning_setup["owner_id"])
    rv = json_patch(client,
                    f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}",
                    {"category": "Other", "body": "Should fail"})
    assert rv.status_code == 403


def test_accepted_member_can_edit_own_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["member_id"])
        db.session.commit()

    _login(client, planning_setup["member_id"])
    rv = json_patch(client,
                    f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}",
                    {"category": "Other", "body": "My edit"})
    assert rv.status_code == 200


def test_accepted_member_cannot_edit_owner_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["owner_id"])
        db.session.commit()

    _login(client, planning_setup["member_id"])
    rv = json_patch(client,
                    f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}",
                    {"category": "Other", "body": "Should fail"})
    assert rv.status_code == 403


# ── Planning permissions — delete ─────────────────────────────────────────────

def test_owner_can_delete_participant_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["member_id"])
        db.session.commit()

    _login(client, planning_setup["owner_id"])
    rv = json_delete(client, f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}")
    assert rv.status_code == 200

    with app.app_context():
        assert SkiTripPlanningPost.query.get(post_id) is None


def test_accepted_member_can_delete_own_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["member_id"])
        db.session.commit()

    _login(client, planning_setup["member_id"])
    rv = json_delete(client, f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}")
    assert rv.status_code == 200


def test_accepted_member_cannot_delete_owner_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["owner_id"])
        db.session.commit()

    _login(client, planning_setup["member_id"])
    rv = json_delete(client, f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}")
    assert rv.status_code == 403


def test_invited_member_cannot_delete_any_post(client, planning_setup):
    with app.app_context():
        post_id = _insert_post(planning_setup["trip_id"], planning_setup["owner_id"])
        db.session.commit()

    _login(client, planning_setup["invited_id"])
    rv = json_delete(client, f"/api/trip/{planning_setup['trip_id']}/planning-posts/{post_id}")
    assert rv.status_code == 403


# ── Link URL security ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected_code", [
    ("https://example.com",     201),
    ("http://example.com",      201),
    ("",                        201),
    ("javascript:alert(1)",     400),
    ("data:text/html,<b>x</b>", 400),
    ("//example.com",           400),
    ("example.com",             400),
])
def test_link_url_validation(client, planning_setup, url, expected_code):
    _login(client, planning_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{planning_setup['trip_id']}/planning-posts",
                   {"category": "Other", "body": "Link test", "link_url": url})
    assert rv.status_code == expected_code, (
        f"Expected {expected_code} for link_url={url!r}, got {rv.status_code}"
    )


def test_link_url_security_unsafe_value_not_stored(client, planning_setup):
    trip_id = planning_setup["trip_id"]
    with app.app_context():
        before = SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count()

    _login(client, planning_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_id}/planning-posts",
                   {"category": "Other", "body": "Hax", "link_url": "javascript:alert(1)"})
    assert rv.status_code == 400

    with app.app_context():
        after = SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count()
    assert after == before, "Unsafe link rejection must not create a post row"


# ── Rate limit ────────────────────────────────────────────────────────────────

def test_rate_limit_triggers_at_11th_request(rate_limit_client):
    """11th planning-post creation within a minute returns 429."""
    with app.app_context():
        resort  = _make_resort()
        user    = _make_user("ratelimit")
        trip    = _make_trip(user, resort=resort)
        db.session.commit()
        user_id = user.id
        trip_id = trip.id

    _login(rate_limit_client, user_id)
    statuses = []
    for i in range(11):
        rv = json_post(rate_limit_client,
                       f"/api/trip/{trip_id}/planning-posts",
                       {"category": "Other", "body": f"Post {i}"})
        statuses.append(rv.status_code)

    assert all(s == 201 for s in statuses[:10]), (
        f"First 10 must be 201, got: {statuses[:10]}"
    )
    assert statuses[10] == 429, (
        f"11th must be 429, got: {statuses[10]}"
    )

    with app.app_context():
        count = SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count()
    assert count == 10, f"Expected exactly 10 posts; got {count}"
