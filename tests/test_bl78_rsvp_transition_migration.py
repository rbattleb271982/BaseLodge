"""Disposable schema coverage for the BL-78 RSVP history branch."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl78_rsvp_transition.py"
)


def _load_migration():
    spec = spec_from_file_location("bl78_rsvp_transition", MIGRATION_PATH)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _operations(connection):
    return Operations(MigrationContext.configure(connection))


def _base_metadata():
    metadata = sa.MetaData()
    sa.Table(
        "user",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    sa.Table(
        "ski_trip",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    return metadata


def _upgrade_on_sqlite(migration):
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base_metadata().create_all(connection)
        original_op = migration.op
        migration.op = _operations(connection)
        try:
            migration.upgrade()
        finally:
            migration.op = original_op
    return engine


def test_revision_precedes_deferred_bl70_in_single_linear_graph():
    migration = _load_migration()
    config = Config(str(Path(__file__).parents[1] / "migrations" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    bl79 = script.get_revision("bl79_friend_history")
    bl80 = script.get_revision("bl80_trip_lifecycle")
    deferred_bl70 = script.get_revision("bl70_user_season_pass")

    assert migration.revision == "bl78_rsvp_transition"
    assert migration.down_revision == "bl52_trip_stay"
    assert migration.branch_labels is None
    assert len(migration.revision) <= 32
    assert bl79.down_revision == "bl78_rsvp_transition"
    assert bl80.down_revision == "bl79_friend_history"
    assert deferred_bl70.down_revision == "bl80_trip_lifecycle"
    assert script.get_heads() == ["bl70_user_season_pass"]


def test_upgrade_creates_only_history_schema_with_constraints_indexes_and_fks():
    migration = _load_migration()
    engine = _upgrade_on_sqlite(migration)
    inspector = sa.inspect(engine)

    assert "ski_trip_rsvp_transition" in inspector.get_table_names()
    assert "user_season_pass" not in inspector.get_table_names()
    assert {
        "id",
        "trip_id",
        "user_id",
        "previous_status",
        "new_status",
        "changed_at",
        "actor_user_id",
        "source",
    } == {
        column["name"]
        for column in inspector.get_columns("ski_trip_rsvp_transition")
    }
    assert {
        index["name"]
        for index in inspector.get_indexes("ski_trip_rsvp_transition")
    } == {
        "ix_strt_trip_changed_at",
        "ix_strt_user_changed_at",
    }
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "ski_trip_rsvp_transition"
        )
    } == {
        "ck_strt_initial_source",
        "ck_strt_new_status",
        "ck_strt_previous_status",
        "ck_strt_source",
        "ck_strt_status_changed",
    }
    foreign_keys = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys(
            "ski_trip_rsvp_transition"
        )
    }
    assert foreign_keys["fk_strt_trip_id"]["options"]["ondelete"] == "CASCADE"
    assert foreign_keys["fk_strt_user_id"]["options"]["ondelete"] == "CASCADE"
    assert (
        foreign_keys["fk_strt_actor_user_id"]["options"]["ondelete"]
        == "SET NULL"
    )


def test_upgrade_writes_no_history_and_constraints_reject_legacy_status():
    migration = _load_migration()
    engine = _upgrade_on_sqlite(migration)
    history = sa.Table(
        "ski_trip_rsvp_transition",
        sa.MetaData(),
        autoload_with=engine,
    )

    with engine.begin() as connection:
        assert connection.execute(
            sa.select(sa.func.count()).select_from(history)
        ).scalar_one() == 0
        connection.execute(sa.text('INSERT INTO "user" (id) VALUES (1), (2)'))
        connection.execute(sa.text("INSERT INTO ski_trip (id) VALUES (1)"))
        connection.execute(history.insert(), {
            "trip_id": 1,
            "user_id": 2,
            "previous_status": None,
            "new_status": "going",
            "actor_user_id": 2,
            "source": "token_response",
        })
        with pytest.raises(IntegrityError):
            connection.execute(history.insert(), {
                "trip_id": 1,
                "user_id": 2,
                "previous_status": "invited",
                "new_status": "accepted",
                "actor_user_id": 1,
                "source": "organizer_rsvp",
            })


def test_upgrade_then_downgrade_removes_only_history_table():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _base_metadata().create_all(connection)
        original_op = migration.op
        migration.op = _operations(connection)
        try:
            migration.upgrade()
            migration.downgrade()
        finally:
            migration.op = original_op

    assert set(sa.inspect(engine).get_table_names()) == {"ski_trip", "user"}