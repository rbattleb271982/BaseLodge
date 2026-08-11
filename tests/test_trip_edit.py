"""
#242 — Inline edit trip tests (spec section 5).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks so each request gets a fresh context.
"""
import pytest
from app import app
from models import db, SkiTrip, GuestStatus
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post, _FUTURE_START2, _FUTURE_END2,
)


@pytest.fixture
def setup(client):
    with app.app_context():
        resort  = _make_resort()
        resort2 = _make_resort()
        owner = _make_user("owner")
        part  = _make_user("participant")
        trip  = _make_trip(owner, resort=resort)
        _add_participant(trip, part, GuestStatus.ACCEPTED)
        db.session.commit()
        data = {
            "owner_id":  owner.id,
            "part_id":   part.id,
            "trip_id":   trip.id,
            "resort_id": resort.id,
            "resort2_id": resort2.id,
        }
    yield data


# ── GET /trips/<id>/edit ──────────────────────────────────────────────────────

def test_edit_get_redirects_owner_to_trip_detail(client, setup):
    _login(client, setup["owner_id"])
    rv = client.get(f"/trips/{setup['trip_id']}/edit", follow_redirects=False)
    assert rv.status_code in (301, 302)
    assert f"/trips/{setup['trip_id']}" in rv.headers["Location"]


def test_edit_get_blocks_non_owner(client, setup):
    _login(client, setup["part_id"])
    rv = client.get(f"/trips/{setup['trip_id']}/edit", follow_redirects=False)
    assert rv.status_code == 403


# ── update-resort ─────────────────────────────────────────────────────────────

def test_update_resort_persists_for_owner(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-resort",
                   {"resort_id": setup["resort2_id"]})
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True
    assert rv.get_json()["resort_id"] == setup["resort2_id"]

    with app.app_context():
        t = SkiTrip.query.get(setup["trip_id"])
        assert t.resort_id == setup["resort2_id"]


def test_update_resort_blocked_for_participant(client, setup):
    _login(client, setup["part_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-resort",
                   {"resort_id": setup["resort2_id"]})
    assert rv.status_code == 403


# ── update-visibility ─────────────────────────────────────────────────────────

def test_update_visibility_persists_for_owner(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-visibility",
                   {"is_public": False})
    assert rv.status_code == 200
    assert rv.get_json()["is_public"] is False

    with app.app_context():
        assert SkiTrip.query.get(setup["trip_id"]).is_public is False

    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-visibility",
                   {"is_public": True})
    assert rv.status_code == 200
    assert rv.get_json()["is_public"] is True


def test_update_visibility_blocked_for_participant(client, setup):
    _login(client, setup["part_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-visibility",
                   {"is_public": False})
    assert rv.status_code == 403


# ── update-status ─────────────────────────────────────────────────────────────

def test_update_status_persists_for_owner(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-status",
                   {"trip_status": "going"})
    assert rv.status_code == 200
    assert rv.get_json()["trip_status"] == "going"

    with app.app_context():
        assert SkiTrip.query.get(setup["trip_id"]).trip_status == "going"


def test_update_status_blocked_for_participant(client, setup):
    _login(client, setup["part_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-status",
                   {"trip_status": "going"})
    assert rv.status_code == 403


def test_update_status_invalid_value_rejected(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-status",
                   {"trip_status": "abandoned"})
    assert rv.status_code == 400


# ── notes ─────────────────────────────────────────────────────────────────────

def test_notes_persist_for_owner(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/notes",
                   {"notes": "Bring avalanche beacon."})
    assert rv.status_code == 200
    assert rv.get_json()["status"] == "success"

    with app.app_context():
        assert SkiTrip.query.get(setup["trip_id"]).notes == "Bring avalanche beacon."


def test_notes_blocked_for_participant(client, setup):
    _login(client, setup["part_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/notes",
                   {"notes": "Sneaky note"})
    assert rv.status_code == 403


def test_notes_cleared_when_empty(client, setup):
    _login(client, setup["owner_id"])
    json_post(client, f"/api/trip/{setup['trip_id']}/notes", {"notes": "Some note"})
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/notes", {"notes": ""})
    assert rv.status_code == 200

    with app.app_context():
        assert SkiTrip.query.get(setup["trip_id"]).notes is None


# ── update-dates ──────────────────────────────────────────────────────────────

def test_update_dates_persists_for_owner(client, setup):
    _login(client, setup["owner_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-dates", {
        "start_date": _FUTURE_START2.isoformat(),
        "end_date":   _FUTURE_END2.isoformat(),
    })
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    with app.app_context():
        t = SkiTrip.query.get(setup["trip_id"])
        assert str(t.start_date) == _FUTURE_START2.isoformat()
        assert str(t.end_date)   == _FUTURE_END2.isoformat()


def test_update_dates_blocked_for_participant(client, setup):
    _login(client, setup["part_id"])
    rv = json_post(client, f"/api/trip/{setup['trip_id']}/update-dates", {
        "start_date": _FUTURE_START2.isoformat(),
        "end_date":   _FUTURE_END2.isoformat(),
    })
    assert rv.status_code == 403
