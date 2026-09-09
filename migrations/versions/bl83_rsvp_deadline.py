"""Add an optional RSVP deadline to canonical ski trips.

Revision ID: bl83_rsvp_deadline
Revises: bl442_worker_heartbeat
"""

from alembic import op
import sqlalchemy as sa


revision = "bl83_rsvp_deadline"
down_revision = "bl442_worker_heartbeat"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ski_trip") as batch_op:
        batch_op.add_column(
            sa.Column("rsvp_deadline", sa.Date(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("ski_trip") as batch_op:
        batch_op.drop_column("rsvp_deadline")