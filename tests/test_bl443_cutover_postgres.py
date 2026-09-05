"""Isolated PostgreSQL 17 concurrency contract for reversible messaging cutover.

This module deliberately uses its own engines and sessions.  It never rebinds
the Flask-SQLAlchemy test application, whose ordinary suite remains SQLite.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import getpass
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import time
from urllib.parse import quote
from uuid import uuid4

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from importlib.util import module_from_spec, spec_from_file_location
import psycopg2
from psycopg2 import sql
import pytest
import sqlalchemy as sa

from models import (
    MessageEventLog,
    MessageOutbox,
    MessagingDeliveryPolicy,
    MessagingReplayEvent,
    MessagingWorkerHeartbeat,
)
from release_identity import ReleaseIdentity
from runtime_config import DatabaseConfiguration, RuntimeConfigurationError
from services.message_outbox import (
    claim_messages,
    enqueue_message,
    finalize_message,
    mark_provider_started,
    recover_expired_leases,
)
from services.messaging_cutover import (
    guarded_transition_inline,
    mutate_policy,
    terminalize_eligible,
)
from services.messaging_staging import (
    finish_staged_messaging,
    stage_messaging_intents,
)
from services.message_outbox_worker import WorkerResult, run_worker
from services.message_worker_runtime import (
    WorkerPreflightError,
    WorkerSettings,
    RuntimeCounters,
    acquire_heartbeat,
    create_worker_resources,
    inspect_heartbeat,
    install_signal_handlers,
    load_worker_settings,
    restore_signal_handlers,
    run_continuous,
    run_startup_preflight,
    publish_heartbeat,
    verify_delivery_ownership,
)


ROOT = Path(__file__).parents[1]
REQUIRE_PG17 = (
    os.environ.get("BL443_REQUIRE_POSTGRES17") == "1"
    or os.environ.get("BL442_REQUIRE_POSTGRES17") == "1"
)


def _free_port():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def _tool_major(executable):
    output = subprocess.run(
        [executable, "--version"], check=True, capture_output=True, text=True
    ).stdout
    return int(output.split()[2].split(".")[0])


@pytest.fixture(scope="session")
def bl443_postgres17(tmp_path_factory):
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    blocker = None
    if not initdb or not pg_ctl:
        blocker = "PostgreSQL initdb and pg_ctl are not available"
    elif _tool_major(initdb) != 17 or _tool_major(pg_ctl) != 17:
        blocker = (
            f"PostgreSQL 17 required; initdb={initdb} "
            f"({_tool_major(initdb)}), pg_ctl={pg_ctl} ({_tool_major(pg_ctl)})"
        )
    if blocker:
        if REQUIRE_PG17:
            pytest.fail(blocker)
        pytest.skip(blocker)

    root = tmp_path_factory.mktemp("bl443-postgres17")
    data = root / "data"
    sockets = root / "socket"
    sockets.mkdir()
    log = root / "postgres.log"
    port = _free_port()
    role = getpass.getuser()
    subprocess.run(
        [initdb, "-D", str(data), "-A", "trust", "--no-locale",
         "--encoding=UTF8", "-U", role],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        [
            "openssl", "req", "-new", "-x509", "-nodes", "-days", "1",
            "-subj", "/CN=localhost",
            "-keyout", str(data / "server.key"),
            "-out", str(data / "server.crt"),
        ],
        check=True, capture_output=True, text=True,
    )
    (data / "server.key").chmod(0o600)
    subprocess.run(
        [pg_ctl, "-D", str(data), "-o",
         f"-F -h 127.0.0.1 -k {sockets} -p {port} -c ssl=on",
         "-l", str(log), "-w", "start"],
        check=True, capture_output=True, text=True,
    )
    admin_url = (
        f"postgresql://{quote(role, safe='')}@localhost:{port}/postgres"
        f"?sslmode=verify-full&sslrootcert={data / 'server.crt'}"
    )

    def database():
        name = f"bl443_{uuid4().hex}"
        connection = psycopg2.connect(admin_url)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version_num")
                assert int(cursor.fetchone()[0]) // 10000 == 17
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(name)
                ))
        finally:
            connection.close()
        return (
            f"postgresql://{quote(role, safe='')}@localhost:{port}/{name}"
            f"?sslmode=verify-full&sslrootcert={data / 'server.crt'}"
        )

    try:
        yield database
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True, capture_output=True, text=True,
        )


def _migration(name):
    path = ROOT / "migrations" / "versions" / f"{name}.py"
    spec = spec_from_file_location(f"{name}_{uuid4().hex}", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(connection, migration):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        migration.upgrade()
    finally:
        migration.op = original


@pytest.fixture
def bl443_sessions(bl443_postgres17):
    url = bl443_postgres17()
    engine = sa.create_engine(url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE "user" (id INTEGER PRIMARY KEY)')
        # Runtime terminalization writes the current full MEL mapping.  Create
        # that dependency from model metadata, then exercise bl440/bl443 DDL.
        MessageEventLog.__table__.create(connection)
        _run_migration(connection, _migration("bl440_message_outbox"))
        _run_migration(connection, _migration("bl443_reversible_cutover"))
        _run_migration(connection, _migration("bl442_worker_heartbeat"))
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version VALUES ('bl442_worker_heartbeat')"
        )
        connection.execute(sa.text(
            'INSERT INTO "user" (id) SELECT generate_series(1, 20)'
        ))
    factory = sa.orm.sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def _policy(session, name, *, epoch=1, paused=False, revision=1):
    policy = session.get(MessagingDeliveryPolicy, name)
    if policy is None:
        policy = MessagingDeliveryPolicy(
            event_name=name, delivery_mode="enqueue_only",
            cutover_epoch=epoch, claims_paused=paused,
            control_revision=revision, operator_reason="postgres test",
            audit_identity="test",
        )
        session.add(policy)
    else:
        policy.delivery_mode = "enqueue_only"
        policy.cutover_epoch = epoch
        policy.claims_paused = paused
        policy.control_revision = revision
    session.commit()
    return policy


def _enqueue(session, occurrence, *, family="family.a", recipient=1, epoch=1):
    return enqueue_message(
        event_name=family, category="test", occurrence_id=occurrence,
        recipient_user_id=recipient, channel="push", provider="test",
        context={}, evidence_ids=[], configuration_epoch=epoch, session=session,
    )


def _thread_results(targets):
    barrier = threading.Barrier(len(targets))
    results = [None] * len(targets)
    errors = []

    def invoke(index, target):
        try:
            barrier.wait(timeout=5)
            results[index] = target()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=invoke, args=(index, target), daemon=True)
        for index, target in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "concurrency test thread timed out"
    if errors:
        raise errors[0]
    return results


def test_simultaneous_enqueue_uniqueness_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    seed.close()

    def insert():
        session = bl443_sessions()
        try:
            row = _enqueue(session, "same-occurrence")
            session.commit()
            return row.id
        finally:
            session.close()

    ids = _thread_results([insert, insert])
    assert ids[0] == ids[1]
    verify = bl443_sessions()
    assert verify.query(MessageOutbox).count() == 1
    verify.close()


def test_multiple_skip_locked_claimers_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    for number in range(4):
        _enqueue(seed, f"claim-{number}", recipient=number + 1)
    seed.commit()
    seed.close()
    hold = threading.Barrier(2)

    def claim(owner):
        session = bl443_sessions()
        try:
            rows = claim_messages(owner, limit=2, session=session)
            ids = [row.id for row in rows]
            hold.wait(timeout=5)  # Both transactions retain locks concurrently.
            session.commit()
            return ids
        finally:
            session.close()

    claimed = _thread_results([
        lambda: claim("worker-a"), lambda: claim("worker-b")
    ])
    assert len(claimed[0]) == len(claimed[1]) == 2
    assert set(claimed[0]).isdisjoint(claimed[1])


def test_pause_active_claim_and_provider_start_ordering_postgres(bl443_sessions):
    seed = bl443_sessions()
    policy = _policy(seed, "family.a")
    row = _enqueue(seed, "pause-claim")
    seed.commit()
    claimed = claim_messages("worker", session=seed)
    token = claimed[0].lease_token
    seed.commit()

    mutate_policy(
        "family.a", expected_revision=policy.control_revision, expected_epoch=1,
        claims_paused=True, reason="pause committed", audit_identity="operator",
        session=seed,
    )
    seed.commit()
    assert claim_messages("later-worker", session=seed) == []
    assert not mark_provider_started(row.id, token, session=seed)
    seed.rollback()

    # Reverse ordering: provider-start owns the policy lock, so pause must wait
    # and can commit only after the persisted provider boundary commits.
    policy = seed.get(MessagingDeliveryPolicy, "family.a")
    policy.claims_paused = False
    policy.control_revision += 1
    second = _enqueue(seed, "provider-first", recipient=2)
    seed.commit()
    claimed = claim_messages("worker", session=seed)
    second_token = next(item.lease_token for item in claimed if item.id == second.id)
    seed.commit()
    worker = bl443_sessions()
    assert mark_provider_started(second.id, second_token, session=worker)
    lock_acquired = threading.Event()
    pause_done = threading.Event()

    def pause():
        operator = bl443_sessions()
        try:
            locked = operator.execute(
                sa.select(MessagingDeliveryPolicy)
                .where(MessagingDeliveryPolicy.event_name == "family.a")
                .with_for_update()
            ).scalar_one()
            lock_acquired.set()
            locked.claims_paused = True
            locked.control_revision += 1
            operator.commit()
            pause_done.set()
        finally:
            operator.close()

    thread = threading.Thread(target=pause, daemon=True)
    thread.start()
    time.sleep(0.15)
    assert not lock_acquired.is_set()
    worker.commit()
    thread.join(timeout=5)
    assert lock_acquired.is_set() and pause_done.is_set()
    worker.close()
    seed.close()


def test_lease_expiry_and_stale_worker_finalization_postgres(bl443_sessions):
    session = bl443_sessions()
    _policy(session, "family.a")
    safe = _enqueue(session, "pre-provider")
    unsafe = _enqueue(session, "post-provider", recipient=2)
    session.commit()
    now = datetime.utcnow()
    claimed = claim_messages(
        "worker", limit=2, lease_seconds=5, now=now, session=session
    )
    tokens = {row.id: row.lease_token for row in claimed}
    assert mark_provider_started(
        unsafe.id, tokens[unsafe.id], now=now, session=session
    )
    session.commit()
    policy = session.get(MessagingDeliveryPolicy, "family.a")
    policy.claims_paused = True
    policy.control_revision = 2
    session.commit()
    with pytest.raises(RuntimeError, match="deliverable rows or live leases"):
        guarded_transition_inline(
            "family.a", expected_revision=2, expected_epoch=1,
            reason="must wait for processing", audit_identity="operator",
            now=now + timedelta(seconds=6), session=session,
        )
    session.rollback()
    result = recover_expired_leases(
        now=now + timedelta(seconds=6), session=session
    )
    session.commit()
    assert result == {"reclaimed": 1, "delivery_unknown": 1}
    assert session.get(MessageOutbox, safe.id).status == "retryable"
    assert session.get(MessageOutbox, unsafe.id).status == "delivery_unknown"
    assert terminalize_eligible(
        "family.a", 1, reason="drained safely", audit_identity="operator",
        now=now + timedelta(seconds=6), session=session,
    ) == 1
    transitioned = guarded_transition_inline(
        "family.a", expected_revision=2, expected_epoch=1,
        reason="safe inline rollback", audit_identity="operator",
        now=now + timedelta(seconds=6), session=session,
    )
    assert transitioned.delivery_mode == "inline"
    assert not finalize_message(
        safe.id, tokens[safe.id], "provider_accepted", session=session
    )
    assert not finalize_message(
        unsafe.id, tokens[unsafe.id], "provider_accepted", session=session
    )
    session.close()


def test_mixed_epochs_and_independent_families_postgres(bl443_sessions):
    session = bl443_sessions()
    _policy(session, "family.a", epoch=2)
    _policy(session, "family.b", epoch=1)
    active_a = _enqueue(session, "active-a", family="family.a", epoch=2)
    _enqueue(session, "stale-a", family="family.a", recipient=2, epoch=1)
    active_b = _enqueue(session, "active-b", family="family.b", recipient=3, epoch=1)
    session.commit()
    claimed = claim_messages("worker", limit=10, session=session)
    assert {row.id for row in claimed} == {active_a.id, active_b.id}
    session.rollback()
    policy_a = session.get(MessagingDeliveryPolicy, "family.a")
    policy_a.claims_paused = True
    session.commit()
    claimed = claim_messages("worker-b", limit=10, session=session)
    assert {row.event_name for row in claimed} == {"family.b"}
    session.close()


def test_rollback_serialization_and_zero_intentional_dual_send_postgres(
    bl443_sessions,
):
    family = "founder.invite_share"
    seed = bl443_sessions()
    _policy(seed, family, paused=True)
    seed.close()
    producer_locked = threading.Event()
    allow_commit = threading.Event()
    transition_started = threading.Event()
    outcomes = {}
    sinks = {"inline": 0, "provider": 0}
    intent = {
        "event_name": family, "actor_user_id": 1, "recipient_user_id": 2,
        "occurrence_id": "serialized-occurrence",
    }

    def enqueue_hook(**values):
        return enqueue_message(
            event_name=values["event_name"], category="system",
            occurrence_id=values["occurrence_id"],
            actor_user_id=values["actor_user_id"],
            recipient_user_id=values["recipient_user_id"],
            channel="push", provider="test", context={}, evidence_ids=[],
            configuration_epoch=values["configuration_epoch"],
            producer_release_sha=values["producer_release_sha"],
            session=values["session"],
        )

    def producer():
        session = bl443_sessions()
        try:
            plan = stage_messaging_intents(
                (intent,), session=session, enqueue=enqueue_hook
            )
            producer_locked.set()
            allow_commit.wait(timeout=5)
            session.commit()
            finish_staged_messaging(
                plan, (intent,),
                inline_emitter=lambda **_values: sinks.__setitem__(
                    "inline", sinks["inline"] + 1
                ),
            )
            outcomes["enqueued"] = True
        finally:
            session.close()

    def transition():
        producer_locked.wait(timeout=5)
        session = bl443_sessions()
        try:
            transition_started.set()
            try:
                guarded_transition_inline(
                    family, expected_revision=1, expected_epoch=1,
                    reason="rollback", audit_identity="operator", session=session,
                )
                session.commit()
                outcomes["inline"] = True
            except RuntimeError:
                session.rollback()
                outcomes["inline"] = False
        finally:
            session.close()

    first = threading.Thread(target=producer, daemon=True)
    second = threading.Thread(target=transition, daemon=True)
    first.start()
    assert producer_locked.wait(timeout=5)
    second.start()
    assert transition_started.wait(timeout=5)
    time.sleep(0.15)
    assert "inline" not in outcomes
    allow_commit.set()
    first.join(timeout=5)
    second.join(timeout=5)
    assert outcomes == {"enqueued": True, "inline": False}
    verify = bl443_sessions()
    assert verify.query(MessageOutbox).filter_by(
        occurrence_id="serialized-occurrence"
    ).count() == 1
    assert verify.get(MessagingDeliveryPolicy, family).delivery_mode == "enqueue_only"
    policy = verify.get(MessagingDeliveryPolicy, family)
    policy.claims_paused = False
    policy.control_revision += 1
    verify.commit()
    verify.close()

    result = run_worker(
        bl443_sessions, owner="sink-worker",
        safety_callback=lambda _row: True,
        provider_callback=lambda _row: (
            sinks.__setitem__("provider", sinks["provider"] + 1)
            or {"status": "provider_accepted"}
        ),
        batch_size=1, max_batches=1,
    )
    assert result.provider_accepted == 1
    assert sinks["inline"] + sinks["provider"] == 1


def test_stale_control_revision_rejected_postgres(bl443_sessions):
    session = bl443_sessions()
    _policy(session, "family.a", revision=4)
    with pytest.raises(RuntimeError, match="stale"):
        mutate_policy(
            "family.a", expected_revision=3, expected_epoch=1,
            claims_paused=True, reason="stale update", audit_identity="operator",
            session=session,
        )
    session.rollback()
    policy = session.get(MessagingDeliveryPolicy, "family.a")
    assert policy.control_revision == 4
    assert not policy.claims_paused
    session.close()


def test_concurrent_replay_idempotency_uses_source_lock_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    source = _enqueue(seed, "replay-source")
    source.status = "dead_letter"
    source.completed_at = datetime.utcnow()
    seed.commit()
    source_id = source.id
    seed.close()

    def replay():
        session = bl443_sessions()
        try:
            locked = session.execute(
                sa.select(MessageOutbox)
                .where(MessageOutbox.id == source_id)
                .with_for_update()
            ).scalar_one()
            evidence = session.query(MessagingReplayEvent).filter_by(
                source_outbox_id=source_id,
                idempotency_key="concurrent-request",
            ).one_or_none()
            if evidence is not None:
                target_id = evidence.target_outbox_id
            else:
                target = _enqueue(
                    session, "replay-target", recipient=locked.recipient_user_id
                )
                target.replay_of_outbox_id = source_id
                session.flush()
                session.add(MessagingReplayEvent(
                    source_outbox_id=source_id, target_outbox_id=target.id,
                    source_epoch=1, target_epoch=1,
                    source_status="dead_letter",
                    idempotency_key="concurrent-request",
                    operator_reason="concurrent replay",
                    duplicate_risk_acknowledged=False,
                    audit_identity="operator",
                ))
                session.flush()
                target_id = target.id
            session.commit()
            return target_id
        finally:
            session.close()

    target_ids = _thread_results([replay, replay])
    assert target_ids[0] == target_ids[1]
    verify = bl443_sessions()
    assert verify.query(MessagingReplayEvent).filter_by(
        source_outbox_id=source_id,
        idempotency_key="concurrent-request",
    ).count() == 1
    assert verify.query(MessageOutbox).filter_by(
        replay_of_outbox_id=source_id
    ).count() == 1
    verify.close()


def _runtime_settings(mode, *, batch_size=1):
    return WorkerSettings(
        database_url="postgresql://unused?sslmode=require",
        worker_identity=f"postgres-{mode}",
        release_sha="a" * 40,
        mode=mode,
        batch_size=batch_size,
        lease_seconds=60,
        idle_seconds=0.1,
        backoff_initial_seconds=0.1,
        backoff_max_seconds=1,
        stale_seconds=30,
        pool_size=1,
        max_overflow=0,
    )


def test_continuous_idle_only_cannot_claim_or_call_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    row = _enqueue(seed, "idle-only-row")
    seed.commit()
    row_id = row.id
    seed.close()
    stop = threading.Event()

    counters = run_continuous(
        _runtime_settings("idle-only"),
        bl443_sessions,
        stop_event=stop,
        delivery_callbacks=None,
        sleep=lambda _delay: True,
    )

    verify = bl443_sessions()
    assert counters.claimed_total == counters.finalized_total == 0
    assert verify.get(MessageOutbox, row_id).status == "pending"
    heartbeat = verify.get(MessagingWorkerHeartbeat, "postgres-idle-only")
    assert heartbeat.graceful_shutdown
    assert heartbeat.claimed_total == 0
    verify.close()


def test_continuous_normal_processes_one_bounded_cycle_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    for number in range(2):
        _enqueue(seed, f"bounded-{number}", recipient=number + 1)
    seed.commit()
    seed.close()
    calls = []

    counters = run_continuous(
        _runtime_settings("normal", batch_size=1),
        bl443_sessions,
        stop_event=threading.Event(),
        delivery_callbacks=(
            lambda _row: True,
            lambda row: calls.append(row.id) or {"status": "provider_accepted"},
            None,
        ),
        max_cycles=1,
    )

    assert counters.claimed_total == counters.finalized_total == 1
    assert len(calls) == 1
    verify = bl443_sessions()
    assert verify.query(MessageOutbox).filter_by(status="pending").count() == 1
    delivered = verify.query(MessageOutbox).filter_by(
        status="provider_accepted"
    ).one()
    assert delivered.last_worker_release_sha == "a" * 40
    verify.close()


def test_continuous_normal_repeats_bounded_cycles_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    for number in range(3):
        _enqueue(seed, f"continuous-{number}", recipient=number + 1)
    seed.commit()
    seed.close()
    calls = []

    counters = run_continuous(
        _runtime_settings("normal", batch_size=1),
        bl443_sessions,
        stop_event=threading.Event(),
        delivery_callbacks=(
            lambda _row: True,
            lambda row: calls.append(row.id) or {"status": "provider_accepted"},
            None,
        ),
        max_cycles=2,
    )

    assert counters.cycles_total == 2
    assert counters.claimed_total == counters.finalized_total == 2
    assert len(calls) == 2
    verify = bl443_sessions()
    assert verify.query(MessageOutbox).filter_by(status="pending").count() == 1
    verify.close()


def test_worker_heartbeat_staleness_and_redaction_postgres(bl443_sessions):
    stop = threading.Event()
    run_continuous(
        _runtime_settings("idle-only"),
        bl443_sessions,
        stop_event=stop,
        sleep=lambda _delay: True,
    )
    session = bl443_sessions()
    heartbeat = session.get(MessagingWorkerHeartbeat, "postgres-idle-only")
    assert "recipient" not in str(heartbeat.queue_health_json).lower()
    snapshot = inspect_heartbeat(
        session,
        "postgres-idle-only",
        stale_seconds=30,
        now=heartbeat.updated_at + timedelta(seconds=31),
    )
    assert snapshot["stale"] is True
    assert set(snapshot["queue_health"]) == {
        "counts", "ready", "expired_leases", "oldest_ready_age_seconds",
    }
    session.close()


def test_worker_rejects_schema_older_than_bl443_postgres(bl443_sessions):
    session = bl443_sessions()
    session.execute(sa.text(
        "UPDATE alembic_version SET version_num = 'bl440_message_outbox'"
    ))
    session.commit()
    with pytest.raises(WorkerPreflightError) as error:
        run_startup_preflight(session)
    assert error.value.category == "schema_incompatible"
    session.close()


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_worker_signal_requests_graceful_stop(signum):
    stop = threading.Event()
    previous = install_signal_handlers(stop)
    try:
        signal.getsignal(signum)(signum, None)
        assert stop.is_set()
    finally:
        restore_signal_handlers(previous)


def test_worker_does_not_claim_after_shutdown_begins_postgres(bl443_sessions):
    seed = bl443_sessions()
    _policy(seed, "family.a")
    row = _enqueue(seed, "shutdown-before-claim")
    seed.commit()
    row_id = row.id
    seed.close()
    stop = threading.Event()
    stop.set()

    counters = run_continuous(
        _runtime_settings("normal"),
        bl443_sessions,
        stop_event=stop,
        delivery_callbacks=(
            lambda _row: True,
            lambda _row: pytest.fail("provider must not be called"),
            None,
        ),
    )

    assert counters.claimed_total == 0
    verify = bl443_sessions()
    assert verify.get(MessageOutbox, row_id).status == "pending"
    verify.close()


def test_worker_database_failure_uses_bounded_backoff_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    delays = []
    monkeypatch.setattr(
        runtime,
        "run_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sa.exc.OperationalError("SELECT 1", {}, RuntimeError("offline"))
        ),
    )
    counters = run_continuous(
        replace(_runtime_settings("normal"), backoff_max_seconds=0.15),
        bl443_sessions,
        stop_event=threading.Event(),
        delivery_callbacks=(lambda _row: True, lambda _row: True, None),
        sleep=lambda delay: delays.append(delay) or False,
        max_cycles=4,
    )
    assert counters.cycles_failed == 4
    assert delays == pytest.approx([0.117, 0.15, 0.15])


def _production_worker_environment():
    return {
        "BASELODGE_RUNTIME_ENV": "production",
        "BASELODGE_WORKER_IDENTITY": "pg17-full-path",
        "BASELODGE_WORKER_MODE": "idle-only",
        "BASELODGE_APPROVED_WORKER_RELEASE_SHA": "b" * 40,
        "ONESIGNAL_APP_ID": "123e4567-e89b-42d3-a456-426614174000",
        "ONESIGNAL_REST_API_KEY": "x" * 16,
    }


def test_full_path_production_settings_resources_and_preflight_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    # The fixture factory deliberately hides its engine; use a checked-out
    # connection's safe URL for this isolated full-path wiring test.
    session = bl443_sessions()
    url = str(session.get_bind().url)
    session.close()
    monkeypatch.setattr(
        runtime, "resolve_worker_database_config",
        lambda _env: DatabaseConfiguration("production", url, "worker_production"),
    )
    monkeypatch.setattr(
        runtime, "resolve_release_identity",
        lambda **_kwargs: ReleaseIdentity("b" * 40, "VERIFIED"),
    )
    settings = load_worker_settings(_production_worker_environment())
    engine, sessions = create_worker_resources(settings)
    try:
        session = sessions()
        run_startup_preflight(session)
        session.close()
    finally:
        sessions.remove()
        engine.dispose()


def test_full_path_rejects_release_mismatch_postgres(bl443_sessions, monkeypatch):
    import services.message_worker_runtime as runtime

    monkeypatch.setattr(
        runtime, "resolve_worker_database_config",
        lambda _env: DatabaseConfiguration(
            "production", "postgresql://localhost/db?sslmode=verify-full",
            "worker_production",
        ),
    )
    monkeypatch.setattr(
        runtime, "resolve_release_identity",
        lambda **_kwargs: ReleaseIdentity("c" * 40, "VERIFIED"),
    )
    with pytest.raises(WorkerPreflightError, match="release_identity_invalid"):
        load_worker_settings(_production_worker_environment())


def test_full_path_rejects_protected_identity_mismatch_postgres(monkeypatch):
    import services.message_worker_runtime as runtime

    monkeypatch.setattr(
        runtime, "resolve_worker_database_config",
        lambda _env: (_ for _ in ()).throw(RuntimeConfigurationError("mismatch")),
    )
    with pytest.raises(WorkerPreflightError, match="database_identity_invalid"):
        load_worker_settings(_production_worker_environment())


def test_full_path_rejects_nonverifying_tls_postgres(monkeypatch):
    import services.message_worker_runtime as runtime

    monkeypatch.setattr(
        runtime, "resolve_worker_database_config",
        lambda _env: DatabaseConfiguration(
            "production", "postgresql://localhost/db?sslmode=require",
            "worker_production",
        ),
    )
    with pytest.raises(WorkerPreflightError, match="database_tls_invalid"):
        load_worker_settings(_production_worker_environment())


def test_shutdown_inside_claim_transaction_rolls_back_lease_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_outbox_worker as worker

    seed = bl443_sessions()
    _policy(seed, "family.a")
    row = _enqueue(seed, "stop-during-claim")
    seed.commit()
    row_id = row.id
    seed.close()
    stop = threading.Event()
    original_claim = worker.claim_messages

    def claim_then_stop(*args, **kwargs):
        rows = original_claim(*args, **kwargs)
        stop.set()
        return rows

    monkeypatch.setattr(worker, "claim_messages", claim_then_stop)
    result = worker.run_worker(
        bl443_sessions, owner="claim-race", safety_callback=lambda _row: True,
        provider_callback=lambda _row: pytest.fail("provider must not run"),
        batch_size=1, max_batches=1, stop_requested=stop.is_set,
    )
    assert result.claimed == 0
    verify = bl443_sessions()
    assert verify.get(MessageOutbox, row_id).status == "pending"
    verify.close()


def test_heartbeat_identity_fencing_and_stale_replacement_postgres(bl443_sessions):
    settings = _runtime_settings("idle-only")
    started = datetime.utcnow()
    first = bl443_sessions()
    acquire_heartbeat(first, settings, started, "first")
    first.close()

    duplicate = bl443_sessions()
    with pytest.raises(WorkerPreflightError, match="worker_identity_in_use"):
        acquire_heartbeat(duplicate, settings, started, "second")
    duplicate.close()

    replace_owner = bl443_sessions()
    row = replace_owner.get(MessagingWorkerHeartbeat, settings.worker_identity)
    row.updated_at = datetime.utcnow() - timedelta(seconds=settings.stale_seconds + 1)
    replace_owner.commit()
    acquire_heartbeat(replace_owner, settings, started, "second")
    replace_owner.close()

    old = bl443_sessions()
    assert not publish_heartbeat(
        old, settings, started, RuntimeCounters(), "first",
        readiness="stopped", shutdown=True,
    )
    old.close()
    verify = bl443_sessions()
    assert verify.get(
        MessagingWorkerHeartbeat, settings.worker_identity
    ).instance_token == "second"
    verify.close()


def test_replaced_runner_exits_before_another_claim_cycle_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    settings = replace(
        _runtime_settings("normal"),
        worker_identity="coordinated-replacement",
        stale_seconds=1,
    )
    cycle_heartbeat_reached = threading.Event()
    replacement_ready = threading.Event()
    calls = []
    errors = []
    original_publish = runtime.publish_heartbeat
    publish_count = 0

    def coordinated_publish(*args, **kwargs):
        nonlocal publish_count
        publish_count += 1
        if publish_count == 2:
            cycle_heartbeat_reached.set()
            assert replacement_ready.wait(timeout=5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(runtime, "publish_heartbeat", coordinated_publish)
    monkeypatch.setattr(
        runtime, "run_worker",
        lambda *_args, **_kwargs: calls.append("bounded-cycle") or WorkerResult(),
    )

    def old_runner():
        try:
            run_continuous(
                settings,
                bl443_sessions,
                stop_event=threading.Event(),
                delivery_callbacks=(lambda _row: True, lambda _row: True, None),
            )
        except WorkerPreflightError as exc:
            errors.append(exc.category)

    thread = threading.Thread(target=old_runner, daemon=True)
    thread.start()
    assert cycle_heartbeat_reached.wait(timeout=5)
    replacement = bl443_sessions()
    row = replacement.get(
        MessagingWorkerHeartbeat, settings.worker_identity, with_for_update=True
    )
    row.updated_at = datetime.utcnow() - timedelta(seconds=2)
    replacement.commit()
    acquire_heartbeat(
        replacement, settings, datetime.utcnow(), "replacement-instance"
    )
    replacement.close()
    replacement_ready.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == ["heartbeat_ownership_lost"]
    assert calls == ["bounded-cycle"]
    verify = bl443_sessions()
    heartbeat = verify.get(
        MessagingWorkerHeartbeat, settings.worker_identity
    )
    assert heartbeat.instance_token == "replacement-instance"
    assert heartbeat.readiness_state == "starting"
    assert not heartbeat.graceful_shutdown
    verify.close()


def test_replacement_immediately_before_final_heartbeat_is_fatal_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    settings = replace(
        _runtime_settings("normal"),
        worker_identity="final-heartbeat-replacement",
        stale_seconds=1,
    )
    final_heartbeat_reached = threading.Event()
    replacement_ready = threading.Event()
    errors = []
    original_publish = runtime.publish_heartbeat
    publish_count = 0

    def coordinated_publish(*args, **kwargs):
        nonlocal publish_count
        publish_count += 1
        if publish_count == 3:
            final_heartbeat_reached.set()
            assert replacement_ready.wait(timeout=5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(runtime, "publish_heartbeat", coordinated_publish)
    monkeypatch.setattr(runtime, "run_worker", lambda *_a, **_k: WorkerResult())

    def old_runner():
        try:
            run_continuous(
                settings,
                bl443_sessions,
                stop_event=threading.Event(),
                delivery_callbacks=(lambda _row: True, lambda _row: True, None),
                max_cycles=1,
            )
        except WorkerPreflightError as exc:
            errors.append(exc.category)

    thread = threading.Thread(target=old_runner, daemon=True)
    thread.start()
    assert final_heartbeat_reached.wait(timeout=5)
    replacement = bl443_sessions()
    row = replacement.get(
        MessagingWorkerHeartbeat, settings.worker_identity, with_for_update=True
    )
    row.updated_at = datetime.utcnow() - timedelta(seconds=2)
    replacement.commit()
    acquire_heartbeat(
        replacement, settings, datetime.utcnow(), "replacement-at-final"
    )
    replacement.close()
    replacement_ready.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == ["heartbeat_ownership_lost"]
    verify = bl443_sessions()
    heartbeat = verify.get(
        MessagingWorkerHeartbeat, settings.worker_identity
    )
    assert heartbeat.instance_token == "replacement-at-final"
    assert heartbeat.readiness_state == "starting"
    assert not heartbeat.graceful_shutdown
    verify.close()


def test_deleted_heartbeat_fences_runner_before_next_cycle_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    settings = replace(
        _runtime_settings("normal"),
        worker_identity="deleted-heartbeat-owner",
    )
    cycle_heartbeat_reached = threading.Event()
    heartbeat_deleted = threading.Event()
    calls = []
    errors = []
    original_publish = runtime.publish_heartbeat
    publish_count = 0

    def coordinated_publish(*args, **kwargs):
        nonlocal publish_count
        publish_count += 1
        if publish_count == 2:
            cycle_heartbeat_reached.set()
            assert heartbeat_deleted.wait(timeout=5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(runtime, "publish_heartbeat", coordinated_publish)
    monkeypatch.setattr(
        runtime, "run_worker",
        lambda *_args, **_kwargs: calls.append("bounded-cycle") or WorkerResult(),
    )

    def runner():
        try:
            run_continuous(
                settings,
                bl443_sessions,
                stop_event=threading.Event(),
                delivery_callbacks=(lambda _row: True, lambda _row: True, None),
            )
        except WorkerPreflightError as exc:
            errors.append(exc.category)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert cycle_heartbeat_reached.wait(timeout=5)
    deleting = bl443_sessions()
    deleting.execute(sa.delete(MessagingWorkerHeartbeat).where(
        MessagingWorkerHeartbeat.worker_identity == settings.worker_identity
    ))
    deleting.commit()
    deleting.close()
    heartbeat_deleted.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == ["heartbeat_ownership_lost"]
    assert calls == ["bounded-cycle"]
    verify = bl443_sessions()
    assert verify.get(
        MessagingWorkerHeartbeat, settings.worker_identity
    ) is None
    verify.close()


def test_deleted_heartbeat_immediately_before_final_is_fatal_postgres(
    bl443_sessions, monkeypatch,
):
    import services.message_worker_runtime as runtime

    settings = replace(
        _runtime_settings("normal"),
        worker_identity="deleted-final-heartbeat",
    )
    final_heartbeat_reached = threading.Event()
    heartbeat_deleted = threading.Event()
    errors = []
    original_publish = runtime.publish_heartbeat
    publish_count = 0

    def coordinated_publish(*args, **kwargs):
        nonlocal publish_count
        publish_count += 1
        if publish_count == 3:
            final_heartbeat_reached.set()
            assert heartbeat_deleted.wait(timeout=5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(runtime, "publish_heartbeat", coordinated_publish)
    monkeypatch.setattr(runtime, "run_worker", lambda *_a, **_k: WorkerResult())

    def runner():
        try:
            run_continuous(
                settings,
                bl443_sessions,
                stop_event=threading.Event(),
                delivery_callbacks=(lambda _row: True, lambda _row: True, None),
                max_cycles=1,
            )
        except WorkerPreflightError as exc:
            errors.append(exc.category)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert final_heartbeat_reached.wait(timeout=5)
    deleting = bl443_sessions()
    deleting.execute(sa.delete(MessagingWorkerHeartbeat).where(
        MessagingWorkerHeartbeat.worker_identity == settings.worker_identity
    ))
    deleting.commit()
    deleting.close()
    heartbeat_deleted.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == ["heartbeat_ownership_lost"]
    verify = bl443_sessions()
    assert verify.get(
        MessagingWorkerHeartbeat, settings.worker_identity
    ) is None
    verify.close()


def test_replacement_before_claim_is_atomically_fenced_postgres(bl443_sessions):
    settings = replace(
        _runtime_settings("normal"),
        worker_identity="replacement-before-claim",
        stale_seconds=1,
    )
    started = datetime.utcnow()
    old = bl443_sessions()
    acquire_heartbeat(old, settings, started, "old-instance")
    _policy(old, "family.a")
    row = _enqueue(old, "fenced-before-claim")
    old.commit()
    row_id = row.id
    old.close()

    replacement = bl443_sessions()
    heartbeat = replacement.get(
        MessagingWorkerHeartbeat, settings.worker_identity, with_for_update=True
    )
    heartbeat.updated_at = datetime.utcnow() - timedelta(seconds=2)
    replacement.commit()
    acquire_heartbeat(
        replacement, settings, datetime.utcnow(), "replacement-instance"
    )
    replacement.close()
    provider_calls = []

    with pytest.raises(WorkerPreflightError, match="heartbeat_ownership_lost"):
        run_worker(
            bl443_sessions,
            owner=settings.worker_identity,
            safety_callback=lambda _row: True,
            provider_callback=lambda row: provider_calls.append(row.id),
            batch_size=1,
            max_batches=1,
            ownership_guard=lambda session, phase: verify_delivery_ownership(
                session, settings, "old-instance", phase
            ),
        )

    verify = bl443_sessions()
    fenced = verify.get(MessageOutbox, row_id)
    assert fenced.status == "pending"
    assert fenced.lease_token is None
    assert provider_calls == []
    verify.close()


def test_replacement_after_claim_before_provider_start_is_safe_postgres(
    bl443_sessions,
):
    settings = replace(
        _runtime_settings("normal"),
        worker_identity="replacement-before-provider",
        stale_seconds=1,
    )
    started = datetime.utcnow()
    seed = bl443_sessions()
    acquire_heartbeat(seed, settings, started, "old-instance")
    _policy(seed, "family.a")
    row = _enqueue(seed, "fenced-before-provider")
    seed.commit()
    row_id = row.id
    seed.close()
    provider_calls = []

    def coordinated_guard(session, phase):
        if phase == "before_provider_start":
            replacement = bl443_sessions()
            heartbeat = replacement.get(
                MessagingWorkerHeartbeat,
                settings.worker_identity,
                with_for_update=True,
            )
            heartbeat.updated_at = datetime.utcnow() - timedelta(seconds=2)
            replacement.commit()
            acquire_heartbeat(
                replacement,
                settings,
                datetime.utcnow(),
                "replacement-instance",
            )
            replacement.close()
        verify_delivery_ownership(session, settings, "old-instance", phase)

    with pytest.raises(WorkerPreflightError, match="heartbeat_ownership_lost"):
        run_worker(
            bl443_sessions,
            owner=settings.worker_identity,
            safety_callback=lambda _row: True,
            provider_callback=lambda row: provider_calls.append(row.id),
            batch_size=1,
            max_batches=1,
            ownership_guard=coordinated_guard,
        )

    verify = bl443_sessions()
    fenced = verify.get(MessageOutbox, row_id)
    assert fenced.status == "retryable"
    assert fenced.provider_phase == "not_started"
    assert fenced.lease_token is None
    assert fenced.attempt_count == 0
    assert provider_calls == []
    verify.close()
