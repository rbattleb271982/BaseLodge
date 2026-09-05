"""Add privacy-safe continuous worker heartbeat.

Revision ID: bl442_worker_heartbeat
Revises: bl443_reversible_cutover
"""

from alembic import op
import sqlalchemy as sa


revision = "bl442_worker_heartbeat"
down_revision = "bl443_reversible_cutover"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "messaging_worker_heartbeat",
        sa.Column("worker_identity", sa.String(120), primary_key=True),
        sa.Column("instance_token", sa.String(64), nullable=False),
        sa.Column("worker_release_sha", sa.String(40), nullable=False),
        sa.Column("process_started_at", sa.DateTime(), nullable=False),
        sa.Column("readiness_state", sa.String(24), nullable=False),
        sa.Column("operating_mode", sa.String(24), nullable=False),
        sa.Column("last_successful_poll_at", sa.DateTime(), nullable=True),
        sa.Column("last_successful_database_check_at", sa.DateTime(), nullable=True),
        sa.Column("last_claim_at", sa.DateTime(), nullable=True),
        sa.Column("last_finalization_at", sa.DateTime(), nullable=True),
        sa.Column("cycles_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cycles_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finalized_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_health_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_error_category", sa.String(40), nullable=True),
        sa.Column("graceful_shutdown", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "operating_mode IN ('idle-only','normal')",
            name="ck_worker_heartbeat_mode",
        ),
        sa.CheckConstraint(
            "readiness_state IN ('starting','ready','unhealthy','stopping','stopped')",
            name="ck_worker_heartbeat_readiness",
        ),
        sa.CheckConstraint(
            "cycles_total >= 0 AND cycles_failed >= 0 AND claimed_total >= 0 "
            "AND finalized_total >= 0",
            name="ck_worker_heartbeat_counters",
        ),
    )
    op.create_index(
        "ix_worker_heartbeat_updated_at",
        "messaging_worker_heartbeat",
        ["updated_at"],
    )


def downgrade():
    op.drop_index(
        "ix_worker_heartbeat_updated_at",
        table_name="messaging_worker_heartbeat",
    )
    op.drop_table("messaging_worker_heartbeat")