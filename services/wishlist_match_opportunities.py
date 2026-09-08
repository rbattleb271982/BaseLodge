"""BL-16 wishlist-match opportunity producers."""

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from models import (
    Friend,
    GuestStatus,
    MessageOutbox,
    Resort,
    SkiTripParticipant,
    SkiTripRsvpTransition,
    User,
)
from services.message_dispatch import enqueue_messaging_event
from services.message_outbox import lock_opportunity_trip
from services.messaging_constants import EventName
from services.opportunity_messaging import (
    lock_opportunity_policy_decisions,
    opportunity_occurrence_id,
    opportunity_timestamp_at_or_after,
    stage_opportunity_intents,
)
from services.opportunity_suppression import (
    initial_opportunity_suppressions,
    terminally_suppress_staged_opportunities,
)
from services.wishlist import normalize_wishlist_resort_ids


@dataclass(frozen=True)
class WishlistMatchOpportunityResult:
    consumed: bool
    marker_outbox_id: int | None = None
    recipient_user_ids: tuple[int, ...] = ()
    reason: str | None = None


def _eligible_resort(trip, session):
    if type(trip.resort_id) is not int:
        return None
    return session.execute(
        sa.select(Resort).where(
            Resort.id == trip.resort_id,
            Resort.is_active.is_(True),
            Resort.is_region.is_(False),
        )
    ).scalar_one_or_none()


def _matching_reciprocal_friend_ids(actor_user_id, resort_id, session):
    """Select reciprocal candidates once, then normalize loaded JSON in memory."""
    reverse = sa.orm.aliased(Friend)
    rows = session.execute(
        sa.select(User.id, User.wish_list_resorts)
        .join(Friend, Friend.friend_id == User.id)
        .join(
            reverse,
            sa.and_(
                reverse.user_id == Friend.friend_id,
                reverse.friend_id == Friend.user_id,
            ),
        )
        .where(
            Friend.user_id == actor_user_id,
            User.id != actor_user_id,
        )
        .order_by(User.id)
    ).all()
    return tuple(
        user_id
        for user_id, raw_wishlist in rows
        if resort_id in normalize_wishlist_resort_ids(
            raw_wishlist, strict=False
        )
    )


