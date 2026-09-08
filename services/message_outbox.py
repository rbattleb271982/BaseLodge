"""Transactional primitives for the durable messaging outbox.

None of these functions commits.  The caller owns transaction boundaries,
including the transaction which creates the business event and its outbox row.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
import uuid
import os

import sqlalchemy as sa

from models import MessageOutbox, MessagingDeliveryPolicy, SkiTrip, db
from services.messaging_constants import (
    EventName,
    OPPORTUNITY_EVENT_TYPES,
    is_opportunity_event,
)
from services.opportunity_messaging import lock_opportunity_policy_decisions


OUTBOX_STATUSES = frozenset({
    "pending", "processing", "retryable", "provider_accepted", "suppressed",
    "dead_letter", "delivery_unknown", "operator_terminalized",
})
TERMINAL_STATUSES = frozenset({
    "provider_accepted", "suppressed", "dead_letter", "delivery_unknown",
    "operator_terminalized",
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
    "resort_id", "rsvp_transition_id",
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
    replay_reason=None,
    replayed_by=None,
    replayed_at=None,
    configuration_epoch=1,
    producer_release_sha=None,
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
    if not isinstance(configuration_epoch, int) or configuration_epoch < 1:
        raise ValueError("configuration_epoch must be positive")
    if producer_release_sha is not None and not re.fullmatch(
        r"[0-9a-f]{40}", producer_release_sha
    ):
        raise ValueError("producer release identity must be a verified SHA")
    if (os.environ.get("BASELODGE_RUNTIME_ENV", "").lower() == "production"
            and producer_release_sha is None):
        raise ValueError("verified producer release identity is required")
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
        replay_reason=sanitize_error(replay_reason),
        replayed_by=(str(replayed_by)[:120] if replayed_by is not None else None),
        replayed_at=replayed_at,
        configuration_epoch=configuration_epoch,
        producer_release_sha=producer_release_sha,
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
    worker_release_sha=None,
):
    """Lease ready work using SKIP LOCKED on PostgreSQL and CAS elsewhere."""
    if not owner or limit < 1 or lease_seconds < 1:
        raise ValueError("owner, positive limit and positive lease_seconds are required")
    work_session = _session(session)
    if worker_release_sha is not None and not re.fullmatch(
        r"[0-9a-f]{40}", worker_release_sha
    ):
        raise ValueError("worker release identity must be a verified SHA")
    if (os.environ.get("BASELODGE_RUNTIME_ENV", "").lower() == "production"
            and worker_release_sha is None):
        raise ValueError("verified worker release identity is required")
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
        sa.exists().where(
            MessagingDeliveryPolicy.event_name == MessageOutbox.event_name,
            MessagingDeliveryPolicy.delivery_mode == "enqueue_only",
            MessagingDeliveryPolicy.claims_paused.is_(False),
            MessagingDeliveryPolicy.cutover_epoch
            == MessageOutbox.configuration_epoch,
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
            row.last_worker_release_sha = worker_release_sha
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
                last_worker_release_sha=worker_release_sha,
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


def mark_provider_started(
    outbox_id, lease_token, *, now=None, session=None, worker_release_sha=None
):
    """Serialize with policy mutation and persist the provider boundary."""
    return _mark_provider_started(
        outbox_id,
        lease_token,
        now=now,
        session=session,
        worker_release_sha=worker_release_sha,
        allow_opportunity=False,
    )


def _mark_provider_started(
    outbox_id,
    lease_token,
    *,
    now=None,
    session=None,
    worker_release_sha=None,
    allow_opportunity=False,
):
    timestamp = _now(now)
    work_session = _session(session)
    identity = work_session.execute(
        sa.select(MessageOutbox.event_name, MessageOutbox.configuration_epoch).where(
            MessageOutbox.id == outbox_id,
            MessageOutbox.status == "processing",
            MessageOutbox.lease_token == lease_token,
            MessageOutbox.provider_phase == "not_started",
            MessageOutbox.lease_expires_at > timestamp,
        )
    ).one_or_none()
    if identity is None:
        return False
    if is_opportunity_event(identity.event_name) and not allow_opportunity:
        return False
    policy = work_session.execute(
        sa.select(MessagingDeliveryPolicy)
        .where(MessagingDeliveryPolicy.event_name == identity.event_name)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        policy is None
        or policy.delivery_mode != "enqueue_only"
        or policy.claims_paused
        or policy.cutover_epoch != identity.configuration_epoch
    ):
        return False
    result = work_session.execute(
        sa.update(MessageOutbox)
        .where(
            MessageOutbox.id == outbox_id,
            MessageOutbox.status == "processing",
            MessageOutbox.lease_token == lease_token,
            MessageOutbox.provider_phase == "not_started",
            MessageOutbox.lease_expires_at > timestamp,
        )
        .values(
            provider_phase="started",
            attempt_count=MessageOutbox.attempt_count + 1,
            updated_at=timestamp,
            last_worker_release_sha=worker_release_sha,
        )
    )
    return result.rowcount == 1


@dataclass(frozen=True)
class OpportunityProviderStartResult:
    status: str
    winner_outbox_id: int | None
    suppressed_outbox_ids: tuple[int, ...] = ()
    reason: str | None = None


class _OpportunityProviderStartRefused(RuntimeError):
    pass


def lock_opportunity_trip(trip_id, *, session=None):
    """Lock the authoritative trip row used as the opportunity mutex."""
    if type(trip_id) is not int or trip_id < 1:
        raise ValueError("trip_id must be a positive integer")
    trip = _session(session).execute(
        sa.select(SkiTrip)
        .where(SkiTrip.id == trip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if trip is None:
        raise LookupError("opportunity trip not found")
    return trip


def _lock_opportunity_siblings_after_trip(current, work_session):
    return tuple(work_session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.object_type == "trip",
            MessageOutbox.object_id == current.object_id,
            MessageOutbox.recipient_user_id == current.recipient_user_id,
            MessageOutbox.channel == current.channel,
            MessageOutbox.provider == current.provider,
            MessageOutbox.event_name.in_(OPPORTUNITY_EVENT_TYPES),
        )
        .order_by(MessageOutbox.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all())


def lock_opportunity_siblings(outbox_id, *, session=None):
    """Lock trip first, then same-recipient opportunity rows by ascending ID."""
    work_session = _session(session)
    current = work_session.get(MessageOutbox, outbox_id)
    if (
        current is None
        or not is_opportunity_event(current.event_name)
        or current.object_type != "trip"
        or type(current.object_id) is not int
        or current.object_id < 1
        or type(current.recipient_user_id) is not int
    ):
        raise ValueError("outbox row is not a valid trip opportunity")
    trip = lock_opportunity_trip(current.object_id, session=work_session)
    siblings = _lock_opportunity_siblings_after_trip(current, work_session)
    return trip, siblings


def _suppress_locked_opportunity(row, reason, timestamp):
    row.status = "suppressed"
    row.last_error = sanitize_error(reason)
    row.completed_at = timestamp
    row.updated_at = timestamp
    row.lease_token = None
    row.lease_owner = None
    row.leased_at = None
    row.lease_expires_at = None


def _decision_allowed(decision):
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, dict):
        return bool(decision.get("allowed"))
    return bool(getattr(decision, "allowed", False))


def _decision_reason(decision):
    if isinstance(decision, dict):
        return decision.get("suppression_reason") or decision.get("reason")
    return getattr(decision, "suppression_reason", None)


def _record_sibling_suppression(row, reason, callback):
    if callback is None:
        return None
    result = callback(row, "suppressed", {"suppression_reason": reason})
    return result.id if hasattr(result, "id") else result


def mark_opportunity_provider_started(
    outbox_id,
    lease_token,
    *,
    safety_callback,
    event_log_callback=None,
    ownership_guard=None,
    now=None,
    session=None,
    worker_release_sha=None,
):
    """Arbitrate sibling opportunity rows and persist one provider-start winner.

    Authorization executes only after the trip and sibling rows are locked.
    Missing callbacks fail closed. This helper never commits or calls a provider.
    """
    work_session = _session(session)
    timestamp = _now(now)
    current = work_session.get(MessageOutbox, outbox_id)
    if (
        current is None
        or current.status != "processing"
        or current.lease_token != lease_token
        or current.provider_phase != "not_started"
    ):
        return OpportunityProviderStartResult(
            "lease_lost", None, reason="invalid_claim"
        )

    connection = work_session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not getattr(connection.connection, "in_transaction", False)
    ):
        connection.exec_driver_sql("BEGIN")
    try:
        with work_session.begin_nested():
            lock_opportunity_trip(current.object_id, session=work_session)
            policy_decisions = lock_opportunity_policy_decisions(
                OPPORTUNITY_EVENT_TYPES, session=work_session
            )
            policy = policy_decisions[current.event_name]
            if (
                not policy.eligible
                or policy.claims_paused
                or policy.cutover_epoch != current.configuration_epoch
            ):
                raise _OpportunityProviderStartRefused(
                    "opportunity policy generation is not deliverable"
                )
            siblings = _lock_opportunity_siblings_after_trip(
                current, work_session
            )
            current = next((row for row in siblings if row.id == outbox_id), None)
            if (
                current is None
                or current.status != "processing"
                or current.lease_token != lease_token
                or current.provider_phase != "not_started"
            ):
                raise _OpportunityProviderStartRefused(
                    "opportunity claim changed during arbitration"
                )

            current_decision = safety_callback(current)
            if not _decision_allowed(current_decision):
                reason = (
                    _decision_reason(current_decision)
                    or "opportunity_authorization_denied"
                )
                return OpportunityProviderStartResult(
                    "suppressed", None, (), reason
                )

            generic_rows = [
                row for row in siblings
                if row.event_name == EventName.FRIEND_TRIP_CREATED
                and row.id != current.id
            ]
            wishlist_rows = [
                row for row in siblings
                if row.event_name == EventName.WISHLIST_MATCH_DETECTED
                and row.id != current.id
            ]
            irreversible_generic = any(
                row.provider_phase in {"started", "accepted", "unknown"}
                or row.status in {"provider_accepted", "delivery_unknown"}
                for row in generic_rows
            )
            deliverable_wishlist = False
            invalid_wishlist_rows = []
            for row in wishlist_rows:
                irreversible = (
                    row.provider_phase in {"started", "accepted", "unknown"}
                    or row.status in {"provider_accepted", "delivery_unknown"}
                )
                if irreversible:
                    deliverable_wishlist = True
                    continue
                if row.status not in {"pending", "processing", "retryable"}:
                    continue
                row_policy = policy_decisions[row.event_name]
                valid_generation = (
                    row_policy.eligible
                    and row.configuration_epoch == row_policy.cutover_epoch
                )
                decision = (
                    safety_callback(row) if valid_generation else None
                )
                if valid_generation and _decision_allowed(decision):
                    deliverable_wishlist = True
                else:
                    invalid_wishlist_rows.append((
                        row,
                        (
                            _decision_reason(decision)
                            if valid_generation
                            else "stale_opportunity_policy_generation"
                        )
                        or "opportunity_authorization_denied",
                    ))

            for row, reason in invalid_wishlist_rows:
                final_event_log_id = _record_sibling_suppression(
                    row, reason, event_log_callback
                )
                _suppress_locked_opportunity(row, reason, timestamp)
                row.final_event_log_id = final_event_log_id

            if (
                current.event_name == EventName.WISHLIST_MATCH_DETECTED
                and irreversible_generic
            ):
                work_session.flush()
                return OpportunityProviderStartResult(
                    "suppressed",
                    None,
                    tuple(row.id for row, _reason in invalid_wishlist_rows),
                    "generic_already_irreversible",
                )
            if (
                current.event_name == EventName.FRIEND_TRIP_CREATED
                and deliverable_wishlist
            ):
                work_session.flush()
                return OpportunityProviderStartResult(
                    "suppressed",
                    None,
                    tuple(row.id for row, _reason in invalid_wishlist_rows),
                    "wishlist_precedence",
                )

            suppressed_ids = [
                row.id for row, _reason in invalid_wishlist_rows
            ]
            if current.event_name == EventName.WISHLIST_MATCH_DETECTED:
                for row in generic_rows:
                    if (
                        row.provider_phase == "not_started"
                        and row.status in {"pending", "processing", "retryable"}
                    ):
                        reason = "wishlist_precedence"
                        final_event_log_id = _record_sibling_suppression(
                            row, reason, event_log_callback
                        )
                        _suppress_locked_opportunity(
                            row, reason, timestamp
                        )
                        row.final_event_log_id = final_event_log_id
                        suppressed_ids.append(row.id)
                work_session.flush()

            if ownership_guard is not None:
                ownership_guard(work_session, "before_provider_start")
            provider_start_timestamp = _now(now)
            if not _mark_provider_started(
                current.id,
                lease_token,
                now=provider_start_timestamp,
                session=work_session,
                worker_release_sha=worker_release_sha,
                allow_opportunity=True,
            ):
                raise _OpportunityProviderStartRefused(
                    "opportunity provider start was refused"
                )
        return OpportunityProviderStartResult(
            "started", outbox_id, tuple(suppressed_ids)
        )
    except _OpportunityProviderStartRefused:
        return OpportunityProviderStartResult(
            "lease_lost", None, reason="provider_start_refused"
        )


def release_pre_provider_claim(outbox_id, lease_token, *, now=None, session=None):
    """Release a still-safe claim without consuming an attempt."""
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
            status="retryable",
            next_attempt_at=timestamp,
            lease_token=None,
            lease_owner=None,
            leased_at=None,
            lease_expires_at=None,
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
    families = []
    policies = work_session.execute(
        sa.select(MessagingDeliveryPolicy).order_by(MessagingDeliveryPolicy.event_name)
    ).scalars().all()
    for policy in policies:
        family_counts = dict(work_session.execute(
            sa.select(MessageOutbox.status, sa.func.count(MessageOutbox.id))
            .where(MessageOutbox.event_name == policy.event_name)
            .group_by(MessageOutbox.status)
        ).all())
        stale = work_session.execute(
            sa.select(sa.func.count(MessageOutbox.id)).where(
                MessageOutbox.event_name == policy.event_name,
                MessageOutbox.configuration_epoch != policy.cutover_epoch,
            )
        ).scalar_one()
        mismatch = work_session.execute(
            sa.select(sa.func.count(MessageOutbox.id)).where(
                MessageOutbox.event_name == policy.event_name,
                MessageOutbox.last_worker_release_sha.is_not(None),
                MessageOutbox.producer_release_sha.is_not(None),
                MessageOutbox.last_worker_release_sha != MessageOutbox.producer_release_sha,
            )
        ).scalar_one()
        deliverable = sum(int(family_counts.get(s, 0)) for s in _READY_STATUSES)
        live = int(family_counts.get("processing", 0))
        epochs = []
        epoch_values = work_session.execute(
            sa.select(MessageOutbox.configuration_epoch)
            .where(MessageOutbox.event_name == policy.event_name)
            .distinct().order_by(MessageOutbox.configuration_epoch)
        ).scalars().all()
        for epoch in epoch_values:
            epoch_counts = dict(work_session.execute(
                sa.select(MessageOutbox.status, sa.func.count(MessageOutbox.id))
                .where(
                    MessageOutbox.event_name == policy.event_name,
                    MessageOutbox.configuration_epoch == epoch,
                ).group_by(MessageOutbox.status)
            ).all())
            phase_counts = dict(work_session.execute(
                sa.select(MessageOutbox.provider_phase, sa.func.count(MessageOutbox.id))
                .where(
                    MessageOutbox.event_name == policy.event_name,
                    MessageOutbox.configuration_epoch == epoch,
                ).group_by(MessageOutbox.provider_phase)
            ).all())
            epoch_oldest = work_session.execute(
                sa.select(sa.func.min(MessageOutbox.next_attempt_at)).where(
                    MessageOutbox.event_name == policy.event_name,
                    MessageOutbox.configuration_epoch == epoch,
                    MessageOutbox.status.in_(_READY_STATUSES),
                    MessageOutbox.next_attempt_at <= timestamp,
                )
            ).scalar_one()
            epoch_expired = work_session.execute(
                sa.select(sa.func.count(MessageOutbox.id)).where(
                    MessageOutbox.event_name == policy.event_name,
                    MessageOutbox.configuration_epoch == epoch,
                    MessageOutbox.status == "processing",
                    MessageOutbox.lease_expires_at <= timestamp,
                )
            ).scalar_one()
            epochs.append({
                "configuration_epoch": epoch,
                "active": epoch == policy.cutover_epoch,
                "counts": {s: int(epoch_counts.get(s, 0)) for s in OUTBOX_STATUSES},
                "provider_phases": {
                    phase: int(phase_counts.get(phase, 0))
                    for phase in PROVIDER_PHASES
                },
                "expired_leases": int(epoch_expired or 0),
                "oldest_ready_age_seconds": (
                    max(0, int((timestamp - epoch_oldest).total_seconds()))
                    if epoch_oldest else None
                ),
            })
        families.append({
            "event_name": policy.event_name,
            "delivery_mode": policy.delivery_mode,
            "cutover_epoch": policy.cutover_epoch,
            "claims_paused": policy.claims_paused,
            "control_revision": policy.control_revision,
            "counts": {s: int(family_counts.get(s, 0)) for s in OUTBOX_STATUSES},
            "stale_generation_rows": int(stale or 0),
            "release_mismatch_rows": int(mismatch or 0),
            "drain_ready": deliverable == 0 and live == 0,
            "epochs": epochs,
        })
    return {
        "counts": {status: int(counts.get(status, 0)) for status in OUTBOX_STATUSES},
        "ready": sum(int(counts.get(status, 0)) for status in _READY_STATUSES),
        "expired_leases": int(expired or 0),
        "oldest_ready_age_seconds": (
            max(0, int((timestamp - oldest_ready).total_seconds()))
            if oldest_ready else None
        ),
        "families": families,
    }


# Explicit aliases used by queue-oriented integrations.
enqueue_outbox = enqueue_message
claim_outbox_batch = claim_messages
finalize_outbox = finalize_message
calculate_backoff = deterministic_backoff
get_queue_health = queue_health