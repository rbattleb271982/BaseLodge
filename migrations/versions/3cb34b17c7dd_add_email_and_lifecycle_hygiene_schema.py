"""Add email and lifecycle hygiene schema: User identity, events, email logging

Revision ID: 3cb34b17c7dd
Revises: fe306bcefa9f
Create Date: 2025-12-18 05:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '3cb34b17c7dd'
down_revision = 'fe306bcefa9f'
branch_labels = None
depends_on = None


def upgrade():
    # User table additions - lifecycle & identity tracking
    op.add_column('user', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('last_active_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('lifecycle_stage', sa.String(20), server_default='new', nullable=False))
    op.add_column('user', sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('profile_completed_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('first_connection_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('first_trip_created_at', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('is_seeded', sa.Boolean(), server_default='false', nullable=False))
    
    # User table additions - notification preferences
    op.add_column('user', sa.Column('email_opt_in', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('user', sa.Column('email_transactional', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('user', sa.Column('email_social', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('user', sa.Column('email_digest', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('user', sa.Column('timezone', sa.String(50), nullable=True))
    
    # Friend table addition - seeded user tracking
    op.add_column('friend', sa.Column('is_seeded', sa.Boolean(), server_default='false', nullable=False))
    
    # Create event table for high-signal events
    op.create_table('event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(100), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('environment', sa.String(10), server_default='dev', nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create email_log table for tracking sends & suppression
    op.create_table('email_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email_type', sa.String(100), nullable=False),
        sa.Column('source_event_id', sa.Integer(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('send_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('environment', sa.String(10), server_default='dev', nullable=False),
        sa.ForeignKeyConstraint(['source_event_id'], ['event.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('email_log')
    op.drop_table('event')
    op.drop_column('friend', 'is_seeded')
    op.drop_column('user', 'timezone')
    op.drop_column('user', 'email_digest')
    op.drop_column('user', 'email_social')
    op.drop_column('user', 'email_transactional')
    op.drop_column('user', 'email_opt_in')
    op.drop_column('user', 'is_seeded')
    op.drop_column('user', 'first_trip_created_at')
    op.drop_column('user', 'first_connection_at')
    op.drop_column('user', 'profile_completed_at')
    op.drop_column('user', 'onboarding_completed_at')
    op.drop_column('user', 'lifecycle_stage')
    op.drop_column('user', 'last_active_at')
    op.drop_column('user', 'created_at')
