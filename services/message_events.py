"""
BaseLodge MessageEventLog v1 — helper utilities.

create_message_event  — append a canonical event row (logging only, no sends)
is_duplicate_event    — dedupe check before dispatching a notification
should_retry          — retry eligibility check for a failed log row
"""

from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_

from models import db, MessageEventLog
from services.messaging_constants import (
    DeliveryStatus,
    SuppressionReason,
    DEDUPE_WINDOW_SECONDS,
    BYPASS_DEDUPE_EVENTS,
    MAX_RETRY_COUNT,
    RETRYABLE_STATUSES,
)


def create_message_event(
    event_name,
    category,
    *,
    actor_user_id=None,
    recipient_user_id=None,
    object_type=None,
    object_id=None,
    channel=None,
    provider=None,
    payload_json=None,
    message_title=None,
    message_body=None,
    delivery_status=DeliveryStatus.PENDING,
    suppression_reason=None,
    error_message=None,
    provider_message_id=None,
    sent_at=None,
    parent_mel_id=None,
):
    """Create and persist a MessageEventLog row.

    This helper only logs the event — it does NOT send any push, email, or
    in-app notification. That wiring is deferred to a future phase.

    Phase D-1 additions (backward-compatible — all new kwargs default to None):
        provider_message_id  — OneSignal notification ID on SENT rows; None otherwise.
        sent_at              — timestamp of successful provider response; None otherwise.
                               Dispatcher-owned: callers set this on SENT rows only.
        parent_mel_id        — FK to original FAILED row for retry child rows.
                               Flat lineage only: always references the original row,
                               never another child.

    processed_at is set internally to datetime.utcnow() at row creation time.
    Callers MUST NOT pass processed_at — it is always the persistence timestamp.

    Returns the created MessageEventLog instance.

    Raises ValueError for missing required fields.
    """
    if not event_name or not isinstance(event_name, str):
        raise ValueError("create_message_event: event_name is required and must be a non-empty string")
    if not category or not isinstance(category, str):
        raise ValueError("create_message_event: category is required and must be a non-empty string")

    if payload_json is None:
        payload_json = {}

    row = MessageEventLog(
        event_name=event_name,
        category=category,
        actor_user_id=actor_user_id,
        recipient_user_id=recipient_user_id,
        object_type=object_type,
        object_id=object_id,
        channel=channel,
        provider=provider,
        payload_json=payload_json,
        message_title=message_title,
        message_body=message_body,
        delivery_status=delivery_status,
        suppression_reason=suppression_reason,
        error_message=error_message,
        provider_message_id=provider_message_id,
        sent_at=sent_at,
        parent_mel_id=parent_mel_id,
        processed_at=datetime.utcnow(),
    )

    db.session.add(row)
    db.session.commit()

    current_app.logger.debug(
        "[MessageEvent] created id=%d event=%s status=%s",
        row.id, row.event_name, row.delivery_status,
    )

    return row


def is_duplicate_event(
    event_name,
    recipient_user_id,
    object_type=None,
    object_id=None,
    window_seconds=DEDUPE_WINDOW_SECONDS,
):
    """Return True if an equivalent event already exists within the time window.

    Admin/test push events (BYPASS_DEDUPE_EVENTS) always return False so that
    repeated test sends are never silently suppressed.

    A failed row does NOT block a fresh attempt — only pending/sent/skipped
    rows within the window are considered duplicates.
    """
    if event_name in BYPASS_DEDUPE_EVENTS:
        return False

    cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)

    query = MessageEventLog.query.filter(
        MessageEventLog.event_name == event_name,
        MessageEventLog.recipient_user_id == recipient_user_id,
        MessageEventLog.created_at >= cutoff,
        MessageEventLog.delivery_status != DeliveryStatus.FAILED,
        or_(
            MessageEventLog.suppression_reason.is_(None),
            MessageEventLog.suppression_reason != SuppressionReason.NOT_IMPLEMENTED,
        ),
    )

    if object_type is None:
        query = query.filter(MessageEventLog.object_type.is_(None))
    else:
        query = query.filter(MessageEventLog.object_type == object_type)

    if object_id is None:
        query = query.filter(MessageEventLog.object_id.is_(None))
    else:
        query = query.filter(MessageEventLog.object_id == object_id)

    return db.session.query(query.exists()).scalar()


def should_retry(log_row):
    """Return True if a failed MessageEventLog row is eligible for retry.

    Rules (all must pass):
    - delivery_status must be FAILED
    - retry_count must be below MAX_RETRY_COUNT
    - suppression_reason (if set) must NOT be in the non-retryable set

    Provider/network failures (no suppression_reason, or suppression_reason
    not in RETRYABLE_STATUSES) are eligible for retry.
    """
    if log_row.delivery_status != DeliveryStatus.FAILED:
        return False

    if log_row.retry_count >= MAX_RETRY_COUNT:
        return False

    if log_row.suppression_reason in RETRYABLE_STATUSES:
        return False

    return True
