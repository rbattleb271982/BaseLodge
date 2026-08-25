"""BL-50 — participant-specific shared-trip attendance dates."""

from datetime import date, timedelta

import pytest

from app import app
from models import (
    db,
    GuestStatus,
    Invitation,
    InviteType,
    ParticipantRole,
    SkiTrip,
    SkiTripParticipant,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


def _setup_trip(status=GuestStatus.GOING, *, start_date=None, end_date=None):
    """Create one owner, one guest, and a shared trip inside an app context."""
    resort = _make_resort()
    owner = _make_user("attendance-owner")
    trip = _make_trip(
        owner,
        resort=resort,
        start_date=start_date or (date.today() + timedelta(days=60)),
        end_date=end_date or (date.today() + timedelta(days=65)),
    )
    guest = _make_user("attendance-guest")
    participant = _add_participant(trip, guest, status)
    db.session.commit()
    return owner.id, guest.id, trip.id, participant.id


def _attendance_url(trip_id):
    return f"/api/trips/{trip_id}/participant/dates"


def _trip_and_participant(trip_id, participant_id):
    return (
        SkiTrip.query.get(trip_id),
        SkiTripParticipant.query.get(participant_id),
    )


def test_going_guest_saves_valid_subrange_and_same_day_attendance(client):
    with app.app_context():
        _owner_id, guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        subrange_start = trip.start_date + timedelta(days=1)
        subrange_end = trip.end_date - timedelta(days=1)

    _login(client, guest_id)
    response = json_post(
        client,
        _attendance_url(trip_id),
        {"start_date": subrange_start.isoformat(), "end_date": subrange_end.isoformat()},
    )
    assert response.status_code == 200
    assert response.get_json()["full_trip"] is False

    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date == subrange_start
        assert participant.end_date == subrange_end

    response = json_post(
        client,
        _attendance_url(trip_id),
        {"start_date": subrange_start.isoformat(), "end_date": subrange_start.isoformat()},
    )
    assert response.status_code == 200
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date == subrange_start
        assert participant.end_date == subrange_start


def test_going_guest_can_store_full_range_or_clear_to_full_trip(client):
    with app.app_context():
        _owner_id, guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)

    _login(client, guest_id)
    response = json_post(
        client,
        _attendance_url(trip_id),
        {"start_date": trip.start_date.isoformat(), "end_date": trip.end_date.isoformat()},
    )
    assert response.status_code == 200

    response = json_post(client, _attendance_url(trip_id), {"clear": True})
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "start_date": None,
        "end_date": None,
        "full_trip": True,
    }
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date is None
        assert participant.end_date is None


@pytest.mark.parametrize(
    ("payload", "error_fragment"),
    [
        ({"start_date": "2030-01-01"}, "Both attendance dates"),
        ({"end_date": "2030-01-01"}, "Both attendance dates"),
        ({"start_date": "not-a-date", "end_date": "2030-01-01"}, "YYYY-MM-DD"),
        ({"start_date": "2030-1-01", "end_date": "2030-01-02"}, "YYYY-MM-DD"),
        ({"start_date": "2030-01-05", "end_date": "2030-01-04"}, "cannot be before"),
    ],
)
def test_attendance_endpoint_rejects_partial_malformed_and_reversed_dates(
    client, payload, error_fragment
):
    with app.app_context():
        _owner_id, guest_id, trip_id, participant_id = _setup_trip()

    _login(client, guest_id)
    response = json_post(client, _attendance_url(trip_id), payload)
    assert response.status_code == 400
    assert error_fragment in response.get_json()["error"]
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date is None
        assert participant.end_date is None


def test_attendance_endpoint_rejects_ranges_outside_the_core_trip(client):
    with app.app_context():
        _owner_id, guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)

    _login(client, guest_id)
    for payload in (
        {
            "start_date": (trip.start_date - timedelta(days=1)).isoformat(),
            "end_date": trip.end_date.isoformat(),
        },
        {
            "start_date": trip.start_date.isoformat(),
            "end_date": (trip.end_date + timedelta(days=1)).isoformat(),
        },
    ):
        response = json_post(client, _attendance_url(trip_id), payload)
        assert response.status_code == 400
        assert "within the trip dates" in response.get_json()["error"]

    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date is None
        assert participant.end_date is None


