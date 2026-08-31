"""
#242 — Trip deletion tests (spec sections 10 + 11).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import secrets
import unittest.mock
import pytest
from datetime import date, datetime, timedelta

from app import app
from models import (
    db, SkiTrip, SkiTripParticipant, SkiTripPlanningPost,
    SkiTripRsvpTransition, SkiTripLifecycleEvent, TripInviteToken, Invitation, Activity, ActivityType,
    GuestStatus, User, Friend,
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


# ── API delete cancels and retains historical data ───────────────────────────

def test_api_delete_cancels_and_retains_history(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    owner_id = full_trip_setup["owner_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        rv = json_post(client, f"/api/trip/{trip_id}/delete")
    assert rv.status_code == 200
    assert rv.get_json()["success"] is True

    with app.app_context():
        assert SkiTrip.query.get(trip_id).lifecycle_state == "cancelled"
        assert SkiTripParticipant.query.filter_by(trip_id=trip_id).count() == 4
        assert SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count() == 1
        assert TripInviteToken.query.filter_by(trip_id=trip_id).count() == 0
        assert Invitation.query.filter_by(trip_id=trip_id).count() == 0
        assert Activity.query.filter_by(
            object_type="trip", object_id=trip_id
        ).count() == 0
        assert SkiTripRsvpTransition.query.get(
            full_trip_setup["deleted_history_id"]
        ) is not None


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

def test_form_delete_cancels_trip(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    _login(client, full_trip_setup["owner_id"])
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        rv = form_post(client, f"/trips/{trip_id}/delete")
    assert rv.status_code in (200, 302)

    with app.app_context():
        assert SkiTrip.query.get(trip_id).lifecycle_state == "cancelled"


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


def test_duplicate_cancellation_sends_zero_notifications(client, full_trip_setup):
    trip_id  = full_trip_setup["trip_id"]
    owner_id = full_trip_setup["owner_id"]

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        json_post(client, f"/api/trip/{trip_id}/delete")
    with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
        rv = json_post(client, f"/api/trip/{trip_id}/delete")

    assert rv.status_code == 200
    assert rv.get_json() == {
        "success": True, "changed": False, "state": "cancelled"
    }
    assert mock_emit.call_count == 0


def test_cancelled_trip_is_immutable(client, full_trip_setup):
    trip_id = full_trip_setup["trip_id"]
    _login(client, full_trip_setup["owner_id"])
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        json_post(client, f"/api/trip/{trip_id}/delete")

    response = json_post(
        client,
        f"/api/trip/{trip_id}/update-visibility",
        {"is_public": False},
    )
    assert response.status_code == 409
    with app.app_context():
        assert SkiTrip.query.get(trip_id).is_public is True


def test_organizer_can_complete_ended_trip(client):
    with app.app_context():
        owner = _make_user("complete-owner")
        resort = _make_resort()
        trip = _make_trip(owner, resort=resort)
        trip.start_date = date.today() - timedelta(days=3)
        trip.end_date = date.today() - timedelta(days=1)
        db.session.commit()
        owner_id, trip_id = owner.id, trip.id

    _login(client, owner_id)
    response = form_post(client, f"/trips/{trip_id}/complete")
    assert response.status_code in (200, 302)
    with app.app_context():
        trip = SkiTrip.query.get(trip_id)
        assert trip.lifecycle_state == "completed"
        assert trip.terminal_at is not None
        assert SkiTripLifecycleEvent.query.filter_by(
            trip_id=trip_id, event_type="completed"
        ).count() == 1


def test_cannot_complete_trip_that_has_not_ended(client, full_trip_setup):
    _login(client, full_trip_setup["owner_id"])
    response = form_post(
        client, f"/trips/{full_trip_setup['trip_id']}/complete"
    )
    assert response.status_code == 409
    with app.app_context():
        assert (
            SkiTrip.query.get(full_trip_setup["trip_id"]).lifecycle_state
            in (None, "active")
        )


def test_created_by_metadata_grants_no_trip_route_authority(client):
    with app.app_context():
        owner = _make_user("route-owner")
        creator = _make_user("route-creator")
        resort = _make_resort()
        trip = _make_trip(owner, resort=resort)
        trip.created_by_user_id = creator.id
        db.session.commit()
        trip_id, creator_id = trip.id, creator.id

    _login(client, creator_id)
    assert json_post(client, f"/api/trip/{trip_id}/delete").status_code == 403
    assert client.get(f"/trips/{trip_id}").status_code == 404
    assert form_post(client, f"/trips/{trip_id}/complete").status_code == 403


def test_terminal_invite_routes_never_render_response_screen(client):
    with app.app_context():
        owner = _make_user("terminal-invite-owner")
        pending = _make_user("terminal-invite-pending")
        resort = _make_resort()
        trip = _make_trip(owner, resort=resort)
        trip.lifecycle_state = "cancelled"
        _add_participant(trip, pending, GuestStatus.PENDING)
        token = secrets.token_urlsafe(32)
        db.session.add(TripInviteToken(
            token=token, trip_id=trip.id, inviter_user_id=owner.id,
        ))
        db.session.commit()
        trip_id, pending_id = trip.id, pending.id

    _login(client, pending_id)
    landing = client.get(f"/trip-invite/{token}")
    assert landing.status_code == 409
    response = form_post(client, f"/trip-invite/{token}/accept", {
        "response": "going",
    })
    assert response.status_code == 409
    invite_detail = client.get(f"/trips/{trip_id}/invite", follow_redirects=False)
    assert invite_detail.status_code == 302
    assert "/my-trips" in invite_detail.headers["Location"]


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_terminal_future_trip_is_not_friend_or_idea_detail_content(
    client, lifecycle_state
):
    with app.app_context():
        viewer = _make_user(f"terminal-viewer-{lifecycle_state}")
        owner = _make_user(f"terminal-owner-{lifecycle_state}")
        resort = _make_resort()
        trip = _make_trip(
            owner, resort=resort,
            start_date=date.today() + timedelta(days=14),
            end_date=date.today() + timedelta(days=16),
        )
        trip.lifecycle_state = lifecycle_state
        db.session.add(Friend(user_id=viewer.id, friend_id=owner.id))
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    _login(client, viewer_id)
    assert client.get(f"/friend-trip/{trip_id}").status_code == 404
    assert client.get(f"/idea/trip/{trip_id}").status_code == 404


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_terminal_future_trip_is_not_in_friends_live_listing(client, lifecycle_state):
    with app.app_context():
        viewer = _make_user(f"listing-viewer-{lifecycle_state}")
        owner = _make_user(f"listing-owner-{lifecycle_state}")
        resort = _make_resort()
        trip = _make_trip(
            owner, resort=resort,
            start_date=date.today() + timedelta(days=14),
            end_date=date.today() + timedelta(days=16),
        )
        trip.lifecycle_state = lifecycle_state
        trip.mountain = f"Terminal {lifecycle_state} Peak"
        db.session.add(Friend(user_id=viewer.id, friend_id=owner.id))
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    assert f"Terminal {lifecycle_state} Peak" not in client.get("/friends").get_data(
        as_text=True
    )


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_notifications_omit_terminal_trip_activities_but_keep_non_trip(
    client, lifecycle_state
):
    with app.app_context():
        recipient = _make_user(f"notification-recipient-{lifecycle_state}")
        actor = _make_user(f"notification-actor-{lifecycle_state}")
        resort = _make_resort(f"Notification Terminal {lifecycle_state} Peak")
        trip = _make_trip(actor, resort=resort)
        trip.lifecycle_state = lifecycle_state
        db.session.add_all([
            Activity(
                actor_user_id=actor.id,
                recipient_user_id=recipient.id,
                type=ActivityType.TRIP_INVITE_RECEIVED.value,
                object_type="trip",
                object_id=trip.id,
                created_at=datetime.utcnow(),
            ),
            Activity(
                actor_user_id=actor.id,
                recipient_user_id=recipient.id,
                type=ActivityType.CONNECTION_ACCEPTED.value,
                object_type="user",
                object_id=actor.id,
                created_at=datetime.utcnow(),
            ),
        ])
        db.session.commit()
        recipient_id, trip_id = recipient.id, trip.id
        actor_first_name = actor.first_name

    _login(client, recipient_id)
    html = client.get("/notifications").get_data(as_text=True)
    assert f"Notification Terminal {lifecycle_state} Peak" not in html
    assert f"/trips/{trip_id}" not in html
    assert "Trip Detail" not in html
    assert f"{actor_first_name} accepted your connection request" in html
