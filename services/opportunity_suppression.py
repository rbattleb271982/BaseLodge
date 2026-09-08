"""Set-based enqueue-time suppression for trip opportunity recipients."""

from datetime import datetime

import sqlalchemy as sa

from models import (
    GuestStatus,
    Invitation,
    InviteType,
    MessageOutbox,
    PushDeviceToken,
    SkiTripParticipant,
    User,
)
from services.messaging_constants import SuppressionReason


_DIRECT_PARTICIPANT_STATUSES = (
    GuestStatus.PENDING,
    GuestStatus.INTERESTED,
    GuestStatus.GOING,
)


def initial_opportunity_suppressions(trip_id, recipient_user_ids, *, session):
    """Return current terminal suppression reasons with fixed-count queries."""
    recipient_ids = tuple(sorted(set(recipient_user_ids)))
    if not recipient_ids:
        return {}

    user_rows = session.execute(
        sa.select(User.id, User.push_notifications_enabled).where(
            User.id.in_(recipient_ids)
        )
    ).all()
    enabled_by_user_id = {
        user_id: enabled is True for user_id, enabled in user_rows
    }
    token_user_ids = set(session.execute(
        sa.select(sa.distinct(PushDeviceToken.user_id)).where(
            PushDeviceToken.user_id.in_(recipient_ids),
            PushDeviceToken.active.is_(True),
        )
    ).scalars().all())
    participant_user_ids = set(session.execute(
        sa.select(sa.distinct(SkiTripParticipant.user_id)).where(
            SkiTripParticipant.trip_id == trip_id,
            SkiTripParticipant.user_id.in_(recipient_ids),
            SkiTripParticipant.status.in_(_DIRECT_PARTICIPANT_STATUSES),
        )
    ).scalars().all())
    invitee_user_ids = set(session.execute(
        sa.select(sa.distinct(Invitation.receiver_id)).where(
            Invitation.trip_id == trip_id,
            Invitation.receiver_id.in_(recipient_ids),
            Invitation.invite_type == InviteType.OUTBOUND,
            Invitation.status == "pending",
        )
    ).scalars().all())

    suppressions = {}
    for recipient_id in recipient_ids:
        if recipient_id in participant_user_ids or recipient_id in invitee_user_ids:
            suppressions[recipient_id] = SuppressionReason.PRIVACY_DENIED
        elif not enabled_by_user_id.get(recipient_id, False):
            suppressions[recipient_id] = SuppressionReason.USER_OPTED_OUT
        elif recipient_id not in token_user_ids:
            suppressions[recipient_id] = SuppressionReason.NO_DEVICE_TOKEN
    return suppressions


def terminally_suppress_staged_opportunities(
    event_name,
    occurrence_id,
    suppressions,
    *,
    session,
    now=None,
):
    """Make initially ineligible consumed occurrences permanently unclaimable."""
    if not suppressions:
        return ()
    rows = session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.event_name == event_name,
            MessageOutbox.occurrence_id == occurrence_id,
            MessageOutbox.recipient_user_id.in_(tuple(suppressions)),
            MessageOutbox.status.in_(("pending", "retryable")),
            MessageOutbox.provider_phase == "not_started",
        )
        .order_by(MessageOutbox.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all()
    timestamp = now or datetime.utcnow()
    for row in rows:
        row.status = "suppressed"
        row.last_error = suppressions[row.recipient_user_id]
        row.completed_at = timestamp
        row.updated_at = timestamp
        row.lease_token = None
        row.lease_owner = None
        row.leased_at = None
        row.lease_expires_at = None
    session.flush()
    return tuple(row.id for row in rows)