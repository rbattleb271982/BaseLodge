"""Disposable schema coverage for the BL-147 send-safety migration."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError


PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl147_send_safety.py"
)


def _migration():
    spec = spec_from_file_location("bl147_send_safety", PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(connection):
    metadata = sa.MetaData()
    sa.Table(
        "message_event_log",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
    )
    metadata.create_all(connection)


def _run(connection, migration, operation):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        operation()
    finally:
        migration.op = original


def test_upgrade_preserves_rows_and_enforces_occurrence_uniqueness():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base(connection)
        connection.execute(sa.text(
            "INSERT INTO message_event_log "
            "(id, recipient_user_id, channel, provider) "
            "VALUES (1, 10, 'push', 'onesignal')"
        ))
        _run(connection, migration, migration.upgrade)

        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("message_event_log")
        }
        constraints = {
            constraint["name"]
            for constraint in sa.inspect(connection).get_unique_constraints(
                "message_event_log"
            )
        }
        assert "occurrence_id" in columns
        assert "uq_mel_logical_occurrence" in constraints
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM message_event_log"
        )).scalar_one() == 1

        connection.execute(sa.text(
            "INSERT INTO message_event_log "
            "(recipient_user_id, channel, provider, occurrence_id) "
            "VALUES (10, 'push', 'onesignal', 'event:1')"
        ))
        with connection.begin_nested():
            with pytest.raises(IntegrityError):
                connection.execute(sa.text(
                    "INSERT INTO message_event_log "
                    "(recipient_user_id, channel, provider, occurrence_id) "
                    "VALUES (10, 'push', 'onesignal', 'event:1')"
                ))

        connection.execute(sa.text(
            "INSERT INTO message_event_log "
            "(recipient_user_id, channel, provider, occurrence_id) "
            "VALUES (11, 'push', 'onesignal', 'event:1')"
        ))


def test_downgrade_removes_occurrence_column_without_losing_legacy_rows():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base(connection)
        connection.execute(sa.text(
            "INSERT INTO message_event_log "
            "(id, recipient_user_id, channel, provider) "
            "VALUES (1, 10, 'push', 'onesignal')"
        ))
        _run(connection, migration, migration.upgrade)
        _run(connection, migration, migration.downgrade)

        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("message_event_log")
        }
        assert "occurrence_id" not in columns
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM message_event_log"
        )).scalar_one() == 1