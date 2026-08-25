"""Add optional shared Stay fields to SkiTrip.

Revision ID: bl52_trip_stay
Revises: bl317_startup_schema
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "bl52_trip_stay"
down_revision = "bl317_startup_schema"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ski_trip", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("stay_name", sa.String(length=200), nullable=True)
        )
        batch_op.add_column(
            sa.Column("stay_description", sa.String(length=500), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("ski_trip", schema=None) as batch_op:
        batch_op.drop_column("stay_description")
        batch_op.drop_column("stay_name")