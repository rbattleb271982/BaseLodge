"""Disposable schema coverage for BL-79 connection history."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = Path(__file__).parents[1] / "migrations" / "versions" / "bl79_friend_history.py"


def _load_migration():
    spec = spec_from_file_location("bl79_friend_history", MIGRATION_PATH)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _base_metadata():
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    return metadata


def _operations(connection):
    return Operations(MigrationContext.configure(connection))


def _upgrade(migration):
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


def test_revision_reparents_bl70_and_is_the_sole_head():
    migration = _load_migration()
    script = ScriptDirectory.from_config(
        Config(str(Path(__file__).parents[1] / "migrations" / "alembic.ini"))
    )
    bl80 = script.get_revision("bl80_trip_lifecycle")
    bl70 = script.get_revision("bl70_user_season_pass")

    assert migration.revision == "bl79_friend_history"
    assert migration.down_revision == "bl78_rsvp_transition"
    assert migration.branch_labels is None
    assert len(migration.revision) <= 32
    assert bl80.down_revision == migration.revision
    bl87 = script.get_revision("bl87_wishlist_history")
    assert bl87.down_revision == bl80.revision
    assert bl70.down_revision == bl87.revision
    assert script.get_heads() == ["bl70_user_season_pass"]


def test_upgrade_creates_exact_history_schema_checks_foreign_keys_and_index():
    engine = _upgrade(_load_migration())
    inspector = sa.inspect(engine)

    assert set(inspector.get_table_names()) == {"friend_connection_event", "user"}
    assert {column["name"] for column in inspector.get_columns("friend_connection_event")} == {
        "id", "user_a_id", "user_b_id", "event_type", "occurred_at",
        "actor_user_id", "source",
    }
    assert {index["name"] for index in inspector.get_indexes("friend_connection_event")} == {
        "ix_fce_pair_occurred_at"
    }
    assert {check["name"] for check in inspector.get_check_constraints(
        "friend_connection_event"
    )} == {"ck_fce_canonical_pair", "ck_fce_event_type", "ck_fce_source"}
    foreign_keys = {
        key["name"]: key for key in inspector.get_foreign_keys("friend_connection_event")
    }
    assert foreign_keys["fk_fce_user_a_id"]["options"]["ondelete"] == "CASCADE"
    assert foreign_keys["fk_fce_user_b_id"]["options"]["ondelete"] == "CASCADE"
    assert foreign_keys["fk_fce_actor_user_id"]["options"]["ondelete"] == "SET NULL"


def test_upgrade_backfills_nothing_and_rejects_invalid_canonical_event_and_source():
    engine = _upgrade(_load_migration())
    history = sa.Table("friend_connection_event", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(history)).scalar_one() == 0
        connection.execute(sa.text('INSERT INTO "user" (id) VALUES (1), (2)'))
        valid = {
            "user_a_id": 1, "user_b_id": 2, "event_type": "formed",
            "actor_user_id": 1, "source": "qr_connect",
        }
        connection.execute(history.insert(), valid)
        for invalid in (
            {**valid, "user_a_id": 2, "user_b_id": 1},
            {**valid, "event_type": "invalid"},
            {**valid, "source": "invalid"},
        ):
            with pytest.raises(IntegrityError):
                connection.execute(history.insert(), invalid)


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
    assert set(sa.inspect(engine).get_table_names()) == {"user"}