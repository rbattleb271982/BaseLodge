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
    DECLINED = "declined"


class ParticipantRole(PyEnum):
    OWNER = "owner"
    GUEST = "guest"


class ParticipantTransportation(PyEnum):
    DRIVING = "driving"
    FLYING = "flying"
    TRAIN = "train"
    BUS = "bus"
    TBD = "tbd"
    OTHER = "other"


class ParticipantEquipment(PyEnum):
    OWN = "own"
    RENTING = "renting"
    NEEDS_RENTALS = "needs_rentals"


class LessonChoice(PyEnum):
    YES = "yes"
    NO = "no"
    MAYBE = "maybe"


class CarpoolRole(PyEnum):
    DRIVER = "driver"
    RIDER = "rider"
    DRIVER_WITH_SPACE = "driver_with_space"
    DRIVER_NO_SPACE = "driver_no_space"
    NEEDS_RIDE = "needs_ride"
    NOT_CARPOOLING = "not_carpooling"
    OTHER = "other"


class EquipmentSlot(PyEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class EquipmentDiscipline(PyEnum):
    SKIER = "skier"
    SNOWBOARDER = "snowboarder"


class Country(db.Model):
    """Admin-managed country reference table for dropdown options."""
    __tablename__ = 'country'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Country {self.code}: {self.name}>'


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
    last_name = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    auth_provider = db.Column(db.String(20), nullable=True)
    provider_id = db.Column(db.String(256), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)
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
    buddy_passes = db.Column(db.JSON, default=dict)  # {"epic": true, "ikon": false} - availability per supported pass
    buddy_passes_available = db.Column(db.Boolean, default=True, nullable=False, server_default='true')
    
    # Email & lifecycle hygiene (Dec 2025)
    created_at = db.Column(db.DateTime, nullable=True)  # Set to earliest trip/friend or NOW
    last_active_at = db.Column(db.DateTime, nullable=True)  # Updated only on login
    lifecycle_stage = db.Column(db.String(20), default='new')  # new, onboarding, active
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)
    profile_completed_at = db.Column(db.DateTime, nullable=True)
    first_connection_at = db.Column(db.DateTime, nullable=True)
    first_trip_created_at = db.Column(db.DateTime, nullable=True)
    is_seeded = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=True, nullable=False, server_default='true')
    # HISTORICAL METADATA: invited_by_user_id records who invited this user.
    # This field is intentionally retained permanently and must NOT be cleared.
    # It enables referral tracking, analytics, and inviter lineage queries.
    invited_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
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
    welcome_modal_seen_at = db.Column(db.DateTime, nullable=True)  # Set when welcome modal dismissed (once only)
    backcountry_capable = db.Column(db.Boolean, default=False, nullable=True)  # Does user ski backcountry?
    avi_certified = db.Column(db.Boolean, nullable=True)  # Avalanche certified (only relevant if backcountry_capable)
    previous_pass = db.Column(db.String(100), nullable=True)  # Pass held last season
    password_changed_at = db.Column(db.DateTime, nullable=True)  # Set on every successful password change/reset

    trips = db.relationship('SkiTrip', foreign_keys='SkiTrip.user_id', backref='user', lazy=True)
    friend_requests_sent = db.relationship('Invitation', foreign_keys='Invitation.sender_id', backref='sender', lazy=True)
    friend_requests_received = db.relationship('Invitation', foreign_keys='Invitation.receiver_id', backref='receiver', lazy=True)
    friends = db.relationship('Friend', foreign_keys='Friend.user_id', backref='user_obj', lazy=True)
    events = db.relationship('Event', backref='user', lazy=True)
    email_logs = db.relationship('EmailLog', backref='user', lazy=True)
    home_resort = db.relationship('Resort', foreign_keys=[home_resort_id], lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def get_reset_token(self):
        """Generate a time-limited password reset token."""
        from itsdangerous import URLSafeTimedSerializer
        from flask import current_app
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        return s.dumps(self.id, salt='password-reset')
    
    @staticmethod
    def verify_reset_token(token, max_age=1800):
        """Verify password reset token and return user if valid (30 min expiry).

        Tokens are single-use: once the user successfully resets their password
        (password_changed_at is set), any token issued before that moment is
        rejected, even if it is still within the 30-minute window.
        """
        from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
        from flask import current_app
        
        if not token:
            return None
        
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            user_id, issued_at = s.loads(
                token, salt='password-reset', max_age=max_age, return_timestamp=True
            )
        except (SignatureExpired, BadSignature):
            return None
        
        user = db.session.get(User, user_id)
        if not user:
            return None

        # Reject if the password was already changed after this token was issued
        if user.password_changed_at:
            # issued_at from itsdangerous may be timezone-aware; normalise to naive UTC
            issued_naive = issued_at.replace(tzinfo=None) if issued_at.tzinfo else issued_at
            if user.password_changed_at > issued_naive:
                return None

        return user

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
        EXCEPTION: If rider_types is ONLY ["Social"], skill_level is NOT required.
        If Social is combined with other rider types, skill_level IS required.
        home_state is optional. Equipment is always optional and never blocks completion.
        Falls back to legacy fields for backward compatibility.
        """
        # New path: rider_types array
        if self.rider_types and len(self.rider_types) > 0:
            # Social-ONLY users don't need skill_level
            is_social_only = self.rider_types == ["Social"]
            if is_social_only:
                return bool(self.pass_type)
            return bool(self.pass_type and self.skill_level)
        # Legacy path: primary_rider_type or rider_type
        rider = self.primary_rider_type or self.rider_type
        return bool(rider and self.pass_type and self.skill_level)
    
    @property
    def display_rider_type(self):
        """
        Returns combined rider types for profile display.
        Format: "Skier" or "Skier + Snowboarder"
        Use in: all profile views, identity formatter
        """
        # New path: rider_types array
        if self.rider_types and len(self.rider_types) > 0:
            # Normalize: some stored values may be comma-separated strings
            # e.g. ["Skier,Snowboarder"] → ["Skier", "Snowboarder"]
            types = []
            for rt in self.rider_types:
                for part in str(rt).split(','):
                    part = part.strip()
                    if part:
                        types.append(part)
            return ' + '.join(types) if types else None
        # Legacy path: primary + secondary
        primary = self.primary_rider_type or self.rider_type
        if not primary:
            return None
        secondary = self.secondary_rider_types or []
        if secondary:
            return f"{primary} + {' + '.join(secondary)}"
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
        return db.session.get(Resort, self.home_resort_id)
    
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
        - terrain_preferences has at least one selection
        Note: Equipment is managed in settings, not part of onboarding flow.
        """
        return self.terrain_preferences is not None and len(self.terrain_preferences) > 0
    
    def get_profile_completion_progress(self):
        """
        Calculate profile completion progress (derived, not stored).
        Returns (completed_steps, total_steps)
        Note: Only terrain preferences is part of progressive onboarding flow.
        """
        completed = 1 if (self.terrain_preferences and len(self.terrain_preferences) > 0) else 0
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
        if self.welcome_modal_seen_at:
            return False
        login_count = self.login_count or 0
        return login_count <= 2


class UserAvailability(db.Model):
    """Per-day availability for a user. Replaces the legacy open_dates JSON column."""
    __tablename__ = 'user_availability'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uq_user_availability_user_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    note = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('availability_rows', lazy='dynamic'))

    def __repr__(self):
        return f'<UserAvailability user_id={self.user_id} date={self.date}>'


