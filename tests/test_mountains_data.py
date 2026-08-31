"""Focused BL-120 coverage for Mountains friend-count privacy."""
from datetime import date, timedelta

import pytest

import app as app_module
from app import app, get_all_active_resorts_map
from conftest import _login, _make_resort, _make_trip, _make_user
from models import Friend, GuestStatus, Resort, SkiTripParticipant, User, db


@pytest.fixture(autouse=True)
def _clear_mountains_caches():
    app_module._mountains_cache.clear()
    get_all_active_resorts_map.cache_clear()
    yield
    app_module._mountains_cache.clear()
    get_all_active_resorts_map.cache_clear()


def _connect(viewer, friend):
    db.session.add(Friend(user_id=viewer.id, friend_id=friend.id))


def _friend_count(client, resort_id):
    response = client.get("/api/mountains-data")
    assert response.status_code == 200
    resorts = {resort["id"]: resort for resort in response.get_json()["resorts"]}
    return resorts[resort_id]["friend_count"]


def test_private_friend_trip_does_not_change_friend_count(client):
    with app.app_context():
        viewer = _make_user("private-viewer")
        friend = _make_user("private-friend")
        resort = _make_resort("Private Count Peak")
        _connect(viewer, friend)
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 0

    with app.app_context():
        friend = db.session.get(User, friend_id)
        resort = db.session.get(Resort, resort_id)
        _make_trip(friend, resort=resort, is_public=False)
        db.session.commit()

    app_module._mountains_cache.clear()
    assert _friend_count(client, resort_id) == 0


def test_public_friend_trips_count_each_friend_once(client):
    with app.app_context():
        viewer = _make_user("public-viewer")
        friend = _make_user("public-friend")
        resort = _make_resort("Public Count Peak")
        _connect(viewer, friend)
        _make_trip(friend, resort=resort)
        _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1


def test_nonfriend_public_trip_does_not_count(client):
    with app.app_context():
        viewer = _make_user("nonfriend-viewer")
        nonfriend = _make_user("nonfriend-owner")
        resort = _make_resort("Nonfriend Count Peak")
        _make_trip(nonfriend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 0


def test_past_and_future_public_friend_trips_still_count(client):
    with app.app_context():
        viewer = _make_user("date-viewer")
        past_friend = _make_user("past-friend")
        future_friend = _make_user("future-friend")
        resort = _make_resort("Date Count Peak")
        _connect(viewer, past_friend)
        _connect(viewer, future_friend)
        today = date.today()
        _make_trip(
            past_friend,
            resort=resort,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=8),
        )
        _make_trip(
            future_friend,
            resort=resort,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=12),
        )
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 2


def test_terminal_public_friend_trips_do_not_count(client):
    with app.app_context():
        viewer = _make_user("terminal-date-viewer")
        completed_friend = _make_user("completed-friend")
        cancelled_friend = _make_user("cancelled-friend")
        active_friend = _make_user("active-friend")
        resort = _make_resort("Terminal Count Peak")
        for friend in (completed_friend, cancelled_friend, active_friend):
            _connect(viewer, friend)

        today = date.today()
        completed = _make_trip(
            completed_friend,
            resort=resort,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=8),
        )
        completed.lifecycle_state = "completed"
        cancelled = _make_trip(
            cancelled_friend,
            resort=resort,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=12),
        )
        cancelled.lifecycle_state = "cancelled"
        _make_trip(
            active_friend,
            resort=resort,
            start_date=today + timedelta(days=20),
            end_date=today + timedelta(days=22),
        )
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1


@pytest.mark.parametrize(
    "participant_status",
    [
        GuestStatus.PENDING,
        GuestStatus.INTERESTED,
        GuestStatus.GOING,
        GuestStatus.DECLINED,
        GuestStatus.REMOVED,
        GuestStatus.INVITED,
        GuestStatus.ACCEPTED,
    ],
)
def test_public_friend_trip_count_remains_independent_of_participant_status(
    client, participant_status
):
    with app.app_context():
        viewer = _make_user(f"status-viewer-{participant_status.value}")
        friend = _make_user(f"status-friend-{participant_status.value}")
        resort = _make_resort(f"Status Count Peak {participant_status.value}")
        _connect(viewer, friend)
        trip = _make_trip(friend, resort=resort)
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=friend.id,
        ).one()
        participant.status = participant_status
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1