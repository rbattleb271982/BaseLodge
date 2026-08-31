"""Schema coverage for the season-specific user pass revision."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl70_user_season_pass.py"
)


def _load_migration():
    spec = spec_from_file_location("bl70_user_season_pass", MIGRATION_PATH)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _operations(connection):
    return Operations(MigrationContext.configure(connection))


def test_revision_is_linear_and_within_version_identifier_limit():
    migration = _load_migration()
    assert migration.revision == "bl70_user_season_pass"
    assert migration.down_revision == "bl52_trip_stay"
    assert len(migration.revision) <= 32


def test_upgrade_creates_constraints_index_and_cascade():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "user",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        original_op = migration.op
        migration.op = _operations(connection)
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

    inspector = sa.inspect(engine)
    assert "user_season_pass" in inspector.get_table_names()
    assert {
        "id",
        "user_id",
        "season_start_year",
        "pass_type",
        "created_at",
        "updated_at",
    } == {
        column["name"]
        for column in inspector.get_columns("user_season_pass")
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("user_season_pass")
    } == {"uq_user_season_pass_user_season"}
    assert {
        index["name"] for index in inspector.get_indexes("user_season_pass")
    } == {"ix_user_season_pass_season_pass"}
    foreign_key = inspector.get_foreign_keys("user_season_pass")[0]
    assert foreign_key["referred_table"] == "user"
    assert foreign_key["options"]["ondelete"] == "CASCADE"

    table = sa.Table("user_season_pass", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(sa.text('INSERT INTO "user" (id) VALUES (1)'))
        connection.execute(
            table.insert(),
            {
                "user_id": 1,
                "season_start_year": 2026,
                "pass_type": "epic",
            },
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                table.insert(),
                {
                    "user_id": 1,
                    "season_start_year": 2026,
                    "pass_type": "ikon",
                },
            )


def test_upgrade_then_downgrade_removes_only_season_pass_table():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "user",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    with engine.begin() as connection:
        metadata.create_all(connection)
        original_op = migration.op
        migration.op = _operations(connection)
        try:
            migration.upgrade()
            migration.downgrade()
        finally:
            migration.op = original_op

    assert sa.inspect(engine).get_table_names() == ["user"]