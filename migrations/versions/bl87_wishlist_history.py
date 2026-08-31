"""Add private wishlist membership transition history.

Revision ID: bl87_wishlist_history
Revises: bl80_trip_lifecycle
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "bl87_wishlist_history"
down_revision = "bl80_trip_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wishlist_resort_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resort_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=8), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('added', 'removed')",
            name="ck_wre_event_type",
        ),
        sa.CheckConstraint(
            "source IN ('settings', 'mountain_detail')",
            name="ck_wre_source",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_wre_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resort_id"],
            ["resort.id"],
            name="fk_wre_resort_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_wre_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wishlist_resort_event"),
    )
    op.create_index(
        "ix_wre_user_occurred_at",
        "wishlist_resort_event",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_wre_user_resort_occurred_at",
        "wishlist_resort_event",
        ["user_id", "resort_id", "occurred_at"],
        unique=False,
    )


def downgrade():
    bind = op.get_bind()
    event_exists = bind.execute(
        sa.text("SELECT 1 FROM wishlist_resort_event LIMIT 1")
    ).first()
    if event_exists:
        raise RuntimeError(
            "Refusing BL-87 downgrade while wishlist history events exist"
        )
    op.drop_index(
        "ix_wre_user_resort_occurred_at",
        table_name="wishlist_resort_event",
    )
    op.drop_index(
        "ix_wre_user_occurred_at",
        table_name="wishlist_resort_event",
    )
    op.drop_table("wishlist_resort_event")