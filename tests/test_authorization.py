"""
#242 — Authorization boundary tests.

Covers:
  - Owner-only routes: update-resort, update-dates, update-visibility,
    update-status, notes, delete
  - Member-only routes: planning-post create
  - Self-only: participant can update own pass; invited / non-member blocked
"""
import pytest
import unittest.mock
from datetime import timedelta, date

from app import app
from models import db, GuestStatus
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post, _TEST_CSRF, _FUTURE_START2, _FUTURE_END2,
)


@pytest.fixture
def trip_setup(client):
    """Yields plain integer IDs; context is CLOSED before yield."""
    with app.app_context():
        resort   = _make_resort()
        owner    = _make_user("owner")
        accepted = _make_user("accepted")
        invited  = _make_user("invited")
        declined = _make_user("declined")
        outsider = _make_user("outsider")
        trip = _make_trip(owner, resort=resort)
        _add_participant(trip, accepted, GuestStatus.ACCEPTED)
        _add_participant(trip, invited,  GuestStatus.INVITED)
        _add_participant(trip, declined, GuestStatus.DECLINED)
        db.session.commit()
        data = {
            "trip_id":     trip.id,
            "resort_id":   resort.id,
            "owner_id":    owner.id,
            "accepted_id": accepted.id,
            "invited_id":  invited.id,
            "declined_id": declined.id,
            "outsider_id": outsider.id,
        }
    yield data


# ── Owner-only: update-resort ─────────────────────────────────────────────────

def test_owner_can_update_resort(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-resort",
                   {"resort_id": trip_setup["resort_id"]})
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True


def test_non_owner_cannot_update_resort(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-resort",
                       {"resort_id": trip_setup["resort_id"]})
        assert rv.status_code == 403, f"user {uid} should get 403"


# ── Owner-only: update-dates ──────────────────────────────────────────────────

def test_owner_can_update_dates(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-dates", {
        "start_date": _FUTURE_START2.isoformat(),
        "end_date":   _FUTURE_END2.isoformat(),
    })
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True


def test_non_owner_cannot_update_dates(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-dates", {
            "start_date": _FUTURE_START2.isoformat(),
            "end_date":   _FUTURE_END2.isoformat(),
        })
        assert rv.status_code == 403


# ── Owner-only: update-visibility ────────────────────────────────────────────

def test_owner_can_update_visibility(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-visibility",
                   {"is_public": False})
    assert rv.status_code == 200


def test_non_owner_cannot_update_visibility(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-visibility",
                       {"is_public": False})
        assert rv.status_code == 403


# ── Owner-only: update-status ─────────────────────────────────────────────────

def test_owner_can_update_status(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-status",
                   {"trip_status": "going"})
    assert rv.status_code == 200


def test_non_owner_cannot_update_status(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-status",
                       {"trip_status": "going"})
        assert rv.status_code == 403


# ── Owner-only: notes ─────────────────────────────────────────────────────────

def test_owner_can_update_notes(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/notes",
                   {"notes": "Pack extra base layers."})
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "success"


def test_non_owner_cannot_update_notes(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/notes",
                       {"notes": "Sneaky note"})
        assert rv.status_code == 403


# ── Owner-only: delete trip ───────────────────────────────────────────────────

def test_owner_can_delete_trip(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/delete")
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True


def test_non_owner_cannot_delete_trip(client, trip_setup):
    for uid in [trip_setup["accepted_id"], trip_setup["outsider_id"]]:
        _login(client, uid)
        rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/delete")
        assert rv.status_code == 403


# ── Member-only: planning post create ────────────────────────────────────────

def _valid_post_payload():
    return {"category": "Other", "body": "What boots should I bring?"}


def test_owner_can_create_planning_post(client, trip_setup):
    _login(client, trip_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/planning-posts",
                   _valid_post_payload())
    assert rv.status_code == 201


def test_accepted_member_can_create_planning_post(client, trip_setup):
    _login(client, trip_setup["accepted_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/planning-posts",
                   _valid_post_payload())
    assert rv.status_code == 201


def test_invited_member_cannot_create_planning_post(client, trip_setup):
    _login(client, trip_setup["invited_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/planning-posts",
                   _valid_post_payload())
    assert rv.status_code == 403


def test_non_member_cannot_create_planning_post(client, trip_setup):
    _login(client, trip_setup["outsider_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/planning-posts",
                   _valid_post_payload())
    assert rv.status_code == 403


# ── Self-only: participant can update own pass ────────────────────────────────

def test_participant_can_update_own_pass(client, trip_setup):
    _login(client, trip_setup["accepted_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-pass",
                   {"pass_type": "ikon"})
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True


def test_non_participant_cannot_update_pass(client, trip_setup):
    _login(client, trip_setup["outsider_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-pass",
                   {"pass_type": "ikon"})
    assert rv.status_code == 403


def test_invited_participant_cannot_update_pass(client, trip_setup):
    _login(client, trip_setup["invited_id"])
    rv = json_post(client, f"/api/trip/{trip_setup['trip_id']}/update-pass",
                   {"pass_type": "ikon"})
    assert rv.status_code == 403