def _organizer_marker(trip, occurrence_id, session):
    return session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.event_name == EventName.WISHLIST_MATCH_DETECTED,
            MessageOutbox.occurrence_id == occurrence_id,
            MessageOutbox.recipient_user_id == trip.user_id,
        )
        .order_by(MessageOutbox.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().first()


def stage_wishlist_match_opportunity(
    trip_id,
    *,
    actor_user_id,
    session,
    source_route,
    rsvp_transition_id=None,
    today=None,
    producer_release_sha=None,
    require_verified_release=False,
):
    """Consume one organizer or changed-to-Going wishlist-match trigger."""
    trip = lock_opportunity_trip(trip_id, session=session)
    decision = lock_opportunity_policy_decisions(
        (EventName.WISHLIST_MATCH_DETECTED,), session=session
    )[EventName.WISHLIST_MATCH_DETECTED]
    if not decision.eligible:
        return WishlistMatchOpportunityResult(False, reason=decision.reason)

    boundary = decision.activation_boundary
    current_date = today or date.today()
    resort = _eligible_resort(trip, session)
    if (
        trip.is_public is not True
        or (trip.lifecycle_state or "active") != "active"
        or trip.start_date is None
        or trip.end_date is None
        or trip.end_date < current_date
        or resort is None
        or boundary is None
        or type(actor_user_id) is not int
    ):
        return WishlistMatchOpportunityResult(
            False, reason="trip_not_eligible"
        )

    organizer_trigger = rsvp_transition_id is None
    transition = None
    if organizer_trigger:
        if (
            trip.user_id != actor_user_id
            or trip.created_at is None
            or not opportunity_timestamp_at_or_after(
                trip.created_at, boundary
            )
        ):
            return WishlistMatchOpportunityResult(
                False, reason="organizer_trigger_not_prospective"
            )
    else:
        if type(rsvp_transition_id) is not int:
            return WishlistMatchOpportunityResult(
                False, reason="invalid_rsvp_transition"
            )
        transition = session.execute(
            sa.select(SkiTripRsvpTransition)
            .where(SkiTripRsvpTransition.id == rsvp_transition_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        participant = session.execute(
            sa.select(SkiTripParticipant).where(
                SkiTripParticipant.trip_id == trip.id,
                SkiTripParticipant.user_id == actor_user_id,
            )
        ).scalar_one_or_none()
        if (
            transition is None
            or transition.trip_id != trip.id
            or transition.user_id != actor_user_id
            or transition.new_status != GuestStatus.GOING.value
            or transition.changed_at is None
            or not opportunity_timestamp_at_or_after(
                transition.changed_at, boundary
            )
            or participant is None
            or participant.status != GuestStatus.GOING
        ):
            return WishlistMatchOpportunityResult(
                False, reason="going_trigger_not_prospective"
            )

    occurrence_id = opportunity_occurrence_id(
        EventName.WISHLIST_MATCH_DETECTED, trip.id
    )
    marker = None
    if organizer_trigger:
        marker = _organizer_marker(trip, occurrence_id, session)
        if marker is not None:
            return WishlistMatchOpportunityResult(
                False,
                marker_outbox_id=marker.id,
                reason="organizer_trigger_already_consumed",
            )

    recipient_ids = _matching_reciprocal_friend_ids(
        actor_user_id, resort.id, session
    )
    metadata = {"resort_id": resort.id}
    if transition is not None:
        metadata["rsvp_transition_id"] = transition.id
    staged_recipient_ids = (
        (trip.user_id, *recipient_ids)
        if organizer_trigger
        else recipient_ids
    )
    preexisting_recipient_ids = set()
    if staged_recipient_ids:
        preexisting_recipient_ids = set(session.execute(
            sa.select(MessageOutbox.recipient_user_id).where(
                MessageOutbox.event_name == EventName.WISHLIST_MATCH_DETECTED,
                MessageOutbox.occurrence_id == occurrence_id,
                MessageOutbox.recipient_user_id.in_(staged_recipient_ids),
            )
        ).scalars().all())
    intents = [
        {
            "event_name": EventName.WISHLIST_MATCH_DETECTED,
            "actor_user_id": actor_user_id,
            "recipient_user_id": recipient_id,
            "entity_type": "trip",
            "entity_id": trip.id,
            "occurrence_id": occurrence_id,
            "metadata": metadata,
            "source_route": source_route,
        }
        for recipient_id in staged_recipient_ids
    ]
    if not intents:
        return WishlistMatchOpportunityResult(
            False, reason="no_matching_recipients"
        )
    staged = stage_opportunity_intents(
        intents,
        session=session,
        enqueue=enqueue_messaging_event,
        producer_release_sha=producer_release_sha,
        require_verified_release=require_verified_release,
    )
    if not staged or not all(staged):
        raise RuntimeError("wishlist match opportunity staging was refused")
    new_recipient_ids = tuple(
        recipient_id
        for recipient_id in recipient_ids
        if recipient_id not in preexisting_recipient_ids
    )
    suppressions = initial_opportunity_suppressions(
        trip.id, new_recipient_ids, session=session
    )
    terminally_suppress_staged_opportunities(
        EventName.WISHLIST_MATCH_DETECTED,
        occurrence_id,
        suppressions,
        session=session,
    )

    if organizer_trigger:
        marker = _organizer_marker(trip, occurrence_id, session)
        if marker is None:
            raise RuntimeError("wishlist match organizer marker was not staged")
    return WishlistMatchOpportunityResult(
        True,
        marker_outbox_id=marker.id if marker is not None else None,
        recipient_user_ids=recipient_ids,
    )