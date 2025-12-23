"""Add role, transportation_status, equipment_status to SkiTripParticipant

Revision ID: 7284516ddc3c
Revises: 370403a1d9f9
Create Date: 2025-12-23 22:10:06.137548

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7284516ddc3c'
down_revision = '370403a1d9f9'
branch_labels = None
depends_on = None


def upgrade():
    # Create enum types first
    role_enum = sa.Enum('OWNER', 'GUEST', name='participant_role_enum')
    transportation_enum = sa.Enum('DRIVING', 'FLYING', 'TRAIN_BUS', 'TBD', name='participant_transportation_enum')
    equipment_enum = sa.Enum('OWN', 'RENTING', 'NEEDS_RENTALS', name='participant_equipment_enum')
    
    role_enum.create(op.get_bind(), checkfirst=True)
    transportation_enum.create(op.get_bind(), checkfirst=True)
    equipment_enum.create(op.get_bind(), checkfirst=True)
    
    # Add columns - role is nullable initially to handle existing rows
    with op.batch_alter_table('ski_trip_participant', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.Enum('OWNER', 'GUEST', name='participant_role_enum'), nullable=True))
        batch_op.add_column(sa.Column('transportation_status', sa.Enum('DRIVING', 'FLYING', 'TRAIN_BUS', 'TBD', name='participant_transportation_enum'), nullable=True))
        batch_op.add_column(sa.Column('equipment_status', sa.Enum('OWN', 'RENTING', 'NEEDS_RENTALS', name='participant_equipment_enum'), nullable=True))
    
    # Set default value for existing rows (they are guests)
    op.execute("UPDATE ski_trip_participant SET role = 'GUEST' WHERE role IS NULL")
    
    # Now make role non-nullable
    with op.batch_alter_table('ski_trip_participant', schema=None) as batch_op:
        batch_op.alter_column('role', nullable=False)


def downgrade():
    with op.batch_alter_table('ski_trip_participant', schema=None) as batch_op:
        batch_op.drop_column('equipment_status')
        batch_op.drop_column('transportation_status')
        batch_op.drop_column('role')
    
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS participant_equipment_enum")
    op.execute("DROP TYPE IF EXISTS participant_transportation_enum")
    op.execute("DROP TYPE IF EXISTS participant_role_enum")
