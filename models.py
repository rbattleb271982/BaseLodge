from datetime import datetime, date
from enum import Enum as PyEnum
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import sqlalchemy as sa

db = SQLAlchemy()


class AccommodationStatus(PyEnum):
    BOOKED = "booked"
    NOT_YET = "not_yet"
    STAYING_WITH_FRIENDS = "staying_with_friends"


class TransportationStatus(PyEnum):
    HAVE_TRANSPORT = "have_transport"
    NEED_TRANSPORT = "need_transport"
    NOT_SURE = "not_sure"


class GuestStatus(PyEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"


class EquipmentSlot(PyEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class EquipmentDiscipline(PyEnum):
    SKIER = "skier"
    SNOWBOARDER = "snowboarder"


class TripDuration(PyEnum):
    DAY_TRIP = "day_trip"
    ONE_NIGHT = "one_night"
    TWO_NIGHTS = "two_nights"
    THREE_PLUS_NIGHTS = "three_plus_nights"


class EquipmentStatus(PyEnum):
    HAVE_OWN_EQUIPMENT = "have_own_equipment"
    NEEDS_RENTALS = "needs_rentals"


class TripEquipmentStatus(PyEnum):
    USE_DEFAULT = "use_default"
    HAVE_OWN_EQUIPMENT = "have_own_equipment"
    NEEDS_RENTALS = "needs_rentals"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    # DEPRECATED: rider_type, primary_rider_type, secondary_rider_types are legacy. Use rider_types instead. Kept for backward compatibility.
    rider_type = db.Column(db.String(50))
    primary_rider_type = db.Column(db.String(50))  # DEPRECATED - use rider_types
    secondary_rider_types = db.Column(db.JSON, default=list)  # DEPRECATED - use rider_types
    rider_types = db.Column(db.JSON, default=list)  # Multi-select rider types: ["Skier"], ["Skier", "Snowboarder"], etc.
    pass_type = db.Column(db.String(100))
    # DEPRECATED: profile_setup_complete is legacy and no longer authoritative.
    # Use is_core_profile_complete property instead. Do not write to this field.
    profile_setup_complete = db.Column(db.Boolean, default=False)
    gender = db.Column(db.String(20))
    birth_year = db.Column(db.Integer)
    home_state = db.Column(db.String(50))
    skill_level = db.Column(db.String(50))
    gear = db.Column(db.String(200))
    home_mountain = db.Column(db.String(100), nullable=True)  # DEPRECATED: Use home_resort_id instead
    mountains_visited = db.Column(db.JSON, default=list)  # DEPRECATED: Use visited_resort_ids instead
    home_resort_id = db.Column(db.Integer, db.ForeignKey('resort.id'), nullable=True)  # FK to Resort table
    visited_resort_ids = db.Column(db.JSON, default=list)  # List of Resort IDs (normalized)
    open_dates = db.Column(db.JSON, default=list)  # List of YYYY-MM-DD strings
    wish_list_resorts = db.Column(db.JSON, default=list)  # List of resort IDs (max 3)
    terrain_preferences = db.Column(db.JSON, default=list)  # List of terrain types (max 2): Groomers, Trees, Park, Backcountry
    equipment_status = db.Column(db.String(20), default='have_own_equipment')  # have_own_equipment or needs_rentals
    
    # Email & lifecycle hygiene (Dec 2025)
    created_at = db.Column(db.DateTime, nullable=True)  # Set to earliest trip/friend or NOW
    last_active_at = db.Column(db.DateTime, nullable=True)  # Updated only on login
    lifecycle_stage = db.Column(db.String(20), default='new')  # new, onboarding, active
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)
    profile_completed_at = db.Column(db.DateTime, nullable=True)
    first_connection_at = db.Column(db.DateTime, nullable=True)
    first_trip_created_at = db.Column(db.DateTime, nullable=True)
    is_seeded = db.Column(db.Boolean, default=False)
    
    # Notification preferences
    email_opt_in = db.Column(db.Boolean, default=True)
    email_transactional = db.Column(db.Boolean, default=True)
    email_social = db.Column(db.Boolean, default=False)
    email_digest = db.Column(db.Boolean, default=False)
    timezone = db.Column(db.String(50), nullable=True)
    
    # Lifecycle signals (Dec 2025)
    login_count = db.Column(db.Integer, default=0)
    first_planning_timestamp = db.Column(db.DateTime, nullable=True)  # Set when user first creates trip or accepts TripGuest
    planning_completed_timestamp = db.Column(db.DateTime, nullable=True)  # Set when user completes OR dismisses planning callout
    # DEPRECATED: planning_dismissed_timestamp is unused. Do NOT read or write.
    # planning_completed_timestamp is the sole signal for both completion and dismissal.
    planning_dismissed_timestamp = db.Column(db.DateTime, nullable=True)
    historical_passes_by_season = db.Column(db.JSON, default=dict)  # e.g., {"2024_25": ["ikon", "epic"]}
    
    # Progressive profile completion (Dec 2025)
    primary_riding_style = db.Column(db.String(50), nullable=True)  # Groomers, Powder, All-Mountain, Park, Mixed
    welcome_next_steps_shown_at = db.Column(db.DateTime, nullable=True)  # Set when welcome screen is shown (once only)
    
    trips = db.relationship('SkiTrip', backref='user', lazy=True)
    friend_requests_sent = db.relationship('Invitation', foreign_keys='Invitation.sender_id', backref='sender', lazy=True)
    friend_requests_received = db.relationship('Invitation', foreign_keys='Invitation.receiver_id', backref='receiver', lazy=True)
    friends = db.relationship('Friend', foreign_keys='Friend.user_id', backref='user_obj', lazy=True)
    events = db.relationship('Event', backref='user', lazy=True)
    email_logs = db.relationship('EmailLog', backref='user', lazy=True)
    home_resort = db.relationship('Resort', foreign_keys=[home_resort_id], lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'
    
    # ─────────────────────────────────────────────────────────────────────────
    # CANONICAL USER STATES (System of Truth - Dec 2025)
    # These computed properties are the authoritative source for lifecycle logic.
    # ─────────────────────────────────────────────────────────────────────────
    
    @property
    def is_core_profile_complete(self):
        """
        A user is core-profile-complete if rider_types (non-empty), pass_type, and skill_level are set.
        home_state is optional. Equipment is always optional and never blocks completion.
        Falls back to legacy fields for backward compatibility.
        """
        # New path: rider_types array
        if self.rider_types and len(self.rider_types) > 0:
            return bool(self.pass_type and self.skill_level)
        # Legacy path: primary_rider_type or rider_type
        rider = self.primary_rider_type or self.rider_type
        return bool(rider and self.pass_type and self.skill_level)
    
    @property
    def display_rider_type(self):
        """
        Returns combined rider types for profile display.
        Format: "Skier" or "Skier & Snowboarder"
        Use in: all profile views, identity formatter
        """
        # New path: rider_types array
        if self.rider_types and len(self.rider_types) > 0:
            return ' & '.join(self.rider_types)
        # Legacy path: primary + secondary
        primary = self.primary_rider_type or self.rider_type
        if not primary:
            return None
        secondary = self.secondary_rider_types or []
        if secondary:
            return f"{primary} & {' & '.join(secondary)}"
        return primary
    
    @property
    def compact_rider_type_display(self):
        """
        DEPRECATED: Use display_rider_type instead.
        Returns combined rider types (same as display_rider_type).
        """
        return self.display_rider_type
    
    @property
    def has_started_planning(self):
        """
        A user has started planning if first_planning_timestamp is set, OR if they
        created a SkiTrip or are an accepted TripGuest (backward compatibility).
        Pending invites do not count. Trip ownership and accepted guest status are equivalent.
        """
        if self.first_planning_timestamp:
            return True
        if self.trips and len(self.trips) > 0:
            return True
        for membership in self.trip_memberships:
            if membership.status == GuestStatus.ACCEPTED:
                return True
        return False
    
    def mark_planning_started(self):
        """
        Set first_planning_timestamp if not already set. Call when user creates a trip
        or accepts a TripGuest invitation. Idempotent - does not overwrite if already set.
        """
        if not self.first_planning_timestamp:
            from datetime import datetime
            self.first_planning_timestamp = datetime.utcnow()
    
    @property
    def is_active_user(self):
        """
        A user is active if they are core-profile-complete AND have started planning.
        This is a product state, not a marketing metric.
        """
        return self.is_core_profile_complete and self.has_started_planning
    
    def update_lifecycle_stage(self):
        """
        Update lifecycle_stage to reflect the canonical computed states.
        Call this after relevant state changes (trip creation, profile update, etc.)
        
        Mapping:
        - Immediately after signup: 'new' (manually set, not derived here)
        - Not core-profile-complete OR not planning started: 'onboarding'
        - Core-profile-complete AND planning started: 'active'
        """
        if self.is_active_user:
            self.lifecycle_stage = 'active'
        elif self.is_core_profile_complete or self.has_started_planning:
            self.lifecycle_stage = 'onboarding'
        # Keep 'new' if neither condition is met (fresh signup)
    
    def get_visited_resorts(self):
        """
        Return list of Resort objects for visited mountains.
        Uses visited_resort_ids (normalized) if available, otherwise returns empty list.
        This enables access to full resort metadata (pass_brands, state, country, etc.)
        """
        if not self.visited_resort_ids or len(self.visited_resort_ids) == 0:
            return []
        from models import Resort
        return Resort.query.filter(Resort.id.in_(self.visited_resort_ids)).all()
    
    @property
    def visited_resorts_count(self):
        """
        Return count of visited resorts.
        Prefers visited_resort_ids (normalized), falls back to mountains_visited (legacy).
        """
        if self.visited_resort_ids and len(self.visited_resort_ids) > 0:
            return len(self.visited_resort_ids)
        return len(self.mountains_visited or [])
    
    def get_home_resort(self):
        """
        Return the home Resort object if home_resort_id is set, otherwise None.
        Enables access to full resort metadata for home mountain.
        """
        if not self.home_resort_id:
            return None
        from models import Resort
        return Resort.query.get(self.home_resort_id)
    
    def get_wishlist_resorts(self):
        """
        Return list of Resort objects for wishlist mountains.
        Uses wish_list_resorts (list of resort IDs).
        """
        if not self.wish_list_resorts or len(self.wish_list_resorts) == 0:
            return []
        from models import Resort
        return Resort.query.filter(Resort.id.in_(self.wish_list_resorts)).all()
    
    @property
    def wishlist_resorts_count(self):
        """Return count of wishlist resorts."""
        return len(self.wish_list_resorts or [])
    
    # ─────────────────────────────────────────────────────────────────────────
    # PROGRESSIVE PROFILE COMPLETION (Dec 2025)
    # ─────────────────────────────────────────────────────────────────────────
    
    def get_active_equipment(self):
        """Get the user's active equipment setup, if any."""
        from models import EquipmentSetup
        return EquipmentSetup.query.filter_by(
            user_id=self.id,
            is_active=True
        ).first()
    
    @property
    def is_equipment_complete(self):
        """
        Equipment step is complete if an active EquipmentSetup exists 
        AND equipment_status is not null.
        Brand/model fields are optional and never gate completion.
        """
        equipment = self.get_active_equipment()
        return equipment is not None and equipment.equipment_status is not None
    
    @property
    def is_profile_complete(self):
        """
        Profile is complete when:
        - primary_riding_style is not null
        Note: Equipment is managed in settings, not part of onboarding flow.
        """
        return self.primary_riding_style is not None
    
    def get_profile_completion_progress(self):
        """
        Calculate profile completion progress (derived, not stored).
        Returns (completed_steps, total_steps)
        Note: Only riding style is part of progressive onboarding flow.
        """
        completed = 1 if self.primary_riding_style else 0
        return completed, 1
    
    @property
    def should_show_progressive_modal(self):
        """
        Determine if progressive profile completion modals should be shown.
        Requirements:
        1. Core identity must be complete first (rider_types, skill_level, pass_type)
        2. Show on 1st login, or 2nd login if profile incomplete
        3. Never show after that
        """
        # Must have core identity before showing follow-up modals
        if not self.is_core_profile_complete:
            return False
        if self.is_profile_complete:
            return False
        if self.welcome_next_steps_shown_at:
            return False
        login_count = self.login_count or 0
        return login_count <= 2


class Resort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)  # Region code: CO, CA, Hokkaido, etc.
    state_full = db.Column(db.String(50), nullable=True)  # Full name: Colorado, California, etc.
    country = db.Column(db.String(2), nullable=True)  # ISO-2 country code: US, CA, FR, etc.
    brand = db.Column(db.String(20), nullable=True)  # 'Epic', 'Ikon', 'Indy', 'Other'
    pass_brands = db.Column(db.String(150), nullable=True)  # Comma-separated: 'Epic', 'Ikon,MountainCollective', etc.
    slug = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    trips = db.relationship('SkiTrip', backref='resort', lazy=True)

    def __repr__(self):
        return f'<Resort {self.name} ({self.state})>'


class SkiTrip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resort_id = db.Column(db.Integer, db.ForeignKey('resort.id'), nullable=True)
    state = db.Column(db.String(50))  # Kept for backward compatibility
    mountain = db.Column(db.String(100))  # Kept for backward compatibility
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    pass_type = db.Column(db.String(50), default="No Pass")
    is_public = db.Column(db.Boolean, default=True)
    ride_intent = db.Column(db.String(20), nullable=True)  # 'can_offer', 'need_ride', or None
    trip_duration = db.Column(db.String(20), nullable=True)  # day_trip, one_night, two_nights, three_plus_nights
    trip_equipment_status = db.Column(db.String(20), nullable=True)  # use_default, have_own_equipment, needs_rentals (null = use_default)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SkiTrip {self.mountain}>'
    
    def get_effective_equipment_status(self):
        """Get effective equipment status, considering trip override and user default."""
        if self.trip_equipment_status and self.trip_equipment_status != 'use_default':
            return self.trip_equipment_status
        # Fall back to user's profile equipment_status
        return self.user.equipment_status or 'have_own_equipment'
    
    @property
    def equipment_display(self):
        """Return human-readable equipment status label."""
        status = self.get_effective_equipment_status()
        labels = {
            'have_own_equipment': 'Have own equipment',
            'needs_rentals': 'Needs rentals'
        }
        return labels.get(status, 'Have own equipment')
    
    @staticmethod
    def calculate_duration(start_date, end_date):
        """Calculate trip duration based on dates."""
        if start_date == end_date:
            return TripDuration.DAY_TRIP.value
        nights = (end_date - start_date).days
        if nights == 1:
            return TripDuration.ONE_NIGHT.value
        elif nights == 2:
            return TripDuration.TWO_NIGHTS.value
        else:
            return TripDuration.THREE_PLUS_NIGHTS.value
    
    @property
    def duration_display(self):
        """Return human-readable duration label."""
        labels = {
            'day_trip': 'Day Trip',
            'one_night': '1 Night',
            'two_nights': '2 Nights',
            'three_plus_nights': '3+ Nights'
        }
        return labels.get(self.trip_duration, 'Day Trip')


class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_seeded = db.Column(db.Boolean, default=False)
    
    friend = db.relationship('User', foreign_keys=[friend_id], backref='friended_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),)

    def __repr__(self):
        return f'<Friend {self.user_id} -> {self.friend_id}>'


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, declined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('sender_id', 'receiver_id', name='unique_invitation'),)

    def __repr__(self):
        return f'<Invitation {self.sender_id} -> {self.receiver_id}>'


class InviteToken(db.Model):
    """Single-use invite token. Validity determined by used_at only."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    inviter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at = db.Column(db.DateTime, nullable=True)

    inviter = db.relationship("User", backref="invite_tokens")

    def is_used(self):
        """Check if token has been used (single-use enforcement via used_at)."""
        return self.used_at is not None

    def __repr__(self):
        return f'<InviteToken {self.token[:8]}... by user {self.inviter_id}>'


class GroupTrip(db.Model):
    """Shared/social trip with host and guests."""
    __tablename__ = 'group_trip'
    
    id = db.Column(db.Integer, primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    accommodation_status = db.Column(
        db.Enum(AccommodationStatus, name='accommodation_status_enum', create_constraint=True),
        nullable=True
    )
    transportation_status = db.Column(
        db.Enum(TransportationStatus, name='transportation_status_enum', create_constraint=True),
        nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    host = db.relationship('User', backref='hosted_trips', foreign_keys=[host_id])
    
    def __repr__(self):
        return f'<GroupTrip {self.id}: {self.title or "Untitled"}>'


class TripGuest(db.Model):
    """Join table for users invited to group trips."""
    __tablename__ = 'trip_guest'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('group_trip.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(
        db.Enum(GuestStatus, name='guest_status_enum', create_constraint=True),
        default=GuestStatus.INVITED,
        nullable=False
    )
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    trip = db.relationship('GroupTrip', backref='guests')
    user = db.relationship('User', backref='trip_memberships')
    
    __table_args__ = (
        db.UniqueConstraint('trip_id', 'user_id', name='unique_trip_guest'),
    )
    
    def __repr__(self):
        return f'<TripGuest trip={self.trip_id} user={self.user_id} status={self.status.value}>'


class EquipmentSetup(db.Model):
    """Profile-level gear setup (max 2 per user: primary + secondary)."""
    __tablename__ = 'equipment_setup'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    slot = db.Column(
        db.Enum(EquipmentSlot, name='equipment_slot_enum', create_constraint=True),
        nullable=True  # Made nullable for onboarding flow
    )
    discipline = db.Column(
        db.Enum(EquipmentDiscipline, name='equipment_discipline_enum', create_constraint=True),
        nullable=True  # Made nullable for onboarding flow
    )
    brand = db.Column(db.String(100), nullable=True)
    model = db.Column(db.String(100), nullable=True)
    length_cm = db.Column(db.Integer, nullable=True)
    width_mm = db.Column(db.Integer, nullable=True)
    binding_type = db.Column(db.String(50), nullable=True)
    boot_brand = db.Column(db.String(50), nullable=True)
    boot_model = db.Column(db.String(100), nullable=True)
    boot_flex = db.Column(db.Integer, nullable=True)
    purchase_year = db.Column(db.Integer, nullable=True)
    
    # Onboarding fields (Dec 2025)
    equipment_status = db.Column(db.String(20), nullable=True)  # 'own', 'rent', 'both'
    is_active = db.Column(db.Boolean, default=True)  # True for primary/active equipment setup
    
    user = db.relationship('User', backref='equipment_setups')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'slot', name='unique_user_equipment_slot'),
    )
    
    def __repr__(self):
        slot_val = self.slot.value if self.slot else 'none'
        discipline_val = self.discipline.value if self.discipline else 'none'
        return f'<EquipmentSetup user={self.user_id} slot={slot_val} discipline={discipline_val}>'


class DismissedNudge(db.Model):
    """Tracks dismissed availability nudges so they don't resurface for the same date range."""
    __tablename__ = 'dismissed_nudge'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_range_start = db.Column(db.Date, nullable=False)
    date_range_end = db.Column(db.Date, nullable=False)
    dismissed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='dismissed_nudges')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date_range_start', 'date_range_end', name='unique_dismissed_nudge'),
    )
    
    def __repr__(self):
        return f'<DismissedNudge user={self.user_id} {self.date_range_start} to {self.date_range_end}>'


