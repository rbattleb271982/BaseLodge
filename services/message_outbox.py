"""Transactional primitives for the durable messaging outbox.

None of these functions commits.  The caller owns transaction boundaries,
including the transaction which creates the business event and its outbox row.
"""

from datetime import datetime, timedelta
import hashlib
import json
import re
import uuid

import sqlalchemy as sa

from models import MessageOutbox, db


OUTBOX_STATUSES = frozenset({
    "pending", "processing", "retryable", "provider_accepted", "suppressed",
    "dead_letter", "delivery_unknown",
})
TERMINAL_STATUSES = frozenset({
    "provider_accepted", "suppressed", "dead_letter", "delivery_unknown",
})
PROVIDER_PHASES = frozenset({"not_started", "started", "accepted", "unknown"})
_READY_STATUSES = ("pending", "retryable")
_SECRET = re.compile(
    r"(?i)(authorization|api[-_ ]?key|access[-_ ]?token|token|secret|password|"
    r"signature|credential)"
    r"(\s*[:=]\s*|\s+)[^\s,;]+"
)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_URL_OR_QUERY = re.compile(
    r"(?i)\b(?:https?://|wss?://)[^\s,;]+|(?:/[^\s,;?]*)?\?[^\s,;]+"
)
_OCCURRENCE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,190}\Z")
_EVIDENCE_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}:[1-9][0-9]{0,18}\Z")
_EVIDENCE_KINDS = frozenset({
    "policy", "invitation_id", "planning_post_id", "lifecycle_event_id",
    "suggestion_batch_id", "subject_user_id", "invite_share_event_id",
})
_MAX_EVIDENCE_IDS = 20
_ALLOWED_CONTEXT_KEYS = frozenset({
    "route", "deep_link", "template", "template_key", "locale", "badge", "sound",
    "collapse_key", "object_type", "object_id",
})
_FORBIDDEN_CONTEXT_KEY = re.compile(
    r"(?i)(title|body|message|content|token|credential|authorization|api[-_]?key|"
    r"secret|password|response)"
)


def _session(session):
    return session if session is not None else db.session


def _now(value):
    return value if value is not None else datetime.utcnow()


def sanitize_error(error, limit=500):
    """Return bounded diagnostic text without common credentials or email PII."""
    if error is None:
        return None
    text = " ".join(str(error).split())
    # URLs frequently carry signed query parameters.  Redact them before
    # individual secret patterns so no partial query value survives.
    text = _URL_OR_QUERY.sub("<redacted-url>", text)
    text = _BEARER.sub("Bearer <redacted>", text)
    text = _SECRET.sub(lambda match: match.group(1) + "=<redacted>", text)
    text = _EMAIL.sub("<redacted-email>", text)
    return text[:limit]


def _validate_occurrence_id(value):
    if not isinstance(value, str) or not _OCCURRENCE_IDENTIFIER.fullmatch(value):
        raise ValueError("occurrence_id must be a bounded canonical identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in (
        "bearer", "basic", "token", "secret", "password", "signature", "signed",
        "credential",
    )):
        raise ValueError("occurrence_id must not contain protected content")


def _validate_evidence_ids(values):
    if not isinstance(values, list):
        raise ValueError("evidence_ids must be a JSON list")
    if len(values) > _MAX_EVIDENCE_IDS:
        raise ValueError("evidence_ids exceeds maximum size")
    for value in values:
        if not isinstance(value, str) or not _EVIDENCE_IDENTIFIER.fullmatch(value):
            raise ValueError("evidence_ids must contain typed identifier strings")
        if value.partition(":")[0] not in _EVIDENCE_KINDS:
            raise ValueError("evidence_ids contains an unknown identifier kind")


def deterministic_backoff(
    attempt_count,
    *,
    identity=0,
    base_seconds=30,
    maximum_seconds=3600,
):
    """Return deterministic, bounded exponential backoff in whole seconds."""
    if attempt_count < 1:
        raise ValueError("attempt_count must be at least 1")
    if base_seconds < 1 or maximum_seconds < base_seconds:
        raise ValueError("invalid backoff bounds")
    exponential = min(maximum_seconds, base_seconds * (2 ** (attempt_count - 1)))
    digest = hashlib.sha256(
        f"{identity}:{attempt_count}".encode("utf-8")
    ).digest()
    # Up to 20% deterministic positive jitter, while respecting the hard cap.
    jitter = int(exponential * 0.2 * int.from_bytes(digest[:2], "big") / 65535)
    return min(maximum_seconds, exponential + jitter)


