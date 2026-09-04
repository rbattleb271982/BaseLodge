"""Add logical messaging occurrence identity.

Revision ID: bl147_send_safety
Revises: bl70_user_season_pass
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa


revision = "bl147_send_safety"
down_revision = "bl70_user_season_pass"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("message_event_log") as batch_op:
        batch_op.add_column(
            sa.Column("occurrence_id", sa.String(length=191), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_mel_logical_occurrence",
            ("occurrence_id", "recipient_user_id", "channel", "provider"),
        )


def downgrade():
    with op.batch_alter_table("message_event_log") as batch_op:
        batch_op.drop_constraint(
            "uq_mel_logical_occurrence",
            type_="unique",
        )
        batch_op.drop_column("occurrence_id")