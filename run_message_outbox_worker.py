"""Executable, bounded application-wired message outbox worker.

The Flask application is deliberately imported only by ``main``.  Merely
importing this module therefore cannot start an application or run migrations.
"""

import argparse
import json
import sys


def _parser():
    parser = argparse.ArgumentParser(description="Run a bounded message outbox worker")
    parser.add_argument("--owner", default="message-outbox-worker")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-messages", type=int)
    parser.add_argument("--lease-seconds", type=int, default=60)
    return parser


def _result_payload(result):
    """Keep command output aggregate-only, with no provider diagnostics."""
    return {
        field: int(getattr(result, field))
        for field in (
            "claimed", "provider_accepted", "suppressed", "retryable",
            "dead_letter", "delivery_unknown", "lease_lost",
        )
    }


def main(argv=None):
    args = _parser().parse_args(argv)
    if (
        not args.owner
        or args.batch_size < 1
        or args.max_batches < 1
        or args.lease_seconds < 1
        or (args.max_messages is not None and args.max_messages < 1)
    ):
        _parser().error("owner and worker bounds must be positive")

    try:
        # These imports belong in the executable path: importing this runner is
        # intentionally side-effect free with respect to Flask and migrations.
        from app import app, is_production, RELEASE_IDENTITY
        from models import db
        from services.message_dispatch import (
            message_outbox_event_log_callback,
            message_outbox_opportunity_start_callback,
            message_outbox_provider_callback,
            message_outbox_safety_callback,
        )
        from services.message_outbox_worker import run_worker

        if is_production and RELEASE_IDENTITY.sha is None:
            raise RuntimeError("verified worker release identity required")
        with app.app_context():
            result = run_worker(
                db.session,
                owner=args.owner,
                safety_callback=message_outbox_safety_callback,
                provider_callback=message_outbox_provider_callback,
                event_log_callback=message_outbox_event_log_callback,
                opportunity_start_callback=(
                    message_outbox_opportunity_start_callback
                ),
                batch_size=args.batch_size,
                max_batches=args.max_batches,
                max_messages=args.max_messages,
                lease_seconds=args.lease_seconds,
                worker_release_sha=RELEASE_IDENTITY.sha,
            )
        print(json.dumps(_result_payload(result), sort_keys=True))
        return 0
    except Exception:
        # Per-message provider failures are represented by run_worker results.
        # Reaching here means app/config/database/worker-wide execution failed;
        # do not leak connection strings, recipients, or provider responses.
        print(json.dumps({"error": "worker_initialization_or_database_failure"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())