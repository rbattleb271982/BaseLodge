"""Disposable schema coverage for the BL-80 lifecycle migration."""

from importlib.util import module_from_spec, spec_from_file_location
import os
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
    / "bl80_trip_lifecycle.py"
)


def _migration():
    spec = spec_from_file_location("bl80_trip_lifecycle", PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(connection):
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table(
        "ski_trip",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
    )
    metadata.create_all(connection)


def _run_upgrade(connection, migration):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        migration.upgrade()
    finally:
        migration.op = original


def test_upgrade_is_nullable_no_backfill_and_has_bounded_history_schema():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base(connection)
        connection.execute(sa.text(
            'INSERT INTO ski_trip (id, user_id) VALUES (1, 1)'
        ))
        _run_upgrade(connection, migration)
        row = connection.execute(sa.text(
            "SELECT lifecycle_state, terminal_at FROM ski_trip WHERE id = 1"
        )).one()
        assert row == (None, None)

        inspector = sa.inspect(connection)
        assert {index["name"] for index in inspector.get_indexes(
            "ski_trip_lifecycle_event"
        )} == {
            "ix_stle_trip_occurred_at",
            "ix_stle_actor_occurred_at",
        }
        with pytest.raises(IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO ski_trip_lifecycle_event "
                "(trip_id, event_type, source) VALUES (1, 'invalid', 'invalid')"
            ))


def test_guarded_downgrade_refuses_terminal_data():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base(connection)
        _run_upgrade(connection, migration)
        connection.execute(sa.text(
            "INSERT INTO ski_trip (id, user_id, lifecycle_state) "
            "VALUES (1, 1, 'completed')"
        ))
        original = migration.op
        migration.op = Operations(MigrationContext.configure(connection))
        try:
            with pytest.raises(RuntimeError, match="Refusing BL-80"):
                migration.downgrade()
        finally:
            migration.op = original


def test_upgrade_runs_on_disposable_postgres():
    database_url = os.environ.get("BL80_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BL80_TEST_POSTGRES_URL is required for PostgreSQL DDL coverage")

    migration = _migration()
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(
                "DROP TABLE IF EXISTS ski_trip_lifecycle_event CASCADE"
            ))
            connection.execute(sa.text("DROP TABLE IF EXISTS ski_trip CASCADE"))
            connection.execute(sa.text('DROP TABLE IF EXISTS \"user\" CASCADE'))
            _base(connection)
            connection.execute(sa.text(
                'INSERT INTO "user" (id) VALUES (1)'
            ))
            connection.execute(sa.text(
                "INSERT INTO ski_trip (id, user_id) VALUES (1, 1)"
            ))
            _run_upgrade(connection, migration)

            row = connection.execute(sa.text(
                "SELECT lifecycle_state, terminal_at FROM ski_trip WHERE id = 1"
            )).one()
            assert row == (None, None)
            assert {
                index["name"]
                for index in sa.inspect(connection).get_indexes(
                    "ski_trip_lifecycle_event"
                )
            } == {
                "ix_stle_trip_occurred_at",
                "ix_stle_actor_occurred_at",
            }
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text(
                "DROP TABLE IF EXISTS ski_trip_lifecycle_event CASCADE"
            ))
            connection.execute(sa.text("DROP TABLE IF EXISTS ski_trip CASCADE"))
            connection.execute(sa.text('DROP TABLE IF EXISTS \"user\" CASCADE'))
        engine.dispose()