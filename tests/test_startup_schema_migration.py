"""Disposable schema coverage for the post-BL-306 startup-schema revision."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl317_startup_schema.py"
)


def _load_migration():
    spec = spec_from_file_location("bl317_startup_schema", MIGRATION_PATH)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _legacy_metadata():
    metadata = sa.MetaData()
    user = sa.Table(
        "user",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    ski_trip = sa.Table(
        "ski_trip",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pass_type", sa.String(50)),
        sa.Column("end_date", sa.Date()),
    )
    sa.Table(
        "equipment_setup",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slot", sa.String(20)),
    )
    sa.Table(
        "push_device_token",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "message_event_log",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_name", sa.String(120), nullable=False),
        sa.Column("recipient_user_id", sa.Integer()),
        sa.Column("object_type", sa.String(80)),
        sa.Column("object_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivery_status", sa.String(40), nullable=False),
    )
    sa.Table(
        "ski_trip_participant",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.ForeignKey(ski_trip.c.id)),
        sa.Column("user_id", sa.ForeignKey(user.c.id)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
    )
    sa.Table(
        "activity",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipient_user_id", sa.Integer()),
        sa.Column("type", sa.String(80)),
        sa.Column("created_at", sa.DateTime()),
    )
    sa.Table(
        "invitation",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receiver_id", sa.Integer()),
        sa.Column("status", sa.String(30)),
        sa.Column("trip_id", sa.Integer()),
    )
    return metadata


def _run_upgrade(engine, migration):
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op


def test_revision_is_linear_after_bl306():
    migration = _load_migration()
    assert migration.down_revision == "bl306_mpv_fk_reconcile"
    assert migration.revision == "bl317_startup_schema"


def test_upgrade_owns_legacy_startup_schema_without_data_backfills():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _legacy_metadata()
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            metadata.tables["equipment_setup"].insert(),
            {"id": 1, "slot": "primary"},
        )
        connection.execute(
            metadata.tables["push_device_token"].insert(),
            {"id": 3, "active": True},
        )

    _run_upgrade(engine, migration)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert {
            "trip_invite_token",
            "app_store_metric",
            "invite_share_event",
            "ski_trip_planning_post",
        } <= set(inspector.get_table_names())
        assert {
            "is_primary",
            "label",
            "created_at",
            "binding_brand",
            "binding_model",
        } <= {
            column["name"]
            for column in inspector.get_columns("equipment_setup")
        }
        assert "apns_environment" in {
            column["name"]
            for column in inspector.get_columns("push_device_token")
        }
        assert {"created_in_batch_id", "updated_at", "notes"} <= {
            column["name"] for column in inspector.get_columns("ski_trip")
        }
        assert "push_notifications_enabled" in {
            column["name"] for column in inspector.get_columns("user")
        }
        assert {"parent_mel_id", "retry_locked_at"} <= {
            column["name"]
            for column in inspector.get_columns("message_event_log")
        }
        assert "pass_type" in {
            column["name"]
            for column in inspector.get_columns("ski_trip_participant")
        }

        equipment_row = connection.execute(
            sa.text(
                "SELECT is_primary, created_at FROM equipment_setup WHERE id=1"
            )
        ).one()
        token_row = connection.execute(
            sa.text(
                "SELECT active, apns_environment "
                "FROM push_device_token WHERE id=3"
            )
        ).one()
        assert equipment_row == (False, None)
        assert token_row == (True, "unknown")


def test_upgrade_is_idempotent_when_legacy_schema_already_exists():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = _legacy_metadata()
    with engine.begin() as connection:
        metadata.create_all(connection)

    _run_upgrade(engine, migration)
    _run_upgrade(engine, migration)

    with engine.connect() as connection:
        assert "bl317_startup_schema" not in sa.inspect(connection).get_table_names()


def test_downgrade_fails_closed():
    migration = _load_migration()
    with pytest.raises(RuntimeError, match="no automatic downgrade"):
        migration.downgrade()