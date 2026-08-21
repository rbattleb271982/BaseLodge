-- Reviewed fresh-database PostgreSQL bootstrap for BaseLodge at BL-60.
-- Schema only. Do not add alembic_version, ski_day, or MountainPageView FKs.

CREATE TYPE guest_status_enum AS ENUM ('invited', 'accepted', 'declined');
CREATE TYPE participant_role_enum AS ENUM ('owner', 'guest');
CREATE TYPE participant_transportation_enum AS ENUM ('driving', 'flying', 'train', 'bus', 'tbd', 'other');
CREATE TYPE participant_equipment_enum AS ENUM ('own', 'renting', 'needs_rentals');
CREATE TYPE lesson_choice_enum AS ENUM ('yes', 'no', 'maybe');
CREATE TYPE carpool_role_enum AS ENUM ('driver', 'rider', 'driver_with_space', 'driver_no_space', 'needs_ride', 'not_carpooling', 'other');
CREATE TYPE equipment_slot_enum AS ENUM ('primary', 'secondary');
CREATE TYPE equipment_discipline_enum AS ENUM ('skier', 'snowboarder');
CREATE TYPE accommodation_status_enum AS ENUM ('booked', 'not_yet', 'staying_with_friends');
CREATE TYPE transportation_status_enum AS ENUM ('have_transport', 'need_transport', 'not_sure');
CREATE TYPE invite_type_enum AS ENUM ('outbound', 'request');
CREATE TYPE ski_trip_participant_status_enum AS ENUM ('invited', 'accepted', 'declined', 'pending', 'interested', 'going', 'removed');

