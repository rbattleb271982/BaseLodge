"""Bounded, application-independent worker for durable message deliveries.

This module neither imports the Flask application nor performs migrations.
Integrators provide a SQLAlchemy session factory plus safety and provider
callbacks.  Each provider call is preceded by a committed ``started`` marker.
"""

from dataclasses import dataclass
import argparse
import importlib
import os

import sqlalchemy as sa

from models import MessageOutbox
from release_identity import resolve_release_identity
from services.message_outbox import (
    claim_messages,
    finalize_message,
    mark_provider_started,
    release_pre_provider_claim,
    recover_expired_leases,
)


@dataclass(frozen=True)
class WorkerResult:
    claimed: int = 0
    provider_accepted: int = 0
    suppressed: int = 0
    retryable: int = 0
    dead_letter: int = 0
    delivery_unknown: int = 0
    lease_lost: int = 0


def _decision_allowed(decision):
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, dict):
        return bool(decision.get("allowed"))
    return bool(getattr(decision, "allowed"))


def _decision_reason(decision):
    if isinstance(decision, dict):
        return decision.get("suppression_reason") or decision.get("reason")
    return getattr(decision, "suppression_reason", None)


def _provider_outcome(result):
    if result is True:
        return "provider_accepted", None, None, None
    if isinstance(result, dict):
        status = result.get("status")
        if status is None:
            return ("delivery_unknown", result.get("provider_message_id"),
                    result.get("error") or "Provider result omitted status", None)
        return (
            status,
            result.get("provider_message_id"),
            result.get("error"),
            result.get("retry_after"),
        )
    status = getattr(result, "status", "provider_accepted")
    return (
        status,
        getattr(result, "provider_message_id", None),
        getattr(result, "error", None),
        getattr(result, "retry_after", None),
    )


def _event_log_id(callback, row, status, details):
    if callback is None:
        return None
    result = callback(row, status, details)
    return result.id if hasattr(result, "id") else result


def process_claim(
    session,
    outbox_id,
    lease_token,
    *,
    safety_callback,
    provider_callback,
    event_log_callback=None,
    worker_release_sha=None,
    ownership_guard=None,
):
    """Process one committed lease and return its resulting status."""
    row = session.get(MessageOutbox, outbox_id)
    if row is None or row.status != "processing" or row.lease_token != lease_token:
        return "lease_lost"

    try:
        decision = safety_callback(row)
    except Exception as exc:
        finalize_message(
            row.id, lease_token, "retryable", error=exc, session=session
        )
        session.commit()
        return "retryable" if row.status == "retryable" else "dead_letter"

    if not _decision_allowed(decision):
        details = {"suppression_reason": _decision_reason(decision)}
        event_log_id = _event_log_id(
            event_log_callback, row, "suppressed", details
        )
        if not finalize_message(
            row.id,
            lease_token,
            "suppressed",
            error=details["suppression_reason"],
            final_event_log_id=event_log_id,
            session=session,
        ):
            session.rollback()
            return "lease_lost"
        session.commit()
        return "suppressed"

    if ownership_guard is not None:
        try:
            ownership_guard(session, "before_provider_start")
        except Exception:
            session.rollback()
            if release_pre_provider_claim(row.id, lease_token, session=session):
                session.commit()
            else:
                session.rollback()
            raise

    if not mark_provider_started(
        row.id, lease_token, session=session, worker_release_sha=worker_release_sha
    ):
        session.rollback()
        if release_pre_provider_claim(row.id, lease_token, session=session):
            session.commit()
        else:
            session.rollback()
        return "lease_lost"
    # This commit is the safety boundary.  A crash after it is recovered as
    # delivery_unknown rather than risking a duplicate provider submission.
    session.commit()

    row = session.get(MessageOutbox, outbox_id)
    try:
        provider_result = provider_callback(row)
        status, provider_message_id, error, retry_after = _provider_outcome(provider_result)
        if status == "accepted":
            status = "provider_accepted"
        if status not in {
            "provider_accepted", "retryable", "dead_letter",
            "delivery_unknown", "suppressed",
        }:
            raise ValueError(f"unsupported provider outcome: {status}")
    except Exception as exc:
        status, provider_message_id, error, retry_after = "delivery_unknown", None, exc, None

    details = {
        "provider_message_id": provider_message_id,
        "error": error,
        "retry_after": retry_after,
    }
    event_log_id = _event_log_id(event_log_callback, row, status, details)
    if not finalize_message(
        outbox_id,
        lease_token,
        status,
        provider_message_id=provider_message_id,
        error=error,
        final_event_log_id=event_log_id,
        retry_after_seconds=retry_after,
        session=session,
    ):
        session.rollback()
        return "lease_lost"
    final_status = session.get(MessageOutbox, outbox_id).status
    session.commit()
    return final_status


