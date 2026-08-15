"""Add friend_suggestion and suggestion_push_cooldown tables (BL-12)

Revision ID: bl12_add_friend_suggestion
Revises: 3a7f1c9e2b4d
Create Date: 2026-08-15

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'bl12_add_friend_suggestion'
down_revision = '3a7f1c9e2b4d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'friend_suggestion',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('suggester_id', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('suggested_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['recipient_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['suggested_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['suggester_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # No full unique constraint — active-row uniqueness is the partial index below.
    )
    # Partial unique index: prevents duplicate ACTIVE rows for the same
    # (suggester, recipient, suggested_user) triple.  Rows with dismissed_at IS NOT NULL
    # fall outside the index, allowing fresh re-suggestion after dismissal or expiry.
    # Both PostgreSQL and SQLite support partial unique indexes.
    op.create_index(
        'uix_friend_suggestion_active',
        'friend_suggestion',
        ['suggester_id', 'recipient_id', 'suggested_user_id'],
        unique=True,
        postgresql_where=sa.text('dismissed_at IS NULL'),
        sqlite_where=sa.text('dismissed_at IS NULL'),
    )
    op.create_index(
        'idx_friend_suggestion_recipient',
        'friend_suggestion',
        ['recipient_id', 'dismissed_at', 'expires_at'],
    )
    op.create_index(
        'idx_friend_suggestion_suggester',
        'friend_suggestion',
        ['suggester_id', 'recipient_id'],
    )

    op.create_table(
        'suggestion_push_cooldown',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('suggester_id', sa.Integer(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['recipient_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['suggester_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('suggester_id', 'recipient_id', name='uq_suggestion_push_cooldown'),
    )


def downgrade():
    op.drop_table('suggestion_push_cooldown')
    op.drop_index('uix_friend_suggestion_active', table_name='friend_suggestion')
    op.drop_index('idx_friend_suggestion_suggester', table_name='friend_suggestion')
    op.drop_index('idx_friend_suggestion_recipient', table_name='friend_suggestion')
    op.drop_table('friend_suggestion')
