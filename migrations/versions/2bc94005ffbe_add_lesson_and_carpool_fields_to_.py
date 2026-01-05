"""Add lesson and carpool fields to SkiTripParticipant

Revision ID: 2bc94005ffbe
Revises: af6f62403e45
Create Date: 2026-01-05 08:34:52.664395

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2bc94005ffbe'
down_revision = 'af6f62403e45'
branch_labels = None
depends_on = None


def upgrade():
    # Create enum types first
    lesson_choice_enum = sa.Enum('yes', 'no', 'maybe', name='lesson_choice_enum')
    carpool_role_enum = sa.Enum('driver', 'rider', name='carpool_role_enum')
    lesson_choice_enum.create(op.get_bind(), checkfirst=True)
    carpool_role_enum.create(op.get_bind(), checkfirst=True)
    
    with op.batch_alter_table('ski_trip_participant', schema=None) as batch_op:
        batch_op.add_column(sa.Column('taking_lesson', sa.Enum('yes', 'no', 'maybe', name='lesson_choice_enum', create_constraint=True), server_default='no', nullable=False))
        batch_op.add_column(sa.Column('carpool_role', sa.Enum('driver', 'rider', name='carpool_role_enum', create_constraint=True), nullable=True))
        batch_op.add_column(sa.Column('carpool_seats', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('needs_ride', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    with op.batch_alter_table('ski_trip_participant', schema=None) as batch_op:
        batch_op.drop_column('needs_ride')
        batch_op.drop_column('carpool_seats')
        batch_op.drop_column('carpool_role')
        batch_op.drop_column('taking_lesson')
    
    # Drop enum types
    sa.Enum(name='lesson_choice_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='carpool_role_enum').drop(op.get_bind(), checkfirst=True)
