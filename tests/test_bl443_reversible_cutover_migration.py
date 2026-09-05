"""Disposable SQLite upgrade/downgrade coverage for bl443."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


ROOT = Path(__file__).parents[1] / "migrations" / "versions"


def _load(name):
    spec = spec_from_file_location(name, ROOT / f"{name}.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, migration, operation):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        operation()
    finally:
        migration.op = original


def _base(connection):
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table(
        "message_event_log", metadata, sa.Column("id", sa.Integer(), primary_key=True)
    )
    metadata.create_all(connection)


def test_upgrade_seeds_inline_paused_and_safe_downgrade_restores_bl440():
    engine = sa.create_engine("sqlite:///:memory:")
    bl440 = _load("bl440_message_outbox")
    bl443 = _load("bl443_reversible_cutover")
    with engine.begin() as connection:
        _base(connection)
        _run(connection, bl440, bl440.upgrade)
        connection.execute(sa.text(
            "INSERT INTO message_outbox "
            "(event_name,category,occurrence_id,channel,provider,context_json,"
            "evidence_ids_json,status,attempt_count,max_attempts,next_attempt_at,"
            "provider_phase,created_at,updated_at) VALUES "
            "('legacy.event','test','legacy','push','test','{}','[]','pending',"
            "0,5,CURRENT_TIMESTAMP,'not_started',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
        ))
        _run(connection, bl443, bl443.upgrade)
        policy = connection.execute(sa.text(
            "SELECT delivery_mode, claims_paused, cutover_epoch "
            "FROM messaging_delivery_policy WHERE event_name='legacy.event'"
        )).one()
        assert tuple(policy) == ("inline", 1, 1)
        statuses = next(
            constraint["sqltext"]
            for constraint in sa.inspect(connection).get_check_constraints(
                "message_outbox"
            )
            if constraint["name"] == "ck_outbox_status"
        )
        assert "operator_terminalized" in statuses
        _run(connection, bl443, bl443.downgrade)
        columns = {
            item["name"] for item in sa.inspect(connection).get_columns("message_outbox")
        }
        assert "configuration_epoch" not in columns
        assert "messaging_delivery_policy" not in sa.inspect(connection).get_table_names()


def test_downgrade_refuses_operational_history():
    engine = sa.create_engine("sqlite:///:memory:")
    bl440 = _load("bl440_message_outbox")
    bl443 = _load("bl443_reversible_cutover")
    with engine.begin() as connection:
        _base(connection)
        _run(connection, bl440, bl440.upgrade)
        _run(connection, bl443, bl443.upgrade)
        connection.execute(sa.text(
            "UPDATE messaging_delivery_policy_event SET action='pause_changed' "
            "WHERE id=(SELECT MIN(id) FROM messaging_delivery_policy_event)"
        ))
        try:
            _run(connection, bl443, bl443.downgrade)
        except RuntimeError as exc:
            assert "operational cutover evidence" in str(exc)
        else:
            raise AssertionError("unsafe downgrade was accepted")
