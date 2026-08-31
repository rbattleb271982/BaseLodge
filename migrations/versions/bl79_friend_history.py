"""Add private direct connection lifecycle history.

Revision ID: bl79_friend_history
Revises: bl78_rsvp_transition
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "bl79_friend_history"
down_revision = "bl78_rsvp_transition"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "friend_connection_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_a_id", sa.Integer(), nullable=False),
        sa.Column("user_b_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=8), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "user_a_id < user_b_id",
            name="ck_fce_canonical_pair",
        ),
        sa.CheckConstraint(
            "event_type IN ('formed', 'removed')",
            name="ck_fce_event_type",
        ),
        sa.CheckConstraint(
            "source IN ('friend_request_accept', 'invite_token_accept', "
            "'qr_connect', 'group_trip_accept', 'shared_trip_connect', "
            "'api_unfriend', 'web_unfriend')",
            name="ck_fce_source",
        ),
        sa.ForeignKeyConstraint(
            ["user_a_id"],
            ["user.id"],
            name="fk_fce_user_a_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_b_id"],
            ["user.id"],
            name="fk_fce_user_b_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_fce_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_friend_connection_event"),
    )
    op.create_index(
        "ix_fce_pair_occurred_at",
        "friend_connection_event",
        ["user_a_id", "user_b_id", "occurred_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_fce_pair_occurred_at",
        table_name="friend_connection_event",
    )
    op.drop_table("friend_connection_event")