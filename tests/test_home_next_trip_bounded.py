"""BL-156 exact bounded Home Next Trip candidate regressions."""

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql, sqlite

import app as app_module
from app import app
from models import Friend, GuestStatus, SkiTrip, SkiTripParticipant, db
from services.happening import get_happening_candidates
from services.ideas_retrieval import get_home_ideas
from services.trip_attendance import (
    effective_attendance_date_expressions,
    effective_attendance_dates,
    set_effective_attendance_dates,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


TODAY = date(2026, 9, 1)


def _reference_next_trip(user_id, today):
    """Reproduce the pre-BL-156 all-candidate Home selector."""
    owned = (
        SkiTrip.query
        .filter(
            SkiTrip.user_id == user_id,
            app_module.active_or_legacy_trip_predicate(),
            SkiTrip.end_date >= today,
        )
        .order_by(SkiTrip.start_date.asc())
        .all()
    )
    owned = [set_effective_attendance_dates(trip) for trip in owned]

    participations = SkiTripParticipant.query.filter(
        SkiTripParticipant.user_id == user_id,
        SkiTripParticipant.active_status_filter(),
    ).all()
    by_trip_id = {participant.trip_id: participant for participant in participations}
    guest_trips = []
    if by_trip_id:
        candidates = SkiTrip.query.filter(
            SkiTrip.id.in_(by_trip_id),
            SkiTrip.user_id != user_id,
            app_module.active_or_legacy_trip_predicate(),
            SkiTrip.end_date >= today,
        ).all()
        guest_trips = [
            set_effective_attendance_dates(trip, by_trip_id[trip.id])
            for trip in candidates
            if effective_attendance_dates(trip, by_trip_id[trip.id])[1] >= today
        ]

    all_upcoming = sorted(
        owned + guest_trips,
        key=lambda trip: trip.attendance_start_date or date.max,
    )
    winner = all_upcoming[0] if all_upcoming else None
    participant = (
        by_trip_id.get(winner.id)
        if winner is not None and winner.user_id != user_id
        else None
    )
    return winner, participant, len(all_upcoming)


def _selection_signature(selection):
    trip, participant, count = selection
    return (
        trip.id if trip else None,
        trip.attendance_start_date if trip else None,
        trip.attendance_end_date if trip else None,
        participant.id if participant else None,
        count,
    )


def _connect(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


def test_effective_attendance_expressions_compile_for_supported_dialects():
    effective_start, effective_end = effective_attendance_date_expressions(
        SkiTrip,
        SkiTripParticipant,
    )
    statement = (
        sa.select(effective_start, effective_end)
        .select_from(SkiTrip)
        .join(
            SkiTripParticipant,
            SkiTripParticipant.trip_id == SkiTrip.id,
        )
    )

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        sql = str(statement.compile(dialect=dialect)).lower()
        assert sql.count("case when") == 2
        assert "ski_trip_participant.status" in sql
        assert "ski_trip_participant.start_date is not null" in sql
        assert "ski_trip_participant.end_date is not null" in sql


def test_bounded_selector_matches_reference_for_mixed_attendance_states(client):
    with app.app_context():
        viewer = _make_user("bound-reference-viewer")
        owner = _make_user("bound-reference-owner")

        _make_trip(
            viewer,
            start_date=TODAY + timedelta(days=12),
            end_date=TODAY + timedelta(days=15),
        )
        terminal = _make_trip(
            viewer,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=2),
        )
        terminal.lifecycle_state = "completed"

        private_winner = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=8),
            end_date=TODAY + timedelta(days=14),
            is_public=False,
        )
        winner_participant = _add_participant(
            private_winner,
            viewer,
            GuestStatus.GOING,
        )
        winner_participant.start_date = TODAY + timedelta(days=3)
        winner_participant.end_date = TODAY + timedelta(days=5)

        incomplete = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=6),
            end_date=TODAY + timedelta(days=9),
        )
        incomplete_participant = _add_participant(
            incomplete,
            viewer,
            GuestStatus.GOING,
        )
        incomplete_participant.start_date = TODAY + timedelta(days=1)

        interested = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=7),
            end_date=TODAY + timedelta(days=10),
        )
        interested_participant = _add_participant(
            interested,
            viewer,
            GuestStatus.INTERESTED,
        )
        interested_participant.start_date = TODAY + timedelta(days=1)
        interested_participant.end_date = TODAY + timedelta(days=2)

        expired = _make_trip(
            owner,
            start_date=TODAY - timedelta(days=5),
            end_date=TODAY + timedelta(days=10),
        )
        expired_participant = _add_participant(
            expired,
            viewer,
            GuestStatus.GOING,
        )
        expired_participant.start_date = TODAY - timedelta(days=5)
        expired_participant.end_date = TODAY - timedelta(days=1)

        pending = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=1),
            end_date=TODAY + timedelta(days=4),
        )
        _add_participant(pending, viewer, GuestStatus.PENDING)
        db.session.commit()
        viewer_id = viewer.id
        expected_winner_id = private_winner.id

        reference = _selection_signature(
            _reference_next_trip(viewer_id, TODAY)
        )
        db.session.expunge_all()
        bounded = _selection_signature(
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert bounded == reference
        assert bounded[0] == expected_winner_id
        assert bounded[1:3] == (
            TODAY + timedelta(days=3),
            TODAY + timedelta(days=5),
        )


def test_equal_effective_date_preserves_owned_first_tie(client):
    with app.app_context():
        viewer = _make_user("bound-tie-viewer")
        owner = _make_user("bound-tie-owner")
        owned = _make_trip(
            viewer,
            start_date=TODAY + timedelta(days=4),
            end_date=TODAY + timedelta(days=8),
        )
        guest = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=2),
            end_date=TODAY + timedelta(days=9),
        )
        participant = _add_participant(guest, viewer, GuestStatus.GOING)
        participant.start_date = owned.start_date
        participant.end_date = TODAY + timedelta(days=6)
        db.session.commit()
        viewer_id = viewer.id
        owned_id = owned.id

        winner, selected_participant, count = (
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert winner.id == owned_id
        assert selected_participant is None
        assert count == 2


def test_equal_owned_dates_match_previous_source_order(client):
    with app.app_context():
        viewer = _make_user("bound-owned-tie-viewer")
        first = _make_trip(
            viewer,
            start_date=TODAY + timedelta(days=4),
            end_date=TODAY + timedelta(days=7),
        )
        _make_trip(
            viewer,
            start_date=first.start_date,
            end_date=TODAY + timedelta(days=8),
        )
        db.session.commit()
        viewer_id = viewer.id

        reference = _selection_signature(
            _reference_next_trip(viewer_id, TODAY)
        )
        db.session.expunge_all()
        bounded = _selection_signature(
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert bounded == reference
        assert bounded[0] == first.id


def test_equal_guest_dates_and_inactive_rows_match_previous_source_order(client):
    with app.app_context():
        viewer = _make_user("bound-guest-tie-viewer")
        owner = _make_user("bound-guest-tie-owner")
        tied = []
        for suffix in ("first", "second"):
            trip = _make_trip(
                owner,
                start_date=TODAY + timedelta(days=4),
                end_date=TODAY + timedelta(days=7),
            )
            participant = _add_participant(
                trip,
                viewer,
                GuestStatus.INTERESTED,
            )
            tied.append((trip, participant))

        for status in (
            GuestStatus.PENDING,
            GuestStatus.DECLINED,
            GuestStatus.REMOVED,
        ):
            excluded = _make_trip(
                owner,
                start_date=TODAY,
                end_date=TODAY + timedelta(days=2),
            )
            _add_participant(excluded, viewer, status)

        terminal = _make_trip(
            owner,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=2),
        )
        terminal.lifecycle_state = "cancelled"
        _add_participant(terminal, viewer, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id
        expected_trip_id = tied[0][0].id
        expected_participant_id = tied[0][1].id

        reference = _selection_signature(
            _reference_next_trip(viewer_id, TODAY)
        )
        db.session.expunge_all()
        bounded = _selection_signature(
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert bounded == reference
        assert bounded[0] == expected_trip_id
        assert bounded[3] == expected_participant_id
        assert bounded[4] == 2


def test_tied_null_owned_dates_match_previous_source_order(client):
    with app.app_context():
        viewer = _make_user("bound-null-tie-viewer")
        first = _make_trip(
            viewer,
            start_date=None,
            end_date=TODAY + timedelta(days=7),
        )
        _make_trip(
            viewer,
            start_date=None,
            end_date=TODAY + timedelta(days=8),
        )
        db.session.commit()
        viewer_id = viewer.id

        reference = _selection_signature(
            _reference_next_trip(viewer_id, TODAY)
        )
        db.session.expunge_all()
        bounded = _selection_signature(
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert bounded == reference
        assert bounded[0] == first.id


def test_null_effective_start_sorts_after_dated_candidate(client):
    with app.app_context():
        viewer = _make_user("bound-null-viewer")
        owner = _make_user("bound-null-owner")
        _make_trip(
            viewer,
            start_date=None,
            end_date=TODAY + timedelta(days=8),
        )
        guest = _make_trip(
            owner,
            start_date=TODAY + timedelta(days=3),
            end_date=TODAY + timedelta(days=5),
        )
        selected = _add_participant(guest, viewer, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id
        guest_id = guest.id
        selected_id = selected.id

        reference = _selection_signature(
            _reference_next_trip(viewer_id, TODAY)
        )
        db.session.expunge_all()
        bounded = _selection_signature(
            app_module._get_home_next_trip_candidate(viewer_id, TODAY)
        )

        assert bounded == reference
        assert bounded[0] == guest_id
        assert bounded[3] == selected_id


@pytest.mark.parametrize("population", [10, 50, 100, 500])
def test_candidate_materialization_is_constant_for_large_populations(
    client,
    population,
):
    with app.app_context():
        viewer = _make_user(f"bound-cardinality-viewer-{population}")
        guest_owner = _make_user(f"bound-cardinality-owner-{population}")
        owned_count = population // 2
        for index in range(owned_count):
            _make_trip(
                viewer,
                start_date=TODAY + timedelta(days=1 + index),
                end_date=TODAY + timedelta(days=3 + index),
            )
        for index in range(population - owned_count):
            guest = _make_trip(
                guest_owner,
                start_date=TODAY + timedelta(days=2 + index),
                end_date=TODAY + timedelta(days=4 + index),
            )
            _add_participant(guest, viewer, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id
        db.session.expunge_all()

        loaded_trip_ids = []
        loaded_participant_ids = []
        statements = []

        def record_trip(target, _context):
            loaded_trip_ids.append(target.id)

        def record_participant(target, _context):
            loaded_participant_ids.append(target.id)

        def record_sql(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(SkiTrip, "load", record_trip)
        event.listen(SkiTripParticipant, "load", record_participant)
        event.listen(db.engine, "before_cursor_execute", record_sql)
        try:
            winner, participant, count = (
                app_module._get_home_next_trip_candidate(viewer_id, TODAY)
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", record_sql)
            event.remove(SkiTripParticipant, "load", record_participant)
            event.remove(SkiTrip, "load", record_trip)

        assert winner is not None
        assert participant is None
        assert count == population
        assert len(loaded_trip_ids) == 2
        assert len(loaded_participant_ids) == 1
        assert len(statements) == 2
        assert all(" limit " in statement.lower() for statement in statements)


@pytest.mark.parametrize("population", [10, 50, 100, 500])
def test_happening_source_population_keeps_one_bounded_statement(
    client,
    population,
):
    with app.app_context():
        viewer = _make_user(f"bound-happening-viewer-{population}")
        friend = _make_user(f"bound-happening-friend-{population}")
        resort = _make_resort(f"Bound Happening {population}")
        for index in range(population):
            trip = _make_trip(
                friend,
                resort,
                start_date=TODAY + timedelta(days=index),
                end_date=TODAY + timedelta(days=index + 2),
            )
            trip.created_at = None
            trip.updated_at = None
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        statements = []

        def record_sql(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", record_sql)
        try:
            rows = get_happening_candidates(
                user_id=viewer_id,
                friend_ids=[friend_id],
                today=TODAY,
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", record_sql)

        assert len(rows) == 1
        assert len(statements) == 1


@pytest.mark.parametrize("population", [10, 50, 100, 500])
def test_ideas_source_population_keeps_one_bounded_statement(
    client,
    population,
):
    with app.app_context():
        viewer = _make_user(f"bound-ideas-viewer-{population}")
        friend = _make_user(f"bound-ideas-friend-{population}")
        _connect(viewer, friend)
        for index in range(population):
            resort = _make_resort(f"Bound Ideas {population}-{index}")
            _make_trip(
                friend,
                resort,
                start_date=TODAY + timedelta(days=index),
                end_date=TODAY + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id
        statements = []

        def record_sql(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", record_sql)
        try:
            rows = get_home_ideas(
                user_id=viewer_id,
                today=TODAY,
                limit=50,
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", record_sql)

        assert len(rows) == 5
        assert len(statements) == 1


def test_home_preserves_full_upcoming_count_with_bounded_candidates(client):
    with app.app_context():
        viewer = _make_user("bound-home-count-viewer")
        for index in range(7):
            _make_trip(
                viewer,
                start_date=date.today() + timedelta(days=index + 1),
                end_date=date.today() + timedelta(days=index + 2),
            )
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    response = client.get("/home")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ">7<" in html
    assert "Trips" in html


def test_warmed_home_query_count_remains_within_bl161_ceiling(client):
    with app.app_context():
        viewer = _make_user("bound-home-query-viewer")
        owner = _make_user("bound-home-query-owner")
        _make_trip(
            viewer,
            start_date=date.today() + timedelta(days=8),
            end_date=date.today() + timedelta(days=10),
        )
        guest = _make_trip(
            owner,
            start_date=date.today() + timedelta(days=4),
            end_date=date.today() + timedelta(days=6),
            is_public=False,
        )
        _add_participant(guest, viewer, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    assert client.get("/home").status_code == 200
    with app.app_context():
        engine = db.engine
    statements = []

    def record_sql(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        response = client.get("/home")
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)

    assert response.status_code == 200
    assert len(statements) <= 25