CREATE TABLE country (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN,
    created_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE TABLE resort (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    state VARCHAR(50) NOT NULL,
    state_full VARCHAR(50),
    country VARCHAR(2),
    country_code VARCHAR(10),
    country_name VARCHAR(100),
    country_name_override VARCHAR(100),
    state_code VARCHAR(50),
    state_name VARCHAR(100),
    brand VARCHAR(20),
    pass_brands VARCHAR(150),
    pass_brands_json JSON,
    slug VARCHAR(120) NOT NULL UNIQUE,
    is_active BOOLEAN,
    is_region BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE "user" (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80),
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256),
    rider_type VARCHAR(50),
    primary_rider_type VARCHAR(50),
    secondary_rider_types JSON,
    rider_types JSON,
    pass_type VARCHAR(100),
    profile_setup_complete BOOLEAN,
    gender VARCHAR(20),
    birth_year INTEGER,
    home_state VARCHAR(50),
    skill_level VARCHAR(50),
    gear VARCHAR(200),
    home_mountain VARCHAR(100),
    mountains_visited JSON,
    home_resort_id INTEGER REFERENCES resort(id),
    visited_resort_ids JSON,
    open_dates JSON,
    wish_list_resorts JSON,
    terrain_preferences JSON,
    equipment_status VARCHAR(20),
    buddy_passes JSON,
    buddy_passes_available BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    last_active_at TIMESTAMP WITHOUT TIME ZONE,
    lifecycle_stage VARCHAR(20),
    onboarding_completed_at TIMESTAMP WITHOUT TIME ZONE,
    profile_completed_at TIMESTAMP WITHOUT TIME ZONE,
    first_connection_at TIMESTAMP WITHOUT TIME ZONE,
    first_trip_created_at TIMESTAMP WITHOUT TIME ZONE,
    is_seeded BOOLEAN,
    invited_by_user_id INTEGER REFERENCES "user"(id),
    email_opt_in BOOLEAN,
    email_transactional BOOLEAN,
    email_social BOOLEAN,
    email_digest BOOLEAN,
    timezone VARCHAR(50),
    login_count INTEGER,
    first_planning_timestamp TIMESTAMP WITHOUT TIME ZONE,
    planning_completed_timestamp TIMESTAMP WITHOUT TIME ZONE,
    planning_dismissed_timestamp TIMESTAMP WITHOUT TIME ZONE,
    historical_passes_by_season JSON,
    primary_riding_style VARCHAR(50),
    welcome_modal_seen_at TIMESTAMP WITHOUT TIME ZONE,
    backcountry_capable BOOLEAN,
    avi_certified BOOLEAN,
    previous_pass VARCHAR(100),
    auth_provider VARCHAR(20),
    provider_id VARCHAR(256),
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    is_verified BOOLEAN NOT NULL DEFAULT true,
    password_changed_at TIMESTAMP WITHOUT TIME ZONE,
    push_notifications_enabled BOOLEAN NOT NULL DEFAULT true,
    discoverable_in_friend_search BOOLEAN NOT NULL DEFAULT true,
    search_first_name VARCHAR(120),
    search_last_name VARCHAR(120),
    mountains_filter_education_seen_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE INDEX ix_user_search_first_name ON "user" (search_first_name varchar_pattern_ops);
CREATE INDEX ix_user_search_last_name ON "user" (search_last_name varchar_pattern_ops);

CREATE TABLE ski_trip (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    resort_id INTEGER REFERENCES resort(id),
    state VARCHAR(50),
    mountain VARCHAR(100),
    start_date DATE,
    end_date DATE,
    pass_type VARCHAR(100),
    is_public BOOLEAN,
    ride_intent VARCHAR(20),
    trip_duration VARCHAR(20),
    trip_equipment_status VARCHAR(20),
    equipment_override VARCHAR(20),
    accommodation_status VARCHAR(20),
    accommodation_link VARCHAR(500),
    max_participants INTEGER,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    is_group_trip BOOLEAN,
    created_by_user_id INTEGER REFERENCES "user"(id),
    trip_status VARCHAR(10),
    created_in_batch_id VARCHAR(36),
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    notes TEXT
);
CREATE INDEX idx_ski_trip_user_end_date ON ski_trip (user_id, end_date);

CREATE TABLE friend (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    friend_id INTEGER NOT NULL REFERENCES "user"(id),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    is_seeded BOOLEAN,
    trip_invites_allowed BOOLEAN,
    has_viewed_profile BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT unique_friendship UNIQUE (user_id, friend_id)
);

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
    created_at TIMESTAMP WITHOUT TIME ZONE,
    pass_type VARCHAR(100),
    CONSTRAINT unique_ski_trip_participant UNIQUE (trip_id, user_id)
);
CREATE INDEX idx_ski_trip_participant_trip_status ON ski_trip_participant (trip_id, status);
CREATE INDEX idx_ski_trip_participant_user_status ON ski_trip_participant (user_id, status);

CREATE TABLE invitation (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES "user"(id),
    receiver_id INTEGER NOT NULL REFERENCES "user"(id),
    trip_id INTEGER REFERENCES ski_trip(id),
    invite_type invite_type_enum NOT NULL DEFAULT 'outbound',
    status VARCHAR(20),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT unique_invitation_per_trip UNIQUE (sender_id, receiver_id, trip_id)
);
CREATE INDEX idx_invitation_receiver_status ON invitation (receiver_id, status) WHERE trip_id IS NULL;

CREATE TABLE invite_token (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL,
    inviter_id INTEGER NOT NULL REFERENCES "user"(id),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    used_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT ix_invite_token_token UNIQUE (token)
);

CREATE TABLE group_trip (
    id SERIAL PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES "user"(id),
    title VARCHAR(200),
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    accommodation_status accommodation_status_enum,
    transportation_status transportation_status_enum,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE TABLE trip_guest (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES group_trip(id),
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    status guest_status_enum NOT NULL,
    joined_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT unique_trip_guest UNIQUE (trip_id, user_id)
);

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
    is_primary BOOLEAN NOT NULL DEFAULT false,
    label VARCHAR(100),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    binding_brand VARCHAR(100),
    binding_model VARCHAR(100),
    CONSTRAINT unique_user_equipment_slot UNIQUE (user_id, slot)
);

