"""PostgreSQL-only two-session concurrency coverage for BL-78."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
import sqlalchemy as sa

from app import app
from models import (
    GuestStatus,
    SkiTripParticipant,
    SkiTripRsvpTransition,
    db,
)
from services.rsvp_transitions import (
    RsvpCurrentStateError,
    transition_rsvp,
)
from tests.conftest import _make_trip, _make_user, _swap_engine


@pytest.fixture(scope="module")
def postgres_rsvp_database():
    database_url = os.environ.get("BL78_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BL78_TEST_POSTGRES_URL is required for lock integration tests")

    engine = sa.create_engine(database_url, pool_pre_ping=True)
    saved_engine = _swap_engine(engine)
    with app.app_context():
        db.drop_all()
        db.create_all()

    try:
        yield
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
        _swap_engine(saved_engine)


def _setup_participant(status=None):
    with app.app_context():
        owner = _make_user(f"pg-owner-{os.urandom(5).hex()}")
        guest = _make_user(f"pg-guest-{os.urandom(5).hex()}")
        trip = _make_trip(owner)
        if status is not None:
            db.session.add(SkiTripParticipant(
                trip_id=trip.id,
                user_id=guest.id,
                status=status,
            ))
        db.session.commit()
        return trip.id, guest.id


def _run_concurrently(trip_id, guest_id, requests):
    barrier = Barrier(len(requests))

    def worker(request_args):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                result = transition_rsvp(
                    trip_id=trip_id,
                    user_id=guest_id,
                    **request_args,
                )
                db.session.commit()
                return (
                    "ok",
                    result.changed,
                    result.previous_status,
                    result.new_status,
                )
            except RsvpCurrentStateError as exc:
                db.session.rollback()
                return ("state_error", exc.current_status)
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(worker, requests))


def test_concurrent_first_establishment_creates_one_participant_and_event(
    postgres_rsvp_database,
):
    trip_id, guest_id = _setup_participant()
    request_args = {
        "new_status": GuestStatus.INTERESTED,
        "source": "token_response",
        "actor_user_id": guest_id,
        "allowed_current_statuses": {GuestStatus.PENDING},
        "establish_missing": True,
    }

    outcomes = _run_concurrently(
        trip_id,
        guest_id,
        [request_args, request_args],
    )

    assert sorted(outcome[0] for outcome in outcomes) == ["ok", "state_error"]
    with app.app_context():
        assert SkiTripParticipant.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).count() == 1
        assert SkiTripRsvpTransition.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).count() == 1


def test_concurrent_same_target_retry_writes_exactly_one_transition(
    postgres_rsvp_database,
):
    trip_id, guest_id = _setup_participant(GuestStatus.PENDING)
    request_args = {
        "new_status": GuestStatus.GOING,
        "source": "invite_response",
        "actor_user_id": guest_id,
        "allowed_current_statuses": {
            GuestStatus.PENDING,
            GuestStatus.INTERESTED,
            GuestStatus.GOING,
        },
    }

    outcomes = _run_concurrently(
        trip_id,
        guest_id,
        [request_args, request_args],
    )

    assert sorted(outcome[1] for outcome in outcomes) == [False, True]
    with app.app_context():
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).one()
        events = SkiTripRsvpTransition.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).all()
        assert participant.status == GuestStatus.GOING
        assert [
            (event.previous_status, event.new_status)
            for event in events
        ] == [("pending", "going")]


def test_concurrent_different_targets_form_one_serial_history_chain(
    postgres_rsvp_database,
):
    trip_id, guest_id = _setup_participant(GuestStatus.PENDING)
    common_args = {
        "source": "invite_response",
        "actor_user_id": guest_id,
        "allowed_current_statuses": {
            GuestStatus.PENDING,
            GuestStatus.INTERESTED,
            GuestStatus.GOING,
        },
    }

    outcomes = _run_concurrently(
        trip_id,
        guest_id,
        [
            {**common_args, "new_status": GuestStatus.GOING},
            {**common_args, "new_status": GuestStatus.INTERESTED},
        ],
    )

    assert all(outcome[0] == "ok" and outcome[1] is True for outcome in outcomes)
    with app.app_context():
        events = SkiTripRsvpTransition.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).order_by(SkiTripRsvpTransition.id).all()
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id,
            user_id=guest_id,
        ).one()
        assert len(events) == 2
        assert events[0].previous_status == "pending"
        assert events[1].previous_status == events[0].new_status
        assert events[1].new_status != events[0].new_status
        assert participant.status.value == events[1].new_status