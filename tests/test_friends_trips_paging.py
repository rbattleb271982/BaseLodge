"""Focused BL-159 Friends' Trips service coverage."""

from datetime import date, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app import app
from models import Friend, GuestStatus, SkiTrip, db
from services.friends_trips_paging import (
    FRIENDS_TRIPS_DETAIL_PAGE_SIZE,
    FRIENDS_TRIPS_PAGE_SIZE,
    FriendsTripsGroupError,
    _display_units_query,
    _group_claims,
    _group_detail_query,
    load_friends_trips_destinations,
    load_friends_trips_group,
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


def _all_units(viewer_id, destination_key=None):
    result = []
    cursor = None
    while True:
        page = load_friends_trips_page(
            viewer_id,
            today=date.today(),
            destination_key=destination_key,
            cursor_value=cursor,
        )
        result.extend(page.rows)
        if not page.has_more:
            return result
        cursor = page.next_cursor


@pytest.mark.parametrize("count", [0, 1, 2, 3, 9, 10, 11, 20, 21])
def test_complete_unit_page_boundaries(client, count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"ft-boundary-viewer-{count}")
        resort = _make_resort(f"FT Boundary {count}")
        friends = []
        for index in range(count):
            friend = _make_user(f"ft-boundary-friend-{count}-{index}")
            _connect(viewer, friend)
            _make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            friends.append(friend)
        db.session.commit()

        first = load_friends_trips_page(viewer.id, today=today)
        assert len(first.rows) == min(count, FRIENDS_TRIPS_PAGE_SIZE)
        assert first.has_more is (count > FRIENDS_TRIPS_PAGE_SIZE)
        rows = _all_units(viewer.id)
        assert len(rows) == count
        assert len({(row.friend_id, row.trip_id) for row in rows}) == count


def test_grouping_uses_friend_destination_status_and_never_embeds_details(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-group-viewer")
        friend = _make_user("ft-group-friend")
        other = _make_user("ft-group-other")
        resort = _make_resort("FT Group Peak")
        _connect(viewer, friend)
        _connect(viewer, other)
        trip_ids = []
        for offset in (1, 3, 5):
            trip_ids.append(_make_trip(
                friend,
                resort=resort,
                trip_status="planning",
                start_date=today + timedelta(days=offset),
                end_date=today + timedelta(days=offset + 1),
            ).id)
        # Same destination but a different friend and status are separate units.
        _make_trip(other, resort=resort, trip_status="planning")
        _make_trip(friend, resort=resort, trip_status="going")
        db.session.commit()

        page = load_friends_trips_page(viewer.id, today=today)
        grouped = [row for row in page.rows if row.grouped]
        assert len(grouped) == 1
        assert grouped[0].grouped_count == 3
        assert grouped[0].trip is None
        assert grouped[0].trip_id is None
        assert grouped[0].group_token

        details = load_friends_trips_group(
            viewer.id, grouped[0].group_token, today=today
        )
        assert [row.trip_id for row in details.rows] == trip_ids


def test_exact_visibility_attendance_and_dedup_rules(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-rules-viewer")
        owner = _make_user("ft-rules-owner")
        going_friend = _make_user("ft-rules-going")
        one_sided = _make_user("ft-rules-one-sided")
        outsider = _make_user("ft-rules-outsider")
        resort = _make_resort("FT Rules Peak")
        _connect(viewer, owner)
        _connect(viewer, going_friend)
        db.session.add(Friend(user_id=viewer.id, friend_id=one_sided.id))

        trip = _make_trip(
            owner, resort=resort, start_date=today, end_date=today + timedelta(days=9)
        )
        attendance = _add_participant(trip, going_friend, GuestStatus.GOING)
        attendance.start_date = today + timedelta(days=4)
        attendance.end_date = today + timedelta(days=5)
        _add_participant(trip, outsider, GuestStatus.GOING)
        private = _make_trip(owner, resort=resort, is_public=False)
        terminal = _make_trip(owner, resort=resort)
        terminal.lifecycle_state = "cancelled"
        stale = _make_trip(one_sided, resort=resort)
        db.session.commit()

        rows = _all_units(viewer.id)
        pairs = {(row.friend_id, row.trip_id) for row in rows}
        assert pairs == {(owner.id, trip.id), (going_friend.id, trip.id)}
        guest_row = next(row for row in rows if row.friend_id == going_friend.id)
        assert guest_row.attendance_start_date == attendance.start_date
        assert private.id not in {row.trip_id for row in rows}
        assert terminal.id not in {row.trip_id for row in rows}
        assert stale.id not in {row.trip_id for row in rows}


def test_destination_options_are_complete_and_filter_is_server_side(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-options-viewer")
        destinations = []
        for index in range(13):
            friend = _make_user(f"ft-options-friend-{index}")
            resort = _make_resort(f"FT Option {index:02d}")
            _connect(viewer, friend)
            _make_trip(friend, resort=resort)
            destinations.append((resort.id, resort.name))
        db.session.commit()

        first = load_friends_trips_page(viewer.id, today=today)
        options = load_friends_trips_destinations(viewer.id, today=today)
        assert len(first.rows) == FRIENDS_TRIPS_PAGE_SIZE
        assert [option.name for option in options] == sorted(name for _, name in destinations)
        selected = options[-1]
        rows = _all_units(viewer.id, selected.key)
        assert len(rows) == 1
        assert rows[0].destination_key == selected.key


def test_destination_grouping_preserves_display_name_identity(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-same-name-viewer")
        friend = _make_user("ft-same-name-friend")
        first_resort = _make_resort("FT Same Name Peak")
        second_resort = _make_resort("FT Same Name Peak")
        second_resort.slug = "ft-same-name-peak-duplicate"
        _connect(viewer, friend)
        for index, resort in enumerate(
            (first_resort, second_resort, first_resort), start=1
        ):
            _make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index),
            )
        db.session.commit()

        page = load_friends_trips_page(viewer.id, today=today)
        options = load_friends_trips_destinations(viewer.id, today=today)
        assert len(page.rows) == 1
        assert page.rows[0].grouped
        assert page.rows[0].grouped_count == 3
        assert [(option.key, option.name) for option in options] == [
            ("m:FT Same Name Peak", "FT Same Name Peak")
        ]


def test_group_detail_reauthorizes_and_pages_twenty(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-detail-viewer")
        friend = _make_user("ft-detail-friend")
        resort = _make_resort("FT Detail Peak")
        _connect(viewer, friend)
        for index in range(FRIENDS_TRIPS_DETAIL_PAGE_SIZE + 1):
            _make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()

        summary = load_friends_trips_page(viewer.id, today=today).rows[0]
        first = load_friends_trips_group(viewer.id, summary.group_token, today=today)
        assert len(first.rows) == FRIENDS_TRIPS_DETAIL_PAGE_SIZE
        assert first.has_more and first.next_cursor
        second = load_friends_trips_group(
            viewer.id,
            summary.group_token,
            today=today,
            cursor_value=first.next_cursor,
        )
        assert len(second.rows) == 1

        Friend.query.filter(
            ((Friend.user_id == viewer.id) & (Friend.friend_id == friend.id))
            | ((Friend.user_id == friend.id) & (Friend.friend_id == viewer.id))
        ).delete(synchronize_session=False)
        db.session.commit()
        with pytest.raises(FriendsTripsGroupError):
            load_friends_trips_group(viewer.id, summary.group_token, today=today)


@pytest.mark.parametrize("count", [3, 19, 20, 21, 40, 41, 500])
def test_group_detail_page_boundaries(client, count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"ft-detail-boundary-viewer-{count}")
        friend = _make_user(f"ft-detail-boundary-friend-{count}")
        resort = _make_resort(f"FT Detail Boundary {count}")
        _connect(viewer, friend)
        for index in range(count):
            _make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
            )
        db.session.commit()
        summary = load_friends_trips_page(viewer.id, today=today).rows[0]
        rows = []
        cursor = None
        while True:
            page = load_friends_trips_group(
                viewer.id,
                summary.group_token,
                today=today,
                cursor_value=cursor,
            )
            rows.extend(page.rows)
            if not page.has_more:
                break
            cursor = page.next_cursor
        assert len(rows) == count
        assert len({row.trip_id for row in rows}) == count


@pytest.mark.parametrize("source_count", [10, 50, 100, 500])
def test_feed_hydration_is_bounded_by_display_units(client, source_count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"ft-cardinality-viewer-{source_count}")
        resort = _make_resort(f"FT Cardinality {source_count}")
        for index in range(source_count):
            friend = _make_user(f"ft-cardinality-friend-{source_count}-{index}")
            _connect(viewer, friend)
            _make_trip(friend, resort=resort)
        db.session.commit()
        viewer_id = viewer.id
        db.session.remove()
        loads = []

        def record(target, _context):
            loads.append(target.id)

        event.listen(SkiTrip, "load", record)
        try:
            page = load_friends_trips_page(viewer_id, today=today)
        finally:
            event.remove(SkiTrip, "load", record)
        assert len(page.rows) == FRIENDS_TRIPS_PAGE_SIZE
        assert len(loads) == FRIENDS_TRIPS_PAGE_SIZE


def test_queries_compile_for_postgresql(client):
    with app.app_context():
        display = _display_units_query(1, date.today())
        claims = {
            "v": 1,
            "viewer": 1,
            "friend": 2,
            "destination": "r:3",
            "status": "planning",
        }
        detail = _group_detail_query(1, date.today(), claims)
        for statement in (display, detail):
            compiled = str(statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            ))
            assert "ORDER BY" in compiled
            assert "row_number()" in compiled.lower()


def test_route_endpoints_and_lazy_group_details(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-route-viewer")
        grouped_friend = _make_user("ft-route-grouped")
        resort = _make_resort("FT Route Group Peak")
        _connect(viewer, grouped_friend)
        for index in range(3):
            _make_trip(
                grouped_friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 1),
            )
        for index in range(10):
            friend = _make_user(f"ft-route-friend-{index:02d}")
            _connect(viewer, friend)
            _make_trip(
                friend,
                resort=_make_resort(f"FT Route Peak {index:02d}"),
                start_date=today + timedelta(days=index + 10),
                end_date=today + timedelta(days=index + 10),
            )
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    standard = client.get("/my-trips")
    assert standard.status_code == 200
    assert "Loading friends' trips" in standard.get_data(as_text=True)

    direct = client.get("/my-trips?tab=friends")
    assert direct.status_code == 200
    html = direct.get_data(as_text=True)
    assert html.count("data-unit-id=") == FRIENDS_TRIPS_PAGE_SIZE
    assert "data-group-token=" in html
    assert "data-trip-id=" not in html

    first = client.get(
        "/api/my-trips/friends/page", query_string={"context": "1"}
    )
    assert first.status_code == 200
    payload = first.get_json()
    assert len(payload["unit_ids"]) == FRIENDS_TRIPS_PAGE_SIZE
    assert len(payload["destinations"]) == 11
    assert payload["has_more"]

    with app.app_context():
        page = load_friends_trips_page(viewer_id, today=today)
        token = next(row.group_token for row in page.rows if row.grouped)
    details = client.get(
        "/api/my-trips/friends/group", query_string={"group": token}
    )
    assert details.status_code == 200
    detail_payload = details.get_json()
    assert len(detail_payload["trip_ids"]) == 3
    assert detail_payload["html"].count("data-trip-id=") == 3


def test_route_reauthorizes_and_rejects_bad_tokens(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-route-auth-viewer")
        friend = _make_user("ft-route-auth-friend")
        resort = _make_resort("FT Route Auth Peak")
        _connect(viewer, friend)
        for index in range(3):
            _make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
            )
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id

    _login(client, viewer_id)
    first = client.get("/api/my-trips/friends/page").get_json()
    token = next(
        unit_id[2:] for unit_id in first["unit_ids"] if unit_id.startswith("g:")
    )
    with app.app_context():
        Friend.query.filter_by(
            user_id=friend_id, friend_id=viewer_id
        ).delete()
        db.session.commit()
    assert client.get(
        "/api/my-trips/friends/group", query_string={"group": token}
    ).status_code == 400
    assert client.get(
        "/api/my-trips/friends/group",
        query_string={"group": "not-a-token"},
    ).status_code == 400
    assert client.get(
        "/api/my-trips/friends/page",
        query_string={"cursor": "not-a-cursor"},
    ).status_code == 400


@pytest.mark.parametrize(
    "mutation",
    [
        "friendship",
        "private",
        "completed",
        "past",
        "interested",
        "declined",
        "removed",
    ],
)
def test_group_detail_reauthorizes_after_every_eligibility_mutation(
    client, mutation
):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"ft-mutation-viewer-{mutation}")
        friend = _make_user(f"ft-mutation-friend-{mutation}")
        owner = _make_user(f"ft-mutation-owner-{mutation}")
        resort = _make_resort(f"FT Mutation Peak {mutation}")
        _connect(viewer, friend)
        _connect(viewer, owner)
        trips = []
        participants = []
        for index in range(3):
            trip = _make_trip(
                owner,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            participants.append(_add_participant(
                trip, friend, GuestStatus.GOING
            ))
            trips.append(trip)
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        token = next(
            row.group_token
            for row in load_friends_trips_page(viewer_id, today=today).rows
            if row.friend_id == friend_id and row.grouped
        )

        if mutation == "friendship":
            Friend.query.filter_by(
                user_id=friend_id, friend_id=viewer_id
            ).delete()
        elif mutation == "private":
            trips[0].is_public = False
        elif mutation == "completed":
            trips[0].lifecycle_state = "completed"
        elif mutation == "past":
            participants[0].start_date = today - timedelta(days=2)
            participants[0].end_date = today - timedelta(days=1)
        else:
            participants[0].status = {
                "interested": GuestStatus.INTERESTED,
                "declined": GuestStatus.DECLINED,
                "removed": GuestStatus.REMOVED,
            }[mutation]
        db.session.commit()

    _login(client, viewer_id)
    response = client.get(
        "/api/my-trips/friends/group", query_string={"group": token}
    )
    assert response.status_code == 400


def test_feed_and_detail_continuations_reauthorize_mutations(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-continuation-viewer")
        resort = _make_resort("FT Continuation Peak")
        friends = []
        trips = []
        for index in range(11):
            friend = _make_user(f"ft-continuation-{index:02d}")
            _connect(viewer, friend)
            friends.append(friend)
            trips.append(_make_trip(
                friend,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
            ))
        grouped_friend = _make_user("ft-continuation-grouped")
        _connect(viewer, grouped_friend)
        grouped_trips = [
            _make_trip(
                grouped_friend,
                resort=_make_resort("FT Detail Continuation Peak"),
                start_date=today + timedelta(days=index + 30),
            )
            for index in range(21)
        ]
        db.session.commit()
        viewer_id = viewer.id
        grouped_friend_id = grouped_friend.id
        hidden_trip_id = trips[-1].id
        detail_hidden_id = grouped_trips[-1].id

    _login(client, viewer_id)
    first_feed = client.get("/api/my-trips/friends/page").get_json()
    with app.app_context():
        db.session.get(SkiTrip, hidden_trip_id).is_public = False
        db.session.commit()
    second_feed = client.get(
        "/api/my-trips/friends/page",
        query_string={"cursor": first_feed["next_cursor"]},
    ).get_json()
    assert hidden_trip_id not in {
        int(unit_id.rsplit(":", 1)[-1])
        for unit_id in second_feed["unit_ids"]
        if unit_id.startswith("t:")
    }

    with app.app_context():
        token = next(
            row.group_token
            for row in load_friends_trips_page(
                viewer_id,
                today=today,
                destination_key="m:FT Detail Continuation Peak",
            ).rows
            if row.friend_id == grouped_friend_id and row.grouped
        )
    first_detail = client.get(
        "/api/my-trips/friends/group", query_string={"group": token}
    ).get_json()
    with app.app_context():
        db.session.get(SkiTrip, detail_hidden_id).lifecycle_state = "cancelled"
        db.session.commit()
    second_detail = client.get(
        "/api/my-trips/friends/group",
        query_string={
            "group": token,
            "cursor": first_detail["next_cursor"],
        },
    ).get_json()
    assert detail_hidden_id not in second_detail["trip_ids"]


def test_friends_trips_tokens_are_viewer_bound(client):
    today = date.today()
    with app.app_context():
        first_viewer = _make_user("ft-token-first")
        second_viewer = _make_user("ft-token-second")
        friend = _make_user("ft-token-friend")
        _connect(first_viewer, friend)
        for index in range(12):
            _make_trip(
                friend,
                resort=_make_resort(f"FT Token Peak {index:02d}"),
                start_date=today + timedelta(days=index + 1),
            )
        group_resort = _make_resort("FT Token Group Peak")
        for index in range(3):
            _make_trip(
                friend,
                resort=group_resort,
                start_date=today + timedelta(days=index + 30),
            )
        db.session.commit()
        first_id = first_viewer.id
        second_id = second_viewer.id

    _login(client, first_id)
    first_payload = client.get(
        "/api/my-trips/friends/page", query_string={"context": "1"}
    ).get_json()
    cursor = first_payload["next_cursor"]
    with app.app_context():
        token = next(
            row.group_token
            for row in load_friends_trips_page(
                first_id,
                today=today,
                destination_key="m:FT Token Group Peak",
            ).rows
            if row.grouped
        )

    _login(client, second_id)
    assert client.get(
        "/api/my-trips/friends/page", query_string={"cursor": cursor}
    ).status_code == 400
    assert client.get(
        "/api/my-trips/friends/group", query_string={"group": token}
    ).status_code == 400


def test_friends_trips_page_endpoint_warmed_budget(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("ft-endpoint-budget-viewer")
        for index in range(FRIENDS_TRIPS_PAGE_SIZE):
            friend = _make_user(f"ft-endpoint-budget-friend-{index}")
            _connect(viewer, friend)
            _make_trip(
                friend,
                resort=_make_resort(f"FT Endpoint Budget Peak {index}"),
                start_date=today + timedelta(days=index + 1),
            )
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine

    _login(client, viewer_id)
    assert client.get(
        "/api/my-trips/friends/page", query_string={"context": "1"}
    ).status_code == 200
    statements = []

    def record(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(
            "/api/my-trips/friends/page", query_string={"context": "1"}
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200
    assert len(statements) <= 4