CREATE TABLE dismissed_nudge (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    dismissed_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT unique_dismissed_nudge UNIQUE (user_id, date_range_start, date_range_end)
);

CREATE TABLE event (
    id SERIAL PRIMARY KEY,
    event_name VARCHAR(100) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    payload JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    environment VARCHAR(10)
);

CREATE TABLE email_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    email_type VARCHAR(100) NOT NULL,
    source_event_id INTEGER REFERENCES event(id),
    sent_at TIMESTAMP WITHOUT TIME ZONE,
    send_count INTEGER,
    environment VARCHAR(10)
);

CREATE TABLE activity (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER NOT NULL REFERENCES "user"(id),
    recipient_user_id INTEGER NOT NULL REFERENCES "user"(id),
    type VARCHAR(50) NOT NULL,
    object_type VARCHAR(20) NOT NULL,
    object_id INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    extra_data JSON
);
CREATE INDEX idx_activity_recipient_type_time ON activity (recipient_user_id, type, created_at DESC);

CREATE TABLE user_availability (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    date DATE NOT NULL,
    is_available BOOLEAN NOT NULL,
    note VARCHAR(200),
    created_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT uq_user_availability_user_date UNIQUE (user_id, date)
);

CREATE TABLE dismissed_insight_card (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    card_type VARCHAR(64) NOT NULL,
    card_key VARCHAR(255) NOT NULL,
    dismissed_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT uq_dismissed_insight_card UNIQUE (user_id, card_type, card_key)
);
CREATE INDEX ix_dismissed_insight_card_user_id ON dismissed_insight_card (user_id);

CREATE TABLE resort_pass (
    id SERIAL PRIMARY KEY,
    resort_id INTEGER NOT NULL REFERENCES resort(id) ON DELETE CASCADE,
    pass_name VARCHAR(50) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    CONSTRAINT uq_resort_pass UNIQUE (resort_id, pass_name)
);
CREATE INDEX ix_resort_pass_resort_id ON resort_pass (resort_id);

CREATE TABLE push_device_token (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id),
    token VARCHAR(512) NOT NULL,
    platform VARCHAR(20) NOT NULL,
    active BOOLEAN NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    apns_environment VARCHAR(20) NOT NULL DEFAULT 'unknown',
    CONSTRAINT uq_push_device_token_user_token UNIQUE (user_id, token)
);

CREATE TABLE friend_cooldown (
    id SERIAL PRIMARY KEY,
    user_a_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    user_b_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    CONSTRAINT uq_friend_cooldown_pair UNIQUE (user_a_id, user_b_id),
    CONSTRAINT ck_friend_cooldown_order CHECK (user_a_id < user_b_id)
);
CREATE INDEX ix_friend_cooldown_user_a ON friend_cooldown (user_a_id);
CREATE INDEX ix_friend_cooldown_user_b ON friend_cooldown (user_b_id);

