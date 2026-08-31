"""Disposable-database coverage for the MountainPageView reconciliation."""

from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from models import FriendCooldown
from runtime_config import database_identity_hash
from test_import_reference_data_postgres import disposable_postgres


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl306_mpv_fk_reconcile.py"
)
SKI_DAY_MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl305_ski_day_foundation.py"
)


def _load_migration(path, module_name):
    spec = spec_from_file_location(module_name, path)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _base_metadata():
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("resort", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    return metadata


def _legacy_page_view_table(metadata):
    return sa.Table(
        "mountain_page_view",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resort_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("viewed_at", sa.DateTime(), nullable=False),
        sa.Column("session_key", sa.String(32), nullable=True),
    )


def _run_migration(engine, migration, operation):
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            operation()
        finally:
            migration.op = original_op


def _load_page_view_migration():
    return _load_migration(MIGRATION_PATH, "bl306_mpv_fk_reconcile")


def _load_ski_day_migration():
    return _load_migration(SKI_DAY_MIGRATION_PATH, "bl305_ski_day_foundation")


def test_model_declares_deployed_friend_cooldown_cascade():
    actions = {
        foreign_key.ondelete
        for column in (FriendCooldown.user_a_id, FriendCooldown.user_b_id)
        for foreign_key in column.foreign_keys
    }
    assert actions == {"CASCADE"}


def test_migration_creates_missing_page_view_table_with_expected_fks():
    migration = _load_page_view_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _base_metadata()

    with engine.begin() as connection:
        metadata.create_all(connection)

    _run_migration(engine, migration, migration.upgrade)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert "mountain_page_view" in inspector.get_table_names()
        assert {
            (fk["referred_table"], (fk["options"] or {}).get("ondelete"))
            for fk in inspector.get_foreign_keys("mountain_page_view")
        } == {("resort", "CASCADE"), ("user", "SET NULL")}


def test_migration_reconciles_valid_legacy_rows_and_preserves_set_null_semantics():
    migration = _load_page_view_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _base_metadata()
    page_views = _legacy_page_view_table(metadata)

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.Table("user", metadata).insert(), [{"id": 1}, {"id": 2}])
        connection.execute(sa.Table("resort", metadata).insert(), [{"id": 1}, {"id": 2}])
        connection.execute(
            page_views.insert(),
            [
                {
                    "id": 1,
                    "resort_id": 1,
                    "user_id": 1,
                    "viewed_at": datetime(2026, 5, 27, 15, 17, 47),
                    "session_key": None,
                },
                {
                    "id": 2,
                    "resort_id": 2,
                    "user_id": 2,
                    "viewed_at": datetime(2026, 5, 28, 4, 17, 1),
                    "session_key": None,
                },
            ],
        )

    _run_migration(engine, migration, migration.upgrade)

    with engine.begin() as connection:
        connection.execute(sa.text('DELETE FROM "user" WHERE id = 1'))
        remaining = connection.execute(
            sa.text(
                "SELECT id, user_id FROM mountain_page_view "
                "WHERE id IN (1, 2) ORDER BY id"
            )
        ).all()
        assert remaining == [(1, None), (2, 2)]

        connection.execute(sa.text("DELETE FROM resort WHERE id = 2"))
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM mountain_page_view WHERE id = 2")
        ).scalar_one() == 0


def test_migration_aborts_with_diagnostics_and_does_not_change_orphan_rows():
    migration = _load_page_view_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _base_metadata()
    page_views = _legacy_page_view_table(metadata)

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.Table("user", metadata).insert(), [{"id": 1}])
        connection.execute(sa.Table("resort", metadata).insert(), [{"id": 1}])
        connection.execute(
            page_views.insert(),
            [
                {
                    "id": 1,
                    "resort_id": 999,
                    "user_id": 1,
                    "viewed_at": datetime(2026, 5, 27, 15, 17, 47),
                    "session_key": None,
                },
                {
                    "id": 2,
                    "resort_id": 1,
                    "user_id": 888,
                    "viewed_at": datetime(2026, 5, 28, 4, 17, 1),
                    "session_key": None,
                },
            ],
        )

    with pytest.raises(RuntimeError, match=r"orphan_id.*999"):
        _run_migration(engine, migration, migration.upgrade)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert inspector.get_foreign_keys("mountain_page_view") == []
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM mountain_page_view")
        ).scalar_one() == 2


