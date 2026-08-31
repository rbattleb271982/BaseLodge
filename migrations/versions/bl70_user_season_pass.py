"""Add canonical season-specific user pass ownership.

Revision ID: bl70_user_season_pass
Revises: bl79_friend_history
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "bl70_user_season_pass"
down_revision = "bl80_trip_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_season_pass",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("season_start_year", sa.Integer(), nullable=False),
        sa.Column("pass_type", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_user_season_pass_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_season_pass"),
        sa.UniqueConstraint(
            "user_id",
            "season_start_year",
            name="uq_user_season_pass_user_season",
        ),
    )
    op.create_index(
        "ix_user_season_pass_season_pass",
        "user_season_pass",
        ["season_start_year", "pass_type"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_user_season_pass_season_pass",
        table_name="user_season_pass",
    )
    op.drop_table("user_season_pass")