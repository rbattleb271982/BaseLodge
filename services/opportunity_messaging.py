"""Fail-closed staging contract for dormant trip opportunity messages."""

from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa

from models import MessagingDeliveryPolicy, MessagingDeliveryPolicyEvent, db
from services.messaging_constants import EventName, is_opportunity_event
from services.messaging_cutover import require_production_confirmation


_OPPORTUNITY_OCCURRENCE_PREFIXES = {
    EventName.FRIEND_TRIP_CREATED: "opportunity.friend_trip.v1.trip",
    EventName.WISHLIST_MATCH_DETECTED: "opportunity.wishlist_match.v1.trip",
}
_OPPORTUNITY_ACTIVATION_ACTIONS = frozenset({
    "opportunity_registered",
    "mode_changed",
})


@dataclass(frozen=True)
class OpportunityPolicyDecision:
    event_name: str
    eligible: bool
    cutover_epoch: int | None = None
    control_revision: int | None = None
    activation_boundary: datetime | None = None
    claims_paused: bool | None = None
    reason: str | None = None
    transaction: object | None = None


def _session(session):
    return session if session is not None else db.session


def _active_transaction_scope(session):
    work_session = _session(session)
    actual_session = (
        work_session()
        if callable(work_session) and not hasattr(work_session, "get_transaction")
        else work_session
    )
    return (
        actual_session.get_nested_transaction()
        or actual_session.get_transaction()
    )


def opportunity_occurrence_id(event_name, trip_id):
    """Build the stable, IDs-only logical occurrence for one trip family."""
    prefix = _OPPORTUNITY_OCCURRENCE_PREFIXES.get(event_name)
    if prefix is None:
        raise ValueError("unsupported opportunity event")
    if type(trip_id) is not int or trip_id < 1:
        raise ValueError("trip_id must be a positive integer")
    occurrence_id = f"{prefix}:{trip_id}"
    if len(occurrence_id) > 191:
        raise ValueError("opportunity occurrence exceeds storage bounds")
    return occurrence_id


def opportunity_timestamp_at_or_after(candidate, boundary):
    """Compare UTC timestamps safely across naive and timezone-aware columns."""
    if not isinstance(candidate, datetime) or not isinstance(boundary, datetime):
        return False

    def utc_naive(value):
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(tzinfo=None)

    return utc_naive(candidate) >= utc_naive(boundary)


def _invalid_policy(event_name, reason):
    return OpportunityPolicyDecision(
        event_name=event_name,
        eligible=False,
        reason=reason,
    )


