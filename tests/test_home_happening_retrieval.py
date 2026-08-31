"""BL-177 bounded Home Happening retrieval regressions."""

from datetime import date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app import app
from models import (
    DismissedInsightCard,
    GuestStatus,
    SkiTrip,
    db,
)
from services.happening import (
    _build_happening_candidates_statement,
    get_happening_candidates,
)
from tests.conftest import _add_participant, _make_resort, _make_trip, _make_user


def _at(days_ago=0):
    return datetime(2026, 8, 30, 12, 0, 0) - timedelta(days=days_ago)


def _set_activity(trip, *, created_at, updated_at=None):
    trip.created_at = created_at
    trip.updated_at = updated_at
    return trip


def _fetch(viewer_id, friend_ids, *, today=date(2026, 8, 30), limit=5):
    return get_happening_candidates(
        user_id=viewer_id,
        friend_ids=friend_ids,
        today=today,
        limit=limit,
    )


def test_owner_eligibility_preserves_privacy_resort_and_in_progress_rules(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-owner-viewer")
        friend = _make_user("hap-owner-friend")
        nonfriend = _make_user("hap-owner-nonfriend")
        resort = _make_resort("Happening Peak")

        qualifying = _make_trip(
            friend,
            resort,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
        )
        _set_activity(qualifying, created_at=_at(1))
        _make_trip(
            friend,
            resort,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
            is_public=False,
        )
        _make_trip(
            friend,
            mountain="No Resort",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
        )
        _make_trip(
            friend,
            resort,
            start_date=today - timedelta(days=5),
            end_date=today - timedelta(days=1),
        )
        _make_trip(
            nonfriend,
            resort,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
        )
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        qualifying_id = qualifying.id

        rows = _fetch(viewer_id, [friend_id])

        assert [row.trip_id for row in rows] == [qualifying_id]
        assert rows[0].resort_name == "Happening Peak"
        assert rows[0].attendance_status == "planning"


def test_going_and_interested_participants_preserve_effective_date_semantics(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-part-viewer")
        owner = _make_user("hap-part-owner")
        going_friend = _make_user("hap-part-going")
        interested_friend = _make_user("hap-part-interested")
        expired_friend = _make_user("hap-part-expired")
        resort = _make_resort("Participant Peak")

        going_trip = _make_trip(
            owner,
            resort,
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=10),
        )
        going = _add_participant(going_trip, going_friend, GuestStatus.GOING)
        going.start_date = today + timedelta(days=2)
        going.end_date = today + timedelta(days=4)
        _set_activity(going_trip, created_at=_at(1))

        interested_trip = _make_trip(
            owner,
            resort,
            start_date=today,
            end_date=today + timedelta(days=8),
        )
        interested = _add_participant(
            interested_trip,
            interested_friend,
            GuestStatus.INTERESTED,
        )
        interested.start_date = today - timedelta(days=5)
        interested.end_date = today - timedelta(days=3)
        _set_activity(interested_trip, created_at=_at(2))

        expired_trip = _make_trip(
            owner,
            resort,
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=8),
        )
        expired = _add_participant(
            expired_trip,
            expired_friend,
            GuestStatus.GOING,
        )
        expired.start_date = today - timedelta(days=5)
        expired.end_date = today - timedelta(days=1)
        _set_activity(expired_trip, created_at=_at(3))
        db.session.commit()

        rows = _fetch(
            viewer.id,
            [going_friend.id, interested_friend.id, expired_friend.id],
        )
        rows_by_friend = {row.attendance_user_id: row for row in rows}

        assert set(rows_by_friend) == {going_friend.id, interested_friend.id}
        assert rows_by_friend[going_friend.id].attendance_status == "going"
        assert rows_by_friend[going_friend.id].attendance_start_date == (
            today + timedelta(days=2)
        )
        assert rows_by_friend[going_friend.id].attendance_end_date == (
            today + timedelta(days=4)
        )
        assert rows_by_friend[interested_friend.id].attendance_status == "planning"
        assert rows_by_friend[interested_friend.id].attendance_start_date == today
        assert rows_by_friend[interested_friend.id].attendance_end_date == (
            today + timedelta(days=8)
        )