CREATE TABLE friend_suggestion (
    id SERIAL PRIMARY KEY,
    suggester_id INTEGER NOT NULL REFERENCES "user"(id),
    recipient_id INTEGER NOT NULL REFERENCES "user"(id),
    suggested_user_id INTEGER NOT NULL REFERENCES "user"(id),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    dismissed_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE INDEX idx_friend_suggestion_recipient ON friend_suggestion (recipient_id, dismissed_at, expires_at);
CREATE INDEX idx_friend_suggestion_suggester ON friend_suggestion (suggester_id, recipient_id);
CREATE UNIQUE INDEX uix_friend_suggestion_active ON friend_suggestion (suggester_id, recipient_id, suggested_user_id) WHERE dismissed_at IS NULL;

CREATE TABLE suggestion_push_cooldown (
    id SERIAL PRIMARY KEY,
    suggester_id INTEGER NOT NULL REFERENCES "user"(id),
    recipient_id INTEGER NOT NULL REFERENCES "user"(id),
    last_sent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    CONSTRAINT uq_suggestion_push_cooldown UNIQUE (suggester_id, recipient_id)
);

CREATE TABLE message_event_log (
    id SERIAL PRIMARY KEY,
    event_name VARCHAR(120) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,
    category VARCHAR(50) NOT NULL,
    actor_user_id INTEGER REFERENCES "user"(id),
    recipient_user_id INTEGER REFERENCES "user"(id),
    object_type VARCHAR(80),
    object_id INTEGER,
    channel VARCHAR(40),
    delivery_status VARCHAR(40) NOT NULL DEFAULT 'pending',
    suppression_reason VARCHAR(80),
    provider VARCHAR(40),
    provider_message_id VARCHAR(255),
    payload_json JSON NOT NULL DEFAULT '{}',
    message_title VARCHAR(255),
    message_body TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    processed_at TIMESTAMP WITHOUT TIME ZONE,
    sent_at TIMESTAMP WITHOUT TIME ZONE,
    parent_mel_id INTEGER REFERENCES message_event_log(id),
    retry_locked_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE INDEX ix_message_event_log_category ON message_event_log (category);
CREATE INDEX ix_message_event_log_created_at ON message_event_log (created_at);
CREATE INDEX ix_message_event_log_delivery_status ON message_event_log (delivery_status);
CREATE INDEX ix_message_event_log_event_name ON message_event_log (event_name);
CREATE INDEX ix_message_event_log_recipient_user_id ON message_event_log (recipient_user_id);
CREATE INDEX idx_mel_dedupe ON message_event_log (event_name, recipient_user_id, object_type, object_id, created_at) WHERE delivery_status <> 'failed';

CREATE TABLE trip_invite_token (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL,
    trip_id INTEGER NOT NULL REFERENCES ski_trip(id) ON DELETE CASCADE,
    inviter_user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    used_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT trip_invite_token_token_key UNIQUE (token)
);
CREATE INDEX idx_trip_invite_token_token ON trip_invite_token (token);

CREATE TABLE mountain_page_view (
    id SERIAL PRIMARY KEY,
    resort_id INTEGER NOT NULL,
    user_id INTEGER,
    viewed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    session_key VARCHAR(32)
);
CREATE INDEX idx_mpv_resort_time ON mountain_page_view (resort_id, viewed_at);

CREATE TABLE app_store_metric (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(16) NOT NULL,
    report_date DATE NOT NULL,
    downloads INTEGER,
    page_views INTEGER,
    conversion_pct DOUBLE PRECISION,
    rating DOUBLE PRECISION,
    review_count INTEGER,
    crashes DOUBLE PRECISION,
    anrs DOUBLE PRECISION,
    fetched_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_app_store_metric_platform_date UNIQUE (platform, report_date)
);
CREATE INDEX ix_app_store_metric_platform ON app_store_metric (platform);
CREATE INDEX ix_app_store_metric_report_date ON app_store_metric (report_date);

CREATE TABLE invite_share_event (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    token_type VARCHAR(16) NOT NULL,
    token_id INTEGER,
    token VARCHAR(64),
    action VARCHAR(16) NOT NULL,
    source VARCHAR(32) NOT NULL,
    user_agent VARCHAR(256),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
);
CREATE INDEX ix_ise_created_at ON invite_share_event (created_at);
CREATE INDEX ix_ise_user_id ON invite_share_event (user_id);

CREATE TABLE ski_trip_planning_post (
    id SERIAL PRIMARY KEY,
    trip_id INTEGER NOT NULL REFERENCES ski_trip(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    category VARCHAR(32) NOT NULL,
    body TEXT NOT NULL,
    link_url VARCHAR(500),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);
CREATE INDEX ix_ski_trip_planning_post_trip_id ON ski_trip_planning_post (trip_id);
CREATE INDEX ix_ski_trip_planning_post_user_id ON ski_trip_planning_post (user_id);