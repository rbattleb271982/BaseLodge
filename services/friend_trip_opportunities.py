"""BL-110 first-public trip discovery producer."""

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from models import Friend, MessageOutbox
from services.message_dispatch import enqueue_messaging_event
from services.message_outbox import lock_opportunity_trip
from services.messaging_constants import EventName
from services.opportunity_messaging import (
    lock_opportunity_policy_decisions,
    opportunity_occurrence_id,
    stage_opportunity_intents,
)


@dataclass(frozen=True)
class FriendTripOpportunityResult:
    consumed: bool
    marker_outbox_id: int | None = None
    recipient_user_ids: tuple[int, ...] = ()
    reason: str | None = None


def _reciprocal_friend_ids(organizer_id, session):
    reverse = sa.orm.aliased(Friend)
    return tuple(session.execute(
        sa.select(sa.distinct(Friend.friend_id))
        .join(
            reverse,
            sa.and_(
                reverse.user_id == Friend.friend_id,
                reverse.friend_id == Friend.user_id,
            ),
        )
        .where(
            Friend.user_id == organizer_id,
            Friend.friend_id != organizer_id,
        )
        .order_by(Friend.friend_id)
    ).scalars().all())


def stage_friend_trip_created_opportunity(
    trip_id,
    *,
    session,
    source_route,
    today=None,
    producer_release_sha=None,
    require_verified_release=False,
):
    """Consume one prospective first-public trip event and fan it out atomically."""
    trip = lock_opportunity_trip(trip_id, session=session)
    decisions = lock_opportunity_policy_decisions(
        (EventName.FRIEND_TRIP_CREATED,), session=session
    )
    decision = decisions[EventName.FRIEND_TRIP_CREATED]
    boundary = decision.activation_boundary
    current_date = today or date.today()
    if not decision.eligible:
        return FriendTripOpportunityResult(False, reason=decision.reason)
    if (
        trip.is_public is not True
        or (trip.lifecycle_state or "active") != "active"
        or trip.start_date is None
        or trip.end_date is None
        or trip.end_date < current_date
        or trip.created_at is None
        or boundary is None
        or trip.created_at < boundary
        or type(trip.user_id) is not int
    ):
        return FriendTripOpportunityResult(False, reason="trip_not_prospective")

    occurrence_id = opportunity_occurrence_id(
        EventName.FRIEND_TRIP_CREATED, trip.id
    )
    marker = session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.event_name == EventName.FRIEND_TRIP_CREATED,
            MessageOutbox.occurrence_id == occurrence_id,
            MessageOutbox.recipient_user_id == trip.user_id,
        )
        .order_by(MessageOutbox.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().first()
    if marker is not None:
        return FriendTripOpportunityResult(
            False, marker_outbox_id=marker.id, reason="already_consumed"
        )

    recipient_ids = _reciprocal_friend_ids(trip.user_id, session)
    intents = [
        {
            "event_name": EventName.FRIEND_TRIP_CREATED,
            "actor_user_id": trip.user_id,
            "recipient_user_id": recipient_id,
            "entity_type": "trip",
            "entity_id": trip.id,
            "occurrence_id": occurrence_id,
            "metadata": {},
            "source_route": source_route,
        }
        for recipient_id in (trip.user_id, *recipient_ids)
    ]
    staged = stage_opportunity_intents(
        intents,
        session=session,
        enqueue=enqueue_messaging_event,
        producer_release_sha=producer_release_sha,
        require_verified_release=require_verified_release,
    )
    if not staged or not all(staged):
        raise RuntimeError("friend trip opportunity staging was refused")
    marker = session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.event_name == EventName.FRIEND_TRIP_CREATED,
            MessageOutbox.occurrence_id == occurrence_id,
            MessageOutbox.recipient_user_id == trip.user_id,
        )
    ).scalar_one()
    return FriendTripOpportunityResult(
        True,
        marker_outbox_id=marker.id,
        recipient_user_ids=recipient_ids,
    )