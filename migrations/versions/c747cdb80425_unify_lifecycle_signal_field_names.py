"""Unify lifecycle signal field names

Revision ID: c747cdb80425
Revises: 730b51599368
Create Date: 2025-12-20 00:41:45.602626

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c747cdb80425'
down_revision = '730b51599368'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('first_planning_timestamp', sa.DateTime(), nullable=True))
        batch_op.alter_column('planning_details_completed_at', new_column_name='planning_completed_timestamp')
        batch_op.alter_column('planning_details_dismissed_at', new_column_name='planning_dismissed_timestamp')


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('planning_dismissed_timestamp', new_column_name='planning_details_dismissed_at')
        batch_op.alter_column('planning_completed_timestamp', new_column_name='planning_details_completed_at')
        batch_op.drop_column('first_planning_timestamp')
