"""
#242 — Trip deletion tests (spec sections 10 + 11).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import secrets
import unittest.mock
import pytest
from datetime import datetime

from app import app
from models import (
    db, SkiTrip, SkiTripParticipant, SkiTripPlanningPost,
    SkiTripRsvpTransition, TripInviteToken, Invitation, Activity, ActivityType,
    GuestStatus, User,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post, form_post,
)


@pytest.fixture
def full_trip_setup(client):
    with app.app_context():
        resort   = _make_resort()
        owner    = _make_user("owner")
        accepted = _make_user("accepted")
        invited  = _make_user("invited")
        declined = _make_user("declined")
        trip = _make_trip(owner, resort=resort)
        _add_participant(trip, accepted, GuestStatus.INTERESTED)
        _add_participant(trip, invited,  GuestStatus.PENDING)
        _add_participant(trip, declined, GuestStatus.DECLINED)

        db.session.add(TripInviteToken(
            token=secrets.token_urlsafe(32),
            trip_id=trip.id,
            inviter_user_id=owner.id,
        ))
        db.session.add(Invitation(
            sender_id=owner.id,
            receiver_id=invited.id,
            trip_id=trip.id,
            status="pending",
        ))
        db.session.add(SkiTripPlanningPost(
            trip_id=trip.id, user_id=owner.id,
            category="Other", body="Bring goggles",
        ))
        db.session.add(Activity(
            actor_user_id=owner.id,
            recipient_user_id=owner.id,
            type=ActivityType.FRIEND_TRIP_OVERLAPS_AVAILABILITY.value,
            object_type="trip",
            object_id=trip.id,
            extra_data={"trip_ids": [trip.id]},
            created_at=datetime.utcnow(),
        ))
        survivor   = _make_user("survivor")
        other_trip = _make_trip(survivor, resort=resort)
        deleted_history = SkiTripRsvpTransition(
            trip_id=trip.id,
            user_id=accepted.id,
            previous_status="pending",
            new_status="interested",
            actor_user_id=accepted.id,
            source="invite_response",
        )
        surviving_history = SkiTripRsvpTransition(
            trip_id=other_trip.id,
            user_id=survivor.id,
            previous_status="interested",
            new_status="going",
            actor_user_id=survivor.id,
            source="self_rsvp",
        )
        db.session.add_all([deleted_history, surviving_history])
        db.session.commit()
        data = {
            "trip_id":       trip.id,
            "owner_id":      owner.id,
            "accepted_id":   accepted.id,
            "invited_id":    invited.id,
            "survivor_id":   survivor.id,
            "other_trip_id": other_trip.id,
            "deleted_history_id": deleted_history.id,
            "surviving_history_id": surviving_history.id,
        }
    yield data


# ── API delete removes all linked data ────────────────────────────────────────

def test_api_delete_removes_all_linked_data(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    owner_id = full_trip_setup["owner_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        rv = json_post(client, f"/api/trip/{trip_id}/delete")
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    with app.app_context():
        assert SkiTrip.query.get(trip_id) is None
        assert SkiTripParticipant.query.filter_by(trip_id=trip_id).count() == 0
        assert SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count() == 0
        assert TripInviteToken.query.filter_by(trip_id=trip_id).count() == 0
        assert Invitation.query.filter_by(trip_id=trip_id).count() == 0
        assert Activity.query.filter_by(
            object_type="trip", object_id=trip_id
        ).count() == 0
        assert SkiTripRsvpTransition.query.get(
            full_trip_setup["deleted_history_id"]
        ) is None


def test_api_delete_unrelated_data_survives(client, full_trip_setup):
    _login(client, full_trip_setup["owner_id"])
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        json_post(client, f"/api/trip/{full_trip_setup['trip_id']}/delete")

    with app.app_context():
        assert SkiTrip.query.get(full_trip_setup["other_trip_id"]) is not None
        assert User.query.get(full_trip_setup["survivor_id"]) is not None
        assert SkiTripRsvpTransition.query.get(
            full_trip_setup["surviving_history_id"]
        ) is not None


def test_non_owner_cannot_delete_via_api(client, full_trip_setup):
    _login(client, full_trip_setup["accepted_id"])
    rv = json_post(client, f"/api/trip/{full_trip_setup['trip_id']}/delete")
    assert rv.status_code == 403

    with app.app_context():
        assert SkiTrip.query.get(full_trip_setup["trip_id"]) is not None


# ── Form delete path ──────────────────────────────────────────────────────────

def test_form_delete_removes_trip(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    _login(client, full_trip_setup["owner_id"])
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        rv = form_post(client, f"/trips/{trip_id}/delete")
    assert rv.status_code in (200, 302)

    with app.app_context():
        assert SkiTrip.query.get(trip_id) is None


# ── TRIP_CANCELLED notification recipients ────────────────────────────────────

def test_cancellation_notified_to_accepted_only(client, full_trip_setup):
    trip_id     = full_trip_setup["trip_id"]
    owner_id    = full_trip_setup["owner_id"]
    accepted_id = full_trip_setup["accepted_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"), \
         unittest.mock.patch("app.emit_messaging_event") as mock_emit:
        json_post(client, f"/api/trip/{trip_id}/delete")

    cancelled_recipients = [
        c.kwargs.get("recipient_user_id")
        for c in mock_emit.call_args_list
        if c.kwargs.get("event_name") == "trip.cancelled"
    ]
    assert accepted_id in cancelled_recipients, "ACCEPTED must be notified"
    assert owner_id not in cancelled_recipients, "Owner must NOT receive own cancellation"


def test_invited_participant_not_notified_on_deletion(client, full_trip_setup):
    trip_id    = full_trip_setup["trip_id"]
    owner_id   = full_trip_setup["owner_id"]
    invited_id = full_trip_setup["invited_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"), \
         unittest.mock.patch("app.emit_messaging_event") as mock_emit:
        json_post(client, f"/api/trip/{trip_id}/delete")

    cancelled_recipients = [
        c.kwargs.get("recipient_user_id")
        for c in mock_emit.call_args_list
        if c.kwargs.get("event_name") == "trip.cancelled"
    ]
    assert invited_id not in cancelled_recipients, "INVITED must NOT receive TRIP_CANCELLED"


def test_failed_deletion_sends_zero_notifications(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    owner_id = full_trip_setup["owner_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"), \
         unittest.mock.patch(
             "app.db.session.delete",
             side_effect=Exception("Simulated DB failure"),
         ), \
         unittest.mock.patch("app.emit_messaging_event") as mock_emit:
        rv = json_post(client, f"/api/trip/{trip_id}/delete")

    assert rv.status_code != 200 or rv.get_json().get("success") is False
    assert mock_emit.call_count == 0, (
        f"No notifications on failed deletion; got {mock_emit.call_count}"
    )
