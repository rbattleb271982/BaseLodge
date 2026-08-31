"""Schema and ancestry coverage for BL-87 wishlist history."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError


PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl87_wishlist_history.py"
)


def _migration():
    spec = spec_from_file_location("bl87_wishlist_history", PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base(connection):
    metadata = sa.MetaData()
    sa.Table(
        "user",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wish_list_resorts", sa.JSON(), nullable=True),
    )
    sa.Table(
        "resort",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(connection)


def _run(connection, migration, operation):
    original = migration.op
    migration.op = Operations(MigrationContext.configure(connection))
    try:
        operation()
    finally:
        migration.op = original


def test_revision_is_linear_single_head_and_within_identifier_limit():
    migration = _migration()
    script = ScriptDirectory.from_config(
        Config(str(Path(__file__).parents[1] / "migrations" / "alembic.ini"))
    )
    assert migration.revision == "bl87_wishlist_history"
    assert migration.down_revision == "bl80_trip_lifecycle"
    assert len(migration.revision) <= 32
    assert script.get_revision("bl70_user_season_pass").down_revision == migration.revision
    assert [revision.revision for revision in script.get_revisions("heads")] == [
        "bl70_user_season_pass"
    ]


def test_upgrade_creates_empty_bounded_schema_without_rewriting_current_state():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        _base(connection)
        connection.execute(sa.text(
            'INSERT INTO "user" (id, wish_list_resorts) VALUES (1, \'[10]\')'
        ))
        connection.execute(sa.text("INSERT INTO resort (id) VALUES (10)"))
        _run(connection, migration, migration.upgrade)

        assert connection.execute(sa.text(
            "SELECT count(*) FROM wishlist_resort_event"
        )).scalar_one() == 0
        assert connection.execute(sa.text(
            'SELECT wish_list_resorts FROM "user" WHERE id=1'
        )).scalar_one() == "[10]"
        inspector = sa.inspect(connection)
        assert {index["name"] for index in inspector.get_indexes(
            "wishlist_resort_event"
        )} == {
            "ix_wre_user_occurred_at",
            "ix_wre_user_resort_occurred_at",
        }
        foreign_keys = {
            fk["name"]: fk["options"]["ondelete"]
            for fk in inspector.get_foreign_keys("wishlist_resort_event")
        }
        assert foreign_keys == {
            "fk_wre_user_id": "CASCADE",
            "fk_wre_resort_id": "CASCADE",
            "fk_wre_actor_user_id": "SET NULL",
        }
        with pytest.raises(IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO wishlist_resort_event "
                "(user_id,resort_id,event_type,source) "
                "VALUES (1,10,'invalid','settings')"
            ))


def test_empty_downgrade_succeeds_and_nonempty_downgrade_refuses():
    migration = _migration()
    empty = sa.create_engine("sqlite:///:memory:")
    with empty.begin() as connection:
        _base(connection)
        _run(connection, migration, migration.upgrade)
        _run(connection, migration, migration.downgrade)
        assert "wishlist_resort_event" not in sa.inspect(connection).get_table_names()

    retained = sa.create_engine("sqlite:///:memory:")
    with retained.begin() as connection:
        _base(connection)
        connection.execute(sa.text('INSERT INTO "user" (id) VALUES (1)'))
        connection.execute(sa.text("INSERT INTO resort (id) VALUES (1)"))
        _run(connection, migration, migration.upgrade)
        connection.execute(sa.text(
            "INSERT INTO wishlist_resort_event "
            "(user_id,resort_id,event_type,source) "
            "VALUES (1,1,'added','settings')"
        ))
        with pytest.raises(RuntimeError, match="Refusing BL-87"):
            _run(connection, migration, migration.downgrade)
        assert "wishlist_resort_event" in sa.inspect(connection).get_table_names()


def test_database_foreign_keys_cascade_subject_and_resort_and_null_actor():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        _base(connection)
        connection.execute(sa.text(
            'INSERT INTO "user" (id) VALUES (1), (2)'
        ))
        connection.execute(sa.text(
            "INSERT INTO resort (id) VALUES (10), (20)"
        ))
        _run(connection, migration, migration.upgrade)
        connection.execute(sa.text(
            "INSERT INTO wishlist_resort_event "
            "(user_id,resort_id,actor_user_id,event_type,source) VALUES "
            "(1,10,2,'added','settings'),"
            "(1,20,1,'added','settings'),"
            "(2,20,1,'added','mountain_detail')"
        ))

        connection.execute(sa.text('DELETE FROM "user" WHERE id=1'))
        surviving = connection.execute(sa.text(
            "SELECT user_id,resort_id,actor_user_id "
            "FROM wishlist_resort_event"
        )).one()
        assert surviving == (2, 20, None)

        connection.execute(sa.text("DELETE FROM resort WHERE id=20"))
        assert connection.execute(sa.text(
            "SELECT count(*) FROM wishlist_resort_event"
        )).scalar_one() == 0