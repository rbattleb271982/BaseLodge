"""Add account-level Mountains filter education state.

Revision ID: bl60_mtn_filter_edu
Revises: bl12_add_friend_suggestion
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa


revision = "bl60_mtn_filter_edu"
down_revision = "bl12_add_friend_suggestion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("mountains_filter_education_seen_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("user", "mountains_filter_education_seen_at")