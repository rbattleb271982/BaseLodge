"""Add terminal SkiTrip lifecycle state and history.

Revision ID: bl80_trip_lifecycle
Revises: bl79_friend_history
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "bl80_trip_lifecycle"
down_revision = "bl79_friend_history"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ski_trip") as batch_op:
        batch_op.add_column(
            sa.Column("lifecycle_state", sa.String(length=10), nullable=True),
        )
        batch_op.add_column(
            sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        )
        batch_op.create_check_constraint(
            "ck_ski_trip_lifecycle_state",
            "lifecycle_state IS NULL OR lifecycle_state IN "
            "('active', 'completed', 'cancelled')",
        )
    op.create_table(
        "ski_trip_lifecycle_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trip_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('completed', 'cancelled')",
            name="ck_stle_event_type",
        ),
        sa.CheckConstraint(
            "source IN ('organizer_action')",
            name="ck_stle_source",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["ski_trip.id"],
            name="fk_stle_trip_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_stle_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ski_trip_lifecycle_event"),
    )
    op.create_index(
        "ix_stle_trip_occurred_at",
        "ski_trip_lifecycle_event",
        ["trip_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_stle_actor_occurred_at",
        "ski_trip_lifecycle_event",
        ["actor_user_id", "occurred_at"],
        unique=False,
    )


def downgrade():
    bind = op.get_bind()
    terminal_trip_exists = bind.execute(sa.text(
        "SELECT 1 FROM ski_trip "
        "WHERE lifecycle_state IN ('completed', 'cancelled') "
        "OR terminal_at IS NOT NULL LIMIT 1"
    )).first()
    lifecycle_event_exists = bind.execute(sa.text(
        "SELECT 1 FROM ski_trip_lifecycle_event LIMIT 1"
    )).first()
    if terminal_trip_exists or lifecycle_event_exists:
        raise RuntimeError(
            "Refusing BL-80 downgrade while terminal trips or lifecycle "
            "events exist"
        )

    op.drop_index(
        "ix_stle_actor_occurred_at",
        table_name="ski_trip_lifecycle_event",
    )
    op.drop_index(
        "ix_stle_trip_occurred_at",
        table_name="ski_trip_lifecycle_event",
    )
    op.drop_table("ski_trip_lifecycle_event")
    with op.batch_alter_table("ski_trip") as batch_op:
        batch_op.drop_constraint(
            "ck_ski_trip_lifecycle_state",
            type_="check",
        )
        batch_op.drop_column("terminal_at")
        batch_op.drop_column("lifecycle_state")