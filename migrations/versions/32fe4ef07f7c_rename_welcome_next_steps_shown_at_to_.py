"""Rename welcome_next_steps_shown_at to welcome_modal_seen_at

Revision ID: 32fe4ef07f7c
Revises: 2dc398f493f6
Create Date: 2025-12-23 23:20:12.604547

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '32fe4ef07f7c'
down_revision = '2dc398f493f6'
branch_labels = None
depends_on = None


def upgrade():
    # Rename column to preserve existing data
    op.alter_column('user', 'welcome_next_steps_shown_at', 
                    new_column_name='welcome_modal_seen_at')


def downgrade():
    # Rename column back
    op.alter_column('user', 'welcome_modal_seen_at', 
                    new_column_name='welcome_next_steps_shown_at')
