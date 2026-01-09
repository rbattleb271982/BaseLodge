"""add join request support v2

Revision ID: 01d489963101
Revises: 5ad569b22019
Create Date: 2026-01-09 21:50:10.024025

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '01d489963101'
down_revision = '5ad569b22019'
branch_labels = None
depends_on = None


def upgrade():
    # Create the enum type manually for PostgreSQL
    invite_type_enum = postgresql.ENUM('OUTBOUND', 'REQUEST', name='invite_type_enum')
    invite_type_enum.create(op.get_bind())

    with op.batch_alter_table('invitation', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trip_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('invite_type', sa.Enum('OUTBOUND', 'REQUEST', name='invite_type_enum'), server_default='OUTBOUND', nullable=False))
        batch_op.drop_constraint('unique_invitation', type_='unique')
        batch_op.create_unique_constraint('unique_invitation_per_trip', ['sender_id', 'receiver_id', 'trip_id'])
        batch_op.create_foreign_key('invitation_trip_id_fkey', 'ski_trip', ['trip_id'], ['id'])

    with op.batch_alter_table('ski_trip', schema=None) as batch_op:
        batch_op.add_column(sa.Column('max_participants', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('ski_trip', schema=None) as batch_op:
        batch_op.drop_column('max_participants')

    with op.batch_alter_table('invitation', schema=None) as batch_op:
        batch_op.drop_constraint('invitation_trip_id_fkey', type_='foreignkey')
        batch_op.drop_constraint('unique_invitation_per_trip', type_='unique')
        batch_op.create_unique_constraint('unique_invitation', ['sender_id', 'receiver_id'])
        batch_op.drop_column('invite_type')
        batch_op.drop_column('trip_id')
    
    # Drop the enum type
    invite_type_enum = postgresql.ENUM('OUTBOUND', 'REQUEST', name='invite_type_enum')
    invite_type_enum.drop(op.get_bind())
