"""Add durable SkiTrip RSVP transition history.

Revision ID: bl78_rsvp_transition
Revises: bl52_trip_stay
Create Date: 2026-08-31
"""

from alembic import op
import sqlalchemy as sa


revision = "bl78_rsvp_transition"
down_revision = "bl52_trip_stay"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ski_trip_rsvp_transition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trip_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('pending', 'interested', 'going', 'declined', 'removed')",
            name="ck_strt_previous_status",
        ),
        sa.CheckConstraint(
            "new_status IN "
            "('pending', 'interested', 'going', 'declined', 'removed')",
            name="ck_strt_new_status",
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status <> new_status",
            name="ck_strt_status_changed",
        ),
        sa.CheckConstraint(
            "previous_status IS NOT NULL OR source IN "
            "('trip_creation_invite', 'organizer_invite', 'token_response', "
            "'join_request_accept')",
            name="ck_strt_initial_source",
        ),
        sa.CheckConstraint(
            "source IN ('trip_creation_invite', 'organizer_invite', "
            "'invite_cancel', 'token_response', 'invite_response', "
            "'self_rsvp', 'organizer_rsvp', 'organizer_remove', "
            "'organizer_reinvite', 'join_request_accept', "
            "'participant_leave')",
            name="ck_strt_source",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["ski_trip.id"],
            name="fk_strt_trip_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_strt_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user.id"],
            name="fk_strt_actor_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ski_trip_rsvp_transition"),
    )
    op.create_index(
        "ix_strt_trip_changed_at",
        "ski_trip_rsvp_transition",
        ["trip_id", "changed_at"],
        unique=False,
    )
    op.create_index(
        "ix_strt_user_changed_at",
        "ski_trip_rsvp_transition",
        ["user_id", "changed_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_strt_user_changed_at",
        table_name="ski_trip_rsvp_transition",
    )
    op.drop_index(
        "ix_strt_trip_changed_at",
        table_name="ski_trip_rsvp_transition",
    )
    op.drop_table("ski_trip_rsvp_transition")