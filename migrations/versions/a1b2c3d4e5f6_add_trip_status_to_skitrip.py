"""Add trip_status to SkiTrip

Revision ID: a1b2c3d4e5f6
Revises: fe306bcefa9f
Create Date: 2026-04-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'fe306bcefa9f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ski_trip', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trip_status', sa.String(length=10), nullable=True))

    op.execute("UPDATE ski_trip SET trip_status = 'going' WHERE trip_status IS NULL")


def downgrade():
    with op.batch_alter_table('ski_trip', schema=None) as batch_op:
        batch_op.drop_column('trip_status')
