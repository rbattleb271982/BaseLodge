from datetime import date, timedelta

from app import app
from models import (
    GuestStatus,
    Invitation,
    InviteType,
    SkiTrip,
    User,
    UserAvailability,
    db,
)
from services.open_dates import (
    get_available_dates_for_user,
    remove_availability_overlapping_ranges,
    replace_current_availability,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_trip,
    _make_user,
    json_post,
)


def _future(days):
    return date.today() + timedelta(days=days)


def _set_availability(user, *days):
    replace_current_availability(user, [day.isoformat() for day in days])
    db.session.commit()


def test_remove_overlap_preserves_both_sides_of_partial_range(client):
    with app.app_context():
        user = _make_user("bl236-split")
        available = [_future(offset) for offset in range(10, 21)]
        _set_availability(user, *available)

        result = remove_availability_overlapping_ranges(
            user, [(_future(15), _future(18))]
        )
        db.session.commit()

        assert result["removed"] == {
            _future(offset).isoformat() for offset in range(15, 19)
        }
        assert get_available_dates_for_user(user) == {
            _future(offset).isoformat()
            for offset in [10, 11, 12, 13, 14, 19, 20]
        }


def test_remove_overlap_handles_multiple_availability_ranges_and_trips(client):
    with app.app_context():
        user = _make_user("bl236-multiple")
        available = [
            *[_future(offset) for offset in range(10, 13)],
            *[_future(offset) for offset in range(20, 24)],
            _future(30),
        ]
        _set_availability(user, *available)

        remove_availability_overlapping_ranges(
            user,
            [
                (_future(11), _future(21)),
                (_future(23), _future(25)),
            ],
        )
        db.session.commit()

        assert get_available_dates_for_user(user) == {
            _future(10).isoformat(),
            _future(22).isoformat(),
            _future(30).isoformat(),
        }


