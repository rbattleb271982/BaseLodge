"""Focused, transaction-neutral SkiTrip RSVP transition operations."""

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional

from models import (
    GuestStatus,
    ParticipantRole,
    SkiTrip,
    SkiTripParticipant,
    SkiTripRsvpTransition,
    db,
)


CANONICAL_RSVP_STATUSES: FrozenSet[str] = frozenset(
    ("pending", "interested", "going", "declined", "removed")
)
RSVP_TRANSITION_SOURCES: FrozenSet[str] = frozenset(
    (
        "trip_creation_invite",
        "organizer_invite",
        "invite_cancel",
        "token_response",
        "invite_response",
        "self_rsvp",
        "organizer_rsvp",
        "organizer_remove",
        "organizer_reinvite",
        "join_request_accept",
        "participant_leave",
    )
)
INITIAL_RSVP_SOURCES: FrozenSet[str] = frozenset(
    (
        "trip_creation_invite",
        "organizer_invite",
        "token_response",
        "join_request_accept",
    )
)


class RsvpCurrentStateError(ValueError):
    """The authoritative RSVP state is not allowed for this operation."""

    def __init__(self, current_status, allowed_statuses):
        self.current_status = current_status
        self.allowed_statuses = frozenset(allowed_statuses)
        super().__init__(
            f"RSVP state {current_status!r} is not one of "
            f"{sorted(self.allowed_statuses)!r}"
        )


@dataclass(frozen=True)
class RsvpTransitionResult:
    trip: SkiTrip
    participant: SkiTripParticipant
    previous_status: Optional[str]
    new_status: str
    changed: bool
    established: bool
    transition: Optional[SkiTripRsvpTransition]
    attendance_dates_cleared: bool


def _status_value(value):
    return value.value if isinstance(value, GuestStatus) else value


def _validated_status(value, field_name):
    value = _status_value(value)
    if value not in CANONICAL_RSVP_STATUSES:
        raise ValueError(f"Invalid canonical RSVP {field_name}: {value!r}")
    return value


def transition_rsvp(
    *,
    trip_id: int,
    user_id: int,
    new_status,
    source: str,
    actor_user_id: Optional[int] = None,
    allowed_current_statuses: Optional[Iterable] = None,
    establish_missing: bool = False,
) -> RsvpTransitionResult:
    """Apply one authoritative guest RSVP transition without committing.

    The trip row is locked before the participant row, serializing participant
    establishment while preserving the participant table's existing unique
    ``(trip_id, user_id)`` behavior.
    """
    target = _validated_status(new_status, "status")
    if source not in RSVP_TRANSITION_SOURCES:
        raise ValueError(f"Invalid RSVP transition source: {source!r}")

    allowed = None
    if allowed_current_statuses is not None:
        allowed = frozenset(
            _validated_status(value, "allowed current status")
            for value in allowed_current_statuses
        )

    # Do not let a stale in-memory participant write itself before the
    # authoritative locked read has refreshed it.
    with db.session.no_autoflush:
        trip = (
            SkiTrip.query.filter_by(id=trip_id)
            .populate_existing()
            .with_for_update()
            .one()
        )
        participant = (
            SkiTripParticipant.query.filter_by(trip_id=trip.id, user_id=user_id)
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )

    if participant is None:
        if not establish_missing:
            raise RsvpCurrentStateError(None, allowed or ())
        if user_id == trip.user_id:
            raise ValueError("Owner bootstrap is not an RSVP history event")
        if source not in INITIAL_RSVP_SOURCES:
            raise ValueError(
                f"Source {source!r} cannot establish an initial RSVP"
            )
        participant = SkiTripParticipant(
            trip_id=trip.id,
            user_id=user_id,
            status=GuestStatus(target),
            role=ParticipantRole.GUEST,
        )
        transition = SkiTripRsvpTransition(
            trip_id=trip.id,
            user_id=user_id,
            previous_status=None,
            new_status=target,
            actor_user_id=actor_user_id,
            source=source,
        )
        db.session.add_all((participant, transition))
        db.session.flush()
        return RsvpTransitionResult(
            trip=trip,
            participant=participant,
            previous_status=None,
            new_status=target,
            changed=True,
            established=True,
            transition=transition,
            attendance_dates_cleared=False,
        )

    current = _validated_status(participant.status, "current status")
    if allowed is not None and current not in allowed:
        raise RsvpCurrentStateError(current, allowed)

    had_attendance_dates = (
        participant.start_date is not None or participant.end_date is not None
    )
    clear_attendance_dates = not (
        current == GuestStatus.GOING.value
        and target == GuestStatus.GOING.value
    )
    if clear_attendance_dates:
        participant.start_date = None
        participant.end_date = None

    if current == target:
        db.session.flush()
        return RsvpTransitionResult(
            trip=trip,
            participant=participant,
            previous_status=current,
            new_status=target,
            changed=False,
            established=False,
            transition=None,
            attendance_dates_cleared=(
                clear_attendance_dates and had_attendance_dates
            ),
        )

    participant.status = GuestStatus(target)
    transition = SkiTripRsvpTransition(
        trip_id=trip.id,
        user_id=user_id,
        previous_status=current,
        new_status=target,
        actor_user_id=actor_user_id,
        source=source,
    )
    db.session.add(transition)
    db.session.flush()
    return RsvpTransitionResult(
        trip=trip,
        participant=participant,
        previous_status=current,
        new_status=target,
        changed=True,
        established=False,
        transition=transition,
        attendance_dates_cleared=had_attendance_dates,
    )


# Descriptive alias for callers that prefer an imperative service name.
apply_rsvp_transition = transition_rsvp