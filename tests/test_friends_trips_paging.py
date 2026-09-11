"""Focused coverage for the trip-centric Friends' Trips feed."""

from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app import app
from models import Friend, GuestStatus, db
from services.friends_trips_paging import (
    FRIENDS_TRIPS_PAGE_SIZE,
    FriendsTripsCursorError,
    load_friends_trips_context,
    load_friends_trips_page,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _connect(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


def _all_rows(viewer_id, *, today=None):
    rows, cursor = [], None
    while True:
        page = load_friends_trips_page(
            viewer_id, today=today or date.today(), cursor_value=cursor
        )
        rows.extend(page.rows)
        if not page.has_more:
            return rows
        cursor = page.next_cursor


@pytest.mark.parametrize("count", [0, 1, 9, 10, 11, 21])
def test_physical_trip_page_boundaries(client, count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"friends-page-viewer-{count}")
        friend = _make_user(f"friends-page-friend-{count}")
        resort = _make_resort(f"Friends Page {count}")
        _connect(viewer, friend)
        for index in range(count):
            _make_trip(
                friend,
                resort=resort,
                trip_status="going",
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        first = load_friends_trips_page(viewer.id, today=today)
        assert len(first.rows) == min(count, FRIENDS_TRIPS_PAGE_SIZE)
        assert first.has_more is (count > FRIENDS_TRIPS_PAGE_SIZE)
        rows = _all_rows(viewer.id, today=today)
        assert len(rows) == count
        assert len({row.trip_id for row in rows}) == count


def test_same_trip_consolidates_eligible_friends_once(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-same-trip-viewer")
        owner = _make_user("z-owner")
        guest = _make_user("a-guest")
        owner.first_name = "Zoe"
        guest.first_name = "Ava"
        resort = _make_resort("Same Trip Peak")
        _connect(viewer, owner)
        _connect(viewer, guest)
        trip = _make_trip(
            owner, resort=resort, trip_status="going",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
        )
        _add_participant(trip, guest, GuestStatus.GOING)
        db.session.commit()

        rows = load_friends_trips_page(viewer.id, today=today).rows
        assert len(rows) == 1
        assert rows[0].trip_id == trip.id
        assert rows[0].friend_ids == (guest.id, owner.id)
        assert rows[0].friend_names == ("Ava", "Zoe")


def test_identical_destination_and_dates_keep_distinct_trip_ids(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-distinct-viewer")
        friend = _make_user("friends-distinct-friend")
        resort = _make_resort("Telluride")
        _connect(viewer, friend)
        trips = [
            _make_trip(
                friend, resort=resort, trip_status="going",
                start_date=today + timedelta(days=3),
                end_date=today + timedelta(days=6),
            )
            for _ in range(2)
        ]
        db.session.commit()
        rows = load_friends_trips_page(viewer.id, today=today).rows
        assert [row.trip_id for row in rows] == [trip.id for trip in trips]


def test_only_authorized_going_activity_is_visible(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-rules-viewer")
        owner = _make_user("friends-rules-owner")
        going = _make_user("friends-rules-going")
        interested = _make_user("friends-rules-interested")
        outsider = _make_user("friends-rules-outsider")
        resort = _make_resort("Rules Peak")
        for friend in (owner, going, interested):
            _connect(viewer, friend)
        planning = _make_trip(
            owner, resort=resort, trip_status="planning",
            start_date=today + timedelta(days=2), end_date=today + timedelta(days=5),
        )
        _add_participant(planning, going, GuestStatus.GOING)
        _add_participant(planning, interested, GuestStatus.INTERESTED)
        _add_participant(planning, outsider, GuestStatus.GOING)
        private = _make_trip(owner, resort=resort, trip_status="going", is_public=False)
        terminal = _make_trip(owner, resort=resort, trip_status="going")
        terminal.lifecycle_state = "cancelled"
        db.session.commit()

        rows = load_friends_trips_page(viewer.id, today=today).rows
        assert [(row.trip_id, row.friend_ids) for row in rows] == [
            (planning.id, (going.id,))
        ]
        assert private.id not in {row.trip_id for row in rows}
        assert terminal.id not in {row.trip_id for row in rows}


def test_ended_effective_attendance_is_excluded(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-attendance-viewer")
        owner = _make_user("friends-attendance-owner")
        guest = _make_user("friends-attendance-guest")
        _connect(viewer, owner)
        _connect(viewer, guest)
        trip = _make_trip(
            owner, trip_status="planning",
            start_date=today - timedelta(days=4),
            end_date=today + timedelta(days=4),
        )
        attendance = _add_participant(trip, guest, GuestStatus.GOING)
        attendance.start_date = today - timedelta(days=3)
        attendance.end_date = today - timedelta(days=1)
        db.session.commit()
        assert load_friends_trips_page(viewer.id, today=today).rows == []


def test_overlap_uses_friend_effective_attendance(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-overlap-viewer")
        owner = _make_user("friends-overlap-owner")
        guest = _make_user("friends-overlap-guest")
        resort = _make_resort("Effective Overlap Peak")
        _connect(viewer, owner)
        _connect(viewer, guest)
        _make_trip(
            viewer, resort=resort, trip_status="going",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=3),
        )
        friend_trip = _make_trip(
            owner, resort=resort, trip_status="planning",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=6),
        )
        attendance = _add_participant(friend_trip, guest, GuestStatus.GOING)
        attendance.start_date = today + timedelta(days=5)
        attendance.end_date = today + timedelta(days=6)
        db.session.commit()
        row = load_friends_trips_page(viewer.id, today=today).rows[0]
        assert row.overlaps_viewer_trip is False


def test_interested_viewer_participation_does_not_create_overlap(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-overlap-interested-viewer")
        friend = _make_user("friends-overlap-visible-friend")
        other_owner = _make_user("friends-overlap-other-owner")
        resort = _make_resort("Interested Overlap Peak")
        _connect(viewer, friend)
        interested_trip = _make_trip(
            other_owner, resort=resort, trip_status="going",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=3),
        )
        _add_participant(interested_trip, viewer, GuestStatus.INTERESTED)
        _make_trip(
            friend, resort=resort, trip_status="going",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
        )
        db.session.commit()
        row = load_friends_trips_page(viewer.id, today=today).rows[0]
        assert row.overlaps_viewer_trip is False


def test_ordering_is_date_destination_then_trip_id(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-order-viewer")
        friend = _make_user("friends-order-friend")
        _connect(viewer, friend)
        zulu = _make_resort("Zulu")
        alpha = _make_resort("Alpha")
        later = _make_trip(
            friend, resort=alpha, trip_status="going",
            start_date=today + timedelta(days=5), end_date=today + timedelta(days=6),
        )
        zulu_trip = _make_trip(
            friend, resort=zulu, trip_status="going",
            start_date=today + timedelta(days=2), end_date=today + timedelta(days=3),
        )
        alpha_trip = _make_trip(
            friend, resort=alpha, trip_status="going",
            start_date=today + timedelta(days=2), end_date=today + timedelta(days=3),
        )
        db.session.commit()
        assert [row.trip_id for row in load_friends_trips_page(
            viewer.id, today=today
        ).rows] == [alpha_trip.id, zulu_trip.id, later.id]


def test_context_distinguishes_no_friends_from_no_visible_trips(client):
    with app.app_context():
        viewer = _make_user("friends-context-viewer")
        friend = _make_user("friends-context-friend")
        assert load_friends_trips_context(viewer.id) == ([], False)
        _connect(viewer, friend)
        db.session.commit()
        assert load_friends_trips_context(viewer.id) == ([], True)


def test_cursor_is_viewer_bound_and_filter_is_rejected(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-cursor-viewer")
        other = _make_user("friends-cursor-other")
        friend = _make_user("friends-cursor-friend")
        _connect(viewer, friend)
        for index in range(FRIENDS_TRIPS_PAGE_SIZE + 1):
            _make_trip(
                friend, trip_status="going",
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        cursor = load_friends_trips_page(viewer.id, today=today).next_cursor
        with pytest.raises(FriendsTripsCursorError):
            load_friends_trips_page(other.id, today=today, cursor_value=cursor)
        with pytest.raises(FriendsTripsCursorError):
            load_friends_trips_page(viewer.id, today=today, destination_key="m:any")


def test_friends_tab_and_page_endpoint_render_trip_ledger(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-route-viewer")
        owner = _make_user("friends-route-owner")
        guest = _make_user("friends-route-guest")
        owner.first_name = "Elena"
        guest.first_name = "Jonah"
        _connect(viewer, owner)
        _connect(viewer, guest)
        trip = _make_trip(
            owner, resort=_make_resort("Telluride"), trip_status="going",
            start_date=today + timedelta(days=2), end_date=today + timedelta(days=4),
        )
        _add_participant(trip, guest, GuestStatus.GOING)
        _make_trip(
            viewer, resort=trip.resort, trip_status="going",
            start_date=today + timedelta(days=1), end_date=today + timedelta(days=3),
        )
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
    _login(client, viewer_id)
    response = client.get("/my-trips?tab=friends")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Elena, Jonah" in html
    assert ">Overlap<" in html
    assert "Overlaps your dates" not in html
    assert "1 trip" in html
    assert "1 entry" not in html
    assert "Friends' Trips destination" not in html
    assert "Filter for a mountain" not in html
    assert 'href="/my-trips?tab=friends"' in html
    assert "view-tab active" in html

    payload = client.get("/api/my-trips/friends/page").get_json()
    assert payload["unit_ids"] == [f"t:{trip_id}"]
    assert "friends-row" in payload["html"]


def test_friends_empty_states_render_distinct_copy_and_actions(client):
    with app.app_context():
        no_friends = _make_user("friends-empty-none")
        has_friend = _make_user("friends-empty-connected")
        friend = _make_user("friends-empty-connected-friend")
        _connect(has_friend, friend)
        db.session.commit()
        no_friends_id = no_friends.id
        has_friend_id = has_friend.id

    _login(client, no_friends_id)
    no_friends_html = client.get("/my-trips?tab=friends").get_data(as_text=True)
    assert "You haven't added any friends yet." in no_friends_html
    assert 'href="/friends">Find friends →</a>' in no_friends_html
    assert "Invite friends →" not in no_friends_html

    _login(client, has_friend_id)
    no_trips_html = client.get("/my-trips?tab=friends").get_data(as_text=True)
    assert "No trips planned yet." in no_trips_html
    assert "None of your friends have upcoming trips." in no_trips_html
    assert 'href="/invite">Invite friends →</a>' in no_trips_html
    assert "Find friends →" not in no_trips_html


def test_page_query_budget_is_fixed(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("friends-budget-viewer")
        friend = _make_user("friends-budget-friend")
        _connect(viewer, friend)
        for index in range(FRIENDS_TRIPS_PAGE_SIZE):
            _make_trip(
                friend, resort=_make_resort(f"Budget {index}"), trip_status="going",
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine
        statements = []
        def record(_connection, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            load_friends_trips_page(viewer_id, today=today)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(statements) <= 4