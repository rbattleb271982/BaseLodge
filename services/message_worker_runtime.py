"""Continuous, fail-closed runtime around the bounded outbox worker.

This module never imports ``app`` and never runs migrations.  Idle-only mode
has a separate code path which has no delivery callbacks and never invokes the
bounded claiming primitive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import signal
import uuid
from typing import Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa

from models import MessagingDeliveryPolicy, MessagingWorkerHeartbeat, db
from release_identity import resolve_release_identity
from runtime_config import (
    RuntimeConfigurationError,
    resolve_worker_database_config,
)
from services.message_outbox import OUTBOX_STATUSES, queue_health
from services.message_outbox_worker import WorkerResult, run_worker


_SHA = re.compile(r"^[0-9a-f]{40}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_APP_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_MODES = frozenset({"idle-only", "normal"})
_ERROR_CATEGORIES = frozenset({
    "database_unavailable",
    "heartbeat_unavailable",
    "worker_cycle_failed",
})
_REQUIRED_TABLE_COLUMNS = {
    "message_outbox": {
        "id", "status", "lease_token", "lease_expires_at", "provider_phase",
        "configuration_epoch", "producer_release_sha", "last_worker_release_sha",
    },
    "messaging_delivery_policy": {
        "event_name", "delivery_mode", "cutover_epoch", "claims_paused",
        "control_revision",
    },
    "messaging_delivery_policy_event": {"id", "event_name", "action"},
    "messaging_replay_event": {"id", "source_outbox_id", "target_outbox_id"},
    "message_event_log": {"id", "occurrence_id", "delivery_status"},
    "messaging_worker_heartbeat": {
        "worker_identity", "instance_token", "worker_release_sha", "readiness_state",
        "operating_mode", "queue_health_json", "updated_at",
    },
}


class WorkerPreflightError(RuntimeError):
    """Sanitized fatal startup failure."""

    def __init__(self, category):
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str
    worker_identity: str
    release_sha: str
    mode: str
    batch_size: int
    lease_seconds: int
    idle_seconds: float
    backoff_initial_seconds: float
    backoff_max_seconds: float
    stale_seconds: int
    pool_size: int
    max_overflow: int


@dataclass
class RuntimeCounters:
    cycles_total: int = 0
    cycles_failed: int = 0
    claimed_total: int = 0
    finalized_total: int = 0


def _value(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def _integer(environ, key, default, minimum, maximum):
    try:
        value = int(_value(environ, key) or default)
    except ValueError as exc:
        raise WorkerPreflightError("configuration_invalid") from exc
    if not minimum <= value <= maximum:
        raise WorkerPreflightError("configuration_invalid")
    return value


def _number(environ, key, default, minimum, maximum):
    try:
        value = float(_value(environ, key) or default)
    except ValueError as exc:
        raise WorkerPreflightError("configuration_invalid") from exc
    if not minimum <= value <= maximum:
        raise WorkerPreflightError("configuration_invalid")
    return value


def _tls_required(database_url):
    parsed = urlsplit(database_url)
    if not parsed.scheme.lower().startswith("postgresql"):
        return False
    values = parse_qs(parsed.query, keep_blank_values=True).get("sslmode", [])
    return len(values) == 1 and values[0].lower() == "verify-full"


def load_worker_settings(environ: Mapping[str, str] | None = None):
    """Resolve all configuration without connecting or importing the web app."""
    environment = os.environ if environ is None else environ
    if _value(environment, "BASELODGE_RUNTIME_ENV") != "production":
        raise WorkerPreflightError("runtime_environment_invalid")
    try:
        database = resolve_worker_database_config(environment)
    except (RuntimeConfigurationError, ValueError) as exc:
        raise WorkerPreflightError("database_identity_invalid") from exc
    if database.source != "worker_production" or not _tls_required(database.database_url):
        raise WorkerPreflightError(
            "database_tls_invalid" if not _tls_required(database.database_url)
            else "database_identity_invalid"
        )
    discovered = resolve_release_identity(runtime_env="production")
    approved = (_value(environment, "BASELODGE_APPROVED_WORKER_RELEASE_SHA") or "").lower()
    if (
        discovered.status != "VERIFIED"
        or not discovered.sha
        or not _SHA.fullmatch(discovered.sha)
        or not _SHA.fullmatch(approved)
        or discovered.sha != approved
    ):
        raise WorkerPreflightError("release_identity_invalid")

    identity = _value(environment, "BASELODGE_WORKER_IDENTITY")
    mode = _value(environment, "BASELODGE_WORKER_MODE")
    if not identity or not _IDENTITY.fullmatch(identity) or mode not in _MODES:
        raise WorkerPreflightError("configuration_invalid")
    app_id = _value(environment, "ONESIGNAL_APP_ID")
    api_key = _value(environment, "ONESIGNAL_REST_API_KEY")
    if not app_id or not _APP_ID.fullmatch(app_id) or not api_key or len(api_key) < 16:
        raise WorkerPreflightError("provider_configuration_invalid")

    idle = _number(environment, "BASELODGE_WORKER_IDLE_SECONDS", 5, 0.1, 300)
    initial = _number(environment, "BASELODGE_WORKER_BACKOFF_INITIAL_SECONDS", 1, 0.1, 60)
    maximum = _number(environment, "BASELODGE_WORKER_BACKOFF_MAX_SECONDS", 60, initial, 900)
    return WorkerSettings(
        database_url=database.database_url,
        worker_identity=identity,
        release_sha=discovered.sha,
        mode=mode,
        batch_size=_integer(environment, "BASELODGE_WORKER_BATCH_SIZE", 25, 1, 100),
        lease_seconds=_integer(environment, "BASELODGE_WORKER_LEASE_SECONDS", 60, 5, 3600),
        idle_seconds=idle,
        backoff_initial_seconds=initial,
        backoff_max_seconds=maximum,
        stale_seconds=_integer(
            environment, "BASELODGE_WORKER_STALE_SECONDS",
            max(30, int(idle * 4)), max(2, int(idle * 2)), 3600,
        ),
        pool_size=_integer(environment, "BASELODGE_WORKER_POOL_SIZE", 2, 1, 5),
        max_overflow=_integer(environment, "BASELODGE_WORKER_MAX_OVERFLOW", 1, 0, 3),
    )


def create_worker_resources(settings):
    """Build a bounded standalone engine/session without a Flask application."""
    engine = sa.create_engine(
        settings.database_url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=10,
        pool_recycle=300,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
    sessions = sa.orm.scoped_session(sa.orm.sessionmaker(
        bind=engine,
        expire_on_commit=False,
    ))
    # Existing shared delivery policy/rendering code resolves its ORM work
    # through this extension-level scoped session. In this dedicated process it
    # is deliberately rebound to the standalone worker session, with no app
    # object, routes, web configuration, or request lifecycle.
    db.session = sessions
    return engine, sessions


def _revision_is_compatible(revision):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    current = scripts.get_revision(revision)
    required = scripts.get_revision("bl443_reversible_cutover")
    if current is None or required is None:
        return False
    return required.revision in {
        item.revision for item in scripts.walk_revisions("base", current.revision)
    }


def run_startup_preflight(session):
    """Perform read-only compatibility checks; never repair or migrate."""
    try:
        if session.bind.dialect.name != "postgresql":
            raise WorkerPreflightError("database_identity_invalid")
        session.execute(sa.text("SELECT 1")).scalar_one()
        encrypted = session.execute(sa.text(
            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )).scalar_one_or_none()
        if encrypted is not True:
            raise WorkerPreflightError("database_tls_invalid")
        revision = session.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        if not _revision_is_compatible(revision):
            raise WorkerPreflightError("schema_incompatible")
        inspector = sa.inspect(session.bind)
        for table, required in _REQUIRED_TABLE_COLUMNS.items():
            if not inspector.has_table(table):
                raise WorkerPreflightError("schema_incompatible")
            columns = {item["name"] for item in inspector.get_columns(table)}
            if not required.issubset(columns):
                raise WorkerPreflightError("schema_incompatible")
        policies = session.execute(
            sa.select(MessagingDeliveryPolicy)
        ).scalars().all()
        if len(policies) < 20 or any(
            policy.delivery_mode not in {"inline", "enqueue_only"}
            or type(policy.cutover_epoch) is not int
            or policy.cutover_epoch < 1
            or type(policy.claims_paused) is not bool
            or type(policy.control_revision) is not int
            or policy.control_revision < 1
            for policy in policies
        ):
            raise WorkerPreflightError("policy_invalid")
        session.rollback()
    except WorkerPreflightError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        raise WorkerPreflightError("database_or_schema_unavailable") from exc


def _safe_health(health):
    return {
        "counts": {
            status: int((health.get("counts") or {}).get(status, 0))
            for status in OUTBOX_STATUSES
        },
        "ready": int(health.get("ready", 0)),
        "expired_leases": int(health.get("expired_leases", 0)),
        "oldest_ready_age_seconds": health.get("oldest_ready_age_seconds"),
    }


def publish_heartbeat(
    session, settings, started_at, counters, instance_token, *, readiness, health=None,
    error_category=None, shutdown=False, result=None,
):
    """Upsert allowlisted aggregate state only."""
    if error_category not in _ERROR_CATEGORIES:
        error_category = None
    now = datetime.utcnow()
    # Lock the current owner row so an old process cannot read its token, be
    # replaced, and then commit a stale final heartbeat over the replacement.
    heartbeat = session.get(
        MessagingWorkerHeartbeat, settings.worker_identity, with_for_update=True
    )
    if heartbeat is None:
        raise WorkerPreflightError("heartbeat_ownership_lost")
    if heartbeat.instance_token != instance_token:
        session.rollback()
        return False
    heartbeat.worker_release_sha = settings.release_sha
    heartbeat.process_started_at = started_at
    heartbeat.readiness_state = readiness
    heartbeat.operating_mode = settings.mode
    heartbeat.cycles_total = counters.cycles_total
    heartbeat.cycles_failed = counters.cycles_failed
    heartbeat.claimed_total = counters.claimed_total
    heartbeat.finalized_total = counters.finalized_total
    if health is not None or heartbeat.queue_health_json is None:
        heartbeat.queue_health_json = _safe_health(health or {})
    heartbeat.last_error_category = error_category
    heartbeat.graceful_shutdown = shutdown
    heartbeat.updated_at = now
    heartbeat.last_successful_database_check_at = now
    if health is not None:
        heartbeat.last_successful_poll_at = now
    if result and result.claimed:
        heartbeat.last_claim_at = now
    if result and _finalized(result):
        heartbeat.last_finalization_at = now
    session.commit()
    return True


def acquire_heartbeat(session, settings, started_at, instance_token):
    """Claim a stable identity; a fresh owner makes duplicate startup fatal."""
    heartbeat = session.get(
        MessagingWorkerHeartbeat, settings.worker_identity, with_for_update=True
    )
    if heartbeat is not None:
        age = max(0, (datetime.utcnow() - heartbeat.updated_at).total_seconds())
        if not heartbeat.graceful_shutdown and age <= settings.stale_seconds:
            session.rollback()
            raise WorkerPreflightError("worker_identity_in_use")
    if heartbeat is None:
        heartbeat = MessagingWorkerHeartbeat(worker_identity=settings.worker_identity)
        session.add(heartbeat)
    heartbeat.instance_token = instance_token
    heartbeat.worker_release_sha = settings.release_sha
    heartbeat.process_started_at = started_at
    heartbeat.readiness_state = "starting"
    heartbeat.operating_mode = settings.mode
    heartbeat.cycles_total = 0
    heartbeat.cycles_failed = 0
    heartbeat.claimed_total = 0
    heartbeat.finalized_total = 0
    heartbeat.queue_health_json = _safe_health({})
    heartbeat.last_error_category = None
    heartbeat.graceful_shutdown = False
    heartbeat.updated_at = datetime.utcnow()
    try:
        session.commit()
    except sa.exc.IntegrityError as exc:
        # The primary-key uniqueness constraint is the final atomic fence when
        # two new processes race to register the same stable identity.
        session.rollback()
        raise WorkerPreflightError("worker_identity_in_use") from exc


def verify_delivery_ownership(session, settings, instance_token, _phase):
    """Fence a delivery transaction on its durable heartbeat generation."""
    heartbeat = session.get(
        MessagingWorkerHeartbeat,
        settings.worker_identity,
        with_for_update=True,
    )
    if heartbeat is None or heartbeat.instance_token != instance_token:
        session.rollback()
        raise WorkerPreflightError("heartbeat_ownership_lost")
    # Refresh while holding the row lock. A stale replacement cannot acquire
    # ownership concurrently with this claim/provider-start transaction.
    heartbeat.updated_at = datetime.utcnow()


def inspect_heartbeat(session, worker_identity, *, stale_seconds, now=None):
    """Return a privacy-safe liveness snapshot with derived staleness."""
    row = session.get(MessagingWorkerHeartbeat, worker_identity)
    if row is None:
        return None
    timestamp = now or datetime.utcnow()
    age = max(0, int((timestamp - row.updated_at).total_seconds()))
    return {
        "worker_identity": row.worker_identity,
        "worker_release_sha": row.worker_release_sha,
        "operating_mode": row.operating_mode,
        "readiness_state": row.readiness_state,
        "heartbeat_age_seconds": age,
        "stale": age > stale_seconds,
        "last_error_category": row.last_error_category,
        "queue_health": dict(row.queue_health_json or {}),
    }


def _finalized(result):
    return sum(
        getattr(result, field)
        for field in (
            "provider_accepted", "suppressed", "dead_letter",
            "delivery_unknown",
        )
    )


def _is_heartbeat_ownership_loss(error):
    return (
        isinstance(error, WorkerPreflightError)
        and error.category == "heartbeat_ownership_lost"
    )


def run_continuous(
    settings, session_factory, *, stop_event, delivery_callbacks=None,
    sleep: Callable[[float], bool] | None = None, max_cycles=None,
):
    """Supervise bounded cycles until signalled.

    ``delivery_callbacks`` is mandatory in normal mode and forbidden in
    idle-only mode, making the latter structurally incapable of provider calls.
    ``max_cycles`` is an optional test/controlled-operation bound; Production
    continuous operation leaves it unset.
    """
    if settings.mode == "idle-only" and delivery_callbacks is not None:
        raise WorkerPreflightError("configuration_invalid")
    if settings.mode == "normal" and not delivery_callbacks:
        raise WorkerPreflightError("configuration_invalid")
    if max_cycles is not None and (
        type(max_cycles) is not int or max_cycles < 1
    ):
        raise WorkerPreflightError("configuration_invalid")
    wait = sleep or stop_event.wait
    started_at = datetime.utcnow()
    instance_token = uuid.uuid4().hex
    counters = RuntimeCounters()
    failure_count = 0
    ownership_lost = False

    session = session_factory()
    try:
        run_startup_preflight(session)
        acquire_heartbeat(session, settings, started_at, instance_token)
        health = queue_health(session=session)
        if not publish_heartbeat(
            session, settings, started_at, counters, instance_token,
            readiness="ready", health=health,
        ):
            raise WorkerPreflightError("heartbeat_ownership_lost")
    finally:
        session.close()

    while not stop_event.is_set():
        result = None
        try:
            if settings.mode == "normal":
                if stop_event.is_set():
                    break
                safety, provider, event_log = delivery_callbacks[:3]
                opportunity_start = (
                    delivery_callbacks[3]
                    if len(delivery_callbacks) > 3
                    else None
                )
                result = run_worker(
                    session_factory,
                    owner=settings.worker_identity,
                    safety_callback=safety,
                    provider_callback=provider,
                    event_log_callback=event_log,
                    batch_size=settings.batch_size,
                    max_batches=1,
                    max_messages=settings.batch_size,
                    lease_seconds=settings.lease_seconds,
                    worker_release_sha=settings.release_sha,
                    stop_requested=stop_event.is_set,
                    ownership_guard=lambda session, phase: verify_delivery_ownership(
                        session, settings, instance_token, phase
                    ),
                    opportunity_start_callback=opportunity_start,
                )
                counters.claimed_total += result.claimed
                counters.finalized_total += _finalized(result)
            session = session_factory()
            try:
                health = queue_health(session=session)
                counters.cycles_total += 1
                if not publish_heartbeat(
                    session, settings, started_at, counters, instance_token,
                    readiness="ready", health=health, result=result,
                ):
                    ownership_lost = True
            finally:
                session.close()
            failure_count = 0
            delay = settings.idle_seconds if settings.mode == "idle-only" or not result or not result.claimed else 0
        except Exception as exc:
            if _is_heartbeat_ownership_loss(exc):
                ownership_lost = True
                delay = 0
            else:
                counters.cycles_failed += 1
                failure_count += 1
                delay = min(
                    settings.backoff_max_seconds,
                    settings.backoff_initial_seconds * (2 ** min(failure_count - 1, 10)),
                )
                # Deterministic positive jitter avoids synchronized workers without
                # requiring process-global random state.
                delay = min(
                    settings.backoff_max_seconds,
                    delay * (1 + ((failure_count * 17) % 20) / 100),
                )
                try:
                    session = session_factory()
                    try:
                        session.rollback()
                        if not publish_heartbeat(
                            session, settings, started_at, counters, instance_token,
                            readiness="unhealthy",
                            error_category=(
                                "database_unavailable"
                                if isinstance(exc, sa.exc.SQLAlchemyError)
                                else "worker_cycle_failed"
                            ),
                        ):
                            ownership_lost = True
                    finally:
                        session.close()
                except Exception as heartbeat_error:
                    if _is_heartbeat_ownership_loss(heartbeat_error):
                        ownership_lost = True
        if ownership_lost:
            break
        if max_cycles is not None and (
            counters.cycles_total + counters.cycles_failed >= max_cycles
        ):
            break
        # Invoke the stop-aware wait even for a productive zero-delay cycle.
        # This gives supervisors and deterministic test controls a boundary
        # between claims while retaining immediate continuous queue draining.
        if wait(delay):
            break

    if not ownership_lost:
        try:
            session = session_factory()
            try:
                if not publish_heartbeat(
                    session, settings, started_at, counters, instance_token,
                    readiness="stopped", shutdown=True,
                ):
                    ownership_lost = True
            finally:
                session.close()
        except Exception as final_heartbeat_error:
            if _is_heartbeat_ownership_loss(final_heartbeat_error):
                ownership_lost = True
    if ownership_lost:
        raise WorkerPreflightError("heartbeat_ownership_lost")
    return counters


def install_signal_handlers(stop_event):
    """Install minimal handlers that only prevent another polling cycle."""
    previous = {}

    def request_stop(_signum, _frame):
        stop_event.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, request_stop)
    return previous


def restore_signal_handlers(previous):
    for signum, handler in previous.items():
        signal.signal(signum, handler)