class Event(db.Model):
    """High-signal user events for email & notification triggers."""
    __tablename__ = 'event'
    
    id = db.Column(db.Integer, primary_key=True)
    event_name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    environment = db.Column(db.String(10), default='dev')
    
    def __repr__(self):
        return f'<Event {self.event_name} user={self.user_id} at {self.created_at}>'


class EmailLog(db.Model):
    """Email send tracking for deduplication & suppression."""
    __tablename__ = 'email_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email_type = db.Column(db.String(100), nullable=False)
    source_event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    send_count = db.Column(db.Integer, default=1)
    environment = db.Column(db.String(10), default='dev')
    
    source_event = db.relationship('Event', backref='email_logs')
    
    def __repr__(self):
        return f'<EmailLog {self.email_type} to user={self.user_id}>'


def check_shared_upcoming_trip(user_a_id: int, user_b_id: int) -> bool:
    """
    Check if two users share at least one accepted, upcoming group trip.
    
    Args:
        user_a_id: ID of the first user
        user_b_id: ID of the second user
    
    Returns:
        True if both users are accepted guests on the same trip with dates >= today
    """
    today = date.today()
    
    user_a_trips = db.session.query(TripGuest.trip_id).filter(
        TripGuest.user_id == user_a_id,
        TripGuest.status == GuestStatus.ACCEPTED
    ).subquery()
    
    user_b_trips = db.session.query(TripGuest.trip_id).filter(
        TripGuest.user_id == user_b_id,
        TripGuest.status == GuestStatus.ACCEPTED
    ).subquery()
    
    shared_trip = db.session.query(GroupTrip).filter(
        GroupTrip.id.in_(sa.select(user_a_trips)),
        GroupTrip.id.in_(sa.select(user_b_trips)),
        GroupTrip.end_date >= today
    ).first()
    
    return shared_trip is not None


