"""BL-158 bounded My Trips retrieval and progressive-loading regressions."""

from datetime import date, timedelta
import re

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app import app
from models import (
    GuestStatus,
    ParticipantRole,
    Resort,
    SkiTrip,
    SkiTripParticipant,
    db,
)
from services.my_trips_paging import (
    MY_TRIPS_PAGE_SIZE,
    MyTripsCursor,
    _candidate_query,
    encode_my_trips_cursor,
    load_my_trips_page,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _all_pages(viewer_id, section):
    rows = []
    cursor = None
    while True:
        page = load_my_trips_page(
            viewer_id,
            section,
            today=date.today(),
            cursor_value=cursor,
        )
        rows.extend(page.rows)
        if not page.has_more:
            assert page.next_cursor is None
            return rows
        assert page.next_cursor
        cursor = page.next_cursor


def _trip_ids_from_html(html, css_class):
    pattern = rf'class="[^"]*\b{css_class}\b[^"]*"[^>]*data-trip-id="(\d+)"'
    return [int(value) for value in re.findall(pattern, html)]


@pytest.mark.parametrize("trip_count", [0, 1, 19, 20, 21, 40, 41])
def test_upcoming_page_boundaries_and_full_concatenation(client, trip_count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"page-boundary-{trip_count}")
        resort = _make_resort(f"Boundary Peak {trip_count}")
        expected_ids = []
        for index in range(trip_count):
            trip = _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            expected_ids.append(trip.id)
        db.session.commit()
        viewer_id = viewer.id

        first = load_my_trips_page(viewer_id, "upcoming", today=today)
        assert len(first.rows) == min(trip_count, MY_TRIPS_PAGE_SIZE)
        assert first.has_more is (trip_count > MY_TRIPS_PAGE_SIZE)
        assert (first.next_cursor is not None) is first.has_more

        all_rows = _all_pages(viewer_id, "upcoming")
        assert [row.trip.id for row in all_rows] == expected_ids
        assert len({row.trip.id for row in all_rows}) == trip_count


def test_total_order_preserves_owned_before_guest_ties(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("order-viewer")
        owner = _make_user("order-owner")
        resort = _make_resort("Order Peak")
        same_start = today + timedelta(days=4)
        owned = [
            _make_trip(
                viewer,
                resort=resort,
                start_date=same_start,
                end_date=same_start + timedelta(days=1),
            )
            for _ in range(2)
        ]
        guests = [
            _make_trip(
                owner,
                resort=resort,
                start_date=same_start,
                end_date=same_start + timedelta(days=1),
            )
            for _ in range(2)
        ]
        for trip in guests:
            _add_participant(trip, viewer, GuestStatus.GOING)
        db.session.commit()

        rows = _all_pages(viewer.id, "upcoming")
        assert [row.trip.id for row in rows] == [
            owned[0].id,
            owned[1].id,
            guests[0].id,
            guests[1].id,
        ]


def test_history_is_chronological_with_owned_before_guest_ties(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("history-order-viewer")
        owner = _make_user("history-order-owner")
        resort = _make_resort("History Order Peak")
        newer = today - timedelta(days=3)
        older = today - timedelta(days=10)
        owned_old = _make_trip(
            viewer, resort=resort, start_date=older, end_date=older
        )
        owned_new = _make_trip(
            viewer, resort=resort, start_date=newer, end_date=newer
        )
        guest_new = _make_trip(
            owner, resort=resort, start_date=newer, end_date=newer
        )
        guest_old = _make_trip(
            owner, resort=resort, start_date=older, end_date=older
        )
        _add_participant(guest_new, viewer, GuestStatus.INTERESTED)
        _add_participant(guest_old, viewer, GuestStatus.GOING)
        db.session.commit()

        rows = _all_pages(viewer.id, "history")
        assert [row.trip.id for row in rows] == [
            owned_new.id,
            guest_new.id,
            owned_old.id,
            guest_old.id,
        ]


def test_history_cards_keep_core_dates_for_going_guest(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("history-dates-viewer")
        owner = _make_user("history-dates-owner")
        resort = _make_resort("History Dates Peak")
        core_start = today - timedelta(days=10)
        trip = _make_trip(
            owner,
            resort=resort,
            start_date=core_start,
            end_date=core_start + timedelta(days=4),
        )
        participant = _add_participant(trip, viewer, GuestStatus.GOING)
        participant.start_date = core_start + timedelta(days=2)
        participant.end_date = core_start + timedelta(days=3)
        db.session.commit()

        page = load_my_trips_page(viewer.id, "history", today=today)
        assert len(page.rows) == 1
        assert not hasattr(page.rows[0].trip, "attendance_start_date")
        with app.test_request_context():
            rendered = app.jinja_env.get_template(
                "components/my_trips_rows.html"
            ).render(rows=page.rows, section="history")
        assert core_start.strftime("%b %-d") in rendered
        assert participant.start_date.strftime("%b %-d") not in rendered


def test_attendance_lifecycle_and_authorization_membership(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("membership-viewer")
        owner = _make_user("membership-owner")
        resort = _make_resort("Membership Peak")

        going = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=10),
        )
        going_participant = _add_participant(going, viewer, GuestStatus.GOING)
        going_participant.start_date = today + timedelta(days=4)
        going_participant.end_date = today + timedelta(days=5)

        incomplete = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
        )
        incomplete_participant = _add_participant(
            incomplete, viewer, GuestStatus.GOING
        )
        incomplete_participant.start_date = today + timedelta(days=3)

        interested = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=6),
            end_date=today + timedelta(days=7),
        )
        interested_participant = _add_participant(
            interested, viewer, GuestStatus.INTERESTED
        )
        interested_participant.start_date = today + timedelta(days=8)
        interested_participant.end_date = today + timedelta(days=9)

        hidden = {}
        for status in (
            GuestStatus.PENDING,
            GuestStatus.DECLINED,
            GuestStatus.REMOVED,
        ):
            trip = _make_trip(
                owner,
                resort=resort,
                start_date=today + timedelta(days=11),
                end_date=today + timedelta(days=12),
            )
            _add_participant(trip, viewer, status)
            hidden[status] = trip.id

        unrelated_private = _make_trip(
            owner,
            resort=resort,
            is_public=False,
            start_date=today + timedelta(days=13),
            end_date=today + timedelta(days=14),
        )
        terminal = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=15),
            end_date=today + timedelta(days=16),
        )
        terminal.lifecycle_state = "cancelled"

        cancelled_guest = _make_trip(
            owner,
            resort=resort,
            start_date=today - timedelta(days=16),
            end_date=today - timedelta(days=15),
        )
        cancelled_guest.lifecycle_state = "cancelled"
        _add_participant(cancelled_guest, viewer, GuestStatus.GOING)

        past_active_owner = _make_trip(
            viewer,
            resort=resort,
            start_date=today - timedelta(days=14),
            end_date=today - timedelta(days=13),
        )
        past_active_owner.lifecycle_state = "active"

        past_legacy_owner = _make_trip(
            viewer,
            resort=resort,
            start_date=today - timedelta(days=12),
            end_date=today - timedelta(days=11),
        )
        past_legacy_owner.lifecycle_state = None

        completed_owner = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=17),
            end_date=today + timedelta(days=18),
        )
        completed_owner.lifecycle_state = "completed"

        historical_going = _make_trip(
            owner,
            resort=resort,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=9),
        )
        _add_participant(historical_going, viewer, GuestStatus.GOING)

        historical_interested = _make_trip(
            owner,
            resort=resort,
            start_date=today - timedelta(days=8),
            end_date=today - timedelta(days=7),
        )
        _add_participant(
            historical_interested, viewer, GuestStatus.INTERESTED
        )

        past_attendance_only = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=20),
            end_date=today + timedelta(days=21),
        )
        past_attendance = _add_participant(
            past_attendance_only, viewer, GuestStatus.GOING
        )
        past_attendance.start_date = today - timedelta(days=2)
        past_attendance.end_date = today - timedelta(days=1)
        db.session.commit()

        upcoming = _all_pages(viewer.id, "upcoming")
        upcoming_by_id = {row.trip.id: row for row in upcoming}
        history_ids = {row.trip.id for row in _all_pages(viewer.id, "history")}

        assert upcoming_by_id[going.id].attendance_start_date == going_participant.start_date
        assert upcoming_by_id[incomplete.id].attendance_start_date == incomplete.start_date
        assert upcoming_by_id[interested.id].attendance_start_date == interested.start_date
        assert hidden[GuestStatus.PENDING] in upcoming_by_id
        assert not (
            {
                hidden[GuestStatus.DECLINED],
                hidden[GuestStatus.REMOVED],
            }
            & set(upcoming_by_id)
        )
        assert unrelated_private.id not in upcoming_by_id
        assert terminal.id not in upcoming_by_id
        assert terminal.id not in history_ids
        assert cancelled_guest.id not in history_ids
        assert past_active_owner.id in history_ids
        assert past_legacy_owner.id in history_ids
        assert completed_owner.id in history_ids
        assert historical_going.id in history_ids
        assert historical_interested.id in history_ids
        assert not (set(hidden.values()) & history_ids)
        assert past_attendance_only.id not in upcoming_by_id
        assert past_attendance_only.id not in history_ids


