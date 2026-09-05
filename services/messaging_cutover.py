"""Transaction-neutral controls for the per-event messaging cutover."""

from dataclasses import dataclass
from datetime import datetime
import os

import sqlalchemy as sa

from models import (
    MessageOutbox,
    MessageEventLog,
    MessagingDeliveryPolicy,
    MessagingDeliveryPolicyEvent,
    db,
)


MODES = frozenset({"inline", "enqueue_only"})
DELIVERABLE_STATUSES = ("pending", "retryable")
_MAX_REASON = 500


@dataclass(frozen=True)
class DeliveryPolicyDecision:
    event_name: str
    delivery_mode: str
    cutover_epoch: int | None
    control_revision: int | None

    @property
    def enqueue_only(self):
        return self.delivery_mode == "enqueue_only"


def _session(session):
    return session if session is not None else db.session


def _reason(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("an explicit operator reason is required")
    return " ".join(value.split())[:_MAX_REASON]


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("an audit identity is required")
    return " ".join(value.split())[:120]


def require_production_confirmation(confirmed, *, production=None):
    """A service-layer guard so callers cannot rely on CSRF as confirmation."""
    if production is None:
        production = os.environ.get("BASELODGE_RUNTIME_ENV", "").lower() == "production"
    if production and confirmed is not True:
        raise PermissionError("production confirmation required")


def lock_policy_decisions(event_names, *, session=None):
    """Capture policies under row locks; absent/invalid rows fail safe to inline."""
    work_session = _session(session)
    decisions = {}
    for event_name in sorted(set(event_names)):
        try:
            row = work_session.execute(
                sa.select(MessagingDeliveryPolicy)
                .where(MessagingDeliveryPolicy.event_name == event_name)
                .with_for_update()
            ).scalar_one_or_none()
        except Exception:
            # Do not make the caller's failed transaction usable by guessing queue.
            raise
        valid = (
            row is not None
            and row.delivery_mode in MODES
            and isinstance(row.cutover_epoch, int)
            and row.cutover_epoch > 0
            and isinstance(row.control_revision, int)
            and row.control_revision > 0
        )
        decisions[event_name] = DeliveryPolicyDecision(
            event_name,
            row.delivery_mode if valid else "inline",
            row.cutover_epoch if valid else None,
            row.control_revision if valid else None,
        )
    return decisions


def _history(row, action, reason, identity, work_session):
    work_session.add(MessagingDeliveryPolicyEvent(
        event_name=row.event_name,
        delivery_mode=row.delivery_mode,
        cutover_epoch=row.cutover_epoch,
        claims_paused=row.claims_paused,
        control_revision=row.control_revision,
        action=action,
        operator_reason=reason,
        audit_identity=identity,
    ))


def mutate_policy(
    event_name,
    *,
    expected_revision,
    expected_epoch,
    reason,
    audit_identity,
    claims_paused=None,
    delivery_mode=None,
    production_confirmed=False,
    production=None,
    session=None,
):
    """Serialize and audit a pause or inline-to-enqueue transition."""
    work_session = _session(session)
    reason = _reason(reason)
    identity = _identity(audit_identity)
    require_production_confirmation(production_confirmed, production=production)
    row = work_session.execute(
        sa.select(MessagingDeliveryPolicy)
        .where(MessagingDeliveryPolicy.event_name == event_name)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("messaging policy not found")
    if row.control_revision != expected_revision or row.cutover_epoch != expected_epoch:
        raise RuntimeError("stale messaging policy revision or epoch")
    if delivery_mode is not None and delivery_mode not in MODES:
        raise ValueError("invalid delivery mode")
    if delivery_mode == "inline" and row.delivery_mode == "enqueue_only":
        raise ValueError("use guarded_transition_inline")
    changed_mode = delivery_mode is not None and delivery_mode != row.delivery_mode
    if changed_mode:
        row.delivery_mode = delivery_mode
        row.cutover_epoch += 1
    if claims_paused is not None:
        row.claims_paused = bool(claims_paused)
    row.control_revision += 1
    row.operator_reason = reason
    row.audit_identity = identity
    row.updated_at = datetime.utcnow()
    _history(row, "mode_changed" if changed_mode else "pause_changed", reason, identity,
             work_session)
    work_session.flush()
    return row


def drain_status(event_name, epoch, *, now=None, session=None):
    work_session = _session(session)
    timestamp = now or datetime.utcnow()
    rows = dict(work_session.execute(
        sa.select(MessageOutbox.status, sa.func.count(MessageOutbox.id))
        .where(
            MessageOutbox.event_name == event_name,
            MessageOutbox.configuration_epoch == epoch,
        )
        .group_by(MessageOutbox.status)
    ).all())
    processing = work_session.execute(
        sa.select(sa.func.count(MessageOutbox.id)).where(
            MessageOutbox.event_name == event_name,
            MessageOutbox.configuration_epoch == epoch,
            MessageOutbox.status == "processing",
        )
    ).scalar_one()
    deliverable = sum(int(rows.get(status, 0)) for status in DELIVERABLE_STATUSES)
    return {
        "event_name": event_name,
        "configuration_epoch": epoch,
        "counts": {str(key): int(value) for key, value in rows.items()},
        "processing": int(processing or 0),
        "live_leases": int(processing or 0),
        "deliverable": deliverable,
        "drain_ready": deliverable == 0 and int(processing or 0) == 0,
    }


def terminalize_eligible(
    event_name, epoch, *, reason, audit_identity, now=None, session=None
    , production_confirmed=False, production=None
):
    """Terminalize only ready rows and expired claims that never started."""
    work_session = _session(session)
    reason = _reason(reason)
    identity = _identity(audit_identity)
    require_production_confirmation(production_confirmed, production=production)
    timestamp = now or datetime.utcnow()
    eligible = sa.or_(
        MessageOutbox.status.in_(DELIVERABLE_STATUSES),
        sa.and_(
            MessageOutbox.status == "processing",
            MessageOutbox.provider_phase == "not_started",
            MessageOutbox.lease_expires_at <= timestamp,
        ),
    )
    rows = work_session.execute(
        sa.select(MessageOutbox)
        .where(
            MessageOutbox.event_name == event_name,
            MessageOutbox.configuration_epoch == epoch,
            eligible,
        )
        .with_for_update()
    ).scalars().all()
    for outbox in rows:
        evidence = MessageEventLog(
            event_name=outbox.event_name,
            category=outbox.category,
            actor_user_id=outbox.actor_user_id,
            recipient_user_id=outbox.recipient_user_id,
            object_type=outbox.object_type,
            object_id=outbox.object_id,
            occurrence_id=outbox.occurrence_id,
            channel=outbox.channel,
            provider=outbox.provider,
            payload_json={"event": outbox.event_name, "outbox_id": outbox.id},
            delivery_status="skipped",
            suppression_reason="environment_blocked",
            error_message="Operator terminalized before provider execution",
            processed_at=timestamp,
        )
        work_session.add(evidence)
        work_session.flush()
        outbox.status = "operator_terminalized"
        outbox.terminalized_at = timestamp
        outbox.terminalization_reason = reason
        outbox.terminalized_by = identity
        outbox.completed_at = timestamp
        outbox.final_event_log_id = evidence.id
        outbox.lease_token = None
        outbox.lease_owner = None
        outbox.leased_at = None
        outbox.lease_expires_at = None
        outbox.updated_at = timestamp
    work_session.flush()
    return len(rows)


def guarded_transition_inline(
    event_name, *, expected_revision, expected_epoch, reason, audit_identity,
    now=None, session=None
    , production_confirmed=False, production=None
):
    """Atomically prove an enqueue generation drained and switch to inline."""
    work_session = _session(session)
    reason = _reason(reason)
    identity = _identity(audit_identity)
    require_production_confirmation(production_confirmed, production=production)
    row = work_session.execute(
        sa.select(MessagingDeliveryPolicy)
        .where(MessagingDeliveryPolicy.event_name == event_name)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("messaging policy not found")
    if row.control_revision != expected_revision or row.cutover_epoch != expected_epoch:
        raise RuntimeError("stale messaging policy revision or epoch")
    if row.delivery_mode != "enqueue_only" or not row.claims_paused:
        raise RuntimeError("family must be enqueue_only and paused")
    from services.message_outbox import recover_expired_leases
    recover_expired_leases(now=now, session=work_session)
    state = drain_status(event_name, expected_epoch, now=now, session=work_session)
    if not state["drain_ready"]:
        raise RuntimeError("family has deliverable rows or live leases")
    row.delivery_mode = "inline"
    row.cutover_epoch += 1
    row.control_revision += 1
    row.operator_reason = reason
    row.audit_identity = identity
    row.updated_at = now or datetime.utcnow()
    _history(row, "transition_inline", reason, identity, work_session)
    work_session.flush()
    return row
