"""Move legacy startup-owned schema into Alembic.

Revision ID: bl317_startup_schema
Revises: bl306_mpv_fk_reconcile
Create Date: 2026-08-21

This revision is deliberately additive and idempotent because existing
databases may already contain some or all of the objects from legacy
application-startup DDL. Historical data corrections remain explicit
maintenance operations and are not performed here.
"""

from alembic import op
import sqlalchemy as sa


revision = "bl317_startup_schema"
down_revision = "bl306_mpv_fk_reconcile"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return _inspector().has_table(table_name)


def _column_names(table_name):
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _index_names(table_name):
    if not _has_table(table_name):
        return set()
    return {index["name"] for index in _inspector().get_indexes(table_name)}


def _add_column_if_missing(table_name, column):
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(name, table_name, columns, **kwargs):
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, **kwargs)


def _require_table(table_name):
    if not _has_table(table_name):
        raise RuntimeError(
            f"Required table {table_name!r} is missing before {revision}; "
            "apply the earlier Alembic history instead of relying on app startup."
        )


def upgrade():
    for table_name in (
        "equipment_setup",
        "push_device_token",
        "ski_trip",
        "user",
        "message_event_log",
        "ski_trip_participant",
        "activity",
        "invitation",
    ):
        _require_table(table_name)

    _add_column_if_missing(
        "equipment_setup",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column_if_missing(
        "equipment_setup", sa.Column("label", sa.String(length=100), nullable=True)
    )
    _add_column_if_missing(
        "equipment_setup", sa.Column("created_at", sa.DateTime(), nullable=True)
    )
    _add_column_if_missing(
        "equipment_setup",
        sa.Column("binding_brand", sa.String(length=100), nullable=True),
    )
    _add_column_if_missing(
        "equipment_setup",
        sa.Column("binding_model", sa.String(length=100), nullable=True),
    )

    _add_column_if_missing(
        "push_device_token",
        sa.Column(
            "apns_environment",
            sa.String(length=20),
            nullable=False,
            server_default="unknown",
        ),
    )
    _add_column_if_missing(
        "ski_trip",
        sa.Column("created_in_batch_id", sa.String(length=36), nullable=True),
    )
    _add_column_if_missing(
        "ski_trip", sa.Column("updated_at", sa.DateTime(), nullable=True)
    )
    _add_column_if_missing("ski_trip", sa.Column("notes", sa.Text(), nullable=True))
    _add_column_if_missing(
        "user",
        sa.Column(
            "push_notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    _add_column_if_missing(
        "message_event_log",
        sa.Column("parent_mel_id", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "message_event_log",
        sa.Column("retry_locked_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "ski_trip_participant",
        sa.Column("pass_type", sa.String(length=100), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        parent_fk_exists = any(
            set(foreign_key.get("constrained_columns") or []) == {"parent_mel_id"}
            for foreign_key in _inspector().get_foreign_keys("message_event_log")
        )
        if not parent_fk_exists:
            op.create_foreign_key(
                "fk_message_event_log_parent_mel",
                "message_event_log",
                "message_event_log",
                ["parent_mel_id"],
                ["id"],
            )
        op.execute(
            "ALTER TABLE ski_trip ALTER COLUMN pass_type TYPE VARCHAR(100)"
        )
        for label in ("pending", "interested", "going", "removed"):
            op.execute(
                "ALTER TYPE ski_trip_participant_status_enum "
                f"ADD VALUE IF NOT EXISTS '{label}'"
            )

    if not _has_table("trip_invite_token"):
        op.create_table(
            "trip_invite_token",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=64), nullable=False),
            sa.Column("trip_id", sa.Integer(), nullable=False),
            sa.Column("inviter_user_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.now(),
            ),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.ForeignKeyConstraint(
                ["trip_id"], ["ski_trip.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["inviter_user_id"], ["user.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )

    if not _has_table("app_store_metric"):
        op.create_table(
            "app_store_metric",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("platform", sa.String(length=16), nullable=False),
            sa.Column("report_date", sa.Date(), nullable=False),
            sa.Column("downloads", sa.Integer(), nullable=True),
            sa.Column("page_views", sa.Integer(), nullable=True),
            sa.Column("conversion_pct", sa.Float(), nullable=True),
            sa.Column("rating", sa.Float(), nullable=True),
            sa.Column("review_count", sa.Integer(), nullable=True),
            sa.Column("crashes", sa.Float(), nullable=True),
            sa.Column("anrs", sa.Float(), nullable=True),
            sa.Column(
                "fetched_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "platform",
                "report_date",
                name="uq_app_store_metric_platform_date",
            ),
        )

    if not _has_table("invite_share_event"):
        op.create_table(
            "invite_share_event",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_type", sa.String(length=16), nullable=False),
            sa.Column("token_id", sa.Integer(), nullable=True),
            sa.Column("token", sa.String(length=64), nullable=True),
            sa.Column("action", sa.String(length=16), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False),
            sa.Column("user_agent", sa.String(length=256), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("ski_trip_planning_post"):
        op.create_table(
            "ski_trip_planning_post",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("trip_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("link_url", sa.String(length=500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["trip_id"], ["ski_trip.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index_if_missing(
        "idx_trip_invite_token_token", "trip_invite_token", ["token"]
    )
    if "idx_mel_dedupe" not in _index_names("message_event_log"):
        op.execute(
            "CREATE INDEX idx_mel_dedupe ON message_event_log "
            "(event_name, recipient_user_id, object_type, object_id, created_at) "
            "WHERE delivery_status != 'failed'"
        )
    _create_index_if_missing(
        "idx_ski_trip_participant_trip_status",
        "ski_trip_participant",
        ["trip_id", "status"],
    )
    _create_index_if_missing(
        "ix_app_store_metric_platform", "app_store_metric", ["platform"]
    )
    _create_index_if_missing(
        "ix_app_store_metric_report_date", "app_store_metric", ["report_date"]
    )
    _create_index_if_missing(
        "ix_ise_user_id", "invite_share_event", ["user_id"]
    )
    _create_index_if_missing(
        "ix_ise_created_at", "invite_share_event", ["created_at"]
    )
    if "idx_activity_recipient_type_time" not in _index_names("activity"):
        op.execute(
            "CREATE INDEX idx_activity_recipient_type_time "
            "ON activity (recipient_user_id, type, created_at DESC)"
        )
    if "idx_invitation_receiver_status" not in _index_names("invitation"):
        op.execute(
            "CREATE INDEX idx_invitation_receiver_status "
            "ON invitation (receiver_id, status) WHERE trip_id IS NULL"
        )
    _create_index_if_missing(
        "idx_ski_trip_user_end_date", "ski_trip", ["user_id", "end_date"]
    )
    _create_index_if_missing(
        "idx_ski_trip_participant_user_status",
        "ski_trip_participant",
        ["user_id", "status"],
    )
    _create_index_if_missing(
        "ix_ski_trip_planning_post_trip_id",
        "ski_trip_planning_post",
        ["trip_id"],
    )
    _create_index_if_missing(
        "ix_ski_trip_planning_post_user_id",
        "ski_trip_planning_post",
        ["user_id"],
    )


def downgrade():
    raise RuntimeError(
        "bl317_startup_schema has no automatic downgrade because some schema "
        "objects may predate Alembic ownership. Use a reviewed forward migration "
        "or restore a backup."
    )