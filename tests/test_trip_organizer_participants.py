"""BL-59 — organizer participant-management regression coverage."""

import pytest

from app import app
from models import Activity, GuestStatus, SkiTripParticipant, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_trip,
    _make_user,
    form_post,
    json_post,
)


def _setup_trip_with_guest(status):
    owner = _make_user("organizer-management-owner")
    trip = _make_trip(owner)
    guest = _make_user(f"organizer-management-{status.value}")
    participant = _add_participant(trip, guest, status)
    return owner, trip, guest, participant


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (GuestStatus.GOING, "interested"),
        (GuestStatus.INTERESTED, "going"),
    ],
)
def test_organizer_can_change_active_guest_rsvp(client, current, target):
    with app.app_context():
        owner, trip, guest, participant = _setup_trip_with_guest(current)
        trip_id, owner_id, guest_id, participant_id = (
            trip.id,
            owner.id,
            guest.id,
            participant.id,
        )
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/rsvp",
        {"response": target},
    )

    assert response.status_code == 200
    with app.app_context():
        saved = SkiTripParticipant.query.get(participant_id)
        assert saved.status == {
            "going": GuestStatus.GOING,
            "interested": GuestStatus.INTERESTED,
        }[target]


@pytest.mark.parametrize("status", [GuestStatus.GOING, GuestStatus.INTERESTED])
def test_organizer_can_remove_active_guest_and_cleanup_dates(client, status):
    with app.app_context():
        owner, trip, guest, participant = _setup_trip_with_guest(status)
        participant.start_date = trip.start_date
        participant.end_date = trip.end_date
        trip_id, owner_id, guest_id, participant_id = (
            trip.id,
            owner.id,
            guest.id,
            participant.id,
        )
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/remove",
        {"confirm": "remove"},
    )

    assert response.status_code == 200
    with app.app_context():
        saved = SkiTripParticipant.query.get(participant_id)
        assert saved.status == GuestStatus.REMOVED
        assert saved.start_date is None
        assert saved.end_date is None


def test_organizer_can_cancel_pending_invite(client):
    with app.app_context():
        owner, trip, guest, participant = _setup_trip_with_guest(GuestStatus.PENDING)
        trip_id, owner_id, guest_id, participant_id = (
            trip.id,
            owner.id,
            guest.id,
            participant.id,
        )
        db.session.commit()

    _login(client, owner_id)
    response = form_post(
        client,
        f"/trips/{trip_id}/invite/cancel",
        {"user_id": guest_id},
    )

    assert response.status_code == 302
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == GuestStatus.REMOVED


@pytest.mark.parametrize("status", [GuestStatus.DECLINED, GuestStatus.REMOVED])
def test_organizer_can_reinvite_declined_or_removed_guest(client, status):
    with app.app_context():
        owner, trip, guest, participant = _setup_trip_with_guest(status)
        participant.start_date = trip.start_date
        participant.end_date = trip.end_date
        trip_id, owner_id, guest_id, participant_id = (
            trip.id,
            owner.id,
            guest.id,
            participant.id,
        )
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/reinvite",
    )

    assert response.status_code == 200
    with app.app_context():
        saved = SkiTripParticipant.query.get(participant_id)
        assert saved.status == GuestStatus.PENDING
        assert saved.start_date is None
        assert saved.end_date is None


def test_organizer_cannot_target_themselves_with_guest_rsvp_controls(client):
    with app.app_context():
        owner = _make_user("organizer-self-target")
        trip = _make_trip(owner)
        owner_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=owner.id,
        ).one()
        trip_id, owner_id, participant_id = trip.id, owner.id, owner_participant.id
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{owner_id}/rsvp",
        {"response": "going"},
    )

    assert response.status_code == 400
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == GuestStatus.INTERESTED


def test_non_organizer_cannot_invoke_guest_management_routes(client):
    with app.app_context():
        owner, trip, guest, _participant = _setup_trip_with_guest(GuestStatus.INTERESTED)
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id
        db.session.commit()

    _login(client, guest_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{owner_id}/rsvp",
        {"response": "going"},
    )

    assert response.status_code == 403


def test_organizer_cannot_edit_guest_attendance_dates(client):
    with app.app_context():
        owner, trip, guest, _participant = _setup_trip_with_guest(GuestStatus.GOING)
        trip_id, owner_id = trip.id, owner.id
        payload = {
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat(),
        }
        db.session.commit()

    _login(client, owner_id)
    response = json_post(client, f"/api/trips/{trip_id}/participant/dates", payload)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("status", "status_label", "expected_action", "forbidden_action"),
    [
        (GuestStatus.GOING, "Going", "Change to Interested", "Change to Going"),
        (GuestStatus.INTERESTED, "Interested", "Change to Going", "Change to Interested"),
        (GuestStatus.PENDING, "Pending", "Cancel invite", "Reinvite"),
        (GuestStatus.DECLINED, "Declined", "Reinvite", "Cancel invite</button>"),
    ],
)
def test_organizer_trip_detail_exposes_state_specific_actions(
    client, status, status_label, expected_action, forbidden_action
):
    with app.app_context():
        owner, trip, guest, _participant = _setup_trip_with_guest(status)
        trip_id, owner_id = trip.id, owner.id
        db.session.commit()

    _login(client, owner_id)
    response = client.get(f"/trips/{trip_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'data-participant-status="{status.value}"' in html
    assert f'td-person-status-chip--{status.value}' in html
    assert f">{status_label}</span>" in html
    assert expected_action in html
    assert forbidden_action not in html


def test_removed_guest_is_not_added_to_visible_rsvp_groups(client):
    with app.app_context():
        owner, trip, guest, _participant = _setup_trip_with_guest(GuestStatus.REMOVED)
        trip_id, owner_id = trip.id, owner.id
        db.session.commit()

    _login(client, owner_id)
    response = client.get(f"/trips/{trip_id}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    rsvp_section = html.split('id="td-rsvp-section"', 1)[1].split("</details>", 1)[0]
    assert 'data-participant-status="removed"' not in rsvp_section
    assert "Reinvite" not in rsvp_section


def test_active_organizer_management_does_not_create_activity(client):
    with app.app_context():
        owner, trip, guest, _participant = _setup_trip_with_guest(GuestStatus.GOING)
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id
        activity_count = Activity.query.count()
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/rsvp",
        {"response": "interested"},
    )

    assert response.status_code == 200
    with app.app_context():
        assert Activity.query.count() == activity_count