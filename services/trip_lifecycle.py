"""Transaction-neutral terminal lifecycle operations for SkiTrip."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import FrozenSet, Optional

from models import SkiTrip, SkiTripLifecycleEvent, db


TERMINAL_LIFECYCLE_STATES: FrozenSet[str] = frozenset(
    ("completed", "cancelled")
)
TRIP_LIFECYCLE_SOURCES: FrozenSet[str] = frozenset(("organizer_action",))


class TripLifecycleAuthorizationError(PermissionError):
    """The actor is not the trip's established organizer."""


class TripLifecycleConflictError(ValueError):
    """A trip already has the opposite terminal state."""

    def __init__(self, current_state: str, requested_state: str):
        self.current_state = current_state
        self.requested_state = requested_state
        super().__init__(
            f"Trip is already {current_state!r}; cannot mark it "
            f"{requested_state!r}"
        )


class TripLifecycleEligibilityError(ValueError):
    """The trip is not eligible for the requested terminal transition."""


@dataclass(frozen=True)
class TripLifecycleTransitionResult:
    trip: SkiTrip
    previous_state: str
    new_state: str
    changed: bool
    event: Optional[SkiTripLifecycleEvent]


def transition_trip_lifecycle(
    *,
    trip_id: int,
    actor_user_id: int,
    new_state: Optional[str] = None,
    target_state: Optional[str] = None,
    source: str = "organizer_action",
    today: Optional[date] = None,
) -> TripLifecycleTransitionResult:
    """Set a trip's terminal state and append at most one event.

    NULL is the legacy representation of active. The trip row is refreshed
    under a lock before authorization and state checks. The caller owns the
    surrounding commit or rollback.
    """
    if new_state is not None and target_state is not None:
        raise ValueError("Specify only one lifecycle target")
    requested_state = new_state if new_state is not None else target_state
    if requested_state not in TERMINAL_LIFECYCLE_STATES:
        raise ValueError(
            f"Invalid terminal lifecycle state: {requested_state!r}"
        )
    if source not in TRIP_LIFECYCLE_SOURCES:
        raise ValueError(f"Invalid trip lifecycle source: {source!r}")

    with db.session.no_autoflush:
        trip = (
            SkiTrip.query.filter_by(id=trip_id)
            .populate_existing()
            .with_for_update()
            .one()
        )

    # Existing product authorization consistently treats SkiTrip.user_id as
    # the owner. created_by_user_id is provenance metadata and must not grant
    # lifecycle authority.
    if trip.user_id != actor_user_id:
        raise TripLifecycleAuthorizationError(
            "Only the trip owner may change its lifecycle state"
        )

    current_state = trip.lifecycle_state or "active"
    if current_state == requested_state:
        db.session.flush()
        return TripLifecycleTransitionResult(
            trip=trip,
            previous_state=current_state,
            new_state=requested_state,
            changed=False,
            event=None,
        )
    if current_state in TERMINAL_LIFECYCLE_STATES:
        raise TripLifecycleConflictError(current_state, requested_state)

    if requested_state == "completed":
        effective_today = today or date.today()
        if (
            trip.start_date is None
            or trip.end_date is None
            or trip.start_date > trip.end_date
            or trip.end_date >= effective_today
        ):
            raise TripLifecycleEligibilityError(
                "A trip can be completed only after a valid date range has ended"
            )

    trip.lifecycle_state = requested_state
    trip.terminal_at = datetime.now(timezone.utc)
    event = SkiTripLifecycleEvent(
        trip_id=trip.id,
        event_type=requested_state,
        actor_user_id=actor_user_id,
        source=source,
    )
    db.session.add(event)
    db.session.flush()
    return TripLifecycleTransitionResult(
        trip=trip,
        previous_state=current_state,
        new_state=requested_state,
        changed=True,
        event=event,
    )


def complete_trip(*, trip_id: int, actor_user_id: int, today=None):
    """Complete an eligible trip without committing."""
    return transition_trip_lifecycle(
        trip_id=trip_id,
        actor_user_id=actor_user_id,
        new_state="completed",
        today=today,
    )


def cancel_trip(*, trip_id: int, actor_user_id: int):
    """Cancel an active trip without committing."""
    return transition_trip_lifecycle(
        trip_id=trip_id,
        actor_user_id=actor_user_id,
        new_state="cancelled",
    )