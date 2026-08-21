"""Add the canonical confirmed SkiDay persistence foundation.

Revision ID: bl305_ski_day_foundation
Revises: bl60_mtn_filter_edu
Create Date: 2026-08-21
"""

from alembic import op
import sqlalchemy as sa


revision = "bl305_ski_day_foundation"
down_revision = "bl60_mtn_filter_edu"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ski_day",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resort_id", sa.Integer(), nullable=False),
        sa.Column("ski_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="user_confirmation",
        ),
        sa.Column("trip_id", sa.Integer(), nullable=True),
        sa.Column(
            "confirmed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resort_id"], ["resort.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trip_id"], ["ski_trip.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "resort_id",
            "ski_date",
            name="uq_ski_day_user_resort_date",
        ),
    )
    op.create_index("ix_ski_day_user_id", "ski_day", ["user_id"])
    op.create_index("ix_ski_day_resort_id", "ski_day", ["resort_id"])
    op.create_index("ix_ski_day_trip_id", "ski_day", ["trip_id"])


def downgrade():
    op.drop_index("ix_ski_day_trip_id", table_name="ski_day")
    op.drop_index("ix_ski_day_resort_id", table_name="ski_day")
    op.drop_index("ix_ski_day_user_id", table_name="ski_day")
    op.drop_table("ski_day")