def test_pending_declined_and_removed_participants_are_excluded(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-status-viewer")
        owner = _make_user("hap-status-owner")
        resort = _make_resort("Status Peak")
        excluded_friends = []
        for status in (
            GuestStatus.PENDING,
            GuestStatus.DECLINED,
            GuestStatus.REMOVED,
        ):
            friend = _make_user(f"hap-status-{status.value}")
            trip = _make_trip(
                owner,
                resort,
                start_date=today,
                end_date=today + timedelta(days=5),
            )
            _add_participant(trip, friend, status)
            excluded_friends.append(friend)
        db.session.commit()

        rows = _fetch(viewer.id, [friend.id for friend in excluded_friends])

        assert rows == []


def test_activity_order_dedupe_and_trip_id_tie_break(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-rank-viewer")
        friend = _make_user("hap-rank-friend")
        owner = _make_user("hap-rank-owner")
        resort = _make_resort("Ranking Peak")

        owned = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        _set_activity(owned, created_at=_at(5), updated_at=_at(2))

        attended = _make_trip(
            owner,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        _add_participant(attended, friend, GuestStatus.GOING)
        _set_activity(attended, created_at=_at(1))

        tied_low = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        tied_high = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        for trip in (tied_low, tied_high):
            _set_activity(trip, created_at=_at(0), updated_at=None)
        db.session.commit()
        tied_high_id = tied_high.id

        rows = _fetch(viewer.id, [friend.id])

        assert len(rows) == 1
        assert rows[0].trip_id == tied_high_id
        assert rows[0].attendance_user_id == friend.id


def test_missing_activity_timestamp_is_oldest_across_supported_dialects(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-null-viewer")
        friend = _make_user("hap-null-friend")
        resort = _make_resort("Null Activity Peak")
        valid = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        missing = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        _set_activity(valid, created_at=_at(3))
        db.session.flush()
        missing_id = missing.id
        valid_id = valid.id
        db.session.commit()
        db.session.execute(
            sa.update(SkiTrip)
            .where(SkiTrip.id == missing_id)
            .values(created_at=None, updated_at=None)
        )
        db.session.commit()

        rows = _fetch(viewer.id, [friend.id])

        assert [row.trip_id for row in rows] == [valid_id]

        statement = _build_happening_candidates_statement(
            user_id=viewer.id,
            friend_ids=[friend.id],
            today=today,
            limit=5,
        )
        postgres_sql = str(statement.compile(dialect=postgresql.dialect()))
        assert postgres_sql.count("DESC NULLS LAST") == 2


def test_dismissed_winner_does_not_fall_back_and_dismissal_is_user_specific(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-dismiss-viewer")
        other_viewer = _make_user("hap-dismiss-other")
        friend = _make_user("hap-dismiss-friend")
        resort = _make_resort("Dismissal Peak")
        older = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        winner = _make_trip(
            friend,
            resort,
            start_date=today,
            end_date=today + timedelta(days=5),
        )
        _set_activity(older, created_at=_at(2))
        _set_activity(winner, created_at=_at(0))
        db.session.flush()
        db.session.add(DismissedInsightCard(
            user_id=viewer.id,
            card_type="happening",
            card_key=f"happening:{winner.id}",
        ))
        db.session.commit()
        viewer_id = viewer.id
        other_viewer_id = other_viewer.id
        friend_id = friend.id
        winner_id = winner.id

        assert _fetch(viewer_id, [friend_id]) == []
        assert [row.trip_id for row in _fetch(other_viewer_id, [friend_id])] == [
            winner_id
        ]


def test_large_population_is_bounded_in_one_query_without_lazy_loads(client):
    today = date(2026, 8, 30)
    with app.app_context():
        viewer = _make_user("hap-bound-viewer")
        resort = _make_resort("Bounded Peak")
        friend_ids = []
        for index in range(20):
            friend = _make_user(f"hap-bound-{index}")
            friend_ids.append(friend.id)
            for trip_index in range(3):
                trip = _make_trip(
                    friend,
                    resort,
                    start_date=today,
                    end_date=today + timedelta(days=10),
                )
                _set_activity(
                    trip,
                    created_at=_at(index + trip_index),
                )
        db.session.commit()
        viewer_id = viewer.id

        statements = []

        def capture(_conn, _cursor, statement, parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement, parameters))

        engine = db.engine
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            rows = _fetch(viewer_id, friend_ids)
            rendered_values = [
                (
                    row.trip_id,
                    row.attendance_user_id,
                    row.resort_name,
                    row.activity_timestamp,
                )
                for row in rows
            ]
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)

        assert len(rows) == 5
        assert len(rendered_values) == 5
        assert len(statements) == 1
        sql = statements[0][0].lower()
        assert "row_number() over" in sql
        assert "limit" in sql
        assert "ranked_happening_occurrences.friend_rank = " in sql


def test_no_friends_skips_the_database_query(client):
    with app.app_context():
        viewer = _make_user("hap-no-friends")
        db.session.commit()
        viewer_id = viewer.id

        statements = []

        def capture(_conn, _cursor, statement, parameters, _context, _many):
            statements.append(statement)

        engine = db.engine
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            rows = _fetch(viewer_id, [])
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)

        assert rows == []
        assert statements == []