def lock_opportunity_policy_decisions(event_names, *, session=None):
    """Lock and validate audited enqueue-only generations for opportunity events."""
    work_session = _session(session)
    names = tuple(sorted(set(event_names)))
    if not names or any(not is_opportunity_event(name) for name in names):
        raise ValueError("only explicit opportunity event families are supported")

    decisions = {}
    for event_name in names:
        policy = work_session.execute(
            sa.select(MessagingDeliveryPolicy)
            .where(MessagingDeliveryPolicy.event_name == event_name)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if policy is None:
            decisions[event_name] = _invalid_policy(event_name, "missing_policy")
            continue
        if (
            policy.delivery_mode != "enqueue_only"
            or type(policy.cutover_epoch) is not int
            or policy.cutover_epoch < 1
            or type(policy.control_revision) is not int
            or policy.control_revision < 1
            or type(policy.claims_paused) is not bool
        ):
            decisions[event_name] = _invalid_policy(event_name, "invalid_policy")
            continue

        audit_rows = work_session.execute(
            sa.select(MessagingDeliveryPolicyEvent)
            .where(
                MessagingDeliveryPolicyEvent.event_name == event_name,
                MessagingDeliveryPolicyEvent.delivery_mode == "enqueue_only",
                MessagingDeliveryPolicyEvent.cutover_epoch == policy.cutover_epoch,
                MessagingDeliveryPolicyEvent.action.in_(
                    _OPPORTUNITY_ACTIVATION_ACTIONS
                ),
            )
            .order_by(
                MessagingDeliveryPolicyEvent.created_at,
                MessagingDeliveryPolicyEvent.id,
            )
        ).scalars().all()
        audit = next(
            (
                row for row in audit_rows
                if (
                    isinstance(row.created_at, datetime)
                    and row.claims_paused is True
                    and type(row.control_revision) is int
                    and 0 < row.control_revision <= policy.control_revision
                    and isinstance(row.operator_reason, str)
                    and bool(row.operator_reason.strip())
                    and isinstance(row.audit_identity, str)
                    and bool(row.audit_identity.strip())
                )
            ),
            None,
        )
        if audit is None:
            decisions[event_name] = _invalid_policy(
                event_name, "missing_activation_audit"
            )
            continue
        decisions[event_name] = OpportunityPolicyDecision(
            event_name=event_name,
            eligible=True,
            cutover_epoch=policy.cutover_epoch,
            control_revision=policy.control_revision,
            activation_boundary=audit.created_at,
            claims_paused=policy.claims_paused,
            transaction=_active_transaction_scope(work_session),
        )
    return decisions


def register_opportunity_policy(
    event_name,
    *,
    reason,
    audit_identity,
    production_confirmed=False,
    production=None,
    session=None,
):
    """Create one dormant, audited opportunity policy without committing."""
    if not is_opportunity_event(event_name):
        raise ValueError("only explicit opportunity event families are supported")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("an explicit operator reason is required")
    if not isinstance(audit_identity, str) or not audit_identity.strip():
        raise ValueError("an audit identity is required")
    require_production_confirmation(
        production_confirmed, production=production
    )
    work_session = _session(session)
    existing = work_session.execute(
        sa.select(MessagingDeliveryPolicy)
        .where(MessagingDeliveryPolicy.event_name == event_name)
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("opportunity policy already exists")
    policy = MessagingDeliveryPolicy(
        event_name=event_name,
        delivery_mode="enqueue_only",
        cutover_epoch=1,
        claims_paused=True,
        control_revision=1,
        operator_reason=" ".join(reason.split())[:500],
        audit_identity=" ".join(audit_identity.split())[:120],
    )
    work_session.add(policy)
    work_session.flush()
    audit = MessagingDeliveryPolicyEvent(
        event_name=event_name,
        delivery_mode="enqueue_only",
        cutover_epoch=policy.cutover_epoch,
        claims_paused=True,
        control_revision=policy.control_revision,
        action="opportunity_registered",
        operator_reason=policy.operator_reason,
        audit_identity=policy.audit_identity,
    )
    work_session.add(audit)
    work_session.flush()
    return policy, audit


def opportunity_activation_boundary(event_name, *, session=None):
    """Return the audited current-generation boundary, or None when ineligible."""
    decision = lock_opportunity_policy_decisions(
        (event_name,), session=session
    )[event_name]
    return decision.activation_boundary if decision.eligible else None


def stage_opportunity_intents(
    intents,
    *,
    session,
    enqueue,
    producer_release_sha=None,
    require_verified_release=False,
):
    """Stage opportunity intents atomically, with no inline compatibility path."""
    normalized = tuple(intents)
    if not normalized:
        return ()
    event_names = tuple(intent.get("event_name") for intent in normalized)
    if any(not is_opportunity_event(name) for name in event_names):
        raise ValueError("stage_opportunity_intents accepts opportunity events only")
    decisions = lock_opportunity_policy_decisions(
        event_names, session=session
    )
    if any(not decisions[name].eligible for name in event_names):
        return tuple(False for _intent in normalized)
    if require_verified_release and producer_release_sha is None:
        raise RuntimeError(
            "verified producer release identity required for opportunity enqueue"
        )

    connection = session.connection()
    if (
        connection.dialect.name == "sqlite"
        and not getattr(connection.connection, "in_transaction", False)
    ):
        connection.exec_driver_sql("BEGIN")
    with session.begin_nested():
        for intent in normalized:
            decision = decisions[intent["event_name"]]
            enqueue(
                **intent,
                configuration_epoch=decision.cutover_epoch,
                activation_boundary=decision.activation_boundary,
                opportunity_policy_decision=decision,
                producer_release_sha=producer_release_sha,
                session=session,
            )
        session.flush()
    return tuple(True for _intent in normalized)