class Resort(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    
    # Legacy columns (kept for backward compatibility)
    state = db.Column(db.String(50), nullable=False)  # Region code: CO, CA, Hokkaido, etc.
    state_full = db.Column(db.String(50), nullable=True)  # Full name: Colorado, California, etc.
    country = db.Column(db.String(2), nullable=True)  # ISO-2 country code: US, CA, FR, etc.
    
    # Canonical geography columns (SINGLE SOURCE OF TRUTH)
    country_code = db.Column(db.String(10), nullable=True)  # ISO-2 code: US, CA, JP, etc.
    country_name = db.Column(db.String(100), nullable=True)  # Display: United States, Canada, etc.
    country_name_override = db.Column(db.String(100), nullable=True)  # Optional admin override for display
    state_code = db.Column(db.String(50), nullable=True)  # Region code: CO, BC, Hokkaido, etc.
    state_name = db.Column(db.String(100), nullable=True)  # Display: Colorado, British Columbia, etc.
    
    brand = db.Column(db.String(20), nullable=True)  # DEPRECATED: legacy single pass
    pass_brands = db.Column(db.String(150), nullable=True)  # Legacy comma-separated, kept for backwards compat
    pass_brands_json = db.Column(db.JSON, nullable=True, default=list)  # NEW: JSON array ['Epic', 'Ikon']
    slug = db.Column(db.String(120), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_region = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    
    trips = db.relationship('SkiTrip', backref='resort', lazy=True)
    
    # Canonical pass brands (display order)
    VALID_PASS_BRANDS = ['Epic', 'Ikon', 'Mountain Collective', 'Indy', 'Other', 'None']
    
    def get_pass_brands_list(self):
        """Returns pass brands as a list, preferring JSON column, falling back to legacy."""
        if self.pass_brands_json:
            return self.pass_brands_json if isinstance(self.pass_brands_json, list) else []
        if self.pass_brands:
            return [p.strip() for p in self.pass_brands.split(',') if p.strip()]
        return []
    
    def set_pass_brands_list(self, value):
        """Sets pass brands - accepts list or comma-separated string."""
        if isinstance(value, list):
            self.pass_brands_json = value
        elif isinstance(value, str):
            self.pass_brands_json = [p.strip() for p in value.split(',') if p.strip()]
        else:
            self.pass_brands_json = []
    
    def get_pass_brands_display(self):
        """Returns pass brands in canonical display order."""
        brands = self.get_pass_brands_list()
        order = {b: i for i, b in enumerate(self.VALID_PASS_BRANDS)}
        return sorted(brands, key=lambda x: order.get(x, 999))
    
    @property
    def display_country_name(self):
        """Returns the resolved country name for display.
        
        Priority: country_name_override > stored country_name > empty string
        Note: No longer derives from COUNTRIES mapping (Section 5 compliant)
        """
        if self.country_name_override:
            return self.country_name_override
        return self.country_name or ''

    def get_passes(self):
        """
        Returns pass brands for this resort as a list of dicts.

        Priority:
          1. resort_pass mapping table (canonical, normalized)
          2. get_pass_brands_list() / pass_brands_json (legacy fallback)

        Returns: [{'pass_name': 'Epic', 'is_primary': True}, ...]
        'None' entries (explicit no-pass marker) are excluded from the list.
        An empty list means the resort has no major pass affiliation.

        This is the preferred read path for all new code.
        """
        try:
            rows = self.pass_mappings.all()
        except Exception:
            rows = []
        if rows:
            return [
                {'pass_name': r.pass_name, 'is_primary': r.is_primary}
                for r in rows
                if r.pass_name and r.pass_name != 'None'
            ]
        # Fall back to JSON/legacy column
        legacy = self.get_pass_brands_list()
        if not legacy:
            return []
        result = []
        for i, brand in enumerate(legacy):
            if brand and brand != 'None':
                result.append({'pass_name': brand, 'is_primary': (i == 0)})
        return result

    def get_primary_pass(self):
        """
        Returns the primary pass name for this resort, or None if no major pass.
        Reads from resort_pass mapping first, falls back to legacy columns.
        """
        passes = self.get_passes()
        if not passes:
            return None
        primary = [p for p in passes if p['is_primary']]
        if primary:
            return primary[0]['pass_name']
        return passes[0]['pass_name']

    def get_pass_names(self):
        """
        Convenience wrapper — returns a plain list of pass name strings.
        Equivalent to [p['pass_name'] for p in self.get_passes()].
        """
        return [p['pass_name'] for p in self.get_passes()]

    def __repr__(self):
        return f'<Resort {self.name} ({self.state_code or self.state})>'


class ResortPass(db.Model):
    """
    Normalized resort-to-pass mapping table.

    Canonical layer for resort-pass relationships, replacing Resort.pass_brands_json
    as the authoritative source over time. Populated via backfill from existing
    pass_brands_json data; kept in sync by admin tooling.

    Design choices:
    - One row per (resort, pass) pair (unique constraint enforced)
    - is_primary flags the main pass affiliation where a resort supports several
    - 'None' is never stored here; absence of rows = no major pass affiliation
    - Backward-compat columns (Resort.pass_brands, Resort.brand) remain untouched

    Read path (for new code): resort.get_passes() → this table → JSON fallback
    """
    __tablename__ = 'resort_pass'
    __table_args__ = (
        db.UniqueConstraint('resort_id', 'pass_name', name='uq_resort_pass'),
    )

    VALID_PASS_NAMES = ['Epic', 'Ikon', 'Mountain Collective', 'Indy', 'Other']

    id = db.Column(db.Integer, primary_key=True)
    resort_id = db.Column(
        db.Integer,
        db.ForeignKey('resort.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    pass_name = db.Column(db.String(50), nullable=False)
    is_primary = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default='false',
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resort = db.relationship(
        'Resort',
        backref=db.backref('pass_mappings', lazy='dynamic', cascade='all, delete-orphan'),
    )

    def __repr__(self):
        label = 'primary' if self.is_primary else 'secondary'
        return f'<ResortPass resort_id={self.resort_id} pass={self.pass_name} ({label})>'


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
    trip_status = db.Column(db.String(10), nullable=True)  # 'planning' or 'going'; NULL treated as 'planning'
    ride_intent = db.Column(db.String(20), nullable=True)  # 'can_offer', 'need_ride', or None
    trip_duration = db.Column(db.String(20), nullable=True)  # day_trip, one_night, two_nights, three_plus_nights
    trip_equipment_status = db.Column(db.String(20), nullable=True)  # use_default, have_own_equipment, needs_rentals (null = use_default)
    equipment_override = db.Column(db.String(20), nullable=True)  # use_default, have_own_equipment, renting
    accommodation_status = db.Column(db.String(20), nullable=True)  # none_yet, hotel, airbnb, other
    accommodation_link = db.Column(db.String(500), nullable=True)  # URL to accommodation booking
    max_participants = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_group_trip = db.Column(db.Boolean, default=False)  # True if trip has participants
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Organizer (null = legacy, use user_id)
    
    participants = db.relationship('SkiTripParticipant', backref='trip', lazy=True, cascade='all, delete-orphan')
    created_by = db.relationship('User', foreign_keys=[created_by_user_id], lazy=True)

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
            'day_trip': '1 night',
            'one_night': '1 night',
            'two_nights': '2 nights',
            'three_plus_nights': '3+ nights'
        }
        return labels.get(self.trip_duration, '1 night')
    
    @property
    def organizer_id(self):
        """Return the organizer user ID. Uses created_by_user_id if set, else user_id."""
        return self.created_by_user_id or self.user_id
    
    def get_organizer(self):
        """Return the organizer User object."""
        return db.session.get(User, self.organizer_id)
    
    def is_organizer(self, user_id):
        """Check if given user_id is the trip organizer."""
        return self.organizer_id == user_id
    
    def get_accepted_participants(self):
        """Return list of accepted SkiTripParticipant records."""
        return [p for p in self.participants if p.status == GuestStatus.ACCEPTED]
    
    def get_pending_participants(self):
        """Return list of pending/invited SkiTripParticipant records."""
        return [p for p in self.participants if p.status == GuestStatus.INVITED]
    
    def get_declined_participants(self):
        """Return list of declined SkiTripParticipant records."""
        return [p for p in self.participants if p.status == GuestStatus.DECLINED]
    
    @property
    def invited_count(self):
        """Return count of invited (pending) participants."""
        return len(self.get_pending_participants())
    
    @property
    def accepted_count(self):
        """Return count of accepted participants."""
        return len(self.get_accepted_participants())
    
    @property
    def invite_summary(self):
        """Return formatted invite summary for trip tiles (e.g., '3 invited · 1 accepted')."""
        invited = self.invited_count
        accepted = self.accepted_count
        if invited == 0 and accepted == 0:
            return None
        parts = []
        if invited > 0:
            parts.append(f"{invited} invited")
        if accepted > 0:
            parts.append(f"{accepted} accepted")
        return " · ".join(parts)
    
    def add_participant(self, user_id, status=None, role=None):
        """Add a participant to the trip. Returns the SkiTripParticipant record."""
        if status is None:
            status = GuestStatus.INVITED
        if role is None:
            role = ParticipantRole.GUEST
        existing = SkiTripParticipant.query.filter_by(trip_id=self.id, user_id=user_id).first()
        if existing:
            existing.status = status
            if role:
                existing.role = role
            return existing
        participant = SkiTripParticipant(trip_id=self.id, user_id=user_id, status=status, role=role)
        db.session.add(participant)
        if role != ParticipantRole.OWNER:
            self.is_group_trip = True
        return participant
    
    def add_owner_as_participant(self):
        """Add trip owner as a participant with OWNER role and ACCEPTED status."""
        return self.add_participant(
            self.user_id,
            status=GuestStatus.ACCEPTED,
            role=ParticipantRole.OWNER
        )
    
    def get_all_participants(self):
        """Get all participants including owner (accepted or owner role)."""
        return SkiTripParticipant.query.filter(
            SkiTripParticipant.trip_id == self.id,
            db.or_(
                SkiTripParticipant.status == GuestStatus.ACCEPTED,
                SkiTripParticipant.role == ParticipantRole.OWNER
            )
        ).all()
    
    def get_group_signals(self):
        """Get aggregated transportation and equipment counts for the group."""
        participants = self.get_all_participants()
        
        transportation = {
            'driving': 0,
            'flying': 0,
            'train': 0,
            'bus': 0,
            'train_bus': 0,
            'tbd': 0,
        }
        equipment = {
            'own': 0,
            'renting': 0,
            'needs_rentals': 0,
        }
        
        for p in participants:
            if p.transportation_status:
                key = p.transportation_status.value
                if key in transportation:
                    transportation[key] += 1
            else:
                transportation['tbd'] += 1
            
            if p.equipment_status:
                key = p.equipment_status.value
                if key in equipment:
                    equipment[key] += 1
            elif p.user and p.user.equipment_status:
                if p.user.equipment_status == EquipmentStatus.HAVE_OWN_EQUIPMENT:
                    equipment['own'] += 1
                elif p.user.equipment_status == EquipmentStatus.NEEDS_RENTALS:
                    equipment['needs_rentals'] += 1
            else:
                pass
        
        return {
            'transportation': transportation,
            'equipment': equipment,
        }


class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_seeded = db.Column(db.Boolean, default=False)
    trip_invites_allowed = db.Column(db.Boolean, default=False)  # Explicit permission for trip invites
    
    friend = db.relationship('User', foreign_keys=[friend_id], backref='friended_by')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),)

    def __repr__(self):
        return f'<Friend {self.user_id} -> {self.friend_id}>'


class SkiTripParticipant(db.Model):
    """Participant in a shared/group SkiTrip."""
    __tablename__ = 'ski_trip_participant'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('ski_trip.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(
        db.Enum(GuestStatus, name='ski_trip_participant_status_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        default=GuestStatus.INVITED,
        nullable=False
    )
    role = db.Column(
        db.Enum(ParticipantRole, name='participant_role_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        default=ParticipantRole.GUEST,
        nullable=False
    )
    transportation_status = db.Column(
        db.Enum(ParticipantTransportation, name='participant_transportation_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        nullable=True
    )
    equipment_status = db.Column(
        db.Enum(ParticipantEquipment, name='participant_equipment_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        nullable=True
    )
    taking_lesson = db.Column(
        db.Enum(LessonChoice, name='lesson_choice_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        default=LessonChoice.NO,
        nullable=False,
        server_default='no'
    )
    carpool_role = db.Column(
        db.Enum(CarpoolRole, name='carpool_role_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        nullable=True
    )
    carpool_seats = db.Column(db.Integer, nullable=True)
    needs_ride = db.Column(db.Boolean, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='ski_trip_participations')
    
    __table_args__ = (
        db.UniqueConstraint('trip_id', 'user_id', name='unique_ski_trip_participant'),
    )
    
    def get_display_transportation(self):
        """Get transportation status for display with labeled fallback."""
        if self.transportation_status:
            labels = {
                ParticipantTransportation.DRIVING: "Driving",
                ParticipantTransportation.FLYING: "Flying",
                ParticipantTransportation.TRAIN: "Train",
                ParticipantTransportation.BUS: "Bus",
                ParticipantTransportation.TBD: "Ride: Not set",
                ParticipantTransportation.OTHER: "Other",
            }
            # Handle legacy train_bus value
            if hasattr(self.transportation_status, 'value') and self.transportation_status.value == 'train_bus':
                return "Train / Bus"
            return labels.get(self.transportation_status, "Ride: Not set")
        return "Ride: Not set"
    
    def get_display_equipment(self):
        """Get equipment status for display with fallback to profile."""
        if self.equipment_status:
            labels = {
                ParticipantEquipment.OWN: "Bringing own",
                ParticipantEquipment.RENTING: "Renting",
                ParticipantEquipment.NEEDS_RENTALS: "Renting",
            }
            return labels.get(self.equipment_status, "Equipment: Not set")
        if self.user and self.user.equipment_status:
            if self.user.equipment_status == EquipmentStatus.HAVE_OWN_EQUIPMENT:
                return "Bringing own"
            elif self.user.equipment_status == EquipmentStatus.NEEDS_RENTALS:
                return "Renting"
        return "Equipment: Not set"
    
    def __repr__(self):
        return f'<SkiTripParticipant trip={self.trip_id} user={self.user_id} status={self.status.value}>'


class InviteType(PyEnum):
    OUTBOUND = "outbound"
    REQUEST = "request"


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trip_id = db.Column(db.Integer, db.ForeignKey('ski_trip.id'), nullable=True)
    invite_type = db.Column(
        db.Enum(InviteType, name='invite_type_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        default=InviteType.OUTBOUND,
        nullable=False,
        server_default='outbound'
    )
    status = db.Column(db.String(20), default='pending')  # pending, accepted, declined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('sender_id', 'receiver_id', 'trip_id', name='unique_invitation_per_trip'),)

    def __repr__(self):
        return f'<Invitation {self.invite_type.value} from {self.sender_id} to {self.receiver_id} trip={self.trip_id}>'


INVITE_EXPIRY_HOURS = 48

class InviteToken(db.Model):
    """Invite token with 48-hour expiration."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    inviter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    inviter = db.relationship("User", backref="invite_tokens")

    def is_expired(self):
        # Temporarily disable expiration for MVP
        return False

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
        db.Enum(AccommodationStatus, name='accommodation_status_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        nullable=True
    )
    transportation_status = db.Column(
        db.Enum(TransportationStatus, name='transportation_status_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
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
        db.Enum(GuestStatus, name='guest_status_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
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
        db.Enum(EquipmentSlot, name='equipment_slot_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
        nullable=True  # Made nullable for onboarding flow
    )
    discipline = db.Column(
        db.Enum(EquipmentDiscipline, name='equipment_discipline_enum', values_callable=lambda x: [e.value for e in x], create_constraint=True),
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


class DismissedInsightCard(db.Model):
    """Tracks dismissed home insight cards so they don't resurface for the same combination."""
    __tablename__ = 'dismissed_insight_card'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    card_type = db.Column(db.String(64), nullable=False)
    card_key = db.Column(db.String(255), nullable=False)
    dismissed_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='dismissed_insight_cards')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'card_type', 'card_key', name='uq_dismissed_insight_card'),
    )

    def __repr__(self):
        return f'<DismissedInsightCard user={self.user_id} type={self.card_type} key={self.card_key}>'


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


class ActivityType(PyEnum):
    """Types of activity for the friends feed."""
    TRIP_CREATED = "trip_created"
    TRIP_UPDATED = "trip_updated"
    FRIEND_JOINED_TRIP = "friend_joined_trip"
    TRIP_INVITE_RECEIVED = "trip_invite_received"
    TRIP_INVITE_ACCEPTED = "trip_invite_accepted"
    TRIP_INVITE_DECLINED = "trip_invite_declined"
    CONNECTION_ACCEPTED = "connection_accepted"
    TRIP_OVERLAP = "trip_overlap"
    FRIEND_TRIP_OVERLAPS_AVAILABILITY = "friend_trip_overlaps_availability"
    CARPOOL_OFFERED = "carpool_offered"
    JOIN_REQUEST_RECEIVED = "join_request_received"
    JOIN_REQUEST_ACCEPTED = "join_request_accepted"
    JOIN_REQUEST_DECLINED = "join_request_declined"


class Activity(db.Model):
    """Activity feed entries for friends updates."""
    __tablename__ = 'activity'
    
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # ActivityType value
    object_type = db.Column(db.String(20), nullable=False)  # "trip" | "user"
    object_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    extra_data = db.Column(db.JSON, nullable=True)  # For grouped updates (friend_ids, trip_ids, dates, etc.)
    
    actor = db.relationship('User', foreign_keys=[actor_user_id], backref='activities_performed')
    recipient = db.relationship('User', foreign_keys=[recipient_user_id], backref='activities_received')
    
    def __repr__(self):
        return f'<Activity {self.type} actor={self.actor_user_id} recipient={self.recipient_user_id}>'
    
    def get_trip(self):
        """Get the associated trip if object_type is 'trip'."""
        if self.object_type == 'trip':
            return db.session.get(SkiTrip, self.object_id)
        return None
    
    def get_actor_user(self):
        """Get the actor User object."""
        return db.session.get(User, self.actor_user_id)


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


