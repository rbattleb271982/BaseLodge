"""BL-58 — canonical participant self-RSVP regression coverage."""

import pytest

from app import app
from models import Activity, GuestStatus, SkiTripParticipant, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_trip,
    _make_user,
    json_post,
)


def _setup_participant(status):
    owner = _make_user("self-rsvp-owner")
    trip = _make_trip(owner)
    guest = _make_user(f"self-rsvp-{status.value}")
    participant = _add_participant(trip, guest, status)
    return owner, trip, guest, participant


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("going", GuestStatus.GOING),
        ("interested", GuestStatus.INTERESTED),
        ("declined", GuestStatus.DECLINED),
    ],
)
def test_pending_guest_can_choose_each_explicit_rsvp(client, target, expected):
    with app.app_context():
        _owner, trip, guest, participant = _setup_participant(GuestStatus.PENDING)
        trip_id, guest_id, participant_id = trip.id, guest.id, participant.id
        db.session.commit()

    _login(client, guest_id)
    response = json_post(client, f"/trips/{trip_id}/respond", {"response": target})

    assert response.status_code == 200
    with app.app_context():
        saved = SkiTripParticipant.query.get(participant_id)
        assert saved.status == expected


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (GuestStatus.INTERESTED, "going"),
        (GuestStatus.INTERESTED, "declined"),
        (GuestStatus.GOING, "interested"),
        (GuestStatus.GOING, "declined"),
    ],
)
def test_active_guest_can_change_only_their_own_rsvp(client, current, target):
    with app.app_context():
        _owner, trip, guest, participant = _setup_participant(current)
        trip_id, guest_id, participant_id = trip.id, guest.id, participant.id
        db.session.commit()

    _login(client, guest_id)
    response = json_post(client, f"/trips/{trip_id}/rsvp", {"response": target})

    assert response.status_code == 200
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == {
            "going": GuestStatus.GOING,
            "interested": GuestStatus.INTERESTED,
            "declined": GuestStatus.DECLINED,
        }[target]


@pytest.mark.parametrize("status", [GuestStatus.DECLINED, GuestStatus.REMOVED])
def test_declined_and_removed_guests_cannot_self_reactivate(client, status):
    with app.app_context():
        _owner, trip, guest, participant = _setup_participant(status)
        trip_id, guest_id, participant_id = trip.id, guest.id, participant.id
        db.session.commit()

    _login(client, guest_id)
    response = json_post(client, f"/trips/{trip_id}/respond", {"response": "going"})

    assert response.status_code == 403
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == status


def test_participant_cannot_change_another_participants_rsvp(client):
    with app.app_context():
        owner, trip, guest, _guest_participant = _setup_participant(GuestStatus.INTERESTED)
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id
        db.session.commit()

    _login(client, guest_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{owner_id}/rsvp",
        {"response": "going"},
    )

    assert response.status_code == 403


def test_active_self_rsvp_does_not_create_activity(client):
    with app.app_context():
        _owner, trip, guest, _participant = _setup_participant(GuestStatus.GOING)
        trip_id, guest_id = trip.id, guest.id
        activity_count = Activity.query.count()
        db.session.commit()

    _login(client, guest_id)
    response = json_post(client, f"/trips/{trip_id}/rsvp", {"response": "interested"})

    assert response.status_code == 200
    with app.app_context():
        assert Activity.query.count() == activity_count


def test_organizer_self_rsvp_remains_limited_to_active_states(client):
    with app.app_context():
        owner = _make_user("organizer-self-rsvp")
        trip = _make_trip(owner)
        owner_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id, user_id=owner.id
        ).one()
        trip_id, owner_id, participant_id = trip.id, owner.id, owner_participant.id
        db.session.commit()

    _login(client, owner_id)
    response = json_post(client, f"/trips/{trip_id}/rsvp", {"response": "declined"})

    assert response.status_code == 400
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == GuestStatus.INTERESTED