def test_active_guest_counts_are_batched_and_do_not_load_participants(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("guest-count-viewer")
        resort = _make_resort("Guest Count Peak")
        trips = []
        for index in range(25):
            trip = _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            active_guest = _make_user(f"active-guest-{index}")
            pending_guest = _make_user(f"pending-guest-{index}")
            _add_participant(trip, active_guest, GuestStatus.GOING)
            _add_participant(trip, pending_guest, GuestStatus.PENDING)
            trips.append(trip)
        db.session.commit()
        viewer_id = viewer.id
        db.session.remove()

        statements = []
        participant_loads = []

        def record_sql(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        def record_participant(target, _context):
            participant_loads.append(target.id)

        event.listen(db.engine, "before_cursor_execute", record_sql)
        event.listen(SkiTripParticipant, "load", record_participant)
        try:
            page = load_my_trips_page(viewer_id, "upcoming", today=today)
            with app.test_request_context():
                rendered = app.jinja_env.get_template(
                    "components/my_trips_rows.html"
                ).render(rows=page.rows, section="upcoming")
        finally:
            event.remove(db.engine, "before_cursor_execute", record_sql)
            event.remove(SkiTripParticipant, "load", record_participant)

        assert len(page.rows) == 20
        assert all(row.active_guest_count == 1 for row in page.rows)
        assert participant_loads == []
        assert len(statements) == 3
        assert rendered.count('class="trip-row"') == 20


@pytest.mark.parametrize("source_count", [10, 50, 100, 500])
def test_page_query_and_materialization_are_constant(client, source_count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"cardinality-{source_count}")
        resort = _make_resort(f"Cardinality Peak {source_count}")
        for index in range(source_count):
            _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id
        db.session.remove()

        statements = []
        trip_loads = []

        def record_sql(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        def record_trip(target, _context):
            trip_loads.append(target.id)

        event.listen(db.engine, "before_cursor_execute", record_sql)
        event.listen(SkiTrip, "load", record_trip)
        try:
            page = load_my_trips_page(viewer_id, "upcoming", today=today)
        finally:
            event.remove(db.engine, "before_cursor_execute", record_sql)
            event.remove(SkiTrip, "load", record_trip)

        assert len(statements) == 3
        assert len(page.rows) == min(source_count, 20)
        assert len(trip_loads) == min(source_count, 20)


def test_fragment_endpoint_rejects_invalid_and_mismatched_cursors(client):
    with app.app_context():
        viewer = _make_user("cursor-viewer")
        db.session.commit()
        viewer_id = viewer.id
    _login(client, viewer_id)

    assert client.get("/api/my-trips/page?section=nope").status_code == 400
    assert (
        client.get(
            "/api/my-trips/page?section=upcoming&cursor=not-a-cursor"
        ).status_code
        == 400
    )
    history_cursor = encode_my_trips_cursor(
        MyTripsCursor("history", 0, 0, date.today(), 1)
    )
    assert (
        client.get(
            f"/api/my-trips/page?section=upcoming&cursor={history_cursor}"
        ).status_code
        == 400
    )


def test_initial_route_and_fragment_render_independent_pages(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("route-pages-viewer")
        resort = _make_resort("Route Pages Peak")
        for index in range(21):
            _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            past_date = today - timedelta(days=index + 2)
            _make_trip(
                viewer,
                resort=resort,
                start_date=past_date,
                end_date=past_date,
            )
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    initial = client.get("/my-trips")
    assert initial.status_code == 200
    initial_html = initial.get_data(as_text=True)
    assert len(_trip_ids_from_html(initial_html, "trip-row")) == 20
    assert len(_trip_ids_from_html(initial_html, "past-row")) == 20
    assert initial_html.count("my-trips-load-more") == 2

    match = re.search(
        r'data-section="upcoming"[^>]+data-cursor="([^"]+)"', initial_html
    )
    assert match
    fragment = client.get(
        f"/api/my-trips/page?section=upcoming&cursor={match.group(1)}"
    )
    assert fragment.status_code == 200
    payload = fragment.get_json()
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None
    assert len(payload["trip_ids"]) == 1
    assert len(_trip_ids_from_html(payload["html"], "trip-row")) == 1


def test_cancelled_trip_is_absent_from_initial_and_fragment_history(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("cancelled-history-route-viewer")
        resort = _make_resort("Cancelled History Route Peak")
        cancelled = _make_trip(
            viewer,
            resort=resort,
            start_date=today - timedelta(days=2),
            end_date=today - timedelta(days=1),
        )
        cancelled.lifecycle_state = "cancelled"
        visible = _make_trip(
            viewer,
            resort=resort,
            start_date=today - timedelta(days=4),
            end_date=today - timedelta(days=3),
        )
        db.session.commit()
        viewer_id = viewer.id
        cancelled_id = cancelled.id
        visible_id = visible.id

    _login(client, viewer_id)
    initial = client.get("/my-trips")
    assert initial.status_code == 200
    initial_history_ids = _trip_ids_from_html(
        initial.get_data(as_text=True), "past-row"
    )
    assert cancelled_id not in initial_history_ids
    assert visible_id in initial_history_ids

    fragment = client.get("/api/my-trips/page?section=history")
    assert fragment.status_code == 200
    payload = fragment.get_json()
    assert cancelled_id not in payload["trip_ids"]
    assert visible_id in payload["trip_ids"]


def test_pending_invites_share_the_bounded_chronological_feed(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("complete-invites-viewer")
        owner = _make_user("complete-invites-owner")
        resort = _make_resort("Complete Invites Peak")
        for index in range(25):
            trip = _make_trip(
                owner,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
            _add_participant(trip, viewer, GuestStatus.PENDING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = client.get("/my-trips").get_data(as_text=True)
    assert html.count("invited you") == MY_TRIPS_PAGE_SIZE
    assert 'aria-label="25 invitations">25</span>' in html
    assert "mine-load-more" in html


def test_mine_projection_relationships_and_people_counts(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("mine-contract-viewer")
        owner = _make_user("mine-contract-owner")
        going_friend = _make_user("mine-contract-going")
        interested_friend = _make_user("mine-contract-interested")
        resort = _make_resort("Mine Contract Peak")

        organized = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=2),
        )
        _add_participant(organized, going_friend, GuestStatus.GOING)
        _add_participant(organized, interested_friend, GuestStatus.INTERESTED)

        going = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        _add_participant(going, viewer, GuestStatus.GOING)
        _add_participant(going, interested_friend, GuestStatus.INTERESTED)

        interested = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=6),
        )
        _add_participant(interested, viewer, GuestStatus.INTERESTED)
        _add_participant(interested, going_friend, GuestStatus.GOING)
        second_going = _make_user("mine-contract-second-going")
        _add_participant(interested, second_going, GuestStatus.GOING)

        invited = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=7),
            end_date=today + timedelta(days=8),
        )
        _add_participant(invited, viewer, GuestStatus.PENDING)
        _add_participant(invited, going_friend, GuestStatus.GOING)
        _add_participant(invited, second_going, GuestStatus.GOING)

        declined = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=9),
            end_date=today + timedelta(days=10),
        )
        _add_participant(declined, viewer, GuestStatus.DECLINED)
        removed = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=11),
            end_date=today + timedelta(days=12),
        )
        _add_participant(removed, viewer, GuestStatus.REMOVED)
        db.session.commit()

        page = load_my_trips_page(viewer.id, "upcoming", today=today)
        rows = {row.trip.id: row for row in page.rows}

        assert [row.relationship for row in page.rows] == [
            "organizing",
            "going",
            "interested",
            "invited",
        ]
        assert rows[organized.id].others_count == 2
        assert rows[going.id].others_count == 2
        assert rows[interested.id].going_count == 2
        assert rows[invited.id].going_count == 2
        assert rows[invited.id].inviter_name == owner.first_name
        assert declined.id not in rows
        assert removed.id not in rows
        assert page.pending_count == 1
        assert page.total_count == 4