def run_worker(
    session_factory,
    *,
    owner,
    safety_callback,
    provider_callback,
    event_log_callback=None,
    batch_size=25,
    max_batches=1,
    max_messages=None,
    lease_seconds=60,
    worker_release_sha=None,
    stop_requested=None,
    ownership_guard=None,
):
    """Run a bounded number of batches and return aggregate counters."""
    if max_batches < 1 or batch_size < 1:
        raise ValueError("max_batches and batch_size must be positive")
    remaining = max_messages
    totals = {field: 0 for field in WorkerResult.__dataclass_fields__}

    for _ in range(max_batches):
        if stop_requested is not None and stop_requested():
            break
        if remaining is not None and remaining <= 0:
            break
        limit = min(batch_size, remaining) if remaining is not None else batch_size
        session = session_factory()
        try:
            if ownership_guard is not None:
                ownership_guard(session, "before_claim")
            recover_expired_leases(session=session)
            claimed = claim_messages(
                owner, limit=limit, lease_seconds=lease_seconds, session=session,
                worker_release_sha=worker_release_sha,
            )
            leases = [(row.id, row.lease_token) for row in claimed]
            # A termination request can arrive while the database claim is
            # still uncommitted. Rolling back here guarantees it cannot turn
            # into a committed processing lease.
            if stop_requested is not None and stop_requested():
                session.rollback()
                break
            session.commit()
            totals["claimed"] += len(leases)
            if not leases:
                break

            for index, (outbox_id, lease_token) in enumerate(leases):
                if stop_requested is not None and stop_requested():
                    # Claims whose provider boundary has not begun are safe to
                    # release immediately. Never reinterpret an in-flight or
                    # ambiguous provider attempt as retryable.
                    for pending_id, pending_token in leases[index:]:
                        release_pre_provider_claim(
                            pending_id, pending_token, session=session
                        )
                    session.commit()
                    break
                outcome = process_claim(
                    session,
                    outbox_id,
                    lease_token,
                    safety_callback=safety_callback,
                    provider_callback=provider_callback,
                    event_log_callback=event_log_callback,
                    worker_release_sha=worker_release_sha,
                    ownership_guard=ownership_guard,
                )
                totals[outcome] += 1
                if remaining is not None:
                    remaining -= 1
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    return WorkerResult(**totals)


def session_factory_from_url(database_url):
    """Build a standalone SQLAlchemy session factory without initializing Flask."""
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    return sa.orm.sessionmaker(bind=engine)


def _load_callback(path):
    module_name, separator, attribute = path.partition(":")
    if not separator:
        raise ValueError("callback must use module.path:attribute syntax")
    return getattr(importlib.import_module(module_name), attribute)


def main(argv=None):
    """CLI entry point with explicit callback wiring and bounded defaults."""
    parser = argparse.ArgumentParser(description="Run a bounded message outbox worker")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("MESSAGE_OUTBOX_DATABASE_URL"),
    )
    parser.add_argument("--owner", required=True)
    parser.add_argument("--safety-callback", required=True)
    parser.add_argument("--provider-callback", required=True)
    parser.add_argument("--event-log-callback")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-messages", type=int)
    parser.add_argument("--lease-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error(
            "--database-url or MESSAGE_OUTBOX_DATABASE_URL is required"
        )
    release_identity = resolve_release_identity(
        runtime_env=os.environ.get("BASELODGE_RUNTIME_ENV", "development").lower()
    )
    if (
        os.environ.get("BASELODGE_RUNTIME_ENV", "development").lower() == "production"
        and release_identity.sha is None
    ):
        parser.error("verified worker release identity is required in production")
    return run_worker(
        session_factory_from_url(args.database_url),
        owner=args.owner,
        safety_callback=_load_callback(args.safety_callback),
        provider_callback=_load_callback(args.provider_callback),
        event_log_callback=(
            _load_callback(args.event_log_callback)
            if args.event_log_callback else None
        ),
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        max_messages=args.max_messages,
        lease_seconds=args.lease_seconds,
        worker_release_sha=release_identity.sha,
    )


if __name__ == "__main__":
    main()