def _validate_context(context):
    """Allow only small, scalar routing/render selection values."""
    if not isinstance(context, dict):
        raise ValueError("context must be a JSON object")
    if len(context) > len(_ALLOWED_CONTEXT_KEYS):
        raise ValueError("context has too many keys")
    for key, value in context.items():
        if not isinstance(key, str):
            raise ValueError("context keys must be strings")
        if _FORBIDDEN_CONTEXT_KEY.search(key):
            raise ValueError(f"protected context key is not allowed: {key}")
        if key not in _ALLOWED_CONTEXT_KEYS:
            raise ValueError(f"context key is not allowlisted: {key}")
        if value is not None and type(value) not in (str, int, bool):
            raise ValueError("context values must be scalar")
        if isinstance(value, str) and len(value) > 512:
            raise ValueError("context string value exceeds 512 characters")
        if type(value) is int and abs(value) > 2147483647:
            raise ValueError("context integer value is out of bounds")


def _existing_delivery(session, occurrence_id, recipient_user_id, channel, provider):
    with session.no_autoflush:
        return session.execute(
            sa.select(MessageOutbox).where(
                MessageOutbox.occurrence_id == occurrence_id,
                MessageOutbox.recipient_user_id == recipient_user_id,
                MessageOutbox.channel == channel,
                MessageOutbox.provider == provider,
            )
        ).scalar_one_or_none()


def enqueue_message(
    *,
    event_name,
    category,
    occurrence_id,
    recipient_user_id,
    channel,
    provider,
    context=None,
    evidence_ids=None,
    actor_user_id=None,
    object_type=None,
    object_id=None,
    max_attempts=5,
    next_attempt_at=None,
    replay_of_outbox_id=None,
    session=None,
):
    """Add and flush an outbox row without committing the surrounding transaction."""
    if not all((event_name, category, occurrence_id, channel, provider)):
        raise ValueError("event, category, occurrence, channel and provider are required")
    if recipient_user_id is None:
        raise ValueError("recipient_user_id is required")
    _validate_context({} if context is None else context)
    _validate_occurrence_id(occurrence_id)
    _validate_evidence_ids([] if evidence_ids is None else evidence_ids)
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    # Refuse accidentally-large payloads: this is routing/render context, not a
    # copy of a domain object or provider response.
    if len(json.dumps(context or {}, default=str)) > 16384:
        raise ValueError("context exceeds 16 KiB")

    work_session = _session(session)
    existing = _existing_delivery(
        work_session, occurrence_id, recipient_user_id, channel, provider
    )
    if existing is not None:
        return existing

    row = MessageOutbox(
        event_name=event_name,
        category=category,
        occurrence_id=occurrence_id,
        actor_user_id=actor_user_id,
        recipient_user_id=recipient_user_id,
        object_type=object_type,
        object_id=object_id,
        channel=channel,
        provider=provider,
        context_json=dict(context or {}),
        evidence_ids_json=list(evidence_ids or []),
        max_attempts=max_attempts,
        next_attempt_at=_now(next_attempt_at),
        replay_of_outbox_id=replay_of_outbox_id,
    )
    try:
        # A duplicate inserted by another transaction rolls back only this
        # savepoint, leaving the caller's surrounding unit of work usable.
        # SQLite otherwise treats a top-level SAVEPOINT release as a commit;
        # establish its enclosing transaction before opening the savepoint.
        connection = work_session.connection()
        if (
            connection.dialect.name == "sqlite"
            and not getattr(connection.connection, "in_transaction", False)
        ):
            connection.exec_driver_sql("BEGIN")
        with work_session.begin_nested():
            work_session.add(row)
            work_session.flush()
    except sa.exc.IntegrityError:
        existing = _existing_delivery(
            work_session, occurrence_id, recipient_user_id, channel, provider
        )
        if existing is not None:
            return existing
        raise
    return row