def test_mine_rendering_uses_locked_labels_counts_and_invitation_actions(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("mine-render-viewer")
        owner = _make_user("mine-render-owner")
        friend_one = _make_user("mine-render-one")
        friend_two = _make_user("mine-render-two")
        resort = _make_resort("Mine Render Peak")

        organized = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=3),
        )
        _add_participant(organized, friend_one, GuestStatus.GOING)

        interested = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=35),
            end_date=today + timedelta(days=38),
        )
        _add_participant(interested, viewer, GuestStatus.INTERESTED)
        _add_participant(interested, friend_one, GuestStatus.GOING)
        _add_participant(interested, friend_two, GuestStatus.GOING)

        invited = _make_trip(
            owner,
            resort=resort,
            start_date=today + timedelta(days=12),
            end_date=today + timedelta(days=14),
        )
        _add_participant(invited, viewer, GuestStatus.PENDING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = client.get("/my-trips").get_data(as_text=True)

    assert "Organizing" in html
    assert "+1 other" in html
    assert "Interested" in html
    assert "2 going" in html
    assert ">Planning<" not in html
    assert "You're a guest" not in html
    assert "See where your season is taking shape." not in html
    assert "Filter for a mountain" not in html
    assert 'data-response="declined"' in html
    assert 'data-response="choose"' in html
    assert 'data-choice="going"' in html
    assert 'data-choice="interested"' in html


@pytest.mark.parametrize("source_count", [10, 50, 100, 500])
def test_initial_route_query_count_is_constant(client, source_count):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"route-budget-{source_count}")
        resort = _make_resort(f"Route Budget Peak {source_count}")
        for index in range(source_count):
            _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    assert client.get("/my-trips").status_code == 200
    statements = []
    with app.app_context():
        engine = db.engine

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get("/my-trips")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    assert len(statements) <= 18
    assert sum(" from user " in f" {statement} " for statement in statements) <= 2


def test_fragment_endpoint_query_budget(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("fragment-budget")
        resort = _make_resort("Fragment Budget Peak")
        for index in range(21):
            _make_trip(
                viewer,
                resort=resort,
                start_date=today + timedelta(days=index + 1),
                end_date=today + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id
        first = load_my_trips_page(viewer_id, "upcoming", today=today)
        cursor = first.next_cursor

    _login(client, viewer_id)
    assert client.get("/my-trips").status_code == 200
    statements = []
    with app.app_context():
        engine = db.engine

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(
            f"/api/my-trips/page?section=upcoming&cursor={cursor}"
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    assert len(statements) <= 4


def test_candidate_queries_compile_for_postgresql(client):
    with app.app_context():
        for section in ("upcoming", "history"):
            statement = _candidate_query(1, section, date.today(), None).statement
            compiled = str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            assert "ORDER BY" in compiled
            assert "ski_trip_participant" in compiled