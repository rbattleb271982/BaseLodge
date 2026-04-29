"""Add has_viewed_profile to Friend

Revision ID: b3d1e7f2a9c4
Revises: aeb125060592
Create Date: 2026-04-29 04:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3d1e7f2a9c4'
down_revision = 'aeb125060592'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('friend', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'has_viewed_profile',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false')
        ))


def downgrade():
    with op.batch_alter_table('friend', schema=None) as batch_op:
        batch_op.drop_column('has_viewed_profile')
