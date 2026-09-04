"""Disposable upgrade/downgrade coverage for the messaging outbox."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl440_message_outbox.py"
)


def _migration():
    spec = spec_from_file_location("bl440_message_outbox", PATH)
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
        "message_event_log",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(connection)


def test_upgrade_creates_bounded_outbox_and_downgrade_removes_it():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base(connection)
        _run(connection, migration, migration.upgrade)
        inspector = sa.inspect(connection)
        assert "message_outbox" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns(
            "message_outbox"
        )}
        assert {
            "occurrence_id", "context_json", "evidence_ids_json", "lease_token",
            "provider_phase", "final_event_log_id", "replay_of_outbox_id",
        } <= columns
        assert "uq_outbox_logical_delivery" in {
            item["name"] for item in inspector.get_unique_constraints(
                "message_outbox"
            )
        }
        foreign_keys = {
            item["constrained_columns"][0]: item
            for item in inspector.get_foreign_keys("message_outbox")
        }
        assert foreign_keys["actor_user_id"]["options"].get("ondelete") == "SET NULL"
        assert foreign_keys["recipient_user_id"]["options"].get("ondelete") == "SET NULL"
        assert next(
            column for column in inspector.get_columns("message_outbox")
            if column["name"] == "recipient_user_id"
        )["nullable"]

        _run(connection, migration, migration.downgrade)
        assert "message_outbox" not in sa.inspect(connection).get_table_names()


def test_revision_identifier_is_bounded_and_follows_send_safety():
    migration = _migration()
    assert len(migration.revision) <= 32
    assert migration.down_revision == "bl147_send_safety"