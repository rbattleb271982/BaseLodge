"""Add the durable messaging outbox.

Revision ID: bl440_message_outbox
Revises: bl147_send_safety
"""

from alembic import op
import sqlalchemy as sa


revision = "bl440_message_outbox"
down_revision = "bl147_send_safety"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("occurrence_id", sa.String(191), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), nullable=True),
        sa.Column("object_type", sa.String(80), nullable=True),
        sa.Column("object_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("leased_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "provider_phase", sa.String(20), nullable=False,
            server_default="not_started",
        ),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("final_event_log_id", sa.Integer(), nullable=True),
        sa.Column("replay_of_outbox_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','processing','retryable','provider_accepted',"
            "'suppressed','dead_letter','delivery_unknown')",
            name="ck_outbox_status",
        ),
        sa.CheckConstraint(
            "provider_phase IN ('not_started','started','accepted','unknown')",
            name="ck_outbox_provider_phase",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_outbox_attempt_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["final_event_log_id"], ["message_event_log.id"]),
        sa.ForeignKeyConstraint(["replay_of_outbox_id"], ["message_outbox.id"]),
        sa.UniqueConstraint(
            "occurrence_id", "recipient_user_id", "channel", "provider",
            name="uq_outbox_logical_delivery",
        ),
        sa.UniqueConstraint("lease_token", name="uq_message_outbox_lease_token"),
        sa.UniqueConstraint(
            "final_event_log_id", name="uq_message_outbox_final_event_log"
        ),
    )
    op.create_index(
        "ix_outbox_claim", "message_outbox",
        ["status", "next_attempt_at", "id"],
    )
    op.create_index(
        "ix_message_outbox_status", "message_outbox", ["status"]
    )
    op.create_index(
        "ix_message_outbox_next_attempt_at", "message_outbox", ["next_attempt_at"]
    )
    op.create_index(
        "ix_message_outbox_lease_expires_at", "message_outbox", ["lease_expires_at"]
    )


def downgrade():
    op.drop_table("message_outbox")