@pytest.mark.parametrize(
    "status",
    [
        GuestStatus.INTERESTED,
        GuestStatus.PENDING,
        GuestStatus.DECLINED,
        GuestStatus.REMOVED,
    ],
)
def test_non_going_guests_cannot_set_attendance_dates(client, status):
    with app.app_context():
        _owner_id, guest_id, trip_id, participant_id = _setup_trip(status)
        trip = SkiTrip.query.get(trip_id)

    _login(client, guest_id)
    response = json_post(
        client,
        _attendance_url(trip_id),
        {"start_date": trip.start_date.isoformat(), "end_date": trip.end_date.isoformat()},
    )
    assert response.status_code == 403
    assert "Only Going guests" in response.get_json()["error"]
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date is None
        assert participant.end_date is None


def test_organizer_and_other_guests_cannot_edit_someone_elses_attendance(client):
    with app.app_context():
        owner_id, guest_id, trip_id, guest_participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        other_guest = _make_user("attendance-other-guest")
        other_participant = _add_participant(trip, other_guest, GuestStatus.GOING)
        db.session.commit()
        other_guest_id = other_guest.id
        other_participant_id = other_participant.id
        payload = {
            "start_date": trip.start_date.isoformat(),
            "end_date": trip.end_date.isoformat(),
        }

    _login(client, owner_id)
    response = json_post(client, _attendance_url(trip_id), payload)
    assert response.status_code == 403

    _login(client, other_guest_id)
    response = json_post(client, _attendance_url(trip_id), payload)
    assert response.status_code == 200
    with app.app_context():
        _trip, guest_participant = _trip_and_participant(trip_id, guest_participant_id)
        _trip, other_participant = _trip_and_participant(trip_id, other_participant_id)
        assert guest_participant.start_date is None
        assert guest_participant.end_date is None
        assert other_participant.start_date == trip.start_date
        assert other_participant.end_date == trip.end_date


def test_going_to_non_going_rsvp_transitions_clear_attendance_dates(client):
    with app.app_context():
        owner_id, guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        participant = SkiTripParticipant.query.get(participant_id)
        participant.start_date = trip.start_date
        participant.end_date = trip.end_date
        db.session.commit()

    _login(client, guest_id)
    response = json_post(client, f"/trips/{trip_id}/rsvp", {"response": "interested"})
    assert response.status_code == 200
    with app.app_context():
        current_trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.status == GuestStatus.INTERESTED
        assert participant.start_date is None
        assert participant.end_date is None

        participant.status = GuestStatus.GOING
        participant.start_date = current_trip.start_date
        participant.end_date = current_trip.end_date
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/rsvp",
        {"response": "interested"},
    )
    assert response.status_code == 200
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.status == GuestStatus.INTERESTED
        assert participant.start_date is None
        assert participant.end_date is None


def test_removal_and_reinvite_clear_attendance_dates(client):
    with app.app_context():
        owner_id, guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        participant = SkiTripParticipant.query.get(participant_id)
        participant.start_date = trip.start_date
        participant.end_date = trip.end_date
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/{trip_id}/participants/{guest_id}/remove",
        {"confirm": "remove"},
    )
    assert response.status_code == 200
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.status == GuestStatus.REMOVED
        assert participant.start_date is None
        assert participant.end_date is None

    response = json_post(client, f"/trips/{trip_id}/participants/{guest_id}/reinvite")
    assert response.status_code == 200
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.status == GuestStatus.PENDING
        assert participant.start_date is None
        assert participant.end_date is None


