"""PostgreSQL-only lock integration coverage for BL-80."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import os
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app import _lock_mutable_trip, app
from models import (
    GuestStatus,
    SkiTrip,
    SkiTripLifecycleEvent,
    SkiTripParticipant,
    TripInviteToken,
    db,
)
from services.rsvp_transitions import transition_rsvp
from services.trip_lifecycle import (
    TripLifecycleAuthorizationError,
    transition_trip_lifecycle,
)
from tests.conftest import _add_participant, _make_trip, _make_user, _swap_engine


@pytest.fixture(scope="module")
def postgres_lifecycle_database():
    database_url = os.environ.get("BL80_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BL80_TEST_POSTGRES_URL is required for lock tests")
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


def test_concurrent_same_terminal_action_appends_one_event(
    postgres_lifecycle_database,
):
    with app.app_context():
        owner = _make_user("bl80-pg")
        trip = _make_trip(owner)
        db.session.commit()
        trip_id, owner_id = trip.id, owner.id

    barrier = Barrier(2)

    def worker(_):
        with app.app_context():
            barrier.wait(timeout=10)
            result = transition_trip_lifecycle(
                trip_id=trip_id,
                actor_user_id=owner_id,
                new_state="cancelled",
            )
            db.session.commit()
            db.session.remove()
            return result.changed

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(worker, range(2)))

    assert sorted(outcomes) == [False, True]
    with app.app_context():
        assert SkiTripLifecycleEvent.query.filter_by(trip_id=trip_id).count() == 1


def _terminal_wins_race(*, trip_id, owner_id, transition, mutation):
    """Run a terminal transition holding the parent lock before a route mutation.

    ``_lock_mutable_trip`` is the exact trip-first lock/check used by the
    request guard. The barrier ensures the mutation attempts its locked read
    only after the lifecycle service has flushed its terminal write.
    """
    barrier = Barrier(2)

    def terminal_worker():
        with app.app_context():
            result = transition()
            barrier.wait(timeout=10)
            db.session.commit()
            db.session.remove()
            return result.changed

    def mutation_worker():
        with app.app_context():
            barrier.wait(timeout=10)
            trip, terminal = _lock_mutable_trip(trip_id)
            if terminal:
                db.session.rollback()
                db.session.remove()
                return False
            mutation(trip)
            db.session.commit()
            db.session.remove()
            return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        terminal_result = executor.submit(terminal_worker)
        mutation_result = executor.submit(mutation_worker)
        return terminal_result.result(timeout=15), mutation_result.result(timeout=15)


def test_cancel_serializes_before_core_trip_edit(
    postgres_lifecycle_database,
):
    with app.app_context():
        owner = _make_user("bl80-cancel-edit")
        trip = _make_trip(owner)
        db.session.commit()
        trip_id, owner_id, original_notes = trip.id, owner.id, trip.notes

    terminal_changed, mutation_changed = _terminal_wins_race(
        trip_id=trip_id,
        owner_id=owner_id,
        transition=lambda: transition_trip_lifecycle(
            trip_id=trip_id, actor_user_id=owner_id, new_state="cancelled",
        ),
        mutation=lambda trip: setattr(trip, "notes", "must not be written"),
    )
    assert (terminal_changed, mutation_changed) == (True, False)
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.lifecycle_state == "cancelled"
        assert trip.notes == original_notes


@pytest.mark.parametrize("kind", ("rsvp", "invite"))
def test_cancel_serializes_before_rsvp_or_invite_mutation(
    postgres_lifecycle_database, kind,
):
    with app.app_context():
        owner = _make_user(f"bl80-cancel-{kind}-owner")
        guest = _make_user(f"bl80-cancel-{kind}-guest")
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.INTERESTED)
        db.session.commit()
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id

    def mutation(_trip):
        if kind == "rsvp":
            transition_rsvp(
                trip_id=trip_id,
                user_id=guest_id,
                new_status=GuestStatus.GOING,
                source="organizer_invite",
                actor_user_id=owner_id,
                allowed_current_statuses={GuestStatus.INTERESTED},
            )
        else:
            db.session.add(TripInviteToken(
                token=f"bl80-{uuid4().hex}",
                trip_id=trip_id,
                inviter_user_id=owner_id,
            ))
            db.session.flush()

    terminal_changed, mutation_changed = _terminal_wins_race(
        trip_id=trip_id,
        owner_id=owner_id,
        transition=lambda: transition_trip_lifecycle(
            trip_id=trip_id, actor_user_id=owner_id, new_state="cancelled",
        ),
        mutation=mutation,
    )
    assert (terminal_changed, mutation_changed) == (True, False)
    with app.app_context():
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=guest_id,
        ).one()
        assert participant.status == GuestStatus.INTERESTED
        assert TripInviteToken.query.filter_by(trip_id=trip_id).count() == 0


def test_complete_serializes_before_date_edit(
    postgres_lifecycle_database,
):
    with app.app_context():
        owner = _make_user("bl80-complete-edit")
        original_end = date.today() - timedelta(days=1)
        trip = _make_trip(
            owner,
            start_date=original_end - timedelta(days=2),
            end_date=original_end,
        )
        db.session.commit()
        trip_id, owner_id = trip.id, owner.id

    terminal_changed, mutation_changed = _terminal_wins_race(
        trip_id=trip_id,
        owner_id=owner_id,
        transition=lambda: transition_trip_lifecycle(
            trip_id=trip_id, actor_user_id=owner_id, new_state="completed",
        ),
        mutation=lambda trip: setattr(trip, "end_date", date.today()),
    )
    assert (terminal_changed, mutation_changed) == (True, False)
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.lifecycle_state == "completed"
        assert trip.end_date == original_end


def test_provenance_creator_has_no_lifecycle_authority(
    postgres_lifecycle_database,
):
    with app.app_context():
        owner = _make_user("bl80-authoritative-owner")
        provenance_creator = _make_user("bl80-provenance-only")
        trip = _make_trip(owner, created_by_user_id=provenance_creator.id)
        db.session.commit()
        with pytest.raises(TripLifecycleAuthorizationError):
            transition_trip_lifecycle(
                trip_id=trip.id,
                actor_user_id=provenance_creator.id,
                new_state="cancelled",
            )
        assert trip.lifecycle_state == "active"


def test_account_deletion_privacy_anonymizes_surviving_lifecycle_actor(
    postgres_lifecycle_database,
):
    """A deleted provenance actor cannot remain attached to another user's trip."""
    with app.app_context():
        owner = _make_user("bl80-surviving-owner")
        deleted_actor = _make_user("bl80-deleted-provenance")
        trip = _make_trip(owner, created_by_user_id=deleted_actor.id)
        event = SkiTripLifecycleEvent(
            trip_id=trip.id,
            event_type="cancelled",
            source="organizer_action",
            actor_user_id=deleted_actor.id,
        )
        db.session.add(event)
        db.session.commit()
        event_id, actor_id = event.id, deleted_actor.id

        # This mirrors account deletion's provenance cleanup. The event must
        # survive because its trip belongs to the canonical owner.
        trip.created_by_user_id = None
        db.session.delete(deleted_actor)
        db.session.commit()
        retained = db.session.get(SkiTripLifecycleEvent, event_id)
        assert retained is not None
        assert retained.actor_user_id is None
        assert db.session.get(SkiTrip, trip.id) is not None
        assert db.session.get(SkiTripLifecycleEvent, event_id).actor_user_id != actor_id