def recover_expired_leases(*, now=None, session=None):
    """Recover safe leases and quarantine ambiguous provider attempts."""
    work_session = _session(session)
    timestamp = _now(now)
    safe = work_session.execute(
        sa.update(MessageOutbox)
        .where(
            MessageOutbox.status == "processing",
            MessageOutbox.lease_expires_at <= timestamp,
            MessageOutbox.provider_phase == "not_started",
        )
        .values(
            status="retryable",
            next_attempt_at=timestamp,
            lease_token=None,
            lease_owner=None,
            leased_at=None,
            lease_expires_at=None,
            updated_at=timestamp,
        )
    ).rowcount
    unknown = work_session.execute(
        sa.update(MessageOutbox)
        .where(
            MessageOutbox.status == "processing",
            MessageOutbox.lease_expires_at <= timestamp,
            MessageOutbox.provider_phase.in_(("started", "accepted", "unknown")),
        )
        .values(
            status="delivery_unknown",
            provider_phase="unknown",
            last_error="Lease expired after provider execution began",
            lease_token=None,
            lease_owner=None,
            leased_at=None,
            lease_expires_at=None,
            completed_at=timestamp,
            updated_at=timestamp,
        )
    ).rowcount
    return {"reclaimed": safe, "delivery_unknown": unknown}