def test_full_chain_upgrades_from_bl60_shape_in_order():
    ski_day_migration = _load_ski_day_migration()
    page_view_migration = _load_page_view_migration()
    assert ski_day_migration.down_revision == "bl60_mtn_filter_edu"
    assert ski_day_migration.revision == "bl305_ski_day_foundation"
    assert page_view_migration.down_revision == ski_day_migration.revision

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _base_metadata()
    sa.Table("ski_trip", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    page_views = _legacy_page_view_table(metadata)

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(sa.Table("user", metadata).insert(), [{"id": 1}])
        connection.execute(sa.Table("resort", metadata).insert(), [{"id": 1}])
        connection.execute(
            page_views.insert(),
            {
                "id": 1,
                "resort_id": 1,
                "user_id": 1,
                "viewed_at": datetime(2026, 5, 27, 15, 17, 47),
                "session_key": None,
            },
        )

    _run_migration(engine, ski_day_migration, ski_day_migration.upgrade)
    _run_migration(engine, page_view_migration, page_view_migration.upgrade)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert {"ski_day", "mountain_page_view"} <= set(inspector.get_table_names())
        assert {
            (fk["referred_table"], (fk["options"] or {}).get("ondelete"))
            for fk in inspector.get_foreign_keys("ski_day")
        } == {
            ("user", "CASCADE"),
            ("resort", "RESTRICT"),
            ("ski_trip", "SET NULL"),
        }
        assert {
            (fk["referred_table"], (fk["options"] or {}).get("ondelete"))
            for fk in inspector.get_foreign_keys("mountain_page_view")
        } == {("resort", "CASCADE"), ("user", "SET NULL")}


def test_alembic_upgrade_traverses_from_bl60_to_bl306_on_isolated_postgres(
    disposable_postgres, monkeypatch
):
    database_url = disposable_postgres("mpv-migration-chain")
    engine = sa.create_engine(database_url)
    metadata = _base_metadata()
    sa.Table("ski_trip", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    _legacy_page_view_table(metadata)

    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(
                sa.text(
                    "CREATE TABLE alembic_version "
                    "(version_num VARCHAR(32) NOT NULL)"
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO alembic_version (version_num) "
                    "VALUES ('bl60_mtn_filter_edu')"
                )
            )

        monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "test")
        monkeypatch.setenv("BASELODGE_MIGRATION_MODE", "1")
        monkeypatch.setenv("BASELODGE_MIGRATION_TARGET", "replit")
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv(
            "BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH",
            database_identity_hash(database_url),
        )
        monkeypatch.setenv(
            "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", "0" * 64
        )
        alembic_config = Config(
            str(MIGRATION_PATH.parents[1] / "alembic.ini")
        )
        alembic_config.set_main_option(
            "script_location", str(MIGRATION_PATH.parents[1])
        )
        command.upgrade(alembic_config, "bl306_mpv_fk_reconcile")

        with engine.connect() as connection:
            assert connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "bl306_mpv_fk_reconcile"
            assert {"ski_day", "mountain_page_view"} <= set(
                sa.inspect(connection).get_table_names()
            )
    finally:
        engine.dispose()


def test_migration_downgrade_fails_closed_without_removing_schema():
    migration = _load_page_view_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _base_metadata()

    with engine.begin() as connection:
        metadata.create_all(connection)

    _run_migration(engine, migration, migration.upgrade)
    with pytest.raises(RuntimeError, match="no automatic downgrade"):
        _run_migration(engine, migration, migration.downgrade)

    with engine.connect() as connection:
        assert {
            (fk["referred_table"], (fk["options"] or {}).get("ondelete"))
            for fk in sa.inspect(connection).get_foreign_keys("mountain_page_view")
        } == {("resort", "CASCADE"), ("user", "SET NULL")}