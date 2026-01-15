"""Create base schema - all tables and enums

Revision ID: 000000000000
Revises: 
Create Date: 2026-01-15 13:00:00.000000

This migration creates the complete initial schema from scratch.
It is the true root of the migration chain and must be applied first
on any empty database (e.g., Supabase).
"""
from alembic import op
import sqlalchemy as sa


revision = '000000000000'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create all enum types first
    op.execute("CREATE TYPE guest_status_enum AS ENUM ('invited', 'accepted', 'declined')")
    op.execute("CREATE TYPE participant_role_enum AS ENUM ('owner', 'guest')")
    op.execute("CREATE TYPE participant_transportation_enum AS ENUM ('driving', 'flying', 'train', 'bus', 'tbd')")
    op.execute("CREATE TYPE participant_equipment_enum AS ENUM ('own', 'renting', 'needs_rentals')")
    op.execute("CREATE TYPE lesson_choice_enum AS ENUM ('yes', 'no', 'maybe')")
    op.execute("CREATE TYPE carpool_role_enum AS ENUM ('driver', 'rider', 'driver_with_space', 'driver_no_space', 'needs_ride', 'not_carpooling', 'other')")
    op.execute("CREATE TYPE equipment_slot_enum AS ENUM ('primary', 'secondary')")
    op.execute("CREATE TYPE equipment_discipline_enum AS ENUM ('skier', 'snowboarder')")
    op.execute("CREATE TYPE accommodation_status_enum AS ENUM ('booked', 'not_yet', 'staying_with_friends')")
    op.execute("CREATE TYPE transportation_status_enum AS ENUM ('have_transport', 'need_transport', 'not_sure')")
    op.execute("CREATE TYPE invite_type_enum AS ENUM ('outbound', 'request')")
    op.execute("CREATE TYPE ski_trip_participant_status_enum AS ENUM ('invited', 'accepted', 'declined')")

    # Create country table
    op.create_table('country',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # Create resort table
    op.create_table('resort',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('state', sa.String(length=50), nullable=False),
        sa.Column('state_full', sa.String(length=50), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('country_code', sa.String(length=10), nullable=True),
        sa.Column('country_name', sa.String(length=100), nullable=True),
        sa.Column('country_name_override', sa.String(length=100), nullable=True),
        sa.Column('state_code', sa.String(length=50), nullable=True),
        sa.Column('state_name', sa.String(length=100), nullable=True),
        sa.Column('brand', sa.String(length=20), nullable=True),
        sa.Column('pass_brands', sa.String(length=150), nullable=True),
        sa.Column('pass_brands_json', sa.JSON(), nullable=True),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_region', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )

    # Create user table
    op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.String(length=80), nullable=False),
        sa.Column('last_name', sa.String(length=80), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('rider_type', sa.String(length=50), nullable=True),
        sa.Column('primary_rider_type', sa.String(length=50), nullable=True),
        sa.Column('secondary_rider_types', sa.JSON(), nullable=True),
        sa.Column('rider_types', sa.JSON(), nullable=True),
        sa.Column('pass_type', sa.String(length=100), nullable=True),
        sa.Column('profile_setup_complete', sa.Boolean(), nullable=True),
        sa.Column('gender', sa.String(length=20), nullable=True),
        sa.Column('birth_year', sa.Integer(), nullable=True),
        sa.Column('home_state', sa.String(length=50), nullable=True),
        sa.Column('skill_level', sa.String(length=50), nullable=True),
        sa.Column('gear', sa.String(length=200), nullable=True),
        sa.Column('home_mountain', sa.String(length=100), nullable=True),
        sa.Column('mountains_visited', sa.JSON(), nullable=True),
        sa.Column('home_resort_id', sa.Integer(), nullable=True),
        sa.Column('visited_resort_ids', sa.JSON(), nullable=True),
        sa.Column('open_dates', sa.JSON(), nullable=True),
        sa.Column('wish_list_resorts', sa.JSON(), nullable=True),
        sa.Column('terrain_preferences', sa.JSON(), nullable=True),
        sa.Column('equipment_status', sa.String(length=20), nullable=True),
        sa.Column('buddy_passes', sa.JSON(), nullable=True),
        sa.Column('buddy_passes_available', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_active_at', sa.DateTime(), nullable=True),
        sa.Column('lifecycle_stage', sa.String(length=20), nullable=True),
        sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True),
        sa.Column('profile_completed_at', sa.DateTime(), nullable=True),
        sa.Column('first_connection_at', sa.DateTime(), nullable=True),
        sa.Column('first_trip_created_at', sa.DateTime(), nullable=True),
        sa.Column('is_seeded', sa.Boolean(), nullable=True),
        sa.Column('invited_by_user_id', sa.Integer(), nullable=True),
        sa.Column('email_opt_in', sa.Boolean(), nullable=True),
        sa.Column('email_transactional', sa.Boolean(), nullable=True),
        sa.Column('email_social', sa.Boolean(), nullable=True),
        sa.Column('email_digest', sa.Boolean(), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=True),
        sa.Column('login_count', sa.Integer(), nullable=True),
        sa.Column('first_planning_timestamp', sa.DateTime(), nullable=True),
        sa.Column('planning_completed_timestamp', sa.DateTime(), nullable=True),
        sa.Column('planning_dismissed_timestamp', sa.DateTime(), nullable=True),
        sa.Column('historical_passes_by_season', sa.JSON(), nullable=True),
        sa.Column('primary_riding_style', sa.String(length=50), nullable=True),
        sa.Column('welcome_modal_seen_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['home_resort_id'], ['resort.id'], ),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    # Create ski_trip table
    op.create_table('ski_trip',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('resort_id', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(length=50), nullable=True),
        sa.Column('mountain', sa.String(length=100), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('pass_type', sa.String(length=50), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=True),
        sa.Column('ride_intent', sa.String(length=20), nullable=True),
        sa.Column('trip_duration', sa.String(length=20), nullable=True),
        sa.Column('trip_equipment_status', sa.String(length=20), nullable=True),
        sa.Column('equipment_override', sa.String(length=20), nullable=True),
        sa.Column('accommodation_status', sa.String(length=20), nullable=True),
        sa.Column('accommodation_link', sa.String(length=500), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_group_trip', sa.Boolean(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['resort_id'], ['resort.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create friend table
    op.create_table('friend',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('friend_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_seeded', sa.Boolean(), nullable=True),
        sa.Column('trip_invites_allowed', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['friend_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'friend_id', name='unique_friendship')
    )

    # Create ski_trip_participant table using raw SQL to avoid enum recreation
    op.execute("""
        CREATE TABLE ski_trip_participant (
            id SERIAL PRIMARY KEY,
            trip_id INTEGER NOT NULL REFERENCES ski_trip(id),
            user_id INTEGER NOT NULL REFERENCES "user"(id),
            status ski_trip_participant_status_enum NOT NULL,
            role participant_role_enum NOT NULL,
            transportation_status participant_transportation_enum,
            equipment_status participant_equipment_enum,
            taking_lesson lesson_choice_enum NOT NULL DEFAULT 'no',
            carpool_role carpool_role_enum,
            carpool_seats INTEGER,
            needs_ride BOOLEAN,
            start_date DATE,
            end_date DATE,
            created_at TIMESTAMP,
            CONSTRAINT unique_ski_trip_participant UNIQUE (trip_id, user_id)
        )
    """)

    # Create invitation table using raw SQL
    op.execute("""
        CREATE TABLE invitation (
            id SERIAL PRIMARY KEY,
            sender_id INTEGER NOT NULL REFERENCES "user"(id),
            receiver_id INTEGER NOT NULL REFERENCES "user"(id),
            trip_id INTEGER REFERENCES ski_trip(id),
            invite_type invite_type_enum NOT NULL DEFAULT 'outbound',
            status VARCHAR(20),
            created_at TIMESTAMP,
            CONSTRAINT unique_invitation_per_trip UNIQUE (sender_id, receiver_id, trip_id)
        )
    """)

    # Create invite_token table
    op.create_table('invite_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('inviter_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['inviter_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_invite_token_token', 'invite_token', ['token'], unique=True)

    # Create group_trip table using raw SQL
    op.execute("""
        CREATE TABLE group_trip (
            id SERIAL PRIMARY KEY,
            host_id INTEGER NOT NULL REFERENCES "user"(id),
            title VARCHAR(200),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            accommodation_status accommodation_status_enum,
            transportation_status transportation_status_enum,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)

    # Create trip_guest table using raw SQL
    op.execute("""
        CREATE TABLE trip_guest (
            id SERIAL PRIMARY KEY,
            trip_id INTEGER NOT NULL REFERENCES group_trip(id),
            user_id INTEGER NOT NULL REFERENCES "user"(id),
            status guest_status_enum NOT NULL,
            joined_at TIMESTAMP,
            CONSTRAINT unique_trip_guest UNIQUE (trip_id, user_id)
        )
    """)

    # Create equipment_setup table using raw SQL
    op.execute("""
        CREATE TABLE equipment_setup (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES "user"(id),
            slot equipment_slot_enum,
            discipline equipment_discipline_enum,
            brand VARCHAR(100),
            model VARCHAR(100),
            length_cm INTEGER,
            width_mm INTEGER,
            binding_type VARCHAR(50),
            boot_brand VARCHAR(50),
            boot_model VARCHAR(100),
            boot_flex INTEGER,
            purchase_year INTEGER,
            equipment_status VARCHAR(20),
            is_active BOOLEAN,
            CONSTRAINT unique_user_equipment_slot UNIQUE (user_id, slot)
        )
    """)

    # Create dismissed_nudge table
    op.create_table('dismissed_nudge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date_range_start', sa.Date(), nullable=False),
        sa.Column('date_range_end', sa.Date(), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date_range_start', 'date_range_end', name='unique_dismissed_nudge')
    )

    # Create event table
    op.create_table('event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(length=100), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('environment', sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create email_log table
    op.create_table('email_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('email_type', sa.String(length=100), nullable=False),
        sa.Column('source_event_id', sa.Integer(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('send_count', sa.Integer(), nullable=True),
        sa.Column('environment', sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(['source_event_id'], ['event.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create activity table
    op.create_table('activity',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('object_type', sa.String(length=20), nullable=False),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('extra_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('activity')
    op.drop_table('email_log')
    op.drop_table('event')
    op.drop_table('dismissed_nudge')
    op.drop_table('equipment_setup')
    op.drop_table('trip_guest')
    op.drop_table('group_trip')
    op.drop_index('ix_invite_token_token', table_name='invite_token')
    op.drop_table('invite_token')
    op.drop_table('invitation')
    op.drop_table('ski_trip_participant')
    op.drop_table('friend')
    op.drop_table('ski_trip')
    op.drop_table('user')
    op.drop_table('resort')
    op.drop_table('country')
    
    op.execute("DROP TYPE IF EXISTS ski_trip_participant_status_enum")
    op.execute("DROP TYPE IF EXISTS invite_type_enum")
    op.execute("DROP TYPE IF EXISTS transportation_status_enum")
    op.execute("DROP TYPE IF EXISTS accommodation_status_enum")
    op.execute("DROP TYPE IF EXISTS equipment_discipline_enum")
    op.execute("DROP TYPE IF EXISTS equipment_slot_enum")
    op.execute("DROP TYPE IF EXISTS carpool_role_enum")
    op.execute("DROP TYPE IF EXISTS lesson_choice_enum")
    op.execute("DROP TYPE IF EXISTS participant_equipment_enum")
    op.execute("DROP TYPE IF EXISTS participant_transportation_enum")
    op.execute("DROP TYPE IF EXISTS participant_role_enum")
    op.execute("DROP TYPE IF EXISTS guest_status_enum")