def test_direct_and_join_request_participants_default_to_full_trip_fallback(client):
    with app.app_context():
        resort = _make_resort()
        owner = _make_user("attendance-default-owner")
        trip = _make_trip(owner, resort=resort)
        direct_guest = _make_user("attendance-direct")
        direct_participant = trip.add_participant(direct_guest.id, GuestStatus.PENDING)

        joiner = _make_user("attendance-joiner")
        request = Invitation(
            sender_id=joiner.id,
            receiver_id=owner.id,
            trip_id=trip.id,
            invite_type=InviteType.REQUEST,
            status="pending",
        )
        db.session.add(request)
        db.session.commit()
        owner_id = owner.id
        trip_id = trip.id
        request_id = request.id
        direct_participant_id = direct_participant.id
        joiner_id = joiner.id

    _login(client, owner_id)
    response = json_post(
        client,
        f"/trips/requests/{request_id}/respond",
        {"action": "accept"},
    )
    assert response.status_code == 200
    with app.app_context():
        direct_participant = SkiTripParticipant.query.get(direct_participant_id)
        joined_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id,
            user_id=joiner_id,
        ).one()
        assert direct_participant.start_date is None
        assert direct_participant.end_date is None
        assert joined_participant.start_date is None
        assert joined_participant.end_date is None


def test_owner_core_date_edits_allow_fitting_overrides_and_block_conflicts(client):
    with app.app_context():
        owner_id, _guest_id, trip_id, participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        participant = SkiTripParticipant.query.get(participant_id)
        participant.start_date = trip.start_date + timedelta(days=1)
        participant.end_date = trip.end_date - timedelta(days=1)
        original_start = trip.start_date
        original_end = trip.end_date
        db.session.commit()

    _login(client, owner_id)
    allowed_response = json_post(
        client,
        f"/api/trip/{trip_id}/update-dates",
        {
            "start_date": original_start.isoformat(),
            "end_date": (original_end + timedelta(days=1)).isoformat(),
        },
    )
    assert allowed_response.status_code == 200

    blocked_response = json_post(
        client,
        f"/api/trip/{trip_id}/update-dates",
        {
            "start_date": original_start.isoformat(),
            "end_date": (original_end - timedelta(days=2)).isoformat(),
        },
    )
    assert blocked_response.status_code == 409
    assert "would exclude" in blocked_response.get_json()["error"]
    with app.app_context():
        trip, participant = _trip_and_participant(trip_id, participant_id)
        assert trip.start_date == original_start
        assert trip.end_date == original_end + timedelta(days=1)
        assert participant.start_date == original_start + timedelta(days=1)
        assert participant.end_date == original_end - timedelta(days=1)


def test_in_progress_going_guest_can_edit_attendance_dates(client):
    with app.app_context():
        start = date.today() - timedelta(days=2)
        end = date.today() + timedelta(days=2)
        _owner_id, guest_id, trip_id, participant_id = _setup_trip(
            start_date=start,
            end_date=end,
        )

    _login(client, guest_id)
    response = json_post(
        client,
        _attendance_url(trip_id),
        {"start_date": start.isoformat(), "end_date": date.today().isoformat()},
    )
    assert response.status_code == 200
    with app.app_context():
        _trip, participant = _trip_and_participant(trip_id, participant_id)
        assert participant.start_date == start
        assert participant.end_date == date.today()


def test_trip_detail_shows_my_dates_only_to_going_guests(client):
    with app.app_context():
        owner_id, going_id, trip_id, _participant_id = _setup_trip()
        interested = _make_user("attendance-interested")
        trip = SkiTrip.query.get(trip_id)
        _add_participant(trip, interested, GuestStatus.INTERESTED)
        db.session.commit()
        interested_id = interested.id

    _login(client, going_id)
    going_html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert 'id="td-participant-date-sheet"' in going_html
    assert 'id="td-participant-date-display">Full trip' in going_html

    _login(client, interested_id)
    interested_html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert 'id="td-participant-date-sheet"' not in interested_html

    _login(client, owner_id)
    owner_html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert 'id="td-participant-date-sheet"' not in owner_html


def test_trip_detail_attendance_sheet_sends_the_page_csrf_token(client):
    with app.app_context():
        _owner_id, going_id, trip_id, _participant_id = _setup_trip()

    _login(client, going_id)
    html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert "const _tdParticipantCsrf =" in html
    assert "'X-CSRF-Token': _tdParticipantCsrf" in html