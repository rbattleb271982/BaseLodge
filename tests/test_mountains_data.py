"""Focused coverage for Mountains friend-count privacy and freshness."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event

from app import app, get_all_active_resorts_map
from conftest import _login, _make_resort, _make_trip, _make_user
from models import Friend, GuestStatus, Resort, SkiTrip, SkiTripParticipant, User, db


@pytest.fixture(autouse=True)
def _clear_resort_cache():
    get_all_active_resorts_map.cache_clear()
    yield
    get_all_active_resorts_map.cache_clear()


def _connect(viewer, friend):
    db.session.add_all([
        Friend(user_id=viewer.id, friend_id=friend.id),
        Friend(user_id=friend.id, friend_id=viewer.id),
    ])


def _mountains_response(client, **kwargs):
    response = client.get("/api/mountains-data", **kwargs)
    assert response.status_code == 200
    return response


def _friend_count(client, resort_id):
    response = _mountains_response(client)
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


def test_public_friend_trip_creation_refreshes_a_previously_zero_count(client):
    with app.app_context():
        viewer = _make_user("fresh-create-viewer")
        friend = _make_user("fresh-create-friend")
        resort = _make_resort("Fresh Create Peak")
        _connect(viewer, friend)
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 0

    with app.app_context():
        _make_trip(
            db.session.get(User, friend_id),
            resort=db.session.get(Resort, resort_id),
        )
        db.session.commit()

    assert _friend_count(client, resort_id) == 1


@pytest.mark.parametrize("terminal_state", ["cancelled", "completed"])
def test_terminal_transition_refreshes_friend_count(client, terminal_state):
    with app.app_context():
        viewer = _make_user(f"fresh-{terminal_state}-viewer")
        friend = _make_user(f"fresh-{terminal_state}-friend")
        resort = _make_resort(f"Fresh {terminal_state.title()} Peak")
        _connect(viewer, friend)
        trip = _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1

    with app.app_context():
        db.session.get(SkiTrip, trip_id).lifecycle_state = terminal_state
        db.session.commit()

    assert _friend_count(client, resort_id) == 0


def test_resort_reassignment_refreshes_both_friend_counts(client):
    with app.app_context():
        viewer = _make_user("fresh-resort-viewer")
        friend = _make_user("fresh-resort-friend")
        old_resort = _make_resort("Fresh Old Peak")
        new_resort = _make_resort("Fresh New Peak")
        _connect(viewer, friend)
        trip = _make_trip(friend, resort=old_resort)
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
        old_resort_id = old_resort.id
        new_resort_id = new_resort.id

    _login(client, viewer_id)
    assert _friend_count(client, old_resort_id) == 1
    assert _friend_count(client, new_resort_id) == 0

    with app.app_context():
        db.session.get(SkiTrip, trip_id).resort_id = new_resort_id
        db.session.commit()

    assert _friend_count(client, old_resort_id) == 0
    assert _friend_count(client, new_resort_id) == 1


def test_visibility_changes_refresh_friend_count_in_both_directions(client):
    with app.app_context():
        viewer = _make_user("fresh-visibility-viewer")
        friend = _make_user("fresh-visibility-friend")
        resort = _make_resort("Fresh Visibility Peak")
        _connect(viewer, friend)
        trip = _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1

    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        trip.is_public = False
        db.session.commit()
    assert _friend_count(client, resort_id) == 0

    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        trip.is_public = True
        db.session.commit()
    assert _friend_count(client, resort_id) == 1


def test_friendship_changes_refresh_friend_count_in_both_directions(client):
    with app.app_context():
        viewer = _make_user("fresh-friendship-viewer")
        friend = _make_user("fresh-friendship-friend")
        resort = _make_resort("Fresh Friendship Peak")
        _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 0

    with app.app_context():
        _connect(
            db.session.get(User, viewer_id),
            db.session.get(User, friend_id),
        )
        db.session.commit()
    assert _friend_count(client, resort_id) == 1

    with app.app_context():
        Friend.query.filter(
            Friend.user_id.in_((viewer_id, friend_id)),
            Friend.friend_id.in_((viewer_id, friend_id)),
        ).delete(synchronize_session=False)
        db.session.commit()
    assert _friend_count(client, resort_id) == 0


def test_one_way_friendship_does_not_count(client):
    with app.app_context():
        viewer = _make_user("one-way-viewer")
        friend = _make_user("one-way-friend")
        resort = _make_resort("One Way Peak")
        db.session.add(Friend(user_id=viewer.id, friend_id=friend.id))
        _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 0


def test_non_count_trip_and_participant_changes_remain_no_ops(client):
    with app.app_context():
        viewer = _make_user("no-op-viewer")
        friend = _make_user("no-op-friend")
        resort = _make_resort("No-op Peak")
        _connect(viewer, friend)
        trip = _make_trip(friend, resort=resort)
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=friend.id,
        ).one()
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
        participant_id = participant.id
        resort_id = resort.id

    _login(client, viewer_id)
    assert _friend_count(client, resort_id) == 1

    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        trip.start_date += timedelta(days=10)
        trip.end_date += timedelta(days=10)
        trip.trip_status = "going"
        participant = db.session.get(SkiTripParticipant, participant_id)
        participant.status = GuestStatus.INVITED
        participant.attendance_start_date = trip.start_date
        participant.attendance_end_date = trip.end_date
        db.session.commit()
    assert _friend_count(client, resort_id) == 1

    with app.app_context():
        participant = db.session.get(SkiTripParticipant, participant_id)
        participant.status = GuestStatus.DECLINED
        participant.attendance_start_date = None
        participant.attendance_end_date = None
        db.session.commit()
    assert _friend_count(client, resort_id) == 1


def test_personalized_response_is_non_storable_and_never_returns_304(client):
    with app.app_context():
        viewer = _make_user("cache-policy-viewer")
        _make_resort("Cache Policy Peak")
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    first = _mountains_response(client)
    assert first.headers["Cache-Control"] == "private, no-store"
    assert "ETag" not in first.headers

    second = _mountains_response(
        client,
        headers={"If-None-Match": '"previous-personalized-response"'},
    )
    assert second.headers["Cache-Control"] == "private, no-store"
    assert "ETag" not in second.headers


def test_mountains_frontend_fetches_fresh_data_on_every_pageshow():
    source = Path("templates/mountains_tab.html").read_text()
    assert "fetch('/api/mountains-data', { cache: 'no-store' })" in source
    pageshow = source.split(
        "window.addEventListener('pageshow'", 1
    )[1].split("initializeFilterEducation()", 1)[0]
    assert "loadMountainsData();" in pageshow
    assert "resetFilters();\n            return;" not in pageshow


def test_friend_count_query_remains_one_grouped_query(client):
    with app.app_context():
        viewer = _make_user("query-budget-viewer")
        resort = _make_resort("Query Budget Peak")
        for index in range(4):
            friend = _make_user(f"query-budget-friend-{index}")
            _connect(viewer, friend)
            _make_trip(friend, resort=resort)
            _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        resort_id = resort.id

    _login(client, viewer_id)
    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    with app.app_context():
        engine = db.engine
        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            assert _friend_count(client, resort_id) == 4
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)

    trip_queries = [
        statement for statement in statements
        if "from ski_trip" in statement
    ]
    assert len(trip_queries) == 1
    assert "group by ski_trip.resort_id" in trip_queries[0]
    assert "count(distinct" in trip_queries[0]
