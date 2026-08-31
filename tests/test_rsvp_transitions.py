from datetime import date, timedelta

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app import app
from conftest import _add_participant, _make_trip, _make_user
from models import GuestStatus, SkiTrip, SkiTripParticipant, SkiTripRsvpTransition, db
from services.rsvp_transitions import (
    RsvpCurrentStateError,
    transition_rsvp,
)


def test_establishes_guest_with_initial_event(client):
    with app.app_context():
        owner = _make_user("rsvp-history-owner")
        guest = _make_user("rsvp-history-guest")
        trip = _make_trip(owner)

        result = transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status=GuestStatus.PENDING,
            source="organizer_invite",
            actor_user_id=owner.id,
            establish_missing=True,
        )

        assert result.changed is True
        assert result.established is True
        assert result.previous_status is None
        assert result.participant.role.value == "guest"
        event = SkiTripRsvpTransition.query.one()
        assert event.previous_status is None
        assert event.new_status == "pending"
        assert event.source == "organizer_invite"
        assert event.actor_user_id == owner.id


def test_emits_postgresql_locks_in_trip_then_participant_order(
    client, monkeypatch
):
    with app.app_context():
        owner = _make_user("rsvp-lock-owner")
        guest = _make_user("rsvp-lock-guest")
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.PENDING)
        lock_order = []
        locked_sql = []
        query_type = type(SkiTrip.query)
        original_with_for_update = query_type.with_for_update

        def tracked_with_for_update(query, *args, **kwargs):
            entity = query.column_descriptions[0].get("entity")
            if entity in {SkiTrip, SkiTripParticipant}:
                lock_order.append(entity)
            locked_query = original_with_for_update(query, *args, **kwargs)
            locked_sql.append(str(locked_query.statement.compile(
                dialect=postgresql.dialect()
            )))
            return locked_query

        monkeypatch.setattr(
            query_type,
            "with_for_update",
            tracked_with_for_update,
        )

        transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status="going",
            source="invite_response",
        )

        assert lock_order[:2] == [SkiTrip, SkiTripParticipant]
        assert all("FOR UPDATE" in statement for statement in locked_sql[:2])
        assert "FROM ski_trip " in locked_sql[0]
        assert "FROM ski_trip_participant " in locked_sql[1]


def test_history_timestamp_is_timezone_aware(client):
    assert (
        SkiTripRsvpTransition.__table__.c.changed_at.type.timezone
        is True
    )


def test_real_transition_and_reversal_create_ordered_events(client):
    with app.app_context():
        owner = _make_user("rsvp-reversal-owner")
        guest = _make_user("rsvp-reversal-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.PENDING)

        first = transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status="going",
            source="invite_response",
            actor_user_id=guest.id,
            allowed_current_statuses={"pending"},
        )
        second = transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status=GuestStatus.PENDING,
            source="organizer_reinvite",
            actor_user_id=owner.id,
            allowed_current_statuses={GuestStatus.GOING},
        )

        assert first.previous_status == "pending"
        assert second.previous_status == "going"
        assert participant.status == GuestStatus.PENDING
        assert [
            (event.previous_status, event.new_status)
            for event in SkiTripRsvpTransition.query.order_by(
                SkiTripRsvpTransition.id
            )
        ] == [("pending", "going"), ("going", "pending")]


def test_same_state_has_no_event_and_cleans_non_going_dates(client):
    with app.app_context():
        owner = _make_user("rsvp-noop-owner")
        guest = _make_user("rsvp-noop-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.INTERESTED)
        participant.start_date = date.today()
        participant.end_date = date.today() + timedelta(days=1)
        db.session.flush()

        result = transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status="interested",
            source="self_rsvp",
        )

        assert result.changed is False
        assert result.transition is None
        assert result.attendance_dates_cleared is True
        assert participant.start_date is None
        assert participant.end_date is None
        assert SkiTripRsvpTransition.query.count() == 0


def test_real_transition_clears_attendance_dates(client):
    with app.app_context():
        owner = _make_user("rsvp-dates-owner")
        guest = _make_user("rsvp-dates-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.GOING)
        participant.start_date = date.today()
        participant.end_date = date.today() + timedelta(days=1)
        db.session.flush()

        result = transition_rsvp(
            trip_id=trip.id,
            user_id=guest.id,
            new_status="declined",
            source="participant_leave",
        )

        assert result.attendance_dates_cleared is True
        assert participant.start_date is None
        assert participant.end_date is None


@pytest.mark.parametrize(
    ("status", "source"),
    [
        ("accepted", "self_rsvp"),
        ("going", "unknown_source"),
    ],
)
def test_rejects_invalid_status_or_source(client, status, source):
    with app.app_context():
        owner = _make_user("rsvp-invalid-owner")
        guest = _make_user("rsvp-invalid-guest")
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.PENDING)

        with pytest.raises(ValueError):
            transition_rsvp(
                trip_id=trip.id,
                user_id=guest.id,
                new_status=status,
                source=source,
            )
        assert SkiTripRsvpTransition.query.count() == 0


def test_rejects_disallowed_authoritative_state(client):
    with app.app_context():
        owner = _make_user("rsvp-state-owner")
        guest = _make_user("rsvp-state-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.DECLINED)

        with pytest.raises(RsvpCurrentStateError) as exc_info:
            transition_rsvp(
                trip_id=trip.id,
                user_id=guest.id,
                new_status="going",
                source="invite_response",
                allowed_current_statuses={"pending"},
            )

        assert exc_info.value.current_status == "declined"
        assert participant.status == GuestStatus.DECLINED
        assert SkiTripRsvpTransition.query.count() == 0


def test_model_constraints_reject_forbidden_initial_source(client):
    with app.app_context():
        owner = _make_user("rsvp-check-owner")
        guest = _make_user("rsvp-check-guest")
        trip = _make_trip(owner)
        db.session.add(
            SkiTripRsvpTransition(
                trip_id=trip.id,
                user_id=guest.id,
                previous_status=None,
                new_status="going",
                source="self_rsvp",
            )
        )

        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()


def test_transition_is_atomic_under_caller_rollback(client):
    with app.app_context():
        owner = _make_user("rsvp-rollback-owner")
        guest = _make_user("rsvp-rollback-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.PENDING)
        db.session.commit()
        trip_id, guest_id = trip.id, guest.id

        transition_rsvp(
            trip_id=trip_id,
            user_id=guest_id,
            new_status="going",
            source="invite_response",
        )
        db.session.rollback()

        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=guest_id
        ).one()
        assert participant.status == GuestStatus.PENDING
        assert SkiTripRsvpTransition.query.count() == 0