def claim_messages(
    owner,
    *,
    limit=25,
    lease_seconds=60,
    now=None,
    session=None,
):
    """Lease ready work using SKIP LOCKED on PostgreSQL and CAS elsewhere."""
    if not owner or limit < 1 or lease_seconds < 1:
        raise ValueError("owner, positive limit and positive lease_seconds are required")
    work_session = _session(session)
    timestamp = _now(now)
    expires = timestamp + timedelta(seconds=lease_seconds)
    bind = work_session.get_bind()
    ready = (
        MessageOutbox.status.in_(_READY_STATUSES),
        MessageOutbox.next_attempt_at <= timestamp,
        sa.or_(
            MessageOutbox.lease_expires_at.is_(None),
            MessageOutbox.lease_expires_at <= timestamp,
        ),
    )

    if bind.dialect.name == "postgresql":
        candidates = work_session.execute(
            sa.select(MessageOutbox)
            .where(*ready)
            .order_by(MessageOutbox.next_attempt_at, MessageOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        claimed = []
        for row in candidates:
            row.status = "processing"
            row.lease_token = uuid.uuid4().hex
            row.lease_owner = owner
            row.leased_at = timestamp
            row.lease_expires_at = expires
            row.provider_phase = "not_started"
            row.updated_at = timestamp
            claimed.append(row)
        work_session.flush()
        return claimed

    candidate_ids = work_session.execute(
        sa.select(MessageOutbox.id)
        .where(*ready)
        .order_by(MessageOutbox.next_attempt_at, MessageOutbox.id)
        .limit(limit)
    ).scalars().all()
    claimed_ids = []
    for row_id in candidate_ids:
        token = uuid.uuid4().hex
        changed = work_session.execute(
            sa.update(MessageOutbox)
            .where(MessageOutbox.id == row_id, *ready)
            .values(
                status="processing",
                lease_token=token,
                lease_owner=owner,
                leased_at=timestamp,
                lease_expires_at=expires,
                provider_phase="not_started",
                updated_at=timestamp,
            )
        ).rowcount
        if changed == 1:
            claimed_ids.append(row_id)
    if not claimed_ids:
        return []
    return work_session.execute(
        sa.select(MessageOutbox)
        .where(MessageOutbox.id.in_(claimed_ids))
        .order_by(MessageOutbox.next_attempt_at, MessageOutbox.id)
    ).scalars().all()


def mark_provider_started(outbox_id, lease_token, *, now=None, session=None):
    """Persist the point after which blind retry could duplicate delivery."""
    timestamp = _now(now)
    result = _session(session).execute(
        sa.update(MessageOutbox)
        .where(
            MessageOutbox.id == outbox_id,
            MessageOutbox.status == "processing",
            MessageOutbox.lease_token == lease_token,
            MessageOutbox.provider_phase == "not_started",
        )
        .values(
            provider_phase="started",
            attempt_count=MessageOutbox.attempt_count + 1,
            updated_at=timestamp,
        )
    )
    return result.rowcount == 1


def finalize_message(
    outbox_id,
    lease_token,
    status,
    *,
    provider_message_id=None,
    error=None,
    final_event_log_id=None,
    now=None,
    session=None,
    backoff_base_seconds=30,
    backoff_maximum_seconds=3600,
    retry_after_seconds=None,
):
    """Finalize a lease iff its opaque token still owns the row."""
    if status not in OUTBOX_STATUSES - {"pending", "processing"}:
        raise ValueError("invalid final status")
    work_session = _session(session)
    timestamp = _now(now)
    row = work_session.execute(
        sa.select(
            MessageOutbox.id,
            MessageOutbox.attempt_count,
            MessageOutbox.max_attempts,
        ).where(
            MessageOutbox.id == outbox_id,
            MessageOutbox.status == "processing",
            MessageOutbox.lease_token == lease_token,
        )
    ).one_or_none()
    if row is None:
        return False

    if status == "retryable" and row.attempt_count >= row.max_attempts:
        status = "dead_letter"
    values = {
        "status": status,
        "provider_message_id": provider_message_id,
        "last_error": sanitize_error(error),
        "final_event_log_id": final_event_log_id,
        "updated_at": timestamp,
        "lease_token": None,
        "lease_owner": None,
        "leased_at": None,
        "lease_expires_at": None,
    }
    if status == "retryable":
        values["provider_phase"] = "not_started"
        backoff_seconds = deterministic_backoff(
            row.attempt_count,
            identity=row.id,
            base_seconds=backoff_base_seconds,
            maximum_seconds=backoff_maximum_seconds,
        )
        # Provider hints are advisory, but valid hints must never cause a
        # retry sooner than local backoff or later than the configured cap.
        if (
            type(retry_after_seconds) is int
            and retry_after_seconds >= 0
        ):
            backoff_seconds = min(
                backoff_maximum_seconds, max(backoff_seconds, retry_after_seconds)
            )
        values["next_attempt_at"] = timestamp + timedelta(seconds=backoff_seconds)
        values["completed_at"] = None
    else:
        values["completed_at"] = timestamp
        if status == "provider_accepted":
            values["provider_phase"] = "accepted"
        elif status == "delivery_unknown":
            values["provider_phase"] = "unknown"
    result = work_session.execute(
        sa.update(MessageOutbox)
        .where(
            MessageOutbox.id == outbox_id,
            MessageOutbox.status == "processing",
            MessageOutbox.lease_token == lease_token,
        )
        .values(**values)
    )
    return result.rowcount == 1


def queue_health(*, now=None, session=None):
    """Return status counts and ready/leased age signals for monitoring."""
    work_session = _session(session)
    timestamp = _now(now)
    counts = dict(work_session.execute(
        sa.select(MessageOutbox.status, sa.func.count(MessageOutbox.id))
        .group_by(MessageOutbox.status)
    ).all())
    oldest_ready = work_session.execute(
        sa.select(sa.func.min(MessageOutbox.next_attempt_at)).where(
            MessageOutbox.status.in_(_READY_STATUSES),
            MessageOutbox.next_attempt_at <= timestamp,
        )
    ).scalar_one()
    expired = work_session.execute(
        sa.select(sa.func.count(MessageOutbox.id)).where(
            MessageOutbox.status == "processing",
            MessageOutbox.lease_expires_at <= timestamp,
        )
    ).scalar_one()
    return {
        "counts": {status: int(counts.get(status, 0)) for status in OUTBOX_STATUSES},
        "ready": sum(int(counts.get(status, 0)) for status in _READY_STATUSES),
        "expired_leases": int(expired or 0),
        "oldest_ready_age_seconds": (
            max(0, int((timestamp - oldest_ready).total_seconds()))
            if oldest_ready else None
        ),
    }


# Explicit aliases used by queue-oriented integrations.
enqueue_outbox = enqueue_message
claim_outbox_batch = claim_messages
finalize_outbox = finalize_message
calculate_backoff = deterministic_backoff
get_queue_health = queue_health