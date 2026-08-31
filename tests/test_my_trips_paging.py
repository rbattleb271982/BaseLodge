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
    pattern = rf'class="{css_class}" data-trip-id="(\d+)"'
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


def test_history_keeps_all_owned_before_guest_rows(client):
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
            owned_old.id,
            guest_new.id,
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
        assert not (set(hidden.values()) & set(upcoming_by_id))
        assert unrelated_private.id not in upcoming_by_id
        assert terminal.id not in upcoming_by_id
        assert terminal.id in history_ids
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
    assert initial_html.count('class="my-trips-load-more"') == 2

    match = re.search(
        r'data-section="upcoming"\s+data-cursor="([^"]+)"', initial_html
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
    assert payload["html"].count('class="trip-row"') == 1


def test_pending_invites_remain_complete_when_viewer_feeds_are_bounded(client):
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
    assert html.count("invited you to a trip") == 25
    assert '<span class="tab-badge">25</span>' in html
    assert '<button type="button"\n                    class="my-trips-load-more"' not in html


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