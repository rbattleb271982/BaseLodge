"""Focused model and service coverage for BL-80 trip lifecycle."""

from datetime import date, timedelta

import pytest

from app import app
from models import SkiTripLifecycleEvent, db
from services.trip_lifecycle import (
    TripLifecycleAuthorizationError,
    TripLifecycleConflictError,
    TripLifecycleEligibilityError,
    transition_trip_lifecycle,
)
from tests.conftest import _make_trip, _make_user


def test_new_trip_defaults_active_but_legacy_null_is_active(client):
    with app.app_context():
        owner = _make_user("bl80-default")
        trip = _make_trip(owner)
        assert trip.lifecycle_state == "active"

        trip.lifecycle_state = None
        db.session.flush()
        result = transition_trip_lifecycle(
            trip_id=trip.id,
            actor_user_id=owner.id,
            new_state="cancelled",
        )
        assert result.previous_state == "active"
        assert result.changed is True
        assert trip.terminal_at is not None
        assert result.event.event_type == "cancelled"
        assert result.event.source == "organizer_action"


def test_completion_requires_organizer_and_ended_valid_dates(client):
    with app.app_context():
        owner = _make_user("bl80-owner")
        other = _make_user("bl80-other")
        trip = _make_trip(
            owner,
            start_date=date.today() - timedelta(days=3),
            end_date=date.today() - timedelta(days=1),
        )

        with pytest.raises(TripLifecycleAuthorizationError):
            transition_trip_lifecycle(
                trip_id=trip.id,
                actor_user_id=other.id,
                new_state="completed",
            )
        result = transition_trip_lifecycle(
            trip_id=trip.id,
            actor_user_id=owner.id,
            new_state="completed",
        )
        assert result.changed is True
        assert SkiTripLifecycleEvent.query.filter_by(trip_id=trip.id).count() == 1


def test_created_by_metadata_does_not_grant_lifecycle_authority(client):
    with app.app_context():
        owner = _make_user("bl80-canonical-owner")
        creator = _make_user("bl80-metadata-creator")
        trip = _make_trip(owner)
        trip.created_by_user_id = creator.id
        db.session.flush()

        with pytest.raises(TripLifecycleAuthorizationError):
            transition_trip_lifecycle(
                trip_id=trip.id,
                actor_user_id=creator.id,
                new_state="cancelled",
            )
        assert trip.lifecycle_state == "active"
        assert SkiTripLifecycleEvent.query.filter_by(trip_id=trip.id).count() == 0


def test_terminal_retry_is_idempotent_and_opposite_state_conflicts(client):
    with app.app_context():
        owner = _make_user("bl80-idempotent")
        trip = _make_trip(owner)
        first = transition_trip_lifecycle(
            trip_id=trip.id,
            actor_user_id=owner.id,
            new_state="cancelled",
        )
        retry = transition_trip_lifecycle(
            trip_id=trip.id,
            actor_user_id=owner.id,
            new_state="cancelled",
        )
        assert first.changed is True
        assert retry.changed is False
        assert retry.event is None
        assert SkiTripLifecycleEvent.query.filter_by(trip_id=trip.id).count() == 1
        with pytest.raises(TripLifecycleConflictError):
            transition_trip_lifecycle(
                trip_id=trip.id,
                actor_user_id=owner.id,
                new_state="completed",
            )


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        (None, date.today() - timedelta(days=1)),
        (date.today(), None),
        (date.today(), date.today() - timedelta(days=1)),
        (date.today(), date.today()),
    ],
)
def test_ineligible_completion_writes_nothing(client, start_date, end_date):
    with app.app_context():
        owner = _make_user("bl80-ineligible")
        trip = _make_trip(owner, start_date=start_date, end_date=end_date)
        with pytest.raises(TripLifecycleEligibilityError):
            transition_trip_lifecycle(
                trip_id=trip.id,
                actor_user_id=owner.id,
                new_state="completed",
            )
        assert trip.lifecycle_state == "active"
        assert trip.terminal_at is None
        assert SkiTripLifecycleEvent.query.filter_by(trip_id=trip.id).count() == 0