def test_overlapping_trip_create_queues_choice_without_mutating_availability(client):
    with app.app_context():
        user = _make_user("bl236-create")
        user_id = user.id
        _set_availability(
            user, _future(40), _future(41), _future(42), _future(43)
        )

    _login(client, user_id)
    response = json_post(client, "/api/trip/create", {
        "mountain": "Choice Peak",
        "state": "CO",
        "start_date": _future(41).isoformat(),
        "end_date": _future(42).isoformat(),
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["availability_overlap_prompt"]["dates"]
    with app.app_context():
        user = db.session.get(User, user_id)
        assert get_available_dates_for_user(user) == {
            _future(offset).isoformat() for offset in range(40, 44)
        }


def test_nonoverlapping_and_failed_trip_creates_do_not_queue_choice(client):
    with app.app_context():
        user = _make_user("bl236-no-prompt")
        user_id = user.id
        _set_availability(user, _future(50))

    _login(client, user_id)
    nonoverlap = json_post(client, "/api/trip/create", {
        "mountain": "Later Peak",
        "state": "CO",
        "start_date": _future(60).isoformat(),
        "end_date": _future(61).isoformat(),
    })
    failed = json_post(client, "/api/trip/create", {
        "mountain": "Broken Peak",
        "state": "CO",
        "start_date": _future(62).isoformat(),
    })

    assert nonoverlap.status_code == 200
    assert nonoverlap.get_json()["availability_overlap_prompt"] is None
    assert failed.status_code == 400
    with client.session_transaction() as session_state:
        assert "availability_trip_overlap_prompt" not in session_state


def test_keep_choice_performs_no_availability_mutation(client):
    with app.app_context():
        user = _make_user("bl236-keep")
        user_id = user.id
        _set_availability(user, _future(70), _future(71), _future(72))
        trip = _make_trip(
            user, start_date=_future(71), end_date=_future(72)
        )
        db.session.commit()
        trip_id = trip.id

    _login(client, user_id)
    with client.session_transaction() as session_state:
        session_state["availability_trip_overlap_prompt"] = {
            "trip_ids": [trip_id],
            "overlap_dates": [
                _future(71).isoformat(),
                _future(72).isoformat(),
            ],
            "dates": "test",
            "trip_label": "test",
        }
    response = json_post(
        client, "/api/availability/trip-overlap", {"action": "keep"}
    )

    assert response.status_code == 200
    assert response.get_json()["removed_count"] == 0
    with app.app_context():
        user = db.session.get(User, user_id)
        assert get_available_dates_for_user(user) == {
            _future(offset).isoformat() for offset in range(70, 73)
        }


def test_joining_overlapping_trip_queues_choice_then_removes_exact_dates(client):
    with app.app_context():
        owner = _make_user("bl236-join-owner")
        guest = _make_user("bl236-join-guest")
        guest_id = guest.id
        _set_availability(
            guest, _future(80), _future(81), _future(82), _future(83)
        )
        trip = _make_trip(
            owner, start_date=_future(81), end_date=_future(82)
        )
        _add_participant(trip, guest, GuestStatus.PENDING)
        db.session.commit()
        trip_id = trip.id

    _login(client, guest_id)
    joined = json_post(
        client, f"/trips/{trip_id}/respond", {"response": "going"}
    )
    assert joined.status_code == 200
    assert joined.get_json()["availability_overlap_prompt"]["dates"]

    removed = json_post(
        client, "/api/availability/trip-overlap", {"action": "remove"}
    )
    assert removed.status_code == 200
    assert removed.get_json()["removed_count"] == 2
    with app.app_context():
        guest = db.session.get(User, guest_id)
        assert get_available_dates_for_user(guest) == {
            _future(80).isoformat(),
            _future(83).isoformat(),
        }
        assert UserAvailability.query.filter_by(user_id=guest_id).count() == 2


def test_owner_accepted_join_request_prompts_requester_on_next_trip_view(client):
    with app.app_context():
        owner = _make_user("bl236-request-owner")
        requester = _make_user("bl236-requester")
        owner_id, requester_id = owner.id, requester.id
        _set_availability(requester, _future(90), _future(91))
        trip = _make_trip(
            owner, start_date=_future(90), end_date=_future(92)
        )
        join_request = Invitation(
            sender_id=requester.id,
            receiver_id=owner.id,
            trip_id=trip.id,
            invite_type=InviteType.REQUEST,
            status="pending",
        )
        db.session.add(join_request)
        db.session.commit()
        trip_id, request_id = trip.id, join_request.id

    _login(client, owner_id)
    accepted = json_post(
        client,
        f"/trips/requests/{request_id}/respond",
        {"action": "accept"},
    )
    assert accepted.status_code == 200

    _login(client, requester_id)
    detail = client.get(f"/trips/{trip_id}")
    assert detail.status_code == 200
    assert b"Update your availability?" in detail.data
    assert b"Remove overlapping dates" in detail.data

    kept = json_post(
        client, "/api/availability/trip-overlap", {"action": "keep"}
    )
    assert kept.status_code == 200

    fresh_client = app.test_client()
    _login(fresh_client, requester_id)
    revisit = fresh_client.get(f"/trips/{trip_id}")
    assert revisit.status_code == 200
    assert b"Update your availability?" not in revisit.data


def test_remove_uses_prompt_snapshot_when_trip_dates_change(client):
    with app.app_context():
        user = _make_user("bl236-snapshot")
        user_id = user.id
        _set_availability(
            user, _future(100), _future(101), _future(102), _future(103)
        )
        trip = _make_trip(
            user, start_date=_future(101), end_date=_future(102)
        )
        db.session.commit()
        trip_id = trip.id

    _login(client, user_id)
    with client.session_transaction() as session_state:
        session_state["availability_trip_overlap_prompt"] = {
            "trip_ids": [trip_id],
            "overlap_dates": [
                _future(101).isoformat(),
                _future(102).isoformat(),
            ],
            "dates": "test",
            "trip_label": "test",
        }
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        trip.start_date = _future(102)
        trip.end_date = _future(103)
        db.session.commit()

    response = json_post(
        client, "/api/availability/trip-overlap", {"action": "remove"}
    )
    assert response.status_code == 200
    assert response.get_json()["removed_count"] == 2
    with app.app_context():
        user = db.session.get(User, user_id)
        assert get_available_dates_for_user(user) == {
            _future(100).isoformat(),
            _future(103).isoformat(),
        }