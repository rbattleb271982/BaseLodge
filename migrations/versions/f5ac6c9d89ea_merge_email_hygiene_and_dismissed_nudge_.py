"""Merge email hygiene and dismissed nudge branches

Revision ID: f5ac6c9d89ea
Revises: 3cb34b17c7dd, 6959ae237c29
Create Date: 2025-12-18 18:47:27.475175

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5ac6c9d89ea'
down_revision = ('3cb34b17c7dd', '6959ae237c29')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
