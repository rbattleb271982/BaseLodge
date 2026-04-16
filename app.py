"""
========================================
BaseLodge Application
========================================

SYSTEM OF RECORD (as of 2026-01-15):
  Supabase is the single system of record for resorts and core app data.
  
  - Resort data: 693 resorts imported from prod_resorts_full.xlsx
  - Schema: Managed exclusively via Flask-Migrate/Alembic
  - Database: SUPABASE_DATABASE_URL environment variable
  
  DO NOT use db.create_all() or run legacy seed scripts.
  All schema changes must go through migrations.
========================================
"""

import os
import secrets
from datetime import datetime, date, timedelta

def _resolve_base_url():
    """Resolve the base URL for invite links and other absolute URLs.

    Priority:
    1. REPLIT_DEV_DOMAIN (only present in the Replit IDE/dev environment, never
       in deployed apps) — ensures invite links point to the current dev server,
       not the hardcoded production domain.
    2. BASE_URL env var (explicit override for production deployments)
    3. Hardcoded production fallback
    """
    replit_domain = os.getenv("REPLIT_DEV_DOMAIN")
    if replit_domain:
        resolved = f"https://{replit_domain}"
        print(f"[BASE_URL] Dev mode — using REPLIT_DEV_DOMAIN: {resolved}")
        return resolved
    explicit = os.getenv("BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    return "https://app.baselodgeapp.com"

BASE_URL = _resolve_base_url()
import sqlalchemy as sa
from sqlalchemy import func
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation, InviteToken, Resort, GroupTrip, TripGuest, GuestStatus, check_shared_upcoming_trip, EquipmentSetup, EquipmentSlot, EquipmentDiscipline, AccommodationStatus, TransportationStatus, DismissedNudge, Event, SkiTripParticipant, ParticipantRole, ParticipantTransportation, ParticipantEquipment, Activity, ActivityType, LessonChoice, CarpoolRole, InviteType
from debug_routes import debug_bp
from services.open_dates import get_open_date_matches
from services.ideas_engine import build_overlap_windows, build_wishlist_overlaps
from io import BytesIO
import segno
import random
import click
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import unicodedata
import re


def generate_resort_slug(name):
    """Generate a URL-safe slug from resort name.
    
    - Lowercase
    - Hyphen-separated
    - ASCII-safe (unicode normalized)
    - Deterministic (same name -> same slug)
    - Never null or empty
    """
    if not name:
        raise ValueError("Resort name is required for slug generation")
    
    # Normalize unicode to ASCII
    slug = unicodedata.normalize('NFKD', str(name))
    slug = slug.encode('ascii', 'ignore').decode('ascii')
    
    # Lowercase
    slug = slug.lower()
    
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    
    # Strip leading/trailing hyphens
    slug = slug.strip('-')
    
    if not slug:
        raise ValueError(f"Could not generate valid slug from name: {name}")
    
    return slug

# ============================================================================
# PROFILE CONSOLIDATION NOTE:
# The app no longer uses /profile or profile.html.
# All profile-related UI lives under /more.
# Do NOT reintroduce profile routes or templates.
# ============================================================================

is_production = os.environ.get("SUPABASE_DATABASE_URL") is not None and "postgresql" in os.environ.get("SUPABASE_DATABASE_URL", "")

# Enforce Supabase connection for resort-related operations
SUPABASE_URL = os.environ.get("SUPABASE_DATABASE_URL")
if not SUPABASE_URL:
    if is_production:
        raise RuntimeError("CRITICAL: SUPABASE_DATABASE_URL is not set in production. App startup aborted.")
    else:
        # Loud warning for development
        print("!" * 70)
        print("⚠️  WARNING: SUPABASE_DATABASE_URL is not set.")
        print("⚠️  Development will fallback to local SQLite but Resort data will be MISSING.")
        print("!" * 70)

app = Flask(__name__)
app.config["PREFERRED_URL_SCHEME"] = "https"

@app.before_request
def redirect_to_canonical_domain():
    parsed_url = urlparse(request.url)
    hostname = parsed_url.hostname.lower() if parsed_url.hostname else ""

    if hostname.endswith("replit.app"):
        new_url = request.url.replace(
            f"{parsed_url.scheme}://{parsed_url.netloc}",
            "https://app.baselodgeapp.com",
            1
        )
        return redirect(new_url, code=301)

# ============================================================================
# SESSION & SECURITY CONFIGURATION
# ============================================================================
app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET")
if not app.config["SECRET_KEY"]:
    if not is_production:
        app.config["SECRET_KEY"] = "dev-secret-key-fallback"
    else:
        raise RuntimeError("SESSION_SECRET environment variable is NOT SET in production.")

# Session configuration for Replit iframe environment
app.config.update(
    SESSION_COOKIE_SECURE=is_production,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_REFRESH_EACH_REQUEST=True
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth"
login_manager.login_message = None

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

from utils.countries import COUNTRIES, STATE_ABBR_MAP

@app.context_processor
def inject_countries():
    return {'COUNTRIES': COUNTRIES}

# Helper to normalize country code
def normalize_country_code(code):
    if not code:
        return None
    code = code.strip().upper()
    if code in COUNTRIES:
        return code
    return None

@app.route("/health")
def health_check():
    """Health check endpoint for production probes. Returns JSON status and DB connectivity check."""
    try:
        # Lightweight query to verify DB connectivity
        db.session.execute(sa.text("SELECT 1")).fetchone()
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "environment": os.environ.get("FLASK_ENV", "development"),
            "timestamp": datetime.utcnow().isoformat()
        }), 200
    except Exception as e:
        app.logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e) if not is_production else "Internal Server Error"
        }), 500

def get_upcoming_trip_count(user):
    """
    Returns the count of unique strictly future trips a user is committed to.
    'Committed' means being the owner or an ACCEPTED participant.
    Filters:
    - Deduplicate by trip.id
    - Includes owner or ACCEPTED participant role
    - Filters for start_date > today (upcoming strictly future)
    - Excludes in-progress, past, canceled, archived, or pending states
    """
    if not user:
        return 0
    
    today = date.today()
    
    # 1. Trips owned by the user
    owned_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date > today
    ).all()

    # 2. Trips where the user is an ACCEPTED participant
    participant_trips = (
        db.session.query(SkiTrip)
        .join(SkiTripParticipant, SkiTrip.id == SkiTripParticipant.trip_id)
        .filter(
            SkiTripParticipant.user_id == user.id,
            SkiTripParticipant.status == GuestStatus.ACCEPTED,
            SkiTrip.start_date > today
        )
        .all()
    )

    # Deduplicate by trip ID
    all_upcoming_trips = {t.id for t in owned_trips}
    for t in participant_trips:
        all_upcoming_trips.add(t.id)

    return len(all_upcoming_trips)


def get_past_trip_count(user):
    """Returns the count of trips owned by user that have already ended."""
    if not user:
        return 0
    return SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.end_date < date.today()
    ).count()


@app.template_filter('display_name')
def display_name_filter(user, current_user_id=None):
    """
    Returns full name (First Last) or 'You' if viewing own profile.
    Usage in templates: {{ user|display_name(current_user.id) }}
    """
    try:
        if not user:
            return ""
        user_id = getattr(user, 'id', None)
        if current_user_id and user_id == current_user_id:
            return "You"
        first = getattr(user, 'first_name', '') or ''
        last = getattr(user, 'last_name', '') or ''
        full_name = f"{first} {last}".strip()
        return full_name if full_name else "Friend"
    except Exception:
        return "Friend"


def format_passes_display(pass_type):
    """
    Helper to format passes as 'Epic · Ikon' style.
    Filters out 'Both' and empty values.
    """
    if not pass_type:
        return ''
    pass_str = str(pass_type).strip()
    if ',' in pass_str:
        passes = [p.strip() for p in pass_str.split(',') if p.strip() and p.strip().lower() not in ('both', 'none', "i don't have a pass")]
        return ' · '.join(passes) if passes else ''
    if pass_str.lower() in ('both', 'none', "i don't have a pass"):
        return ''
    return pass_str


@app.template_filter('identity_line')
def identity_line_filter(user):
    """
    Formats user identity as: Rider type · Level · Pass(es)
    Example: Skier · Advanced · Epic · Ikon
    """
    try:
        if not user:
            return ""

        parts = []

        # Rider type — use display_rider_type which correctly handles
        # legacy comma-separated entries like ["Skier,Snowboarder"] → "Skier + Snowboarder"
        display_rider = getattr(user, 'display_rider_type', None)
        if display_rider:
            parts.append(display_rider)

        # Skill level
        skill_level = getattr(user, "skill_level", None)
        if skill_level:
            parts.append(str(skill_level))

        # Passes (formatted properly with · separator)
        pass_type = getattr(user, "pass_type", None)
        if pass_type:
            formatted_passes = format_passes_display(pass_type)
            if formatted_passes:
                # Split individual passes and add each as a part
                for p in formatted_passes.split(' · '):
                    parts.append(p)

        return " · ".join(parts)

    except Exception:
        return ""

@app.template_filter('pass_display')
def pass_display_filter(pass_type):
    """
    Displays passes individually as 'Epic · Ikon'.
    Use for standalone pass display in stats cards and settings.
    """
    return format_passes_display(pass_type)


@app.template_filter('country_name')
def country_name_filter(code):
    """
    Returns full country name from ISO code.
    Usage: {{ resort.country_code|country_name }}
    """
    if not code:
        return ""
    return COUNTRIES.get(code.upper(), code)


@app.template_filter('mountain_passes')
def mountain_passes_filter(resort):
    """
    Formats mountain pass brands as 'Epic · Ikon' (no "Pass" suffix).
    Returns empty string if no passes.
    Usage: {{ trip.resort|mountain_passes }}
    """
    if not resort:
        return ""
    pass_brands = getattr(resort, 'pass_brands', None)
    if not pass_brands:
        return ""
    # Split comma-separated, filter empties and normalize
    brands = [b.strip() for b in str(pass_brands).split(',') if b.strip()]
    # Filter out placeholder values
    brands = [b for b in brands if b.lower() not in ('none', 'n/a', '')]
    if not brands:
        return ""
    return ' · '.join(brands)


@app.template_filter('state_abbrev')
def state_abbrev_filter(resort_or_code):
    """
    Returns state abbreviation (e.g., 'CO').
    Accepts resort object or state_code string.
    Usage: {{ trip.resort|state_abbrev }} or {{ 'Colorado'|state_abbrev }}
    """
    if not resort_or_code:
        return ""
    # If it's a resort object, get state_code
    if hasattr(resort_or_code, 'state_code'):
        return resort_or_code.state_code or ""
    # If it's already a short code (2-3 chars), return as-is
    if isinstance(resort_or_code, str) and len(resort_or_code) <= 3:
        return resort_or_code
    return ""


@app.template_filter('state_fullname')
def state_fullname_filter(resort_or_code):
    """
    Returns full state name (e.g., 'Colorado').
    Accepts resort object or state_name string.
    Falls back to state_code or state field if state_name not available.
    Usage: {{ trip.resort|state_fullname }}
    """
    if not resort_or_code:
        return ""
    # If it's a resort object, get state_name with fallbacks
    if hasattr(resort_or_code, 'state_name'):
        return resort_or_code.state_name or getattr(resort_or_code, 'state', '') or ""
    # Also try state field directly (for legacy objects)
    if hasattr(resort_or_code, 'state'):
        return resort_or_code.state or ""
    # If it's already a string, return as-is
    if isinstance(resort_or_code, str):
        return resort_or_code
    return ""


@app.template_filter('relative_time')
def relative_time_filter(dt):
    """
    Convert datetime to relative time string (e.g., "2h ago", "Yesterday").
    """
    if not dt:
        return ''
    
    now = datetime.utcnow()
    diff = now - dt
    
    seconds = diff.total_seconds()
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{int(seconds // 60)}m ago'
    if seconds < 86400:
        return f'{int(seconds // 3600)}h ago'
    if seconds < 172800:
        return 'Yesterday'
    return dt.strftime('%b %d')


@app.template_filter('format_name')
def format_name_filter(name):
    from utils.formatting import format_name
    return format_name(name)


@app.before_request
def before_request_handlers():
    import sys
    
    # Make sessions permanent for Replit iframe compatibility
    session.permanent = True
    
    # HARD BYPASS: Invite routes must work for anonymous users - skip ALL auth/profile logic
    if request.path.startswith("/invite/"):
        return None
    
    # Bypass for health check endpoint
    if request.endpoint == 'health_check':
        return None
    
    # Require profile setup for authenticated users
    excluded_endpoints = {'auth', 'identity_setup', 'setup_profile', 'logout', 'static', 'invite_token_landing', 'test_login_direct', 'forgot_password', 'reset_password', 'index'}
    if request.endpoint in excluded_endpoints:
        return None
    
    # DIAGNOSTIC: before_request (only for non-bypassed routes)
    if request.endpoint and request.endpoint not in ['static', 'root']:
        print("=== BEFORE_REQUEST ===", file=sys.stderr)
        print("endpoint:", request.endpoint, file=sys.stderr)
        print("current_user.is_authenticated:", current_user.is_authenticated, file=sys.stderr)
        print("session:", dict(session), file=sys.stderr)
        print("cookies:", dict(request.cookies), file=sys.stderr)
        print("=====================", file=sys.stderr)
    if current_user.is_authenticated:
        # Check for profile completion: rider_types (new) or primary_rider_type/rider_type (legacy) + pass_type
        has_rider_types = current_user.rider_types and len(current_user.rider_types) > 0
        has_rider_type_legacy = current_user.primary_rider_type or current_user.rider_type
        if not (has_rider_types or has_rider_type_legacy) or not current_user.pass_type:
            return redirect(url_for('identity_setup'))
    return None

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        admin_emails_str = os.environ.get("ALLOWED_ADMIN_EMAILS", "richardbattlebaxter@gmail.com,battle@battle.com")
        admin_emails = [e.strip().lower() for e in admin_emails_str.split(",") if e.strip()]
        if not current_user.is_authenticated or current_user.email.lower() not in admin_emails:
            if request.path.startswith('/api/'):
                return jsonify({'status': 'error', 'message': 'Admin privileges required'}), 403
            return "Admin privileges required.", 403
        return f(*args, **kwargs)
    return wrapper

def emit_event(event_name, user, payload=None):
    """Emit high-signal event, skip if user is seeded (test data)."""
    if user.is_seeded:
        return
    event = Event(
        event_name=event_name,
        user_id=user.id,
        payload=payload or {},
        created_at=datetime.utcnow(),
        environment='prod' if is_production else 'dev'
    )
    db.session.add(event)
    db.session.commit()


def get_friend_ids(user_id):
    """Get all direct friend IDs for a user."""
    friends = Friend.query.filter_by(user_id=user_id).all()
    return [f.friend_id for f in friends]


def create_activity(actor_user_id, recipient_user_id, activity_type, object_type, object_id):
    """Create an activity record."""
    if actor_user_id == recipient_user_id:
        return
    activity = Activity(
        actor_user_id=actor_user_id,
        recipient_user_id=recipient_user_id,
        type=activity_type.value if hasattr(activity_type, 'value') else activity_type,
        object_type=object_type,
        object_id=object_id,
        created_at=datetime.utcnow()
    )
    db.session.add(activity)


def emit_trip_created_activities(trip, actor_user_id):
    """Create TRIP_CREATED activities for all friends of the actor."""
    friend_ids = get_friend_ids(actor_user_id)
    for friend_id in friend_ids:
        create_activity(
            actor_user_id=actor_user_id,
            recipient_user_id=friend_id,
            activity_type=ActivityType.TRIP_CREATED,
            object_type='trip',
            object_id=trip.id
        )
    check_and_emit_trip_overlap_activities(trip, actor_user_id)
    emit_availability_overlap_activities_for_trip(trip)


def emit_trip_updated_activities(trip, actor_user_id, dates_changed=False):
    """Create TRIP_UPDATED activities for all friends if dates changed."""
    if not dates_changed:
        return
    friend_ids = get_friend_ids(actor_user_id)
    for friend_id in friend_ids:
        create_activity(
            actor_user_id=actor_user_id,
            recipient_user_id=friend_id,
            activity_type=ActivityType.TRIP_UPDATED,
            object_type='trip',
            object_id=trip.id
        )
    check_and_emit_trip_overlap_activities(trip, actor_user_id)
    emit_availability_overlap_activities_for_trip(trip)


def check_and_emit_trip_overlap_activities(trip, actor_user_id):
    """Check for overlapping trips with friends and emit TRIP_OVERLAP activities."""
    friend_ids = get_friend_ids(actor_user_id)
    if not friend_ids:
        return
    
    overlapping_trips = SkiTrip.query.filter(
        SkiTrip.user_id.in_(friend_ids),
        SkiTrip.start_date <= trip.end_date,
        SkiTrip.end_date >= trip.start_date,
        db.or_(
            SkiTrip.resort_id == trip.resort_id,
            SkiTrip.mountain == trip.mountain
        )
    ).all()
    
    notified_users = set()
    for overlap_trip in overlapping_trips:
        if overlap_trip.user_id not in notified_users:
            create_activity(
                actor_user_id=actor_user_id,
                recipient_user_id=overlap_trip.user_id,
                activity_type=ActivityType.TRIP_OVERLAP,
                object_type='trip',
                object_id=trip.id
            )
            notified_users.add(overlap_trip.user_id)


def emit_connection_accepted_activity(actor_user_id, other_user_id):
    """Create CONNECTION_ACCEPTED activity when a friend request is accepted."""
    create_activity(
        actor_user_id=actor_user_id,
        recipient_user_id=other_user_id,
        activity_type=ActivityType.CONNECTION_ACCEPTED,
        object_type='user',
        object_id=actor_user_id
    )


def emit_trip_invite_accepted_activity(trip, acceptor_user_id, trip_owner_id):
    """Create TRIP_INVITE_ACCEPTED activity for the trip owner."""
    create_activity(
        actor_user_id=acceptor_user_id,
        recipient_user_id=trip_owner_id,
        activity_type=ActivityType.TRIP_INVITE_ACCEPTED,
        object_type='trip',
        object_id=trip.id
    )


def emit_trip_invite_received_activity(trip, inviter_user_id, invitee_user_id):
    """Create TRIP_INVITE_RECEIVED activity for the invited user."""
    create_activity(
        actor_user_id=inviter_user_id,
        recipient_user_id=invitee_user_id,
        activity_type=ActivityType.TRIP_INVITE_RECEIVED,
        object_type='trip',
        object_id=trip.id
    )


def emit_trip_invite_declined_activity(trip, decliner_user_id, trip_owner_id):
    """Create TRIP_INVITE_DECLINED activity for the trip owner."""
    create_activity(
        actor_user_id=decliner_user_id,
        recipient_user_id=trip_owner_id,
        activity_type=ActivityType.TRIP_INVITE_DECLINED,
        object_type='trip',
        object_id=trip.id
    )


def emit_friend_joined_trip_activities(trip, joiner_user_id):
    """Create FRIEND_JOINED_TRIP activities for other participants on the trip."""
    participants = SkiTripParticipant.query.filter(
        SkiTripParticipant.trip_id == trip.id,
        SkiTripParticipant.user_id != joiner_user_id,
        SkiTripParticipant.status == GuestStatus.ACCEPTED
    ).all()
    
    joiner_friend_ids = set(get_friend_ids(joiner_user_id))
    
    for participant in participants:
        if participant.user_id in joiner_friend_ids:
            create_activity(
                actor_user_id=joiner_user_id,
                recipient_user_id=participant.user_id,
                activity_type=ActivityType.FRIEND_JOINED_TRIP,
                object_type='trip',
                object_id=trip.id
            )


def delete_activities_for_trip(trip_id):
    """Delete all activities related to a trip (application-level cleanup)."""
    Activity.query.filter(
        Activity.object_type == 'trip',
        Activity.object_id == trip_id
    ).delete()


def emit_carpool_activity(user, trip, seats):
    """Emit carpool offered activity to friends with overlapping trip dates.
    
    Only emits to friends with trips that overlap dates and location.
    Group trips do not emit carpool activities (handled at caller).
    """
    if user.is_seeded:
        return
    
    friend_ids = get_friend_ids(user.id)
    if not friend_ids:
        return
    
    # Find friends with overlapping trips at the same location
    overlapping_friends = set()
    for friend_id in friend_ids:
        friend_trips = SkiTrip.query.filter(
            SkiTrip.user_id == friend_id,
            SkiTrip.start_date <= trip.end_date,
            SkiTrip.end_date >= trip.start_date,
            db.or_(
                SkiTrip.mountain == trip.mountain,
                SkiTrip.resort_id == trip.resort_id
            ) if trip.resort_id else SkiTrip.mountain == trip.mountain
        ).first()
        if friend_trips:
            overlapping_friends.add(friend_id)
    
    # Create activity for each overlapping friend
    mountain_name = trip.mountain or (trip.resort.name if trip.resort else 'Unknown')
    for friend_id in overlapping_friends:
        activity = Activity(
            actor_user_id=user.id,
            recipient_user_id=friend_id,
            type=ActivityType.CARPOOL_OFFERED.value,
            object_type='trip',
            object_id=trip.id,
            extra_data={
                'seats': seats,
                'mountain': mountain_name
            }
        )
        db.session.add(activity)
    
    if overlapping_friends:
        db.session.commit()


def coalesce_date_ranges(date_ranges):
    """Merge contiguous or overlapping date ranges into continuous ranges.
    
    Args:
        date_ranges: List of (start_date, end_date) tuples
        
    Returns:
        List of merged (start_date, end_date) tuples
    """
    if not date_ranges:
        return []
    
    sorted_ranges = sorted(date_ranges, key=lambda x: x[0])
    merged = [sorted_ranges[0]]
    
    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + timedelta(days=1):
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    
    return merged


def compute_friend_trip_availability_overlaps(user):
    """Compute overlaps between user's open availability and friends' trips.
    
    Returns a list of overlap groups, each containing:
    - overlap_start_date, overlap_end_date
    - list of (friend_id, trip_id, resort_id, resort_name, state, country)
    """
    if not user.open_dates:
        print("DEBUG_COMPUTE: User has no open_dates field")
        return []
    
    user_open_dates = set()
    for d in user.open_dates:
        try:
            if isinstance(d, str):
                user_open_dates.add(datetime.strptime(d, '%Y-%m-%d').date())
            else:
                user_open_dates.add(d)
        except (ValueError, TypeError):
            continue
    
    if not user_open_dates:
        print("DEBUG_COMPUTE: Parsed user_open_dates is empty")
        return []
    
    print(f"DEBUG_COMPUTE: User has {len(user_open_dates)} parsed open dates")
    friend_ids = get_friend_ids(user.id)
    if not friend_ids:
        print("DEBUG_COMPUTE: User has no friends")
        return []
    
    friend_trips = SkiTrip.query.filter(
        SkiTrip.user_id.in_(friend_ids),
        SkiTrip.end_date >= date.today()
    ).all()
    print(f"DEBUG_COMPUTE: Found {len(friend_trips)} active friend trips")
    
    overlap_by_range = {}
    
    for trip in friend_trips:
        trip_dates = set()
        current = trip.start_date
        while current <= trip.end_date:
            trip_dates.add(current)
            current += timedelta(days=1)
        
        overlapping_dates = user_open_dates & trip_dates
        if not overlapping_dates:
            continue
        
        print(f"DEBUG_COMPUTE: Trip {trip.id} to {trip.mountain} has {len(overlapping_dates)} overlapping days")
        sorted_dates = sorted(overlapping_dates)
        ranges = []
        range_start = sorted_dates[0]
        range_end = sorted_dates[0]
        
        for d in sorted_dates[1:]:
            if d == range_end + timedelta(days=1):
                range_end = d
            else:
                ranges.append((range_start, range_end))
                range_start = d
                range_end = d
        ranges.append((range_start, range_end))
        
        resort = Resort.query.get(trip.resort_id) if trip.resort_id else None
        resort_name = resort.name if resort else (trip.mountain or "Unknown")
        state = resort.state_code if resort else None
        country = resort.country_code if resort else None
        
        # Get friend user data for display
        friend_user = User.query.get(trip.user_id)
        friend_first_name = friend_user.first_name if friend_user else "Friend"
        friend_last_name = friend_user.last_name if friend_user else ""
        
        for range_start, range_end in ranges:
            key = (range_start, range_end)
            if key not in overlap_by_range:
                overlap_by_range[key] = []
            overlap_by_range[key].append({
                'friend_id': trip.user_id,
                'trip_id': trip.id,
                'resort_id': trip.resort_id,
                'resort_name': resort_name,
                'state': state,
                'country': country,
                'first_name': friend_first_name,
                'last_name': friend_last_name
            })
    
    coalesced = coalesce_date_ranges(list(overlap_by_range.keys()))
    
    result = []
    for start, end in coalesced:
        friends_data = []
        for (r_start, r_end), data_list in overlap_by_range.items():
            if r_start >= start and r_end <= end:
                friends_data.extend(data_list)
        
        seen_trips = set()
        unique_friends_data = []
        for d in friends_data:
            if d['trip_id'] not in seen_trips:
                unique_friends_data.append(d)
                seen_trips.add(d['trip_id'])
        
        if unique_friends_data:
            result.append({
                'overlap_start_date': start,
                'overlap_end_date': end,
                'friends': unique_friends_data
            })
    
    return result


def delete_availability_overlap_activities_for_trip(trip_id):
    """Delete all FRIEND_TRIP_OVERLAPS_AVAILABILITY activities that reference a specific trip."""
    activities = Activity.query.filter(
        Activity.type == ActivityType.FRIEND_TRIP_OVERLAPS_AVAILABILITY.value
    ).all()
    
    for activity in activities:
        if activity.extra_data and trip_id in activity.extra_data.get('trip_ids', []):
            db.session.delete(activity)


def emit_availability_overlap_activities_for_user(user):
    """Create or update FRIEND_TRIP_OVERLAPS_AVAILABILITY activities for a user.
    
    Called when:
    - User updates their open availability dates
    - A friend creates or edits a trip
    """
    Activity.query.filter(
        Activity.recipient_user_id == user.id,
        Activity.type == ActivityType.FRIEND_TRIP_OVERLAPS_AVAILABILITY.value
    ).delete()
    
    overlaps = compute_friend_trip_availability_overlaps(user)
    
    for overlap in overlaps:
        friend_ids = list(set(f['friend_id'] for f in overlap['friends']))
        trip_ids = list(set(f['trip_id'] for f in overlap['friends']))
        resort_ids = list(set(f['resort_id'] for f in overlap['friends'] if f['resort_id']))
        states = list(set(f['state'] for f in overlap['friends'] if f['state']))
        countries = list(set(f['country'] for f in overlap['friends'] if f['country']))
        
        actor_id = friend_ids[0] if friend_ids else user.id
        
        extra_data = {
            'friend_ids': friend_ids,
            'trip_ids': trip_ids,
            'overlap_start_date': overlap['overlap_start_date'].isoformat(),
            'overlap_end_date': overlap['overlap_end_date'].isoformat(),
            'resort_ids': resort_ids,
            'friends_data': overlap['friends'],
            'state': states,
            'country': countries
        }
        
        activity = Activity(
            actor_user_id=actor_id,
            recipient_user_id=user.id,
            type=ActivityType.FRIEND_TRIP_OVERLAPS_AVAILABILITY.value,
            object_type='availability',
            object_id=user.id,
            created_at=datetime.utcnow(),
            extra_data=extra_data
        )
        db.session.add(activity)


def emit_availability_overlap_activities_for_trip(trip):
    """Recompute availability overlaps for all friends when a trip is created/edited."""
    friend_ids = get_friend_ids(trip.user_id)
    
    for friend_id in friend_ids:
        friend = User.query.get(friend_id)
        if friend and friend.open_dates:
            emit_availability_overlap_activities_for_user(friend)


# Database Configuration
supabase_url = os.environ.get("SUPABASE_DATABASE_URL")
if supabase_url:
    supabase_url = supabase_url.strip().strip('"').strip("'")
    if supabase_url.startswith("postgres://"):
        supabase_url = "postgresql://" + supabase_url[len("postgres://"):]
    if supabase_url.startswith("postgresql+psycopg2://"):
        supabase_url = "postgresql://" + supabase_url[len("postgresql+psycopg2://"):]
    for bad_prefix in ["postgresql+asyncpg://", "postgresql+aiopg://"]:
        if supabase_url.startswith(bad_prefix):
            supabase_url = "postgresql://" + supabase_url[len(bad_prefix):]
    if supabase_url.startswith(("postgresql://", "postgres://")) and "@" in supabase_url and "://" in supabase_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = supabase_url
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///baselodge.db"
else:
    if is_production:
        raise RuntimeError("SUPABASE_DATABASE_URL must be set in production.")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///baselodge.db"

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)

# Auto-create tables for SQLite (local development only)
if "sqlite" in app.config.get("SQLALCHEMY_DATABASE_URI", ""):
    with app.app_context():
        db.create_all()
app.register_blueprint(debug_bp)

# ============================================================================
# PRODUCTION DIAGNOSTICS - Print on startup
# ============================================================================
def log_startup_diagnostics():
    """Log database and user counts on startup for debugging."""
    try:
        with app.app_context():
            db_url = os.environ.get("SUPABASE_DATABASE_URL")
            
            # Mask credentials
            if db_url and "@" in db_url:
                safe_db = db_url.split("@")[-1]
            elif not is_production:
                safe_db = "DEVELOPMENT FALLBACK: SQLite (baselodge.db)"
            else:
                safe_db = "ERROR: NOT SET"
            
            print("=" * 70)
            print("🔧 BASELODGE STARTUP DIAGNOSTICS")
            print("=" * 70)
            print(f"DATABASE: {safe_db}")
            print(f"PRODUCTION MODE: {is_production}")
            
            # Count records
            user_count = User.query.count()
            friend_count = Friend.query.count()
            trip_count = SkiTrip.query.count()
            
            print("USER COUNT: " + str(user_count))
            print("FRIEND COUNT: " + str(friend_count))
            print("TRIP COUNT: " + str(trip_count))
            print("=" * 70)
            print("✅ BaseLodge started successfully and is ready to serve requests.")
            print("=" * 70)
            
            # Check specific users
            richard = User.query.filter(db.func.lower(User.email) == "richardbattlebaxter@gmail.com").first()
            jonathan = User.query.filter(db.func.lower(User.email) == "jonathanmschmitz@gmail.com").first()
            
            if richard:
                richard_friends = Friend.query.filter_by(user_id=richard.id).count()
                print(f"RICHARD (id={richard.id}): {richard_friends} friends")
            else:
                print("RICHARD: NOT FOUND")
            
            if jonathan:
                jonathan_friends = Friend.query.filter_by(user_id=jonathan.id).count()
                print(f"JONATHAN (id={jonathan.id}): {jonathan_friends} friends")
            else:
                print("JONATHAN: NOT FOUND")
            
            print("=" * 70)
    except Exception as e:
        print(f"⚠️ STARTUP DIAGNOSTICS FAILED: {e}")

# Run diagnostics on import (will show in server logs)
import atexit
@app.before_request
def run_startup_diagnostics_once():
    """Run startup diagnostics once on first request."""
    if not hasattr(app, '_diagnostics_run'):
        app._diagnostics_run = True
        log_startup_diagnostics()

# ============================================================================
# ERROR HANDLERS - Must be registered at module level, not inside functions
# ============================================================================
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found errors with user-friendly template."""
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors with full traceback logging."""
    import traceback
    import sys
    print("=" * 70)
    print("🚨 INTERNAL SERVER ERROR (500)")
    print("=" * 70)
    print(f"Error: {error}")
    print("Full traceback:")
    traceback.print_exc(file=sys.stdout)
    print("=" * 70)
    db.session.rollback()
    return render_template("500.html"), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle all exceptions with full traceback logging (except HTTP errors)."""
    from werkzeug.exceptions import HTTPException
    
    # Don't catch HTTP errors like 404 - let them return normally
    if isinstance(e, HTTPException):
        if e.code == 404:
            return render_template("404.html"), 404
        return e
    
    import traceback
    import sys
    print("=" * 70)
    print(f"🚨 UNHANDLED EXCEPTION: {type(e).__name__}")
    print("=" * 70)
    print(f"Error: {e}")
    print("Full traceback:")
    traceback.print_exc(file=sys.stdout)
    print("=" * 70)
    db.session.rollback()
    return render_template("500.html"), 500

def get_or_create_invite_token(user):
    """Get existing valid invite token for user or create a new one.
    
    Returns None if user has reached their max invite accepts limit.
    Single-use tokens: each token can only be used once (used_at is set on use).
    """
    # Check if user can still accept more invites
    if not can_sender_accept_more_invites(user):
        return None
    
    # Look for existing unused token (most recent first)
    existing = InviteToken.query.filter_by(inviter_id=user.id).order_by(InviteToken.created_at.desc()).all()
    for token_obj in existing:
        if not token_obj.is_used():
            return token_obj
    
    # Create new token with 48-hour expiration
    token = secrets.token_urlsafe(16)
    expires_at = datetime.utcnow() + timedelta(hours=48)
    invite = InviteToken(token=token, inviter_id=user.id, expires_at=expires_at)
    db.session.add(invite)
    db.session.commit()
    return invite

def can_sender_accept_more_invites(user):
    """Check if sender can accept more invites. Always returns True since invite limits are removed."""
    return True

def count_friends_open_on_same_dates(user):
    """Count UNIQUE friends who have open dates overlapping with the current user.
    
    Returns:
        tuple: (friend_count, user_has_open_dates)
    """
    try:
        today = date.today()
        today_str = today.strftime('%Y-%m-%d')
        
        # Get user's future open dates
        user_open_dates = set(user.open_dates or [])
        user_open_dates = {d for d in user_open_dates if d >= today_str}
        
        # If no open dates, return 0 count but indicate user has no dates
        if not user_open_dates:
            return 0, False
        
        # Get user's friends
        friend_links = Friend.query.filter_by(user_id=user.id).all()
        friend_ids = [f.friend_id for f in friend_links]
        
        if not friend_ids:
            return 0, True
        
        # Get friends' data
        friends = User.query.filter(User.id.in_(friend_ids)).all()
        
        # Count unique friends with overlapping open dates
        matching_friends = set()
        for friend in friends:
            friend_dates = set(friend.open_dates or [])
            # Check if there's any intersection
            if user_open_dates & friend_dates:
                matching_friends.add(friend.id)
        
        return len(matching_friends), True
    except Exception as e:
        app.logger.warning(f"Error counting open date friends: {e}")
        return 0, False

STATE_ABBR = {
    "Alaska": "AK",
    "California": "CA",
    "Colorado": "CO",
    "Idaho": "ID",
    "Maine": "ME",
    "Michigan": "MI",
    "Montana": "MT",
    "New Hampshire": "NH",
    "New Mexico": "NM",
    "New York": "NY",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Utah": "UT",
    "Vermont": "VT",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wyoming": "WY"
}

STATE_NAMES = {v: k for k, v in STATE_ABBR.items()}

COUNTRY_NAMES = {
    "US": "United States",
    "CA": "Canada",
    "JP": "Japan",
    "FR": "France",
    "CH": "Switzerland",
    "AT": "Austria",
    "IT": "Italy",
    "CL": "Chile",
    "ES": "Spain",
    "NO": "Norway",
    "SE": "Sweden",
}

ALL_US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming")
]

ALL_CANADA_PROVINCES = [
    ("AB", "Alberta"), ("BC", "British Columbia"), ("MB", "Manitoba"),
    ("NB", "New Brunswick"), ("NL", "Newfoundland and Labrador"), ("NS", "Nova Scotia"),
    ("NT", "Northwest Territories"), ("NU", "Nunavut"), ("ON", "Ontario"),
    ("PE", "Prince Edward Island"), ("QC", "Quebec"), ("SK", "Saskatchewan"), ("YT", "Yukon")
]

ALL_JAPAN_REGIONS = [
    ("Hokkaido", "Hokkaido"), ("Nagano", "Nagano"), ("Niigata", "Niigata"),
    ("Gunma", "Gunma"), ("Yamagata", "Yamagata"), ("Iwate", "Iwate")
]

ALL_FRANCE_REGIONS = [
    ("Auvergne-Rhône-Alpes", "Auvergne-Rhône-Alpes"), ("Provence-Alpes-Côte d'Azur", "Provence-Alpes-Côte d'Azur"),
    ("Occitanie", "Occitanie"), ("Nouvelle-Aquitaine", "Nouvelle-Aquitaine")
]

ALL_SWITZERLAND_REGIONS = [
    ("Valais", "Valais"), ("Graubünden", "Graubünden"), ("Bern", "Bern"),
    ("Vaud", "Vaud"), ("Uri", "Uri"), ("Obwalden", "Obwalden")
]

ALL_AUSTRIA_REGIONS = [
    ("Tyrol", "Tyrol"), ("Salzburg", "Salzburg"), ("Vorarlberg", "Vorarlberg"),
    ("Styria", "Styria"), ("Carinthia", "Carinthia")
]

ALL_ITALY_REGIONS = [
    ("Trentino-Alto Adige", "Trentino-Alto Adige"), ("Valle d'Aosta", "Valle d'Aosta"),
    ("Lombardy", "Lombardy"), ("Piedmont", "Piedmont"), ("Veneto", "Veneto")
]

# Canonical states/regions by country code
CANONICAL_STATES_BY_COUNTRY = {
    "US": ALL_US_STATES,
    "CA": ALL_CANADA_PROVINCES,
    "JP": ALL_JAPAN_REGIONS,
    "FR": ALL_FRANCE_REGIONS,
    "CH": ALL_SWITZERLAND_REGIONS,
    "AT": ALL_AUSTRIA_REGIONS,
    "IT": ALL_ITALY_REGIONS,
}

def get_all_countries():
    """Get canonical list of all countries (not derived from resorts).
    Returns list of (country_code, country_name) tuples, sorted with US first.
    """
    countries = list(COUNTRY_NAMES.items())
    # Sort: US first, then alphabetically by name
    def sort_key(item):
        code, name = item
        if code == "US":
            return (0, "")
        return (1, name)
    return sorted(countries, key=sort_key)

def get_all_states_by_country():
    """Get canonical states/regions for all countries (not derived from resorts).
    Returns dict mapping country_code to list of (state_code, state_name) tuples.
    """
    result = {}
    for country_code, states in CANONICAL_STATES_BY_COUNTRY.items():
        result[country_code] = sorted(states, key=lambda x: x[1])
    return result

def get_grouped_locations():
    """Get locations grouped by country for the unified location selector.
    Returns dict with country names as keys and sorted list of (code, name) tuples as values.
    """
    return {
        "United States": sorted(ALL_US_STATES, key=lambda x: x[1]),
        "Canada": sorted(ALL_CANADA_PROVINCES, key=lambda x: x[1])
    }

def get_resorts_for_trip_form():
    """Get all active resorts for the Add Trip form.
    Returns list of dicts with id, name, country_code, state_code, pass_brands.
    
    ⚠️ CONTRACT: This data is used ONLY for filtering States and Resorts after
    a country is selected. The Country dropdown is populated from COUNTRIES
    in utils/countries.py, NOT from this data. Do not change this contract.
    
    Excludes region-level entities (is_region=True).
    """
    resorts = Resort.query.filter_by(is_active=True, is_region=False).order_by(
        Resort.country_code, Resort.state_code, Resort.name
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "country_code": r.country_code or r.country,
            "state_code": r.state_code or r.state,
            "pass_brands": r.pass_brands or r.brand or ""
        }
        for r in resorts
    ]

RIDER_TYPES = ["Skier", "Snowboarder", "Telemark", "Cross-Country", "Adaptive", "Social"]

def normalize_rider_type(rider_type):
    """Map 'Both' to 'Skier' for display. All other values pass through."""
    if rider_type == "Both":
        return "Skier"
    return rider_type

CANONICAL_PASSES = [
    "I don't have a pass",
    "Epic",
    "Ikon",
    "MountainCollective",
    "Indy",
    "PowderAlliance",
    "Freedom",
    "SkiCalifornia",
    "Other"
]

def get_sorted_passes():
    """Return passes sorted: Epic, Ikon, others (alphabetical), Other, None"""
    epic = [p for p in CANONICAL_PASSES if p == "Epic Pass"]
    ikon = [p for p in CANONICAL_PASSES if p == "Ikon Pass"]
    middle = sorted([p for p in CANONICAL_PASSES if p not in ["Epic Pass", "Ikon Pass", "Other", "None"]])
    other = [p for p in CANONICAL_PASSES if p == "Other"]
    none = [p for p in CANONICAL_PASSES if p == "None"]
    return epic + ikon + middle + other + none

PASS_OPTIONS = get_sorted_passes()

# Rider-aware copy helpers
def get_gear_term(rider_type):
    """Return rider-aware gear terminology."""
    if rider_type and rider_type.lower() in ['snowboarder', 'snowboarding']:
        return 'board'
    elif rider_type and rider_type.lower() in ['skier', 'skiing', 'both']:
        return 'skis'
    return 'gear'

def get_ride_term(rider_type):
    """Return rider-aware action terminology."""
    if rider_type and rider_type.lower() in ['snowboarder', 'snowboarding']:
        return 'ride'
    elif rider_type and rider_type.lower() in ['skier', 'skiing', 'both']:
        return 'ski'
    return 'ride'

# Seasonal awareness helper
def get_season_context():
    """Return seasonal copy context based on current date."""
    today = date.today()
    month, day = today.month, today.day
    
    # Pre-season: October 1 – November 30
    if (month == 10) or (month == 11):
        return 'preseason'
    # Mid-season: December 1 – March 15
    elif (month == 12) or (month in [1, 2]) or (month == 3 and day <= 15):
        return 'midseason'
    # Spring: March 16 – April 30
    elif (month == 3 and day > 15) or (month == 4):
        return 'spring'
    # Off-season
    return 'offseason'

def get_seasonal_empty_state(context_type='trip'):
    """Return seasonally appropriate empty state copy."""
    season = get_season_context()
    
    if context_type == 'trip':
        if season == 'preseason':
            return "Plan your first trip of the season"
        elif season == 'midseason':
            return "Who's heading out this week?"
        elif season == 'spring':
            return "Any final turns planned?"
        return "Add a trip to get started"
    
    return ""

# State name mappings for display
STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
    'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
    'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi', 'MO': 'Missouri',
    'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey',
    'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont',
    'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
    'DC': 'District of Columbia', 'BC': 'British Columbia', 'AB': 'Alberta', 'ON': 'Ontario', 'QC': 'Quebec'
}

# Note: COUNTRY_NAMES defined above at line ~353

def group_resorts_for_display(resorts):
    """
    Group and sort resorts for display.
    US resorts grouped by state name, non-US resorts grouped by country name.
    Groups sorted alphabetically, resorts within groups sorted alphabetically.
    Returns list of dicts: [{'label': 'Colorado', 'resorts': [resort, ...]}, ...]
    """
    groups = {}
    
    for resort in resorts:
        if resort.country_code == 'US':
            group_key = 'US-' + (resort.state_code or 'Unknown')
            group_label = STATE_NAMES.get(resort.state_code, resort.state_code or 'Unknown')
        else:
            group_key = resort.country_code or 'Unknown'
            group_label = COUNTRY_NAMES.get(resort.country_code, resort.country_code or 'Unknown')
        
        if group_key not in groups:
            groups[group_key] = {'label': group_label, 'resorts': []}
        groups[group_key]['resorts'].append(resort)
    
    # Sort groups alphabetically by label
    sorted_groups = sorted(groups.values(), key=lambda g: g['label'])
    
    # Sort resorts within each group alphabetically by name
    for group in sorted_groups:
        group['resorts'] = sorted(group['resorts'], key=lambda r: r.name.lower())
    
    return sorted_groups

def format_trip_dates(trip):
    """
    Simplified trip date display logic.
    
    Rules:
    1) If start_date == end_date: "Jan 25"
    2) If same month: "Jan 25–27"
    3) If different months: "Jan 25–Feb 1"
    
    No year included.
    """
    try:
        if not trip:
            return ""
        
        start = getattr(trip, 'start_date', None)
        end = getattr(trip, 'end_date', None)
        
        if start and hasattr(start, 'date'):
            start = start.date()
        if end and hasattr(end, 'date'):
            end = end.date()
        
        if not start or not end:
            return ""
        
        if start == end:
            return start.strftime('%b %-d')
        elif start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.strftime('%-d')}"
        else:
            return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d')}"
    except Exception:
        return ""

# Make functions available to Jinja2 templates
app.jinja_env.globals['normalize_rider_type'] = normalize_rider_type
app.jinja_env.globals['get_sorted_passes'] = get_sorted_passes
app.jinja_env.globals['get_gear_term'] = get_gear_term
app.jinja_env.globals['get_ride_term'] = get_ride_term
app.jinja_env.globals['format_trip_dates'] = format_trip_dates
app.jinja_env.globals['get_season_context'] = get_season_context
app.jinja_env.globals['get_seasonal_empty_state'] = get_seasonal_empty_state


def group_trips_by_month(trips):
    """
    Group a list of SkiTrip objects (pre-sorted by start_date asc)
    into (month_label, [trips]) tuples based on each trip's start_date month.
    Trips without a start_date are collected under 'TBD'.
    Example output: [("February", [trip1, trip2]), ("March", [trip3])]
    """
    groups = []
    current_label = None
    current_trips = []
    for trip in (trips or []):
        start = getattr(trip, 'start_date', None)
        if start:
            label = start.strftime('%B')
        else:
            label = 'TBD'
        if label != current_label:
            if current_label is not None:
                groups.append((current_label, current_trips))
            current_label = label
            current_trips = [trip]
        else:
            current_trips.append(trip)
    if current_label is not None:
        groups.append((current_label, current_trips))
    return groups


app.jinja_env.globals['group_trips_by_month'] = group_trips_by_month

MOUNTAINS_BY_STATE = {
    "CO": sorted(["Vail", "Breckenridge", "Keystone", "Copper Mountain", "Arapahoe Basin", "Loveland", "Winter Park", "Steamboat", "Aspen Snowmass", "Telluride", "Crested Butte", "Eldora"]),
    "UT": sorted(["Park City", "Deer Valley", "Snowbird", "Alta", "Brighton", "Solitude", "Snowbasin", "Powder Mountain"]),
    "CA": sorted(["Mammoth Mountain", "Palisades Tahoe", "Northstar", "Heavenly", "Kirkwood", "Big Bear", "June Mountain"]),
    "AK": sorted(["Alyeska Resort"]),
    "ID": sorted(["Sun Valley", "Schweitzer", "Bogus Basin", "Brundage Mountain"]),
    "ME": sorted(["Sugarloaf", "Sunday River", "Saddleback"]),
    "MI": sorted(["Boyne Mountain", "Crystal Mountain MI", "Nubs Nob"]),
    "MT": sorted(["Big Sky", "Whitefish Mountain", "Bridger Bowl", "Red Lodge Mountain"]),
    "NH": sorted(["Bretton Woods", "Cannon Mountain", "Loon Mountain", "Wildcat Mountain"]),
    "NM": sorted(["Taos Ski Valley", "Ski Santa Fe", "Angel Fire"]),
    "NY": sorted(["Whiteface", "Gore Mountain", "Hunter Mountain", "Windham Mountain"]),
    "OR": sorted(["Mt. Hood Meadows", "Timberline", "Mt. Bachelor", "Anthony Lakes"]),
    "VT": sorted(["Stowe", "Killington", "Sugarbush", "Jay Peak", "Stratton", "Mount Snow", "Okemo"]),
    "WA": sorted(["Crystal Mountain", "Stevens Pass", "Mt. Baker", "Snoqualmie"]),
    "WY": sorted(["Jackson Hole", "Grand Targhee", "Snow King"])
}

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        try:
            email = request.form.get("email", "").lower().strip()
            user = User.query.filter(sa.func.lower(User.email) == email).first()
            
            if user:
                # Generate token using itsdangerous
                token = user.get_reset_token()
                
                # Send Email via SendGrid
                # Canonical base URL
                reset_url = f"{BASE_URL}/reset-password/{token}"
                
                message = Mail(
                    from_email='noreply@baselodgeapp.com',
                    to_emails=user.email,
                    subject='Reset your BaseLodge password',
                    plain_text_content=f'Please use the following link to reset your password: {reset_url}\n\nThis link will expire in 30 minutes.'
                )
                
                try:
                    key = os.environ.get('SENDGRID_API_KEY', '')
                    sg = SendGridAPIClient(key)
                    app.logger.info(f"SendGrid initialized with key starting with: {key[:4] if key else 'NONE'}")
                    response = sg.send(message)
                    app.logger.info(f"SendGrid response status code: {response.status_code}")
                    app.logger.info(f"Password reset email sent to {user.email}")
                except Exception as e:
                    app.logger.error(f"Error sending password reset email: {e}")
        except Exception as e:
            app.logger.error(f"Error in forgot_password POST handler: {e}")
            db.session.rollback()
        
        # Always show same message
        flash("If an account exists with that email, you’ll receive a password reset link.", "info")
        return render_template("forgot_password.html")
        
    return render_template("forgot_password.html")

@app.route("/reset-password", methods=["GET", "POST"])
@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token=None):
    # Support both /reset-password?token=... and /reset-password/<token>
    if token is None:
        token = request.args.get("token")

    user = User.verify_reset_token(token)

    if not user:
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("auth"))

    if request.method == "POST":
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not password:
            flash("Password cannot be empty.", "error")
            return redirect(request.url)
        
        if not password or len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("reset_password.html", token=token)
            
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()

        login_user(user)
        flash("Your password has been reset.", "success")
        return redirect("/")

    return render_template("reset_password.html", token=token)

def build_trip_idea(user, idea_type, destination=None, resort_id=None, start_date_str=None, end_date_str=None, social_context=None, friends=None):
    """Canonical Trip Idea builder."""
    has_dates = bool(start_date_str and end_date_str)
    
    # Display Date
    display_date = ""
    if has_dates:
        try:
            d = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            display_date = d.strftime('%b %-d')
        except:
            display_date = start_date_str
            
    # CTA URL
    params = []
    if resort_id: params.append(f"resort_id={resort_id}")
    if has_dates:
        params.append(f"start_date={start_date_str}")
        params.append(f"end_date={end_date_str}")
    
    cta_url = "/add_trip"
    if params:
        cta_url += "?" + "&".join(params)
        
    return {
        "type": idea_type,
        "destination": destination,
        "resort_id": resort_id,
        "social_context": social_context,
        "has_dates": has_dates,
        "start_date_str": start_date_str,
        "end_date_str": end_date_str,
        "display_date": display_date,
        "cta_url": cta_url,
        "friends": friends or []
    }

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return redirect(url_for("auth"))

@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "POST":
        form_type = request.form.get("form_type", "login")
        
        if form_type == "signup":
            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            email = request.form.get("email", "").lower().strip()
            password = request.form.get("password", "")
            
            if not first_name or not last_name or not email or not password:
                flash("Please fill in all fields.", "error")
                return render_template("auth.html", has_invite=("invite_token" in session))
            
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return render_template("auth.html", has_invite=("invite_token" in session))
            
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("An account with this email already exists.", "error")
                return render_template("auth.html", has_invite=("invite_token" in session))
            
            new_user = User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                buddy_passes_available=True
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user, remember=True)
            session.modified = True
            
            # Connect with inviter if coming from invite link
            if "invite_token" in session:
                # Pre-set post-onboarding redirect to friends before token is consumed
                session["post_onboarding_redirect"] = url_for("friends")
                _connect_pending_inviter(new_user)
            
            return redirect(url_for("identity_setup"))
        
        elif form_type == "login":
            email = request.form.get("email", "").lower().strip()
            password = request.form.get("password", "")
            
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user, remember=True)
                session.modified = True
                db.session.commit()
                
                # Connect with inviter if coming from invite link
                if "invite_token" in session:
                    connected = _connect_pending_inviter(user)
                    if connected:
                        # Redirect to friends page to show the new connection
                        return redirect(url_for("friends"))
                
                return redirect(url_for("home"))
            
            flash("Invalid email or password.", "error")

    return render_template("auth.html", has_invite=("invite_token" in session))


@app.route("/identity-setup", methods=["GET", "POST"])
@login_required
def identity_setup():
    """Identity setup screen - shown immediately after signup to collect core identity."""
    # If user already has core identity, redirect to home
    if current_user.is_core_profile_complete:
        return redirect(url_for("home"))
    
    if request.method == "POST":
        rider_types = request.form.getlist("rider_types")
        skill_level = request.form.get("skill_level", "").strip()
        pass_type = request.form.get("pass_type", "").strip()
        home_state = request.form.get("home_state", "").strip()
        backcountry_capable = request.form.get("backcountry_capable") == "1"
        avi_certified_raw = request.form.get("avi_certified")
        avi_certified = (avi_certified_raw == "1") if backcountry_capable else None

        # Validate required fields
        if not rider_types:
            flash("Please select your rider type.")
            return render_template("identity_setup.html", grouped_locations=get_grouped_locations())

        if not skill_level:
            flash("Please select your skill level.")
            return render_template("identity_setup.html", grouped_locations=get_grouped_locations())

        if not pass_type:
            flash("Please select a pass option.")
            return render_template("identity_setup.html", grouped_locations=get_grouped_locations())

        if not home_state:
            flash("Please select your home state or province.")
            return render_template("identity_setup.html", grouped_locations=get_grouped_locations())

        # Save all onboarding data in one shot
        current_user.rider_types = rider_types
        current_user.skill_level = skill_level
        current_user.pass_type = pass_type
        current_user.home_state = home_state
        current_user.backcountry_capable = backcountry_capable
        current_user.avi_certified = avi_certified

        db.session.commit()

        # Redirect — invite signups go to friends, others go to home
        next_url = (
            session.pop("post_onboarding_redirect", None)
            or session.pop("next_after_setup", None)
        )
        if next_url:
            return redirect(next_url)
        return redirect(url_for("home"))

    return render_template("identity_setup.html", grouped_locations=get_grouped_locations())


@app.route("/location-setup", methods=["GET", "POST"])
@login_required
def location_setup():
    """Location setup screen - step 2 of onboarding to collect home state only."""
    user = current_user
    
    # If user hasn't completed identity setup, redirect back
    if not user.is_core_profile_complete:
        return redirect(url_for("identity_setup"))
    
    # If user already has home_state, redirect to home
    if user.home_state:
        return redirect(url_for("home"))
    
    if request.method == "POST":
        home_state = request.form.get("home_state", "").strip()
        
        # Validate required field
        if not home_state:
            flash("Please select your home state.", "error")
            return redirect(url_for("location_setup"))
        
        # Save home state
        user.home_state = home_state
        db.session.commit()
        
        # Redirect to home - welcome modal will show
        next_url = session.pop("next_after_setup", None)
        if next_url:
            return redirect(next_url)
        return redirect(url_for("home"))
    
    # Get grouped locations for the unified selector
    grouped_locations = get_grouped_locations()
    
    return render_template("location_setup.html", grouped_locations=grouped_locations)


def _connect_pending_inviter(user):
    """Helper to connect user with pending inviter from session invite_token."""
    invite_token_str = session.get("invite_token")
    if not invite_token_str:
        # Legacy fallback
        legacy_inviter_id = session.get("pending_inviter_id")
        if legacy_inviter_id:
            inviter = User.query.get(legacy_inviter_id)
            if inviter and inviter.id != user.id:
                existing = Friend.query.filter_by(user_id=user.id, friend_id=inviter.id).first()
                if not existing:
                    f1 = Friend(user_id=user.id, friend_id=inviter.id)
                    f2 = Friend(user_id=inviter.id, friend_id=user.id)
                    db.session.add_all([f1, f2])
                    user.invited_by_user_id = inviter.id
                    db.session.commit()
            session.pop("pending_inviter_id", None)
        return False

    invite = InviteToken.query.filter_by(token=invite_token_str).first()
    # Check if token is invalid, already used, or expired
    if not invite or invite.is_used() or invite.is_expired():
        session.pop("invite_token", None)
        return False

    inviter = User.query.get(invite.inviter_id)
    connected = False
    if inviter and inviter.id != user.id:
        # Idempotent: check if friend connection already exists
        existing = Friend.query.filter_by(user_id=user.id, friend_id=inviter.id).first()
        if not existing:
            f1 = Friend(user_id=user.id, friend_id=inviter.id)
            f2 = Friend(user_id=inviter.id, friend_id=user.id)
            db.session.add_all([f1, f2])
            user.invited_by_user_id = inviter.id
            connected = True
            app.logger.info(f"Connected {user.id} with inviter {inviter.id} via token {invite_token_str}")
        
        # Mark token as used (even if already friends, prevent reuse)
        invite.used_at = datetime.utcnow()
        db.session.commit()
        connected = True
    
    session.pop("invite_token", None)
    return connected


@app.route("/invite/<token>")
def invite_token_landing(token):
    """Time-limited invite landing page."""
    now_utc = datetime.utcnow()
    invite = InviteToken.query.filter_by(token=token).first()

    # ── Diagnostic logging for invite debugging ────────────────────────────
    print(f"[INVITE] token={token[:8]}... | found={invite is not None} | now_utc={now_utc.isoformat()}")
    if invite:
        print(
            f"[INVITE] created_at={invite.created_at} | expires_at={invite.expires_at} "
            f"| used_at={invite.used_at} | is_expired()={invite.is_expired()} "
            f"| is_used()={invite.is_used()} | inviter_id={invite.inviter_id}"
        )
        if invite.expires_at:
            delta = invite.expires_at - now_utc
            print(f"[INVITE] time_until_expiry={delta} (positive = not yet expired)")
    else:
        print(f"[INVITE] Token not found in DB — BASE_URL={BASE_URL}")
    # ──────────────────────────────────────────────────────────────────────

    if not invite or invite.is_expired():
        return render_template("invite_expired.html")

    session["invite_token"] = token

    inviter = User.query.get(invite.inviter_id)
    if not inviter:
        return render_template("invite_expired.html")

    inviter_trips_count = get_upcoming_trip_count(inviter)

    return render_template(
        "invite_landing.html",
        inviter=inviter,
        inviter_trips_count=inviter_trips_count
    )


@app.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile():
    user = current_user
    
    if request.method == "POST":
        rider_types = request.form.getlist("rider_types")
        passes = request.form.getlist("pass_type")

        if not rider_types:
            flash("Please select at least one rider type.", "error")
            return redirect(url_for("setup_profile"))

        user.rider_types = rider_types
        user.pass_type = ",".join(sorted(set(passes))) if passes else "None"
        user.onboarding_completed_at = datetime.utcnow()
        user.update_lifecycle_stage()
        db.session.commit()
        
        # Emit onboarding_completed event
        emit_event('onboarding_completed', user)

        return redirect(url_for("home"))

    return render_template("setup_profile.html", rider_types=RIDER_TYPES, pass_options=CANONICAL_PASSES)


@app.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    # Explicit permission check: only profile owner can edit
    user = current_user
    if user.id != current_user.id:
        abort(403)
    
    if request.method == "POST":
        user.gender = request.form.get("gender") or None
        birth_year_raw = request.form.get("birth_year")
        user.birth_year = int(birth_year_raw) if birth_year_raw else None
        
        # Handle rider types (multi-select)
        rider_types_raw = request.form.get("rider_types", "")
        rider_types = [rt.strip() for rt in rider_types_raw.split(",") if rt.strip()]
        user.rider_types = rider_types if rider_types else []
        
        passes_raw = request.form.get("pass_type", "")
        passes = [p.strip() for p in passes_raw.split(",") if p.strip()]
        user.pass_type = ",".join(sorted(set(passes))) if passes else "None"
        user.home_state = request.form.get("home_state") or None
        # Clear skill_level only for Social-only users, otherwise use form value
        is_social_only = rider_types == ["Social"]
        user.skill_level = None if is_social_only else (request.form.get("skill_level") or None)
        user.gear = request.form.get("gear") or None
        home_resort_id_raw = request.form.get("home_resort_id") or None
        if home_resort_id_raw:
            home_resort = Resort.query.get(int(home_resort_id_raw))
            if home_resort:
                user.home_resort_id = home_resort.id
                user.home_mountain = home_resort.name  # Keep legacy field in sync
            else:
                user.home_resort_id = None
                user.home_mountain = None
        else:
            user.home_resort_id = None
            user.home_mountain = None
        
        terrain_raw = request.form.get("terrain_preferences", "")
        terrain_list = [t.strip() for t in terrain_raw.split(",") if t.strip()][:2]
        user.terrain_preferences = terrain_list if terrain_list else []
        user.previous_pass = request.form.get("previous_pass") or None
        user.profile_completed_at = datetime.utcnow()
        user.update_lifecycle_stage()
        
        try:
            db.session.commit()
            
            # Emit profile_completed event
            emit_event('profile_completed', user)
            
            return redirect(url_for("more"))
        except Exception as e:
            db.session.rollback()
            print(f"Error saving profile: {e}")
            flash("Something went wrong while saving your profile. Please try again.", "error")
            return redirect(url_for("edit_profile"))
    
    primary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.PRIMARY).first()
    secondary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.SECONDARY).first()
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    
    # Build resorts by state from database (exclude region-level entities)
    all_resorts = Resort.query.filter_by(is_active=True, is_region=False).order_by(Resort.state, Resort.name).all()
    resorts_by_state = {}
    for resort in all_resorts:
        if resort.state not in resorts_by_state:
            resorts_by_state[resort.state] = []
        resorts_by_state[resort.state].append({"id": resort.id, "name": resort.name})
    
    return render_template("edit_profile.html", user=user, friends_count=friends_count, state_abbr=STATE_ABBR, pass_options=CANONICAL_PASSES, rider_types=RIDER_TYPES, all_states=ALL_US_STATES, primary_equipment=primary_equipment, secondary_equipment=secondary_equipment, resorts_by_state=resorts_by_state, grouped_locations=get_grouped_locations())

@app.route("/my-trips")
@login_required
def my_trips():
    user = current_user
    today = date.today()
    active_tab = request.args.get("tab", "my_trips")
    show_connected_banner = request.args.get("connected") == "true"

    # Trip queries (wrapped for production safety)
    try:
        upcoming_trips = (
            SkiTrip.query
            .filter(SkiTrip.user_id == current_user.id)
            .filter(SkiTrip.end_date >= today)
            .order_by(SkiTrip.start_date.asc())
            .all()
        ) or []
    except Exception:
        upcoming_trips = []

    try:
        past_trips = (
            SkiTrip.query
            .filter(SkiTrip.user_id == current_user.id)
            .filter(SkiTrip.end_date < today)
            .order_by(SkiTrip.start_date.desc())
            .all()
        ) or []
    except Exception:
        past_trips = []

    # Get trips where user is INVITED (pending invites)
    invited_trips = []
    try:
        invited_participations = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == current_user.id,
            SkiTripParticipant.status == GuestStatus.INVITED
        ).all()
        invited_trip_ids = [p.trip_id for p in invited_participations]
        print(f"--- TRIP INVITE DEBUG (User {current_user.id}) ---")
        print(f"  Invited participations: {[(p.trip_id, p.status.value) for p in invited_participations]}")
        print(f"  Invited trip IDs: {invited_trip_ids}")
        if invited_trip_ids:
            invited_trips = SkiTrip.query.filter(
                SkiTrip.id.in_(invited_trip_ids),
                SkiTrip.end_date >= today
            ).order_by(SkiTrip.start_date.asc()).all() or []
            print(f"  Invited trips found: {[t.id for t in invited_trips]}")
        print(f"  Final invited_trips count: {len(invited_trips)}")
        print(f"-------------------------------------------")
    except Exception as e:
        print(f"  ERROR fetching invited trips: {e}")
        invited_trips = []

    # Get trips where user is ACCEPTED as guest (not owner)
    accepted_guest_trips = []
    try:
        accepted_participations = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == current_user.id,
            SkiTripParticipant.status == GuestStatus.ACCEPTED
        ).all()
        accepted_trip_ids = [p.trip_id for p in accepted_participations]
        if accepted_trip_ids:
            # Exclude trips the user owns (they're already in upcoming_trips)
            accepted_guest_trips = SkiTrip.query.filter(
                SkiTrip.id.in_(accepted_trip_ids),
                SkiTrip.user_id != current_user.id,
                SkiTrip.end_date >= today
            ).order_by(SkiTrip.start_date.asc()).all() or []
    except Exception:
        accepted_guest_trips = []

    # Get friends (wrapped for production safety)
    try:
        friend_links = Friend.query.filter_by(user_id=user.id).all()
        friend_ids = [f.friend_id for f in friend_links] if friend_links else []
        friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    except Exception:
        friend_links = []
        friend_ids = []
        friends = []

    # Friends' upcoming trips (wrapped for production safety)
    friend_trips = []
    try:
        if friend_ids:
            friend_trips = SkiTrip.query.filter(
                SkiTrip.user_id.in_(friend_ids),
                SkiTrip.end_date >= today,
                SkiTrip.is_public == True
            ).order_by(SkiTrip.start_date.asc()).all() or []
    except Exception:
        friend_trips = []

    # Build overlaps list (wrapped for production safety)
    overlaps = []
    try:
        for my in upcoming_trips:
            for friend_trip in friend_trips:
                if my.user_id != friend_trip.user_id:
                    # Resort match: prefer resort_id (canonical), fall back to mountain string
                    if my.resort_id and friend_trip.resort_id:
                        same_resort = (my.resort_id == friend_trip.resort_id)
                    else:
                        my_mountain = my.mountain if my.mountain else (my.resort.name if my.resort else None)
                        friend_mountain = friend_trip.mountain if friend_trip.mountain else (friend_trip.resort.name if friend_trip.resort else None)
                        same_resort = bool(my_mountain and friend_mountain and my_mountain == friend_mountain)
                    if same_resort:
                        if my.start_date and my.end_date and friend_trip.start_date and friend_trip.end_date:
                            if date_ranges_overlap(my.start_date, my.end_date, friend_trip.start_date, friend_trip.end_date):
                                resort = my.resort or friend_trip.resort
                                my_mountain_str = my.mountain if my.mountain else (my.resort.name if my.resort else None)
                                friend_first_name = friend_trip.user.first_name if friend_trip.user else "Friend"
                                overlaps.append({
                                    "my_trip_id": my.id,
                                    "friend_name": friend_first_name,
                                    "friend_first_name": friend_first_name,
                                    "friend_id": friend_trip.user_id,
                                    "mountain": resort.name if resort else my_mountain_str,
                                    "state": resort.state if resort else (my.state or ""),
                                    "brand": resort.brand if resort else None,
                                    "resort_id": resort.id if resort else None,
                                    "start_date": max(my.start_date, friend_trip.start_date),
                                    "end_date": min(my.end_date, friend_trip.end_date)
                                })
    except Exception:
        overlaps = []

    # Load requested trips (join requests sent by me, not yet accepted/promoted to participant)
    requested_trips = []
    try:
        requests = Invitation.query.filter_by(
            sender_id=current_user.id,
            invite_type=InviteType.REQUEST
        ).all()
        for req in requests:
            if req.status == 'accepted':
                exists = SkiTripParticipant.query.filter_by(
                    trip_id=req.trip_id,
                    user_id=current_user.id,
                    status=GuestStatus.ACCEPTED
                ).first()
                if exists:
                    continue
            trip = SkiTrip.query.get(req.trip_id)
            if trip and trip.end_date >= today:
                requested_trips.append({
                    'invitation_id': req.id,
                    'trip': trip,
                    'owner': User.query.get(req.receiver_id),
                    'status': req.status.capitalize()
                })
    except Exception:
        requested_trips = []

    return render_template(
        "my_trips.html",
        user=user,
        upcoming_trips=upcoming_trips or [],
        past_trips=past_trips or [],
        invited_trips=invited_trips or [],
        accepted_guest_trips=accepted_guest_trips or [],
        requested_trips=requested_trips,
        active_tab=active_tab,
        show_connected_banner=show_connected_banner,
        friends=friends or [],
        friend_trips=friend_trips or [],
        overlaps=overlaps or [],
        today=today
    )

@app.route("/season-snapshot")
@login_required
def season_snapshot():
    today = date.today()
    try:
        upcoming_owned = (
            SkiTrip.query
            .filter(SkiTrip.user_id == current_user.id)
            .filter(SkiTrip.end_date >= today)
            .order_by(SkiTrip.start_date.asc())
            .all()
        ) or []
    except Exception:
        upcoming_owned = []

    try:
        accepted_participations = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == current_user.id,
            SkiTripParticipant.status == GuestStatus.ACCEPTED
        ).all()
        accepted_trip_ids = [p.trip_id for p in accepted_participations]
        if accepted_trip_ids:
            accepted_guest_trips = SkiTrip.query.filter(
                SkiTrip.id.in_(accepted_trip_ids),
                SkiTrip.user_id != current_user.id,
                SkiTrip.end_date >= today
            ).order_by(SkiTrip.start_date.asc()).all() or []
        else:
            accepted_guest_trips = []
    except Exception:
        accepted_guest_trips = []

    all_upcoming = sorted(
        upcoming_owned + accepted_guest_trips,
        key=lambda t: t.start_date if t.start_date else date.max
    )

    return render_template(
        "season_snapshot.html",
        user=current_user,
        all_upcoming=all_upcoming,
        today=today,
    )


@app.route("/overlap-detail")
@login_required
def overlap_detail():
    """Overlap detail screen showing friends involved and Start a trip CTA."""
    user = current_user
    
    # Get parameters
    overlap_type = request.args.get('type', 'trip')
    date_str = request.args.get('date')
    mountain = request.args.get('mountain')
    resort_id = request.args.get('resort_id', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Parse dates
    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    # Get friends from the overlap
    friend_ids_str = request.args.get('friends', '')
    friend_ids = [int(fid) for fid in friend_ids_str.split(',') if fid.isdigit()]
    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    
    # Get resort info if available
    resort = Resort.query.get(resort_id) if resort_id else None
    
    # Build display info
    if overlap_type == 'trip':
        title = mountain or (resort.name if resort else 'Trip Overlap')
        subtitle = None
        if start_date and end_date:
            if start_date == end_date:
                subtitle = start_date.strftime('%b %-d')
            else:
                subtitle = f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d')}"
    else:
        # Open date overlap
        if start_date:
            title = f"Open on {start_date.strftime('%b %-d')}"
        else:
            title = "Open Date Overlap"
        subtitle = f"{len(friends)} friend{'s' if len(friends) != 1 else ''} also open"
    
    return render_template(
        "overlap_detail.html",
        user=user,
        overlap_type=overlap_type,
        title=title,
        subtitle=subtitle,
        friends=friends,
        resort=resort,
        resort_id=resort_id,
        mountain=mountain,
        start_date=start_date,
        end_date=end_date,
        date_str=date_str or (start_date_str if start_date_str else '')
    )


@app.route("/trip-ideas")
@login_required
def trip_ideas():
    """Trip Ideas page — 3-state system: setup / reengagement / populated."""
    from services.ideas_engine import build_ranked_idea_feed
    from services.open_dates import get_available_dates_for_user
    user = current_user

    # ── Friends ────────────────────────────────────────────────────────────────
    friend_links = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friend_links]
    all_friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    has_friends = bool(friend_ids)

    # Full names for Ideas feed — spec requires full name for 1-friend cards
    display_names = {}
    for f in all_friends:
        fname = f.first_name or ""
        lname = f.last_name or ""
        display_names[f.id] = f"{fname} {lname}".strip() if lname else fname

    # ── Availability hint (soft prompt when no availability is set) ───────────
    has_availability = bool(get_available_dates_for_user(user))

    # ── Unified idea feed ─────────────────────────────────────────────────────
    idea_feed = build_ranked_idea_feed(user, all_friends) if has_friends else []

    # ── State determination ───────────────────────────────────────────────────
    if not has_friends:
        ideas_state = "setup"
    elif not idea_feed:
        ideas_state = "reengagement"
    else:
        ideas_state = "populated"

    # ── Debug logging ─────────────────────────────────────────────────────────
    print(f"[trip_ideas] state={ideas_state} feed={len(idea_feed)} card(s)")
    for _c in idea_feed:
        print(f"  • [{_c['score']:.0f}pts] [{_c['idea_type']}] {_c['title']}")

    return render_template(
        "trip_ideas.html",
        user=user,
        ideas_state=ideas_state,
        idea_feed=idea_feed,
        has_friends=has_friends,
        has_availability=has_availability,
        display_names=display_names,
    )


def _ideas_normalize_pass(pt):
    """
    Short pass display for Ideas screens.
    Strips generic suffixes ('Pass', 'pass') and filters junk values.
    'Ikon Pass' -> 'Ikon', 'Epic Pass' -> 'Epic', 'Mountain Collective Pass' -> 'Mountain Collective'
    """
    import re as _re
    if not pt:
        return ""
    for part in pt.split(","):
        part = part.strip()
        if not part or part.lower() in ("none", "i don't have a pass", "other", "no pass"):
            continue
        return _re.sub(r"\s+[Pp]ass$", "", part).strip()
    return ""


def _ideas_rider_pass_line(user_obj):
    """
    Build 'Skier · Ikon' (or 'Snowboarder · Epic', or just 'Ikon', etc.)
    for a participant row. Returns empty string if neither is set.
    """
    rider = (user_obj.display_rider_type or "").strip()
    norm_pass = _ideas_normalize_pass(user_obj.pass_type)
    if rider and norm_pass:
        return f"{rider} \u00b7 {norm_pass}"
    return rider or norm_pass


@app.route("/idea/availability")
@login_required
def idea_detail_availability():
    """Detail screen for an availability overlap idea card."""
    from datetime import date as _date
    user = current_user

    # Parse query params
    friend_ids_raw = request.args.get("friend_ids", "")
    try:
        raw_ids = [int(x.strip()) for x in friend_ids_raw.split(",") if x.strip().isdigit()]
    except ValueError:
        raw_ids = []
    resort_id = request.args.get("resort_id", type=int)
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    # Security: only expose friends of the current user
    user_friend_ids = {
        f.friend_id for f in Friend.query.filter_by(user_id=user.id).all()
    }
    friend_ids = [fid for fid in raw_ids if fid in user_friend_ids]

    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    resort = Resort.query.get(resort_id) if resort_id else None

    # Format date range for display
    date_range_display = None
    if start_date_str and end_date_str:
        try:
            s = _date.fromisoformat(start_date_str)
            e = _date.fromisoformat(end_date_str)
            if s == e:
                date_range_display = s.strftime("%B %-d")
            elif s.month == e.month:
                date_range_display = f"{s.strftime('%B %-d')} \u2013 {e.strftime('%-d')}"
            else:
                date_range_display = f"{s.strftime('%B %-d')} \u2013 {e.strftime('%B %-d')}"
        except (ValueError, TypeError):
            pass

    participants = []
    for f in friends:
        participants.append({
            "full_name": f"{f.first_name or ''} {f.last_name or ''}".strip(),
            "pass_display": _ideas_rider_pass_line(f),
            "friend_id": f.id,
        })

    user_pass_display = _ideas_rider_pass_line(user)

    _num_words = {1:"One",2:"Two",3:"Three",4:"Four",5:"Five",
                  6:"Six",7:"Seven",8:"Eight",9:"Nine",10:"Ten"}
    n_people = len(friends) + 1
    people_word = _num_words.get(n_people, str(n_people))

    return render_template(
        "idea_detail_availability.html",
        user=user,
        participants=participants,
        resort=resort,
        date_range_display=date_range_display,
        user_pass_display=user_pass_display,
        people_word=people_word,
    )


@app.route("/idea/wishlist")
@login_required
def idea_detail_wishlist():
    """Detail screen for a wishlist overlap idea card."""
    user = current_user

    resort_id = request.args.get("resort_id", type=int)
    friend_ids_raw = request.args.get("friend_ids", "")
    try:
        raw_ids = [int(x.strip()) for x in friend_ids_raw.split(",") if x.strip().isdigit()]
    except ValueError:
        raw_ids = []

    # Security: only expose friends of the current user
    user_friend_ids = {
        f.friend_id for f in Friend.query.filter_by(user_id=user.id).all()
    }
    friend_ids = [fid for fid in raw_ids if fid in user_friend_ids]

    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    resort = Resort.query.get(resort_id) if resort_id else None

    participants = []
    for f in friends:
        participants.append({
            "full_name": f"{f.first_name or ''} {f.last_name or ''}".strip(),
            "pass_display": _ideas_rider_pass_line(f),
            "friend_id": f.id,
        })

    user_pass_display = _ideas_rider_pass_line(user)
    resort_name = resort.name if resort else "this resort"

    return render_template(
        "idea_detail_wishlist.html",
        user=user,
        participants=participants,
        resort=resort,
        resort_name=resort_name,
        user_pass_display=user_pass_display,
    )


@app.route("/idea/trip/<int:trip_id>")
@login_required
def idea_detail_trip(trip_id):
    """Detail screen for a trip overlap idea card — informational only, no CTA."""
    from datetime import date as _date
    user = current_user

    trip = SkiTrip.query.get_or_404(trip_id)

    # Must be a public trip belonging to a friend
    if not trip.is_public:
        abort(404)

    user_friend_ids = {
        f.friend_id for f in Friend.query.filter_by(user_id=user.id).all()
    }
    if trip.user_id not in user_friend_ids and trip.user_id != user.id:
        abort(404)

    trip_owner = User.query.get(trip.user_id)
    trip_status = trip.trip_status or "planning"
    anchor_name = trip_owner.first_name if trip_owner else "Your friend"

    # Format date range
    date_range_display = None
    if trip.start_date and trip.end_date:
        s = trip.start_date
        e = trip.end_date
        if s == e:
            date_range_display = s.strftime("%B %-d")
        elif s.month == e.month:
            date_range_display = f"{s.strftime('%B %-d')} \u2013 {e.strftime('%-d')}"
        else:
            date_range_display = f"{s.strftime('%B %-d')} \u2013 {e.strftime('%B %-d')}"

    # Explanatory "why" line varies by trip status
    if trip_status == "going":
        why_line = f"{anchor_name} is going."
    else:
        why_line = f"{anchor_name} is considering this trip."

    # Build participant list: host first, then accepted guests, then "You, if you join"
    participants = []
    if trip_owner:
        participants.append({
            "full_name": f"{trip_owner.first_name or ''} {trip_owner.last_name or ''}".strip(),
            "pass_display": _ideas_rider_pass_line(trip_owner),
            "is_host": True,
            "friend_id": trip_owner.id,
        })

    accepted_rows = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, status=GuestStatus.ACCEPTED
    ).all()
    for row in accepted_rows:
        if row.user_id == trip_owner.id if trip_owner else False:
            continue
        if row.user_id == user.id:
            continue
        guest = User.query.get(row.user_id)
        if guest:
            participants.append({
                "full_name": f"{guest.first_name or ''} {guest.last_name or ''}".strip(),
                "pass_display": _ideas_rider_pass_line(guest),
                "is_host": False,
                "friend_id": guest.id,
            })

    user_pass_display = _ideas_rider_pass_line(user)
    resort_name = trip.mountain or "the mountain"

    return render_template(
        "idea_detail_trip.html",
        user=user,
        trip=trip,
        trip_status=trip_status,
        trip_owner=trip_owner,
        anchor_name=anchor_name,
        participants=participants,
        date_range_display=date_range_display,
        why_line=why_line,
        resort_name=resort_name,
        user_pass_display=user_pass_display,
    )

@app.route("/api/mountains/<state>")
def get_mountains(state):
    # DEPRECATED: Not called by any current UI. Kept for external compatibility only.
    # The active Add Trip UI derives states/resorts from the Resort table via get_resorts_for_trip_form().
    state_code = state.upper()
    mountains = MOUNTAINS_BY_STATE.get(state_code, [])
    return jsonify(mountains)

@app.route("/api/trip/create", methods=["POST"])
@login_required
def create_trip():
    user = current_user
    
    data = request.get_json()
    resort_id_raw = data.get("resort_id")
    state = data.get("state")
    mountain = data.get("mountain")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    pass_type = data.get("pass_type", user.pass_type or "No Pass")
    is_public = data.get("is_public", True)

    # Resolve resort — canonical source of truth for mountain/state
    resolved_resort = None
    if resort_id_raw:
        try:
            resolved_resort = Resort.query.get(int(resort_id_raw))
        except (ValueError, TypeError):
            resolved_resort = None
        if resolved_resort:
            mountain = resolved_resort.name
            state = resolved_resort.state_code or resolved_resort.state

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
    
    if not start_date or not end_date:
        return jsonify({"success": False, "error": "Please provide both start and end dates."}), 400
    
    if end_date < start_date:
        return jsonify({"success": False, "error": "End date cannot be before start date."}), 400
    
    overlapping = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date <= end_date,
        SkiTrip.end_date >= start_date
    ).first()
    
    if overlapping:
        return jsonify({"success": False, "error": "You already have a trip during these dates."}), 409
    
    # Check if this is a group trip proposal
    friend_id = data.get("friend_id")
    is_group_trip = data.get("is_group", False)
    
    trip = SkiTrip(
        user_id=user.id,
        resort_id=resolved_resort.id if resolved_resort else None,
        state=state,
        mountain=mountain,
        start_date=start_date,
        end_date=end_date,
        pass_type=pass_type,
        is_public=is_public,
        trip_status='planning',
        is_group_trip=is_group_trip or (friend_id is not None),
        created_by_user_id=user.id
    )
    db.session.add(trip)
    db.session.flush()  # Get trip.id before adding participants
    
    # Auto-add owner as participant
    trip.add_owner_as_participant()
    
    # Add participant if friend_id is provided
    if friend_id:
        trip.add_participant(friend_id, GuestStatus.INVITED)
    
    # Track first trip created if not already set
    if not user.first_trip_created_at:
        user.first_trip_created_at = datetime.utcnow()
    
    # Mark planning started (lifecycle signal)
    user.mark_planning_started()
    
    # Update lifecycle stage (planning started)
    user.update_lifecycle_stage()
    
    db.session.commit()
    
    # Emit trip_created event
    emit_event('trip_created', user, {
        'trip_id': trip.id,
        'mountain': mountain,
        'state': state
    })
    
    return jsonify({
        "success": True,
        "trip": {
            "id": trip.id,
            "resort_id": trip.resort_id,
            "state": trip.state,
            "state_abbr": STATE_ABBR.get(trip.state, trip.state),
            "mountain": trip.mountain,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
            "pass_type": trip.pass_type,
            "is_public": trip.is_public
        }
    })

@app.route("/api/trip/<int:trip_id>/edit", methods=["POST"])
@login_required
def edit_trip(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    data = request.get_json()
    trip.state = data.get("state")
    trip.mountain = data.get("mountain")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    trip.pass_type = data.get("pass_type", trip.pass_type or "No Pass")
    trip.is_public = data.get("is_public", True)
    
    trip.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    trip.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
    
    if not trip.start_date or not trip.end_date:
        return jsonify({"success": False, "error": "Please provide both start and end dates."}), 400
    
    if trip.end_date < trip.start_date:
        return jsonify({"success": False, "error": "End date cannot be before start date."}), 400
    
    overlapping = SkiTrip.query.filter(
        SkiTrip.user_id == current_user.id,
        SkiTrip.id != trip_id,
        SkiTrip.start_date <= trip.end_date,
        SkiTrip.end_date >= trip.start_date
    ).first()
    
    if overlapping:
        return jsonify({"success": False, "error": "You already have a trip during these dates."}), 409
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "trip": {
            "id": trip.id,
            "state": trip.state,
            "state_abbr": STATE_ABBR.get(trip.state, trip.state),
            "mountain": trip.mountain,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
            "pass_type": trip.pass_type,
            "is_public": trip.is_public
        }
    })

@app.route("/api/trip/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete_trip(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    delete_activities_for_trip(trip_id)
    db.session.delete(trip)
    db.session.commit()
    
    return jsonify({"success": True})


@app.route("/api/trip/<int:trip_id>/participant/settings", methods=["POST"])
@login_required
def update_participant_settings(trip_id):
    """Update current user's lesson and carpool settings for a trip."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Find participant record for current user
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id,
        user_id=current_user.id
    ).first()
    
    if not participant:
        return jsonify({"success": False, "error": "You are not a participant of this trip"}), 403
    
    data = request.get_json() or {}
    
    # Track if carpool changed for activity emission
    old_carpool_role = participant.carpool_role
    old_carpool_seats = participant.carpool_seats
    
    # Update lesson setting
    if 'taking_lesson' in data:
        lesson_val = data['taking_lesson']
        if lesson_val in ['yes', 'no', 'maybe']:
            participant.taking_lesson = LessonChoice(lesson_val)
    
    # Update carpool settings
    if 'carpool_role' in data:
        new_role = data['carpool_role']
        
        if new_role == 'driver':
            participant.carpool_role = CarpoolRole.DRIVER
            participant.needs_ride = None
            seats = data.get('carpool_seats', 1)
            participant.carpool_seats = max(1, min(int(seats), 10)) if seats else 1
        elif new_role == 'rider':
            participant.carpool_role = CarpoolRole.RIDER
            participant.carpool_seats = None
            participant.needs_ride = True
        else:
            # Not participating
            participant.carpool_role = None
            participant.carpool_seats = None
            participant.needs_ride = None
    
    # Handle seat update separately if driver
    if 'carpool_seats' in data and participant.carpool_role == CarpoolRole.DRIVER:
        seats = data['carpool_seats']
        participant.carpool_seats = max(1, min(int(seats), 10)) if seats else 1
    
    db.session.commit()
    
    # Emit activity if user became driver or changed seats
    if participant.carpool_role == CarpoolRole.DRIVER:
        should_emit = (
            old_carpool_role != CarpoolRole.DRIVER or
            old_carpool_seats != participant.carpool_seats
        )
        if should_emit and not trip.is_group_trip:
            emit_carpool_activity(current_user, trip, participant.carpool_seats)
    
    return jsonify({
        "success": True,
        "participant": {
            "taking_lesson": participant.taking_lesson.value if participant.taking_lesson else 'no',
            "carpool_role": participant.carpool_role.value if participant.carpool_role else None,
            "carpool_seats": participant.carpool_seats,
            "needs_ride": participant.needs_ride
        }
    })

@app.route("/api/friends/invite", methods=["POST"])
@login_required
def invite_friend():
    # Authentication guard (already protected by @login_required)
    if not current_user.is_authenticated:
        abort(401)
    
    # Safe form data handling
    data = request.get_json() or {}
    friend_email = data.get("friend_email")
    
    if not friend_email:
        return jsonify({"success": False, "error": "Friend email is required"}), 400
    
    # Validate target user exists
    friend = User.query.filter_by(email=friend_email).first()
    if not friend:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    if friend.id == current_user.id:
        return jsonify({"success": False, "error": "Cannot add yourself as a friend"}), 400
    
    # Prevent duplicate friendships
    existing_friendship = Friend.query.filter_by(user_id=current_user.id, friend_id=friend.id).first()
    if existing_friendship:
        return jsonify({"success": False, "error": "Already friends"}), 409
    
    # Prevent duplicate invites
    existing_invitation = Invitation.query.filter_by(sender_id=current_user.id, receiver_id=friend.id, status='pending').first()
    if existing_invitation:
        return jsonify({"success": False, "error": "Invitation already sent"}), 409
    
    # Database write safety
    try:
        invitation = Invitation(sender_id=current_user.id, receiver_id=friend.id, status='pending')
        db.session.add(invitation)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Invite failed")
        return jsonify({"success": False, "error": "Invite failed"}), 500
    
    return jsonify({"success": True, "message": "Invitation sent"}), 201

@app.route("/api/friends", methods=["GET"])
@login_required
def get_friends():
    friends = Friend.query.filter_by(user_id=current_user.id).all()
    
    friends_list = [{
        "id": f.friend.id,
        "name": f"{f.friend.first_name} {f.friend.last_name}",
        "email": f.friend.email,
        "pass_type": f.friend.pass_type or "No Pass"
    } for f in friends]
    
    return jsonify({"success": True, "friends": friends_list}), 200

@app.route("/api/friends/<int:friend_id>", methods=["GET"])
@login_required
def get_friend_profile(friend_id):
    
    friend = User.query.get(friend_id)
    if not friend:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    return jsonify({
        "success": True,
        "friend": {
            "id": friend.id,
            "name": f"{friend.first_name} {friend.last_name}",
            "email": friend.email,
            "pass_type": friend.pass_type or "No Pass",
            "rider_type": friend.display_rider_type or "Not specified"
        }
    }), 200

@app.route("/api/friends/invite/<int:invitation_id>/accept", methods=["POST"])
@login_required
def accept_invitation(invitation_id):
    invitation = Invitation.query.get(invitation_id)
    
    if not invitation:
        return jsonify({"success": False, "error": "Invitation not found"}), 404
    
    if invitation.receiver_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    invitation.status = 'accepted'
    
    friend_relationship = Friend(user_id=current_user.id, friend_id=invitation.sender_id)
    reverse_friend = Friend(user_id=invitation.sender_id, friend_id=current_user.id)
    
    db.session.add(friend_relationship)
    db.session.add(reverse_friend)
    emit_connection_accepted_activity(current_user.id, invitation.sender_id)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Friend added"}), 200

@app.route("/api/friends/<int:friend_id>", methods=["DELETE"])
@login_required
def remove_friend(friend_id):
    friend1 = Friend.query.filter_by(user_id=current_user.id, friend_id=friend_id).first()
    friend2 = Friend.query.filter_by(user_id=friend_id, friend_id=current_user.id).first()
    
    if not friend1 and not friend2:
        return jsonify({"success": False, "error": "Friendship not found"}), 404
    
    if friend1:
        db.session.delete(friend1)
    if friend2:
        db.session.delete(friend2)
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Friend removed"}), 200


@app.route("/api/friends/<int:friend_id>/set-trip-invites", methods=["POST"])
@login_required
def set_trip_invites(friend_id):
    """Set trip_invites_allowed for a friendship (explicit Yes/No, no toggle)."""
    friendship = Friend.query.filter_by(user_id=current_user.id, friend_id=friend_id).first()
    
    if not friendship:
        return jsonify({"success": False, "error": "Friendship not found"}), 404
    
    data = request.get_json() or {}
    allow = data.get('allow', False)
    
    friendship.trip_invites_allowed = bool(allow)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "trip_invites_allowed": friendship.trip_invites_allowed
    }), 200


@app.route("/api/buddy-pass", methods=["POST"])
@login_required
def update_buddy_pass():
    """Update buddy pass availability for a specific pass."""
    SUPPORTED_PASSES = ['epic', 'ikon', 'mountain_collective']
    
    data = request.get_json() or {}
    pass_key = data.get('pass_key', '').lower()
    available = data.get('available', False)
    
    if pass_key not in SUPPORTED_PASSES:
        return jsonify({"success": False, "error": "Unsupported pass"}), 400
    
    # Create a fresh dict to ensure SQLAlchemy detects the change
    buddy_passes = dict(current_user.buddy_passes or {})
    buddy_passes[pass_key] = bool(available)
    current_user.buddy_passes = buddy_passes
    
    db.session.commit()
    
    return jsonify({"success": True, "buddy_passes": buddy_passes}), 200


def pass_category(pass_type):
    """Categorize pass type into Epic, Ikon, or Other."""
    if pass_type in ["Epic", "Epic Local", "Epic Pass", "Epic 4-day"]:
        return "Epic"
    if pass_type in ["Ikon", "Ikon Base", "Ikon Plus", "Ikon Session"]:
        return "Ikon"
    return "Other"

@app.route("/friends")
@login_required
def friends():
    user = current_user
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    # Load friend relationships
    friend_links = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friend_links]
    all_friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    
    # Friends' Trips - upcoming trips from friends (for trips tab)
    friend_trips = []
    if friend_ids:
        friend_trips = SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.end_date >= today,
            SkiTrip.is_public == True
        ).order_by(SkiTrip.start_date.asc()).all()
    
    # User's upcoming trips for overlap detection
    user_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.end_date >= today
    ).all()
    
    # Build trip overlaps list (user trips vs friend trips at same location)
    trip_overlaps = []
    for my_trip in user_trips:
        for friend_trip in friend_trips:
            if my_trip.user_id != friend_trip.user_id:
                my_mountain = my_trip.mountain if my_trip.mountain else (my_trip.resort.name if my_trip.resort else None)
                friend_mountain = friend_trip.mountain if friend_trip.mountain else (friend_trip.resort.name if friend_trip.resort else None)
                if my_mountain and friend_mountain and my_mountain == friend_mountain:
                    if date_ranges_overlap(my_trip.start_date, my_trip.end_date, friend_trip.start_date, friend_trip.end_date):
                        resort = my_trip.resort or friend_trip.resort
                        overlap_start = max(my_trip.start_date, friend_trip.start_date)
                        overlap_end = min(my_trip.end_date, friend_trip.end_date)
                        trip_overlaps.append({
                            "type": "trip",
                            "mountain": my_mountain,
                            "resort": resort,
                            "resort_id": resort.id if resort else None,
                            "friend_id": friend_trip.user_id,
                            "friend_first_name": friend_trip.user.first_name,
                            "friend_trip_id": friend_trip.id,
                            "my_trip_id": my_trip.id,
                            "start_date": overlap_start,
                            "end_date": overlap_end
                        })
    
    # Build open date overlaps (user open dates vs friend open dates)
    open_date_overlaps = []
    user_open_dates = set(d for d in (user.open_dates or []) if d >= today_str)
    
    if user_open_dates and friend_ids:
        for friend in all_friends:
            friend_open_dates = set(d for d in (friend.open_dates or []) if d >= today_str)
            shared_dates = user_open_dates & friend_open_dates
            for date_str in shared_dates:
                open_date_overlaps.append({
                    "type": "open",
                    "date_str": date_str,
                    "friend_id": friend.id,
                    "friend_first_name": friend.first_name
                })
    
    # Build a lookup for friendship data (including trip_invites_allowed and created_at)
    friendship_lookup = {f.friend_id: f for f in friend_links}

    # Build per-friend label lookups
    trip_overlap_by_friend = {}
    for ov in trip_overlaps:
        fid = ov['friend_id']
        if fid not in trip_overlap_by_friend:
            trip_overlap_by_friend[fid] = []
        trip_overlap_by_friend[fid].append(ov)

    open_overlap_by_friend = {}
    for ov in open_date_overlaps:
        fid = ov['friend_id']
        if fid not in open_overlap_by_friend:
            open_overlap_by_friend[fid] = []
        open_overlap_by_friend[fid].append(ov['date_str'])

    friend_trips_by_id = {}
    for ft in friend_trips:
        fid = ft.user_id
        if fid not in friend_trips_by_id:
            friend_trips_by_id[fid] = []
        friend_trips_by_id[fid].append(ft)
    
    # Calculate sorting data for each friend
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    for friend in all_friends:
        friendship = friendship_lookup.get(friend.id)
        
        # Attach friendship permission
        friend._trip_invites_allowed = friendship.trip_invites_allowed if friendship else False
        
        # Is this a new friend (within 7 days)?
        friend._is_new_friend = False
        if friendship and friendship.created_at:
            friend._is_new_friend = friendship.created_at >= seven_days_ago
        
        # Get upcoming trips count using centralized helper
        friend._upcoming_trip_count = get_upcoming_trip_count(friend)
        friend._has_upcoming_trip = friend._upcoming_trip_count > 0
        
        # Find most recent upcoming trip created_at (for sorting)
        # We still need the actual trip objects for sorting metadata
        upcoming_owner_trips = SkiTrip.query.filter(
            SkiTrip.user_id == friend.id,
            SkiTrip.end_date >= today
        ).all()
        upcoming_participant_trips = (
            db.session.query(SkiTrip)
            .join(SkiTripParticipant, SkiTrip.id == SkiTripParticipant.trip_id)
            .filter(
                SkiTripParticipant.user_id == friend.id,
                SkiTripParticipant.status == GuestStatus.ACCEPTED,
                SkiTrip.end_date >= today
            )
            .all()
        )
        all_upcoming_trips_dict = {t.id: t for t in upcoming_owner_trips}
        for t in upcoming_participant_trips:
            all_upcoming_trips_dict[t.id] = t

        if all_upcoming_trips_dict:
            latest_created = max(t.created_at for t in all_upcoming_trips_dict.values() if t.created_at)
            friend._latest_upcoming_trip_created_at = latest_created
        else:
            friend._latest_upcoming_trip_created_at = None

        # Directory tab: trip count + going count
        friend._trip_count = friend._upcoming_trip_count
        friend._going_count = sum(
            1 for t in friend_trips_by_id.get(friend.id, [])
            if (t.trip_status or 'planning') == 'going'
        )

        # Compute display labels for friend list row
        friend._overlap_label = None
        friend._next_trip_label = None

        friend_ov_trips = sorted(trip_overlap_by_friend.get(friend.id, []), key=lambda x: x['start_date'])
        if friend_ov_trips:
            ov = friend_ov_trips[0]
            sd, ed = ov['start_date'], ov['end_date']
            if sd == ed:
                dates_str = sd.strftime('%b %-d')
            elif sd.month == ed.month:
                dates_str = f"{sd.strftime('%b %-d')}–{ed.strftime('%-d')}"
            else:
                dates_str = f"{sd.strftime('%b %-d')}–{ed.strftime('%b %-d')}"
            friend._overlap_label = f"Overlap at {ov['mountain']} · {dates_str}"
        else:
            friend_open_ovs = sorted(open_overlap_by_friend.get(friend.id, []))
            if friend_open_ovs:
                d = datetime.strptime(friend_open_ovs[0], '%Y-%m-%d').date()
                friend._overlap_label = f"Both free {d.strftime('%b %-d')}"

        friend_upcoming_pub = sorted(friend_trips_by_id.get(friend.id, []), key=lambda t: t.start_date)
        if friend_upcoming_pub:
            ft = friend_upcoming_pub[0]
            resort_name = ft.resort.name if ft.resort else (ft.mountain or '')
            state = ft.resort.state if ft.resort else (ft.state or '')
            dates_str = format_trip_dates(ft)
            ft_status = ft.trip_status or 'planning'
            dest = resort_name
            if state:
                dest += f", {state}"
            if dates_str:
                dest += f" · {dates_str}"
            if ft_status == 'going':
                label = f"Going to {dest}"
            else:
                label = f"Planning {dest}"
            friend._next_trip_label = label

    # Sort friends by:
    # 1. New friends first (is_new_friend DESC)
    # 2. Has upcoming trip (DESC)
    # 3. Latest upcoming trip created_at (DESC)
    # 4. First name alphabetically (ASC)
    def friend_sort_key(f):
        is_new = 0 if f._is_new_friend else 1  # 0 sorts before 1
        has_trip = 0 if f._has_upcoming_trip else 1
        # Use negative timestamp for DESC sort (more recent = smaller negative = earlier)
        latest_ts = 0
        if f._latest_upcoming_trip_created_at:
            latest_ts = -f._latest_upcoming_trip_created_at.timestamp()
        else:
            latest_ts = float('inf')  # No trips sorts last
        first_name = (f.first_name or '').lower()
        return (is_new, has_trip, latest_ts, first_name)
    
    all_friends_sorted = sorted(all_friends, key=friend_sort_key)

    invite_token_obj = get_or_create_invite_token(user)
    invite_url = (
        f"{BASE_URL}{url_for('invite_token_landing', token=invite_token_obj.token)}"
        if invite_token_obj else None
    )

    # ── friend_count for empty vs populated state switch ──────────────────────
    friend_count = len(all_friends)

    # ── alpha_groups: alphabetically grouped friends for directory tab ─────────
    alpha_sorted = sorted(all_friends, key=lambda f: (f.first_name or '').lower())
    alpha_groups = []
    for _f in alpha_sorted:
        _letter = (_f.first_name or '?')[0].upper()
        if not alpha_groups or alpha_groups[-1]['letter'] != _letter:
            alpha_groups.append({'letter': _letter, 'friends': []})
        alpha_groups[-1]['friends'].append(_f)

    # ── friends_trips_tab: month + destination grouped rows ───────────────────
    from collections import OrderedDict as _ODt
    friend_map = {f.id: f for f in all_friends}
    _raw_rows = []
    for _trip in friend_trips:
        _owner = friend_map.get(_trip.user_id)
        if not _owner:
            continue
        _dest = _trip.resort.name if _trip.resort else (_trip.mountain or 'TBD')
        _status = _trip.trip_status or 'planning'
        _is_new = bool(_trip.created_at and _trip.created_at >= seven_days_ago)
        _fmt_date = format_trip_dates(_trip)
        if _trip.start_date:
            _mkey = _trip.start_date.strftime('%Y-%m')
            _mlabel = _trip.start_date.strftime('%B %Y')
        else:
            _mkey = '9999-99'
            _mlabel = 'Dates TBD'
        _raw_rows.append({
            'destination': _dest,
            'friend_name': _owner.first_name or '',
            'friend_id': _owner.id,
            'status': _status,
            'is_new': _is_new,
            'formatted_date': _fmt_date,
            'month_key': _mkey,
            'month_label': _mlabel,
        })
    _months_dict = _ODt()
    for _row in _raw_rows:
        _mk = _row['month_key']
        if _mk not in _months_dict:
            _months_dict[_mk] = {'month_label': _row['month_label'], 'destinations': _ODt()}
        _dk = _row['destination']
        if _dk not in _months_dict[_mk]['destinations']:
            _months_dict[_mk]['destinations'][_dk] = []
        _months_dict[_mk]['destinations'][_dk].append(_row)
    friends_trips_tab = [
        {
            'month_label': _md['month_label'],
            'destinations': [
                {'name': _dn, 'rows': _dr}
                for _dn, _dr in _md['destinations'].items()
            ],
        }
        for _md in _months_dict.values()
    ]

    return render_template(
        "friends.html",
        user=user,
        friends=all_friends_sorted,
        invite_url=invite_url,
        format_trip_dates=format_trip_dates,
        friend_count=friend_count,
        alpha_groups=alpha_groups,
        friends_trips_tab=friends_trips_tab,
    )

@app.route("/friends/<int:friend_id>")
@login_required
def friend_profile(friend_id):
    friend = User.query.get_or_404(friend_id)
    user = current_user
    
    # Parse overlap context from URL params (for context banner)
    overlap_context = None
    resort_id = request.args.get('resort_id', type=int)
    overlap_start = request.args.get('overlap_start')
    overlap_end = request.args.get('overlap_end')
    
    if resort_id and overlap_start:
        resort = Resort.query.get(resort_id)
        if resort:
            try:
                start_date = datetime.strptime(overlap_start, '%Y-%m-%d').date()
                end_date = datetime.strptime(overlap_end, '%Y-%m-%d').date() if overlap_end else start_date
                overlap_context = {
                    'resort_name': resort.name,
                    'start_date': start_date,
                    'end_date': end_date
                }
            except (ValueError, TypeError):
                pass
    
    mountains = friend.mountains_visited or []
    friend_mountains_count = len(mountains)
    friend_mountains_sorted = sorted([m.name if hasattr(m, 'name') else m for m in mountains])
    
    # Get Resort objects for profile card (new unified component)
    friend_visited_resorts = friend.get_visited_resorts()
    friend_wishlist_resorts = friend.get_wishlist_resorts()
    
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    # Get friend's equipment
    friend_primary_equipment = EquipmentSetup.query.filter_by(user_id=friend.id, slot=EquipmentSlot.PRIMARY).first()
    friend_secondary_equipment = EquipmentSetup.query.filter_by(user_id=friend.id, slot=EquipmentSlot.SECONDARY).first()
    
    # Get friend's trips
    trips = (
        SkiTrip.query
        .filter_by(user_id=friend.id, is_public=True)
        .filter(SkiTrip.end_date >= today)
        .order_by(SkiTrip.start_date.asc())
        .all()
    )
    
    # Get current user's trips (for overlap detection and pass compatibility)
    user_trips = (
        SkiTrip.query
        .filter_by(user_id=user.id)
        .filter(SkiTrip.end_date >= today)
        .all()
    )
    
    # Build trip overlaps list for display
    trip_overlaps = []
    for trip in trips:
        trip.has_trip_overlap = False
        for user_trip in user_trips:
            # Resort match: prefer resort_id (canonical), fall back to mountain string
            if trip.resort_id and user_trip.resort_id:
                same_resort = (trip.resort_id == user_trip.resort_id)
            else:
                same_resort = bool(trip.mountain and user_trip.mountain and trip.mountain == user_trip.mountain)
            if same_resort:
                if date_ranges_overlap(trip.start_date, trip.end_date, user_trip.start_date, user_trip.end_date):
                    trip.has_trip_overlap = True
                    overlap_start = max(trip.start_date, user_trip.start_date)
                    overlap_end = min(trip.end_date, user_trip.end_date)
                    resort = trip.resort or user_trip.resort
                    trip_overlaps.append({
                        "mountain": resort.name if resort else trip.mountain,
                        "state": resort.state if resort else trip.state,
                        "start_date": overlap_start,
                        "end_date": overlap_end
                    })
                    break
    
    # Check pass compatibility - can friend ski at user's upcoming trips?
    friend_passes = set(p.strip() for p in friend.pass_type.split(',')) if friend.pass_type else set()
    can_ski_user_trips = False
    for user_trip in user_trips:
        if user_trip.resort:
            # Use pass_brands if available, fallback to brand
            resort_pass_str = user_trip.resort.pass_brands or user_trip.resort.brand
            if resort_pass_str:
                resort_passes = set(p.strip() for p in resort_pass_str.split(','))
                if friend_passes & resort_passes:
                    can_ski_user_trips = True
                    break
    
    # Get friend's open dates from JSON field (filter to future dates only)
    friend_open_dates_raw = friend.open_dates or []
    friend_open_dates = sorted([d for d in friend_open_dates_raw if d >= today_str])
    friend_open_dates_display = format_open_dates_summary(friend_open_dates) if friend_open_dates else None
    
    # Compute availability overlaps
    user_open_dates_raw = user.open_dates or []
    user_open_dates = sorted([d for d in user_open_dates_raw if d >= today_str])
    
    availability_overlaps = compute_availability_overlaps(user_open_dates, friend_open_dates)
    availability_display, availability_remaining = format_availability_ranges(availability_overlaps)
    
    # Check for shared GroupTrips and existing friendship
    shared_trip_exists = check_shared_upcoming_trip(user.id, friend.id)
    already_friends = Friend.query.filter_by(user_id=user.id, friend_id=friend.id).first() is not None
    show_connect_button = shared_trip_exists and not already_friends
    
    # Get friend's wish list resorts
    friend_wish_list_ids = friend.wish_list_resorts or []
    friend_wish_list = Resort.query.filter(Resort.id.in_(friend_wish_list_ids)).all() if friend_wish_list_ids else []
    
    # Calculate wish list overlap with current user
    user_wish_list_ids = set(user.wish_list_resorts or [])
    wish_list_overlap_ids = [rid for rid in friend_wish_list_ids if rid in user_wish_list_ids]
    wish_list_overlap = Resort.query.filter(Resort.id.in_(wish_list_overlap_ids)).all() if wish_list_overlap_ids else []
    
    return render_template(
        "friend_profile.html",
        friend=friend,
        friend_mountains_count=friend_mountains_count,
        friend_mountains=friend_mountains_sorted,
        trips=trips,
        trip_overlaps=trip_overlaps,
        friend_open_dates=friend_open_dates,
        friend_open_dates_display=friend_open_dates_display,
        has_availability_overlap=len(availability_overlaps) > 0,
        availability_display=availability_display,
        availability_remaining=availability_remaining,
        show_connect_button=show_connect_button,
        friend_primary_equipment=friend_primary_equipment,
        friend_secondary_equipment=friend_secondary_equipment,
        can_ski_user_trips=can_ski_user_trips,
        friend_wish_list=friend_wish_list,
        wish_list_overlap=wish_list_overlap,
        visited_resorts=friend_visited_resorts,
        wishlist_resorts=friend_wishlist_resorts,
        overlap_context=overlap_context,
        stat_upcoming=len(trips),
        stat_mountains=friend.visited_resorts_count,
        stat_past=get_past_trip_count(friend),
        stat_wishlist=len(friend.wish_list_resorts or []),
        stat_trips_total=SkiTrip.query.filter_by(user_id=friend.id).count(),
    )

@app.route("/profile/<int:user_id>")
@login_required
def friend_profile_legacy(user_id):
    """Legacy route - redirect to the main friend profile page."""
    # Check if viewing own profile
    if user_id == current_user.id:
        return redirect(url_for("more"))
    
    # Redirect to the main friend profile route
    return redirect(url_for("friend_profile", friend_id=user_id))

@app.route("/api/profile/update", methods=["POST"])
@login_required
def update_profile():
    user = current_user
    
    data = request.get_json()
    
    if "first_name" in data:
        user.first_name = data.get("first_name", "").strip()
    if "last_name" in data:
        user.last_name = data.get("last_name", "").strip()
    if "rider_type" in data:
        # Update primary_rider_type instead of legacy rider_type
        user.primary_rider_type = data.get("rider_type", "").strip()
    if "primary_rider_type" in data:
        user.primary_rider_type = data.get("primary_rider_type", "").strip()
    if "secondary_rider_types" in data:
        secondary = data.get("secondary_rider_types", [])
        if isinstance(secondary, list):
            user.secondary_rider_types = secondary[:2]
    if "pass_type" in data:
        user.pass_type = data.get("pass_type", "").strip()
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Profile updated"}), 200

@app.route("/create-trip")
@login_required
def create_trip_page():
    # Legacy route — retired. Redirect to canonical /add_trip, preserving all prefill params.
    params = {k: v for k, v in request.args.items()}
    return redirect(url_for("add_trip", **params), 302)

# ============================================================================
# PLANNING FEATURE
# Shows availability overlap windows between current user and friends
# ============================================================================

def group_dates_into_windows(dates):
    """Group a list of date strings into consecutive windows.
    
    Args:
        dates: List of 'YYYY-MM-DD' date strings (must be sorted)
    
    Returns:
        List of tuples: [(start_date, end_date), ...]
    """
    if not dates:
        return []
    
    windows = []
    sorted_dates = sorted(dates)
    
    window_start = sorted_dates[0]
    window_end = sorted_dates[0]
    
    for i in range(1, len(sorted_dates)):
        current = sorted_dates[i]
        prev = sorted_dates[i - 1]
        
        # Check if consecutive (within 1 day)
        try:
            current_date = datetime.strptime(current, '%Y-%m-%d').date()
            prev_date = datetime.strptime(prev, '%Y-%m-%d').date()
            
            if (current_date - prev_date).days <= 1:
                window_end = current
            else:
                windows.append((window_start, window_end))
                window_start = current
                window_end = current
        except ValueError:
            continue
    
    windows.append((window_start, window_end))
    return windows


def get_planning_windows(user):
    """Get availability overlap windows for the planning feed.
    
    Returns a list of windows, each containing:
    - start_date: 'YYYY-MM-DD'
    - end_date: 'YYYY-MM-DD'
    - friends: list of friend user objects
    - friend_names_display: formatted string for display
    """
    from services.open_dates import get_open_date_matches
    
    matches = get_open_date_matches(user)
    if not matches:
        return []
    
    # Group matches by date
    date_to_friends = {}
    friend_cache = {}
    
    for match in matches:
        d = match['date']
        fid = match['friend_id']
        
        if d not in date_to_friends:
            date_to_friends[d] = set()
        date_to_friends[d].add(fid)
        
        # Cache friend info
        if fid not in friend_cache:
            friend_cache[fid] = {
                'id': fid,
                'name': match['friend_name'],
                'pass': match['friend_pass']
            }
    
    # Filter to future dates only
    today_str = date.today().strftime('%Y-%m-%d')
    future_dates = sorted([d for d in date_to_friends.keys() if d >= today_str])
    
    if not future_dates:
        return []
    
    # Group consecutive dates into windows
    windows = group_dates_into_windows(future_dates)
    
    # For each window, find friends who are available for ALL dates in that window
    result = []
    for start, end in windows:
        # Get all dates in this window
        window_dates = [d for d in future_dates if start <= d <= end]
        
        if not window_dates:
            continue
        
        # Find friends available on ALL dates in window
        friends_per_date = [date_to_friends.get(d, set()) for d in window_dates]
        common_friends = set.intersection(*friends_per_date) if friends_per_date else set()
        
        if not common_friends:
            continue
        
        # Build friend info list
        friends = [friend_cache[fid] for fid in common_friends]
        friends.sort(key=lambda f: f['name'] or '')
        
        # Format display string
        names = [f['name'] for f in friends if f['name']]
        if len(names) == 0:
            continue
        elif len(names) == 1:
            display = f"{names[0]} is free"
        elif len(names) == 2:
            display = f"{names[0]} and {names[1]} are free"
        else:
            display = f"{names[0]} + {len(names) - 1} others are free"
        
        result.append({
            'start_date': start,
            'end_date': end,
            'friends': friends,
            'friend_names_display': display
        })
    
    return result


def format_planning_dates(start_str, end_str):
    """Format date range for planning display (e.g., 'Jan 18–21' or 'Jan 25–Feb 1')."""
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d').date()
        end = datetime.strptime(end_str, '%Y-%m-%d').date()
        
        if start == end:
            return start.strftime('%b %-d')
        elif start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.day}"
        else:
            return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d')}"
    except ValueError:
        return f"{start_str} – {end_str}"


@app.route("/planning")
@login_required
def planning():
    """Redirect to My Trips with Ideas tab selected (legacy Planning route)."""
    return redirect(url_for('my_trips', tab='ideas'))


@app.route("/planning/window/<start_date>/<end_date>")
@login_required
def planning_window(start_date, end_date):
    user = current_user
    
    # Validate date format
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        flash("Invalid date range", "error")
        return redirect(url_for('my_trips', tab='ideas'))
    
    # Get friends available in this window
    from services.open_dates import get_open_date_matches
    matches = get_open_date_matches(user)
    
    # Find friends with overlapping dates in this window
    window_dates = set()
    d = start
    while d <= end:
        window_dates.add(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    
    # Group by friend and check if they overlap with this window
    friend_ids_in_window = set()
    for match in matches:
        if match['date'] in window_dates:
            friend_ids_in_window.add(match['friend_id'])
    
    # Load friend details
    friends_data = []
    if friend_ids_in_window:
        friends = User.query.filter(User.id.in_(friend_ids_in_window)).all()
        for friend in friends:
            # Build identity line (same format as elsewhere)
            identity_parts = []
            if friend.primary_rider_type:
                identity_parts.append(friend.primary_rider_type)
            if friend.pass_type:
                identity_parts.append(friend.pass_type)
            if friend.skill_level:
                identity_parts.append(friend.skill_level)
            
            identity_line = ' · '.join(identity_parts) if identity_parts else ''
            
            friends_data.append({
                'id': friend.id,
                'name': f"{friend.first_name} {friend.last_name}".strip(),
                'identity_line': identity_line
            })
        
        friends_data.sort(key=lambda f: f['name'])
    
    # Format header
    display_dates = format_planning_dates(start_date, end_date)
    
    return render_template(
        "planning_window.html",
        user=user,
        friends=friends_data,
        display_dates=display_dates,
        start_date=start_date,
        end_date=end_date
    )


@app.route("/invite")
@login_required
def invite():
    # Check if user has reached their invite accept limit
    if not can_sender_accept_more_invites(current_user):
        return render_template("invite_limit_reached.html", user=current_user)
    
    invite_token = get_or_create_invite_token(current_user)
    invite_url = f"{BASE_URL}{url_for('invite_token_landing', token=invite_token.token)}"
    
    return render_template("invite.html", user=current_user, invite_url=invite_url, remaining_invites=None)

@app.route("/my-qr")
@login_required
def my_qr():
    invite_token = get_or_create_invite_token(current_user)
    if not invite_token:
        return render_template("invite_limit_reached.html", user=current_user)
    qr_url = f"{BASE_URL}{url_for('invite_token_landing', token=invite_token.token)}"
    qr = segno.make(qr_url)
    buf = BytesIO()
    qr.save(buf, kind="png", scale=8)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/connect/<int:user_id>")
def connect_via_qr(user_id):
    inviter = User.query.get_or_404(user_id)
    
    if not current_user.is_authenticated:
        return redirect(url_for("auth", next=url_for("connect_via_qr", user_id=user_id)))
    
    if current_user.id == inviter.id:
        return render_template("connect_self.html")
    
    existing = Friend.query.filter_by(user_id=current_user.id, friend_id=inviter.id).first()
    if existing:
        return render_template("already_friends.html", friend=inviter)
    
    return render_template("connect_confirm.html", friend=inviter)

@app.route("/connect/<int:user_id>/add", methods=["POST"])
@login_required
def connect_add(user_id):
    inviter = User.query.get_or_404(user_id)
    
    existing_a_to_b = Friend.query.filter_by(user_id=current_user.id, friend_id=inviter.id).first()
    existing_b_to_a = Friend.query.filter_by(user_id=inviter.id, friend_id=current_user.id).first()
    
    if not existing_a_to_b:
        new_a_to_b = Friend(user_id=current_user.id, friend_id=inviter.id)
        db.session.add(new_a_to_b)
    
    if not existing_b_to_a:
        new_b_to_a = Friend(user_id=inviter.id, friend_id=current_user.id)
        db.session.add(new_b_to_a)
    
    db.session.commit()
    return render_template("connect_success.html", friend=inviter)

@app.route("/invite/<int:user_id>")
def invite_link(user_id):
    inviter = User.query.get_or_404(user_id)

    # If not logged in → send to login/signup
    if not current_user.is_authenticated:
        return redirect(url_for("auth", next=url_for("invite_link", user_id=user_id)))

    # Prevent connecting to self
    if current_user.id == inviter.id:
        return render_template("connect_self.html")

    # Check if already friends
    existing = Friend.query.filter_by(user_id=current_user.id, friend_id=inviter.id).first()
    if existing:
        return render_template("already_friends.html", friend=inviter)

    # Create mutual friendship
    pair1 = Friend(user_id=current_user.id, friend_id=inviter.id)
    pair2 = Friend(user_id=inviter.id, friend_id=current_user.id)

    db.session.add(pair1)
    db.session.add(pair2)
    db.session.commit()

    return render_template("connect_success.html", friend=inviter)

def date_ranges_overlap(start1, end1, start2, end2):
    """Check if two date ranges overlap"""
    return start1 <= end2 and start2 <= end1

def format_open_dates_summary(date_strings):
    """Format a list of YYYY-MM-DD strings into human-readable summary grouped by month.
    E.g., ['2024-12-14', '2024-12-18', '2024-12-19', '2025-01-03', '2025-01-04'] 
    -> 'Dec 14,18,19 | Jan 3,4'
    
    Preserves year separation: dates from different years with same month are kept separate.
    """
    if not date_strings:
        return None
    
    from datetime import datetime as dt
    from collections import OrderedDict
    
    # Parse and sort dates
    dates = sorted([dt.strptime(d, '%Y-%m-%d').date() for d in date_strings])
    
    # Group dates by (year, month) to preserve year separation
    months = OrderedDict()
    for d in dates:
        month_key = (d.year, d.month, d.strftime('%b'))  # (2024, 12, 'Dec')
        if month_key not in months:
            months[month_key] = []
        months[month_key].append(d.day)
    
    # Format each month group: "Jan 1,2,3,4"
    # Year is omitted from display but used for correct grouping
    formatted = []
    for (year, month, month_name), days in months.items():
        days_str = ','.join(str(d) for d in days)
        formatted.append(f"{month_name} {days_str}")
    
    return '\n'.join(formatted)

def dates_to_ranges(date_strings):
    """Convert a list of YYYY-MM-DD strings to a list of {start_date, end_date} dicts.
    Groups consecutive dates into ranges.
    E.g., ['2024-12-14', '2024-12-15', '2024-12-16'] -> [{start_date: date(2024-12-14), end_date: date(2024-12-16)}]
    """
    if not date_strings:
        return []
    
    from datetime import datetime as dt
    
    # Parse and sort dates
    dates = sorted([dt.strptime(d, '%Y-%m-%d').date() for d in date_strings])
    
    # Group consecutive dates
    ranges = []
    current_start = dates[0]
    current_end = dates[0]
    
    for i in range(1, len(dates)):
        if (dates[i] - current_end).days == 1:
            current_end = dates[i]
        else:
            ranges.append({"start_date": current_start, "end_date": current_end})
            current_start = dates[i]
            current_end = dates[i]
    
    ranges.append({"start_date": current_start, "end_date": current_end})
    return ranges


def check_trip_invite_eligibility(user_id, friend_id):
    """
    Check if user can invite friend to a trip.
    Returns True if at least ONE condition is met:
    1. They share a trip overlap (past or upcoming)
    2. They share open availability
    3. The friendship has trip_invites_allowed = True
    """
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    # Check 1: Friendship permission
    friendship = Friend.query.filter_by(user_id=user_id, friend_id=friend_id).first()
    if friendship and friendship.trip_invites_allowed:
        return True
    
    # Check 2: Trip overlap (any trip, past or upcoming)
    user_trips = SkiTrip.query.filter_by(user_id=user_id).all()
    friend_trips = SkiTrip.query.filter(
        SkiTrip.user_id == friend_id,
        SkiTrip.is_public == True
    ).all()
    
    for ut in user_trips:
        for ft in friend_trips:
            if ut.mountain == ft.mountain:
                if date_ranges_overlap(ut.start_date, ut.end_date, ft.start_date, ft.end_date):
                    return True
    
    # Check 3: Shared open availability
    user = User.query.get(user_id)
    friend = User.query.get(friend_id)
    if user and friend:
        user_open_dates = set(d for d in (user.open_dates or []) if d >= today_str)
        friend_open_dates = set(d for d in (friend.open_dates or []) if d >= today_str)
        if user_open_dates & friend_open_dates:
            return True
    
    return False


def compute_availability_overlaps(user_open_dates, friend_open_dates):
    """Compute overlapping date ranges between user and friend's open dates.
    Returns list of {start_date, end_date} dicts representing overlap ranges.
    Uses exact overlap logic: overlap_start = max(...), overlap_end = min(...).
    Then merges overlapping/adjacent ranges.
    """
    if not user_open_dates or not friend_open_dates:
        return []
    
    # Convert individual dates to ranges
    user_ranges = dates_to_ranges(user_open_dates)
    friend_ranges = dates_to_ranges(friend_open_dates)
    
    # Find all overlaps
    overlaps = []
    for user_r in user_ranges:
        for friend_r in friend_ranges:
            overlap_start = max(user_r["start_date"], friend_r["start_date"])
            overlap_end = min(user_r["end_date"], friend_r["end_date"])
            
            if overlap_start <= overlap_end:
                overlaps.append({"start_date": overlap_start, "end_date": overlap_end})
    
    if not overlaps:
        return []
    
    # Sort by start_date
    overlaps = sorted(overlaps, key=lambda x: x["start_date"])
    
    # Merge overlapping/adjacent ranges
    merged = [overlaps[0]]
    for current in overlaps[1:]:
        last = merged[-1]
        # Check if current overlaps or is adjacent to last (within 1 day)
        if current["start_date"] <= last["end_date"] + timedelta(days=1):
            # Merge
            last["end_date"] = max(last["end_date"], current["end_date"])
        else:
            # No overlap, add as new range
            merged.append(current)
    
    return merged

def format_availability_ranges(ranges):
    """Format a list of {start_date, end_date} dicts for display.
    E.g., [{start: date(2024-12-14), end: date(2024-12-19)}] -> 'Dec 14–19'
    """
    if not ranges:
        return None, 0
    
    formatted = []
    for r in ranges[:2]:  # Only display first 2
        start_str = r["start_date"].strftime('%b %d').replace(' 0', ' ')
        end_str = r["end_date"].strftime('%d').lstrip('0')
        
        # If same month, just show "Dec 14–19"
        if r["start_date"].month == r["end_date"].month:
            formatted.append(f"{start_str}–{end_str}")
        else:
            end_full = r["end_date"].strftime('%b %d').replace(' 0', ' ')
            formatted.append(f"{start_str}–{end_full}")
    
    remaining_count = max(0, len(ranges) - 2)
    return ' · '.join(formatted), remaining_count

@app.route("/home")
@login_required
def home():
    user = current_user
    today = date.today()

    # --- Next Trip (created or accepted) ---
    try:
        my_trips = SkiTrip.query.filter(
            SkiTrip.user_id == user.id,
            SkiTrip.end_date >= today
        ).order_by(SkiTrip.start_date.asc()).all()
    except Exception:
        db.session.rollback()
        my_trips = []

    try:
        accepted_participations = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == user.id,
            SkiTripParticipant.status == GuestStatus.ACCEPTED
        ).all()
        accepted_trip_ids = [p.trip_id for p in accepted_participations]
        accepted_guest_trips = SkiTrip.query.filter(
            SkiTrip.id.in_(accepted_trip_ids),
            SkiTrip.user_id != user.id,
            SkiTrip.end_date >= today
        ).order_by(SkiTrip.start_date.asc()).all() if accepted_trip_ids else []
    except Exception:
        db.session.rollback()
        accepted_guest_trips = []

    all_upcoming = sorted(my_trips + accepted_guest_trips, key=lambda t: t.start_date)
    next_trip = all_upcoming[0] if all_upcoming else None
    next_trip_countdown = None
    if next_trip:
        days_until = (next_trip.start_date - today).days
        if days_until == 0:
            next_trip_countdown = "Starts today"
        elif days_until == 1:
            next_trip_countdown = "Tomorrow"
        else:
            next_trip_countdown = f"In {days_until} days"

    # --- Friend IDs ---
    try:
        friend_links = Friend.query.filter_by(user_id=user.id).all()
        friend_ids = [f.friend_id for f in friend_links]
    except Exception:
        db.session.rollback()
        friend_ids = []

    # --- Trip Invite Banner (soonest active pending trip invite) ---
    banner_invite = None
    banner_invite_count = 0
    try:
        invited_participations = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == user.id,
            SkiTripParticipant.status == GuestStatus.INVITED
        ).all()
        active_invites = sorted(
            [p for p in invited_participations if p.trip and p.trip.end_date >= today],
            key=lambda p: p.trip.start_date
        )
        banner_invite_count = len(active_invites)
        if active_invites:
            p = active_invites[0]
            trip = p.trip
            inviter = User.query.get(trip.user_id)
            resort = trip.resort
            banner_invite = {
                'trip_id': trip.id,
                'trip': trip,
                'resort': resort,
                'inviter_name': inviter.first_name if inviter else 'Someone',
            }
    except Exception:
        db.session.rollback()

    # --- Availability Nudge (open date overlap with friends) ---
    availability_nudge = None
    try:
        my_open_dates = {d for d in (user.open_dates or []) if d >= today.strftime('%Y-%m-%d')}
        if my_open_dates and friend_ids:
            friends_with_open = User.query.filter(User.id.in_(friend_ids)).all()
            best_date = None
            best_friends = []
            for date_str in sorted(my_open_dates):
                matching = [f for f in friends_with_open if date_str in set(f.open_dates or [])]
                if len(matching) > len(best_friends):
                    best_date = date_str
                    best_friends = matching
            if best_date and best_friends:
                date_obj = datetime.strptime(best_date, '%Y-%m-%d').date()
                display = date_obj.strftime('%b %-d')
                if len(best_friends) == 1:
                    nudge_text = f"You and {best_friends[0].first_name} are free {display}"
                else:
                    nudge_text = f"You and {len(best_friends)} friends are free {display}"
                availability_nudge = {
                    'text': nudge_text,
                    'href': url_for('friends', tab='overlaps')
                }
    except Exception:
        db.session.rollback()
        availability_nudge = None

    # --- Secondary Card (priority: connect_invite > overlap > friend_trip) ---
    secondary_card = None
    try:
        connect_inv = Invitation.query.filter_by(
            receiver_id=user.id,
            status='pending'
        ).filter(Invitation.trip_id == None).first()
        if connect_inv:
            sender = User.query.get(connect_inv.sender_id)
            secondary_card = {
                'type': 'connect_invite',
                'invitation_id': connect_inv.id,
                'sender_name': sender.first_name if sender else 'Someone',
            }
    except Exception:
        db.session.rollback()

    # --- Next Best Match (ranked — same #1 as Ideas page) ---
    next_match = None
    has_overlaps = False
    try:
        from services.ideas_ranking import score_overlap_windows as _rank_home
        overlap_matches = get_open_date_matches(user)
        if overlap_matches:
            has_overlaps = True
            home_windows = build_overlap_windows(overlap_matches, user.pass_type)
            home_friend_users = (
                User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
            )
            home_wishlist_set = set(user.wish_list_resorts or [])
            home_shared_wishlist_ids = set()
            if home_wishlist_set:
                for _hf in home_friend_users:
                    if home_wishlist_set & set(_hf.wish_list_resorts or []):
                        home_shared_wishlist_ids.add(_hf.id)
            home_windows = _rank_home(home_windows, user, home_shared_wishlist_ids)
            if home_windows:
                best_win = home_windows[0]
                start_obj = date.fromisoformat(best_win["start_date"])
                anchor_name = best_win.get("anchor_friend_name") or "a friend"
                anchor_id = best_win.get("anchor_friend_id")
                extra_friends = max(best_win.get("friend_count", 1) - 1, 0)
                next_match = {
                    "match_date": best_win["start_date"],
                    "display_date": start_obj.strftime("%A · %b %-d"),
                    "friend_name": anchor_name,
                    "friend_id": anchor_id,
                    "same_day_count": extra_friends,
                }
    except Exception:
        db.session.rollback()

    if not secondary_card and availability_nudge:
        secondary_card = {
            'type': 'overlap',
            'text': availability_nudge['text'],
            'href': availability_nudge['href'],
        }

    if not secondary_card and friend_ids:
        try:
            friend_trip = SkiTrip.query.filter(
                SkiTrip.user_id.in_(friend_ids),
                SkiTrip.is_public == True,
                SkiTrip.end_date >= today
            ).order_by(SkiTrip.start_date.asc()).first()
            if friend_trip:
                trip_friend = User.query.get(friend_trip.user_id)
                trip_resort = friend_trip.resort
                mountain_name = trip_resort.name if trip_resort else friend_trip.mountain
                secondary_card = {
                    'type': 'friend_trip',
                    'trip_id': friend_trip.id,
                    'friend_name': trip_friend.first_name if trip_friend else 'A friend',
                    'mountain': mountain_name,
                    'trip_status': friend_trip.trip_status or 'planning',
                }
        except Exception:
            db.session.rollback()

    return render_template(
        'home.html',
        user=user,
        next_trip=next_trip,
        next_trip_countdown=next_trip_countdown,
        banner_invite=banner_invite,
        banner_invite_count=banner_invite_count,
        secondary_card=secondary_card,
        next_match=next_match,
        has_overlaps=has_overlaps,
        stat_upcoming=get_upcoming_trip_count(user),
        stat_mountains=user.visited_resorts_count,
        stat_past=get_past_trip_count(user),
        stat_trips_total=SkiTrip.query.filter_by(user_id=user.id).count(),
        stat_wishlist=len(user.wish_list_resorts or []),
        stat_trips_url=url_for('my_trips'),
        stat_mountains_url=url_for('mountains_visited'),
        stat_wishlist_url=url_for('settings_wish_list'),
        home_eq=user.get_active_equipment(),
    )


@app.route("/onboarding/equipment", methods=["POST"])
@login_required
def save_onboarding_equipment():
    """Save equipment status from progressive completion modal."""
    user = current_user
    
    equipment_status = request.form.get("equipment_status")
    equipment_brand = request.form.get("equipment_brand", "").strip() or None
    equipment_model = request.form.get("equipment_model", "").strip() or None
    boot_brand = request.form.get("boot_brand", "").strip() or None
    boot_model = request.form.get("boot_model", "").strip() or None
    
    if not equipment_status:
        return redirect(url_for("home"))
    
    # Get or create active equipment setup
    equipment = EquipmentSetup.query.filter_by(
        user_id=user.id,
        is_active=True
    ).first()
    
    if not equipment:
        equipment = EquipmentSetup(
            user_id=user.id,
            is_active=True
        )
        db.session.add(equipment)
    
    equipment.equipment_status = equipment_status
    equipment.brand = equipment_brand
    equipment.model = equipment_model
    equipment.boot_brand = boot_brand
    equipment.boot_model = boot_model
    
    db.session.commit()
    return redirect(url_for("home"))


@app.route("/onboarding/riding-style", methods=["POST"])
@login_required
def save_onboarding_riding_style():
    """Save terrain preferences from progressive completion modal."""
    user = current_user
    
    # Try hidden input first (populated by JS), then fall back to checkbox values
    terrain_raw = request.form.get("terrain_preferences", "")
    terrain_list = [t.strip() for t in terrain_raw.split(",") if t.strip()][:2]
    
    # Fallback: read directly from checkboxes if hidden input is empty
    if not terrain_list:
        terrain_list = request.form.getlist("terrain_pref")[:2]
    
    if terrain_list:
        user.terrain_preferences = terrain_list
        db.session.commit()
    
    return redirect(url_for("home"))


@app.route("/onboarding/welcome-shown", methods=["POST"])
@login_required
def mark_welcome_shown():
    """Mark the welcome modal as dismissed (once only)."""
    user = current_user
    
    if not user.welcome_modal_seen_at:
        user.welcome_modal_seen_at = datetime.utcnow()
        db.session.commit()
    
    # Support custom redirect destinations from welcome screen
    redirect_to = request.form.get("redirect_to")
    if redirect_to and redirect_to.startswith('/'):
        return redirect(redirect_to)
    
    return redirect(url_for("home"))


@app.route("/dismiss-nudge", methods=["POST"])
@login_required
def dismiss_nudge():
    """Dismiss an availability nudge so it doesn't resurface."""
    date_str = request.form.get("date")
    if date_str:
        try:
            nudge_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            # Store dismissal for this specific date
            existing = DismissedNudge.query.filter_by(
                user_id=current_user.id,
                date_range_start=nudge_date,
                date_range_end=nudge_date
            ).first()
            if not existing:
                dismissal = DismissedNudge(
                    user_id=current_user.id,
                    date_range_start=nudge_date,
                    date_range_end=nudge_date
                )
                db.session.add(dismissal)
                db.session.commit()
        except ValueError:
            pass
    return redirect(url_for("home"))


@app.route("/friend-trip/<int:trip_id>")
@login_required
def friend_trip_details(trip_id):
    """View details of a friend's trip."""
    trip = SkiTrip.query.get_or_404(trip_id)
    friend = User.query.get(trip.user_id)

    # Prevent users from viewing trips of non-friends (unless it's their own)
    if trip.user_id != current_user.id:
        is_friend = Friend.query.filter_by(
            user_id=current_user.id,
            friend_id=friend.id
        ).first()

        if not is_friend:
            return "Unauthorized", 403

    # Calculate overlapping days with current user's trips at the same resort
    your_trips = SkiTrip.query.filter_by(user_id=current_user.id).all()
    
    # Filter for same mountain/resort
    # Note: Resort ID is preferred if both trips have it, otherwise fallback to mountain string
    matching_trips = []
    for yt in your_trips:
        if trip.resort_id and yt.resort_id:
            if trip.resort_id == yt.resort_id:
                matching_trips.append(yt)
        elif yt.mountain == trip.mountain:
            matching_trips.append(yt)

    def overlapping_days(a_start, a_end, b_start, b_end):
        latest_start = max(a_start, b_start)
        earliest_end = min(a_end, b_end)
        delta = (earliest_end - latest_start).days + 1
        return max(0, delta)

    your_overlap_days = 0
    your_overlap_ranges = []

    for yt in matching_trips:
        days = overlapping_days(
            trip.start_date,
            trip.end_date,
            yt.start_date,
            yt.end_date
        )
        if days > 0:
            your_overlap_days += days
            your_overlap_ranges.append(yt)

    has_overlap = your_overlap_days > 0
    
    # PRIVACY: Do NOT query or display other friends' availability.
    # Non-owners should only see their own overlap with this trip.
    # The friends_open_on_trip feature has been removed to prevent
    # showing third-party friend data (e.g., "Richard · Epic") when
    # Jonathan views Charles's trip.

    # Gating for "Request to Join" - Final Production Rules
    # This logic is intentionally simplified for production UX. Do not reintroduce friendship or legacy invite gating.
    today = date.today()
    can_request_join = False
    has_pending_request = False
    is_accepted = False
    
    if trip.user_id != current_user.id:
        # 1. Check if viewer is already an accepted participant (CRITICAL: status=ACCEPTED only)
        is_accepted = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, 
            user_id=current_user.id,
            status=GuestStatus.ACCEPTED
        ).first() is not None
        
        # 2. Check for pending join request (status=pending)
        pending_request = Invitation.query.filter_by(
            trip_id=trip_id,
            sender_id=current_user.id,
            invite_type=InviteType.REQUEST,
            status='pending'
        ).first()
        has_pending_request = pending_request is not None
        
        # 3. Trip must be in the future (has not ended)
        is_future = trip.end_date >= today
        
        # Final CTA State Decision:
        # - Already Accepted: Template shows "You're Going"
        # - Future + Not Accepted + No Pending Request: Template shows "Request to Join"
        # - Future + Not Accepted + Has Pending Request: Template shows "Request Sent"
        if is_future and not is_accepted:
            if not has_pending_request:
                can_request_join = True

    return render_template(
        "friend_trip_details.html",
        trip=trip,
        friend=friend,
        has_overlap=has_overlap,
        overlap_days=your_overlap_days,
        your_overlap_ranges=your_overlap_ranges,
        friends_open_on_trip=[],  # Privacy protection
        can_request_join=can_request_join,
        has_pending_request=has_pending_request,
        is_accepted=is_accepted
    )

@app.route("/feedback", methods=["GET", "POST"])
@login_required
def feedback():
    success = False
    error = None
    
    if request.method == "POST":
        feedback_text = request.form.get("feedback_text", "").strip()
        
        if not feedback_text:
            error = "Please enter your feedback before submitting."
        else:
            admin_email = os.environ.get("ADMIN_FEEDBACK_EMAIL")
            sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")
            
            if not admin_email:
                error = "Feedback system is not configured. Please try again later."
            elif not sendgrid_api_key:
                error = "Email service is not configured. Please try again later."
            else:
                try:
                    import sendgrid
                    from sendgrid.helpers.mail import Mail, Email, To, Content
                    
                    sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)
                    
                    from_email = Email("feedback@baselodge.app")
                    to_email = To(admin_email)
                    subject = "New BaseLodge Feedback"
                    
                    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    body = f"""New feedback received from BaseLodge:

Feedback:
{feedback_text}

---
User Details:
- Name: {current_user.first_name} {current_user.last_name}
- Email: {current_user.email}
- User ID: {current_user.id}
- Submitted: {timestamp}
"""
                    content = Content("text/plain", body)
                    mail = Mail(from_email, to_email, subject, content)
                    
                    response = sg.client.mail.send.post(request_body=mail.get())
                    
                    if response.status_code in [200, 201, 202]:
                        success = True
                    else:
                        error = "Failed to send feedback. Please try again later."
                        
                except Exception as e:
                    print(f"Feedback email error: {e}")
                    error = "Failed to send feedback. Please try again later."
    
    return render_template("feedback.html", success=success, error=error)

@app.route("/more")
@login_required
def more():
    return redirect(url_for('settings'))

@app.route("/more_info")
@login_required
def more_info():
    mountains = current_user.mountains_visited or []
    mountains_visited_count = len(mountains)
    
    return render_template("more_info.html", mountains_visited_count=mountains_visited_count)

@app.route("/profile")
@login_required
def profile():
    mountains_visited_count = current_user.visited_resorts_count

    primary_equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=EquipmentSlot.PRIMARY).first()
    secondary_equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=EquipmentSlot.SECONDARY).first()

    has_equipment = primary_equipment is not None or secondary_equipment is not None
    equipment_summary = ""
    if primary_equipment:
        equipment_summary = f"{primary_equipment.brand or 'Primary'}"
        if secondary_equipment:
            equipment_summary += f" + {secondary_equipment.brand or 'Secondary'}"
    elif secondary_equipment:
        equipment_summary = f"{secondary_equipment.brand or 'Secondary'}"

    # Wish list data
    wish_list_ids = current_user.wish_list_resorts or []
    wish_list_count = len(wish_list_ids)
    wish_list_resorts = Resort.query.filter(Resort.id.in_(wish_list_ids)).all() if wish_list_ids else []

    friends_count = Friend.query.filter_by(user_id=current_user.id).count()

    # Total trips (all, not just upcoming) — owned by user
    all_trips_count = SkiTrip.query.filter_by(user_id=current_user.id).count()

    return render_template("profile.html",
                           page_title="Profile",
                           mountains_visited_count=mountains_visited_count,
                           has_equipment=has_equipment,
                           equipment_summary=equipment_summary,
                           wish_list_count=wish_list_count,
                           wish_list_resorts=wish_list_resorts,
                           friends_count=friends_count,
                           upcoming_count=get_upcoming_trip_count(current_user),
                           all_trips_count=all_trips_count)

@app.route("/settings")
@login_required
def settings():
    return redirect(url_for("profile"), code=301)


@app.route("/settings/profile", methods=["GET", "POST"])
@login_required
def settings_profile():
    return redirect(url_for('edit_profile'))


@app.route("/settings/equipment")
@login_required
def settings_equipment():
    primary_equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=EquipmentSlot.PRIMARY).first()
    secondary_equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=EquipmentSlot.SECONDARY).first()
    
    return render_template("settings_equipment.html",
                           primary_equipment=primary_equipment,
                           secondary_equipment=secondary_equipment,
                           user=current_user)


@app.route("/settings/equipment/save", methods=["POST"])
@login_required
def settings_equipment_save():
    slot_str = request.form.get("slot", "primary")
    discipline_str = request.form.get("discipline", "")
    brand = request.form.get("brand", "")
    model = request.form.get("model", "")
    length_cm = request.form.get("length_cm", "")
    width_mm = request.form.get("width_mm", "")
    binding_type = request.form.get("binding_type", "")
    boot_brand = request.form.get("boot_brand", "")
    boot_model = request.form.get("boot_model", "")
    boot_flex = request.form.get("boot_flex", "")
    purchase_year = request.form.get("purchase_year", "")
    
    if not discipline_str:
        return jsonify({"error": "Discipline required"}), 400
    
    slot = EquipmentSlot.PRIMARY if slot_str == "primary" else EquipmentSlot.SECONDARY
    discipline = EquipmentDiscipline.SKIER if discipline_str == "Skier" else EquipmentDiscipline.SNOWBOARDER
    
    equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=slot).first()
    
    if not equipment:
        equipment = EquipmentSetup(user_id=current_user.id, slot=slot, discipline=discipline)
        db.session.add(equipment)
    else:
        old_discipline = equipment.discipline
        equipment.discipline = discipline
        if old_discipline != discipline:
            equipment.binding_type = None
    
    equipment.brand = brand if brand else None
    equipment.model = model if model else None
    equipment.length_cm = int(length_cm) if length_cm else None
    equipment.width_mm = int(width_mm) if width_mm else None
    equipment.binding_type = binding_type if binding_type else None
    equipment.boot_brand = boot_brand if boot_brand else None
    equipment.boot_model = boot_model if boot_model else None
    equipment.boot_flex = int(boot_flex) if boot_flex and int(boot_flex) > 0 else None
    
    # Purchase year only for primary equipment
    if slot == EquipmentSlot.PRIMARY:
        equipment.purchase_year = int(purchase_year) if purchase_year and purchase_year.isdigit() else None
    
    db.session.commit()
    return jsonify({"success": True})


@app.route("/settings/equipment/delete", methods=["POST"])
@login_required
def settings_equipment_delete():
    slot_str = request.form.get("slot", "primary")
    slot = EquipmentSlot.PRIMARY if slot_str == "primary" else EquipmentSlot.SECONDARY
    
    equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=slot).first()
    if equipment:
        db.session.delete(equipment)
        db.session.commit()
    
    return jsonify({"success": True})


@app.route("/settings/equipment-status", methods=["POST"])
@login_required
def settings_equipment_status():
    """Update user's equipment_status (have_own_equipment or needs_rentals)."""
    status = request.form.get("equipment_status", "have_own_equipment")
    if status not in ["have_own_equipment", "needs_rentals"]:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    
    current_user.equipment_status = status
    db.session.commit()
    
    return jsonify({"success": True})


@app.route("/settings/mountains-visited")
@login_required
def settings_mountains():
    return redirect(url_for('mountains_visited'))


@app.route("/settings/password")
@login_required
def settings_password():
    return redirect(url_for('change_password'))


@app.route("/settings/wish-list")
@login_required
def settings_wish_list():
    # Get all resorts for selection, ordered by country, state, name (exclude regions)
    resorts = Resort.query.filter_by(is_active=True, is_region=False).order_by(
        Resort.country_code, Resort.state_code, Resort.name
    ).all()
    
    # Get current wish list resort IDs
    wish_list_ids = current_user.wish_list_resorts or []
    
    # Get full resort objects for display
    wish_list_resorts = Resort.query.filter(Resort.id.in_(wish_list_ids)).all() if wish_list_ids else []
    
    # Group and sort wish list resorts for display
    grouped_wish_list = group_resorts_for_display(wish_list_resorts)
    
    # Get canonical countries for dropdown from the shared COUNTRIES mapping
    # Safeguard: Dropdown options MUST come from canonical country list, not resort data
    from utils.countries import COUNTRIES
    countries_list = sorted(COUNTRIES.keys(), key=lambda c: (c != 'US', COUNTRIES[c]))
    
    return render_template("settings_wish_list.html",
                           resorts=resorts,
                           wish_list_resorts=wish_list_resorts,
                           grouped_wish_list=grouped_wish_list,
                           wish_list_ids=wish_list_ids,
                           countries=countries_list)


@app.route("/settings/wish-list/save", methods=["POST"])
@login_required
def settings_wish_list_save():
    data = request.get_json()
    resort_ids = data.get("resort_ids", [])
    
    # Enforce max of 3
    if len(resort_ids) > 3:
        return jsonify({"error": "Maximum 3 resorts allowed"}), 400
    
    # Validate resort IDs exist
    valid_ids = []
    for rid in resort_ids:
        resort = Resort.query.get(rid)
        if resort:
            valid_ids.append(rid)
    
    current_user.wish_list_resorts = valid_ids
    db.session.commit()
    
    return jsonify({"success": True, "count": len(valid_ids)})


# =====================================================================
# INSTANT-SAVE API — Mountains Visited
# =====================================================================

@app.route("/api/mountains-visited/add", methods=["POST"])
@login_required
def api_mountains_visited_add():
    data = request.get_json() or {}
    resort_id = data.get("resort_id")
    if not resort_id:
        return jsonify({"error": "resort_id required"}), 400
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({"error": "Resort not found"}), 404
    ids = list(current_user.visited_resort_ids or [])
    if resort_id not in ids:
        ids.append(resort_id)
        names = list(current_user.mountains_visited or [])
        if resort.name not in names:
            names.append(resort.name)
        current_user.visited_resort_ids = ids
        current_user.mountains_visited = names
        db.session.commit()
    return jsonify({"success": True, "count": len(ids)})


@app.route("/api/mountains-visited/remove", methods=["POST"])
@login_required
def api_mountains_visited_remove():
    data = request.get_json() or {}
    resort_id = data.get("resort_id")
    if not resort_id:
        return jsonify({"error": "resort_id required"}), 400
    resort = Resort.query.get(resort_id)
    ids = [i for i in (current_user.visited_resort_ids or []) if i != resort_id]
    names = list(current_user.mountains_visited or [])
    if resort and resort.name in names:
        names.remove(resort.name)
    current_user.visited_resort_ids = ids
    current_user.mountains_visited = names
    db.session.commit()
    return jsonify({"success": True, "count": len(ids)})


# =====================================================================
# INSTANT-SAVE API — Wishlist
# =====================================================================

@app.route("/api/wishlist/add", methods=["POST"])
@login_required
def api_wishlist_add():
    data = request.get_json() or {}
    resort_id = data.get("resort_id")
    if not resort_id:
        return jsonify({"error": "resort_id required"}), 400
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({"error": "Resort not found"}), 404
    ids = list(current_user.wish_list_resorts or [])
    if len(ids) >= 3:
        return jsonify({"error": "Maximum 3 resorts", "at_limit": True}), 200
    if resort_id not in ids:
        ids.append(resort_id)
        current_user.wish_list_resorts = ids
        db.session.commit()
    return jsonify({"success": True, "count": len(ids), "at_limit": len(ids) >= 3})


@app.route("/api/wishlist/remove", methods=["POST"])
@login_required
def api_wishlist_remove():
    data = request.get_json() or {}
    resort_id = data.get("resort_id")
    if not resort_id:
        return jsonify({"error": "resort_id required"}), 400
    ids = [i for i in (current_user.wish_list_resorts or []) if i != resort_id]
    current_user.wish_list_resorts = ids
    db.session.commit()
    return jsonify({"success": True, "count": len(ids), "at_limit": len(ids) >= 3})


# =====================================================================
# FRIEND READ-ONLY VIEWS — Mountains Visited + Wishlist
# =====================================================================

@app.route("/mountains-visited/<int:user_id>")
@login_required
def friend_mountains_visited(user_id):
    """Read-only view of another user's mountains visited (friends only)."""
    friend = User.query.get_or_404(user_id)
    # Must be a confirmed friend
    is_friend = Friend.query.filter_by(
        user_id=current_user.id, friend_id=user_id
    ).first() is not None
    if not is_friend:
        abort(403)

    # Friend's visited resorts
    visited_ids = friend.visited_resort_ids or []
    visited_resorts = Resort.query.filter(Resort.id.in_(visited_ids)).all() if visited_ids else []
    grouped = group_resorts_for_display(visited_resorts)

    # Current user's wishlist for "On your wishlist" indicator
    user_wishlist_ids = set(current_user.wish_list_resorts or [])

    return render_template(
        "mountains_visited.html",
        read_only=True,
        view_user=friend,
        grouped_selected=grouped,
        mountains_visited_count=len(visited_ids),
        user_wishlist_ids=user_wishlist_ids,
        # own-view fields not needed in read-only — set safe defaults
        resorts=[],
        selected_resort_ids=[],
        countries=[],
        COUNTRIES={},
    )


@app.route("/wishlist/<int:user_id>")
@login_required
def friend_wishlist(user_id):
    """Read-only view of another user's wishlist (friends only)."""
    friend = User.query.get_or_404(user_id)
    is_friend = Friend.query.filter_by(
        user_id=current_user.id, friend_id=user_id
    ).first() is not None
    if not is_friend:
        abort(403)

    # Friend's wishlist
    wish_ids = friend.wish_list_resorts or []
    wish_resorts = Resort.query.filter(Resort.id.in_(wish_ids)).all() if wish_ids else []
    grouped = group_resorts_for_display(wish_resorts)

    # Current user's visited for "You've been here" indicator
    user_visited_ids = set(current_user.visited_resort_ids or [])

    return render_template(
        "settings_wish_list.html",
        read_only=True,
        view_user=friend,
        grouped_wish_list=grouped,
        wish_list_ids=wish_ids,
        user_visited_ids=user_visited_ids,
        # own-view fields not needed in read-only
        resorts=[],
        countries=[],
        COUNTRIES={},
    )


# =====================================================================
# SHARED RESORT FILTERING API (for Wishlist & Mountains Visited only)
# =====================================================================

@app.route("/api/resort-countries")
@login_required
def api_resort_countries():
    """Get all countries that have resorts in the database."""
    countries = db.session.query(Resort.country_code).distinct().filter(
        Resort.country_code.isnot(None),
        Resort.country_code != ''
    ).all()
    
    # Map country codes to display names
    country_names = {
        'US': 'United States',
        'CA': 'Canada',
        'JP': 'Japan',
        'FR': 'France',
        'CH': 'Switzerland',
        'AT': 'Austria',
        'IT': 'Italy'
    }
    
    result = []
    for (code,) in countries:
        if code:
            result.append({
                'code': code,
                'name': country_names.get(code, code)
            })
    
    # Sort by name, with US and CA first
    def sort_key(c):
        if c['code'] == 'US':
            return (0, c['name'])
        elif c['code'] == 'CA':
            return (1, c['name'])
        else:
            return (2, c['name'])
    
    result.sort(key=sort_key)
    return jsonify(result)


@app.route("/api/resort-regions/<country_code>")
@login_required
def api_resort_regions(country_code):
    """Get all regions/states for a specific country."""
    regions = db.session.query(Resort.state_code).distinct().filter(
        Resort.country_code == country_code.upper(),
        Resort.state_code.isnot(None),
        Resort.state_code != ''
    ).all()
    
    result = sorted([r[0] for r in regions if r[0]])
    return jsonify(result)


@app.route("/add-open-dates", methods=["GET", "POST"])
@login_required
def add_open_dates():
    if request.method == "POST":
        # Get selected dates from form (comma-separated YYYY-MM-DD strings)
        selected_dates = request.form.get("selected_dates", "")
        
        if selected_dates:
            dates_list = [d.strip() for d in selected_dates.split(",") if d.strip()]
            # Validate and filter dates
            valid_dates = []
            today_str = date.today().strftime('%Y-%m-%d')
            for d in dates_list:
                try:
                    datetime.strptime(d, '%Y-%m-%d')
                    if d >= today_str:
                        valid_dates.append(d)
                except ValueError:
                    pass
            
            current_user.open_dates = sorted(set(valid_dates))
        else:
            current_user.open_dates = []
        
        db.session.commit()
        
        # Recompute availability overlap activities for this user
        emit_availability_overlap_activities_for_user(current_user)
        db.session.commit()
        
        return redirect(url_for("home", tab="open"))
    
    # Pre-populate with existing dates
    existing_dates = current_user.open_dates or []
    
    return render_template(
        "add_open_dates.html",
        user=current_user,
        existing_dates=existing_dates,
    )

@app.route("/add_trip", methods=["GET", "POST"])
@login_required
def add_trip():
    # Single source of truth: Resort table
    resorts = get_resorts_for_trip_form()
    
    countries_map = COUNTRIES
    states_map = STATE_ABBR_MAP

    user_passes = [p.strip() for p in (current_user.pass_type or "").split(",") if p.strip()]
    print(f"[add_trip] User passes: {user_passes}")
    
    # Get prefill parameters for "Propose a trip" flow
    def safe_int(val):
        if val in (None, "", "null", "None"):
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    raw_friend_id = request.args.get('friend_id')
    raw_resort_id = request.args.get('resort_id')
    
    prefill_friend_id = safe_int(raw_friend_id)
    prefill_start_date = request.args.get('start_date') or None
    prefill_end_date = request.args.get('end_date') or None
    prefill_resort_id = safe_int(raw_resort_id)
    is_group = request.args.get('is_group') == '1'
    
    # Clean up empty strings from query params
    if prefill_start_date == "": prefill_start_date = None
    if prefill_end_date == "": prefill_end_date = None
    
    prefill_friend = None
    if prefill_friend_id is not None:
        prefill_friend = User.query.get(prefill_friend_id)

    prefill_resort = None
    if prefill_resort_id is not None:
        prefill_resort = Resort.query.get(prefill_resort_id)

    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        ride_intent = request.form.get("ride_intent") or None
        trip_equipment_status = request.form.get("trip_equipment_status") or "use_default"
        
        friend_id = request.form.get("friend_id", type=int)
        is_group_trip = request.form.get("is_group") == "1"

        errors = []

        if not resort_id:
            errors.append("Please select a resort.")
        if not start_date_str:
            errors.append("Please select a start date.")
        if not end_date_str:
            errors.append("Please select an end date.")

        resort = None
        if resort_id:
            resort = Resort.query.get(resort_id)
            if not resort:
                errors.append("Invalid resort selected.")

        start_date = None
        end_date = None
        today = date.today()
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                if end_date < start_date:
                    errors.append("End date cannot be before start date.")
                if start_date < today:
                    errors.append("Start date cannot be in the past.")
                if end_date < today:
                    errors.append("End date cannot be in the past.")
            except ValueError:
                errors.append("Invalid date format.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "add_trip.html",
                trip=None,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("add_trip"),
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
                prefill_resort=prefill_resort,
                is_group=is_group,
            )
        
        overlapping = SkiTrip.query.filter(
            SkiTrip.user_id == current_user.id,
            SkiTrip.resort_id == resort.id,
            SkiTrip.end_date >= today,
            SkiTrip.start_date <= end_date,
            SkiTrip.end_date >= start_date
        ).first()
        
        if overlapping:
            return render_template(
                "add_trip.html",
                trip=None,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("add_trip"),
                overlap_trip=overlapping,
                overlap_resort_name=resort.name,
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
                prefill_resort=prefill_resort,
                is_group=is_group,
            )

        trip_duration = SkiTrip.calculate_duration(start_date, end_date)

        trip = SkiTrip(
            user_id=current_user.id,
            resort_id=resort.id,
            state=resort.state_code or resort.state,
            mountain=resort.name,
            start_date=start_date,
            end_date=end_date,
            is_public=is_public,
            trip_status='planning',
            ride_intent=ride_intent,
            trip_duration=trip_duration,
            trip_equipment_status=trip_equipment_status if trip_equipment_status != 'use_default' else None,
            is_group_trip=is_group_trip or (friend_id is not None),
            created_by_user_id=current_user.id,
        )
        try:
            db.session.add(trip)
            db.session.flush()
            trip.add_owner_as_participant()
            if friend_id:
                trip.add_participant(friend_id, GuestStatus.INVITED)
            emit_trip_created_activities(trip, current_user.id)
            db.session.commit()
            flash("Trip added.", "trip")
            return redirect(url_for("trip_detail", trip_id=trip.id))
        except Exception as e:
            db.session.rollback()
            print(f"Error adding trip: {e}")
            flash("Something went wrong while saving your trip. Please try again.", "error")
            return render_template(
                "add_trip.html",
                trip=None,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("add_trip"),
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
                is_group=is_group,
            )

    # GET - render the add trip form
    # ⚠️ CONTRACT LOCK: countries_map must ALWAYS be passed to template.
    # The country dropdown is server-rendered from COUNTRIES (not derived from resorts).
    return render_template(
        "add_trip.html",
        trip=None,
        resorts=resorts,
        countries_map=countries_map,
        states_map=states_map,
        user=current_user,
        form_action=url_for("add_trip"),
        user_passes=user_passes,
        prefill_friend=prefill_friend,
        prefill_start_date=prefill_start_date,
        prefill_end_date=prefill_end_date,
        is_group=is_group,
    )

@app.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@login_required
def edit_trip_form(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        abort(403)
    
    resorts = get_resorts_for_trip_form()
    original_start = trip.start_date
    original_end = trip.end_date
    user_passes = [p.strip() for p in (current_user.pass_type or "").split(",") if p.strip()]
    
    # Get current user's participant record for this trip
    my_participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=current_user.id
    ).first()
    my_transportation = my_participant.transportation_status.value if my_participant and my_participant.transportation_status else None

    countries_map = COUNTRIES
    states_map = STATE_ABBR_MAP

    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        transportation_status = request.form.get("transportation_status") or None
        trip_equipment_status = request.form.get("trip_equipment_status") or "use_default"
        trip_status_raw = request.form.get("trip_status", "planning")
        trip_status = trip_status_raw if trip_status_raw in ("planning", "going") else "planning"

        errors = []

        if not resort_id:
            errors.append("Please select a resort.")
        if not start_date_str:
            errors.append("Please select a start date.")
        if not end_date_str:
            errors.append("Please select an end date.")

        resort = None
        if resort_id:
            resort = Resort.query.get(resort_id)
            if not resort:
                errors.append("Invalid resort selected.")

        start_date = None
        end_date = None
        today = date.today()
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                if end_date < start_date:
                    errors.append("End date cannot be before start date.")
                dates_changed = (start_date != original_start or end_date != original_end)
                if dates_changed:
                    if start_date < today:
                        errors.append("Start date cannot be in the past.")
                    if end_date < today:
                        errors.append("End date cannot be in the past.")
            except ValueError:
                errors.append("Invalid date format.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "edit_trip.html",
                trip=trip,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                user_passes=user_passes,
                my_transportation=my_transportation,
                trip_status=trip_status,
            )
        
        overlapping = SkiTrip.query.filter(
            SkiTrip.user_id == current_user.id,
            SkiTrip.id != trip.id,
            SkiTrip.resort_id == resort.id,
            SkiTrip.end_date >= today,
            SkiTrip.start_date <= end_date,
            SkiTrip.end_date >= start_date
        ).first()
        
        if overlapping:
            flash("You already have a trip that overlaps these dates.", "error")
            return render_template(
                "edit_trip.html",
                trip=trip,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                user_passes=user_passes,
                my_transportation=my_transportation,
                trip_status=trip_status,
            )

        dates_changed = (start_date != original_start or end_date != original_end)
        
        trip.resort_id = resort.id
        trip.state = resort.state_code or resort.state
        trip.mountain = resort.name
        trip.start_date = start_date
        trip.end_date = end_date
        trip.is_public = is_public
        trip.trip_status = trip_status
        trip.trip_equipment_status = trip_equipment_status if trip_equipment_status != 'use_default' else None
        trip.trip_duration = SkiTrip.calculate_duration(start_date, end_date)
        
        # Update current user's transportation_status on their participant record
        if my_participant and transportation_status:
            try:
                my_participant.transportation_status = ParticipantTransportation(transportation_status)
            except ValueError:
                pass  # Invalid value, ignore
        elif my_participant and not transportation_status:
            my_participant.transportation_status = None
        
        try:
            emit_trip_updated_activities(trip, current_user.id, dates_changed=dates_changed)
            db.session.commit()
            flash("Changes saved.", "trip")
            return redirect(url_for("trip_detail", trip_id=trip.id))
        except Exception as e:
            db.session.rollback()
            print(f"Error updating trip: {e}")
            flash("Something went wrong while saving your trip. Please try again.", "error")
            return render_template(
                "edit_trip.html",
                trip=trip,
                resorts=resorts,
                countries_map=countries_map,
                states_map=states_map,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                user_passes=user_passes,
                my_transportation=my_transportation,
                trip_status=trip_status,
            )

    return render_template(
        "edit_trip.html",
        trip=trip,
        resorts=resorts,
        countries_map=countries_map,
        states_map=states_map,
        user=current_user,
        form_action=url_for("edit_trip_form", trip_id=trip.id),
        user_passes=user_passes,
        my_transportation=my_transportation,
        trip_status=(trip.trip_status or 'planning'),
    )

@app.route("/trips/<int:trip_id>")
@login_required
def trip_detail(trip_id):
    """Trip Detail page - primary hub for viewing and managing a trip."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Check if user is owner or a participant
    is_owner = trip.user_id == current_user.id
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=current_user.id
    ).first()
    is_guest = participant and participant.status == GuestStatus.ACCEPTED
    is_invited = participant and participant.status == GuestStatus.INVITED
    
    # Owner, accepted guests, and invited users can view the trip detail
    if not is_owner and not is_guest and not is_invited:
        abort(404)
    
    # Get participants grouped by status
    invited_participants = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, status=GuestStatus.INVITED
    ).all()
    accepted_participants = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, status=GuestStatus.ACCEPTED
    ).all()
    
    # Get connected friends for invite modal (owner only)
    friends_for_invite = []
    if is_owner:
        friend_links = Friend.query.filter_by(user_id=current_user.id).all()
        friend_ids = [f.friend_id for f in friend_links]
        if friend_ids:
            friends = User.query.filter(User.id.in_(friend_ids)).all()
            
            # Check which friends are already invited or accepted
            existing_participants = {p.user_id: p.status for p in trip.participants}
            
            for friend in friends:
                status = existing_participants.get(friend.id)
                friends_for_invite.append({
                    'user': friend,
                    'status': status.value if status else None,
                    'disabled': status is not None,
                    'label': 'Already on trip' if status == GuestStatus.ACCEPTED else ('Invite sent' if status == GuestStatus.INVITED else None)
                })
    
    # Get trip owner info
    owner = User.query.get(trip.user_id)
    
    # Get group signals for aggregated view
    group_signals = trip.get_group_signals()
    
    # Get all participants (owner + accepted guests) for display
    # EXCLUDE organizer from all_participants list for the "Who's Going" section
    all_participants = [p for p in trip.get_all_participants() if p.user_id != trip.user_id]
    
    # Get pending join requests (owner only)
    pending_requests = []
    if is_owner:
        pending_requests = Invitation.query.filter_by(
            trip_id=trip_id,
            invite_type=InviteType.REQUEST,
            status='pending'
        ).all()
    
    # Get current user's participant record for inline editing
    current_user_participant = participant
    if is_owner:
        # Owner needs their own participant record
        current_user_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=current_user.id, role=ParticipantRole.OWNER
        ).first()
    
    # Calculate participant overlaps (for "You and X overlap for Y days" display)
    participant_overlaps = []
    today = date.today()
    if trip.start_date and trip.end_date and (is_owner or is_guest):
        trip_dates = set()
        d = trip.start_date
        while d <= trip.end_date:
            trip_dates.add(d)
            d += timedelta(days=1)
        
        # Get other participants' confirmed trips at the same resort during the same period
        other_user_ids = [p.user_id for p in all_participants if p.user_id != current_user.id]
        if other_user_ids:
            # Find overlapping trips from other participants
            for user_id in other_user_ids:
                other_user = User.query.get(user_id)
                if not other_user:
                    continue
                
                # Get their ACTIVE trips (not past, at same resort, overlapping dates).
                # When the current trip has resort_id, match by resort_id OR by mountain string
                # for legacy participant trips that share the same mountain but lack resort_id.
                # This handles mixed canonical/legacy data in the same query.
                if trip.resort_id and trip.mountain:
                    other_trips = SkiTrip.query.filter(
                        SkiTrip.user_id == user_id,
                        db.or_(
                            SkiTrip.resort_id == trip.resort_id,
                            db.and_(
                                SkiTrip.resort_id.is_(None),
                                SkiTrip.mountain == trip.mountain
                            )
                        ),
                        SkiTrip.start_date <= trip.end_date,
                        SkiTrip.end_date >= trip.start_date,
                        SkiTrip.end_date >= today
                    ).all()
                elif trip.resort_id:
                    other_trips = SkiTrip.query.filter(
                        SkiTrip.user_id == user_id,
                        SkiTrip.resort_id == trip.resort_id,
                        SkiTrip.start_date <= trip.end_date,
                        SkiTrip.end_date >= trip.start_date,
                        SkiTrip.end_date >= today
                    ).all()
                elif trip.mountain:
                    other_trips = SkiTrip.query.filter(
                        SkiTrip.user_id == user_id,
                        SkiTrip.mountain == trip.mountain,
                        SkiTrip.start_date <= trip.end_date,
                        SkiTrip.end_date >= trip.start_date,
                        SkiTrip.end_date >= today
                    ).all()
                else:
                    other_trips = []
                
                if other_trips:
                    # Calculate overlap days using a SET to avoid double-counting
                    overlap_day_set = set()
                    for ot in other_trips:
                        if ot.start_date and ot.end_date:
                            ot_d = ot.start_date
                            while ot_d <= ot.end_date:
                                if ot_d in trip_dates:
                                    overlap_day_set.add(ot_d)
                                ot_d += timedelta(days=1)
                    
                    if overlap_day_set:
                        participant_overlaps.append({
                            'name': other_user.first_name,
                            'days': len(overlap_day_set)
                        })
    
    return render_template(
        "trip_detail.html",
        trip=trip,
        owner=owner,
        is_owner=is_owner,
        is_guest=is_guest,
        is_invited=is_invited,
        invited_participants=invited_participants,
        accepted_participants=accepted_participants,
        friends_for_invite=friends_for_invite,
        invite_count=len(invited_participants),
        group_signals=group_signals,
        all_participants=all_participants,
        current_user_participant=current_user_participant,
        participant_overlaps=participant_overlaps,
        pending_requests=pending_requests,
        today=date.today(),
    )


@app.route("/trips/<int:trip_id>/invite")
@login_required
def trip_invite_detail(trip_id):
    """Invite detail page - view trip invitation before accepting or after accepting."""
    trip = SkiTrip.query.get_or_404(trip_id)
    today = date.today()
    
    # Check if invite has expired (trip start date has passed)
    if trip.start_date and trip.start_date < today:
        flash("This invite has expired.", "error")
        return redirect(url_for("my_trips"))
    
    # Check if user has an invite (pending, accepted, or declined) for this trip
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=current_user.id
    ).first()
    
    if not participant:
        flash("You don't have an invite for this trip.", "error")
        return redirect(url_for("my_trips"))
    
    # Check if user has accepted (unlocked state)
    is_accepted = participant.status == GuestStatus.ACCEPTED
    
    # Check if we should show the nudge (just accepted via query param)
    show_nudge = request.args.get("just_accepted") == "1" and is_accepted
    
    # Get trip owner
    owner = User.query.get(trip.user_id)
    
    # Get all participants
    all_participants = SkiTripParticipant.query.filter_by(trip_id=trip_id).all()
    
    # Sort participants by status
    accepted_participants = [p for p in all_participants if p.status == GuestStatus.ACCEPTED]
    other_participants = [p for p in all_participants if p.status != GuestStatus.ACCEPTED]
    
    # Calculate going count: owner (always) + accepted invitees
    going_count = 1 + len(accepted_participants)  # 1 for owner
    
    # Check if user owns equipment (has EquipmentSetup with brand or model)
    user_owns_equipment = EquipmentSetup.query.filter(
        EquipmentSetup.user_id == current_user.id,
        db.or_(
            EquipmentSetup.brand.isnot(None),
            EquipmentSetup.model.isnot(None)
        )
    ).first() is not None
    
    return render_template(
        "trip_invite_detail.html",
        trip=trip,
        owner=owner,
        participant=participant,
        accepted_participants=accepted_participants,
        other_participants=other_participants,
        is_accepted=is_accepted,
        show_nudge=show_nudge,
        going_count=going_count,
        user_owns_equipment=user_owns_equipment,
    )








@app.route("/api/trip/<int:trip_id>/accommodation", methods=["POST"])
@login_required
def update_trip_accommodation(trip_id):
    """Update accommodation status (owner-only)."""
    trip = db.session.get(SkiTrip, trip_id)
    if not trip:
        return jsonify({"status": "error", "message": "Trip not found"}), 404
    
    if trip.user_id != current_user.id:
        return jsonify({"status": "error", "message": "Only the trip organizer can manage accommodations"}), 403

    data = request.json
    status = data.get("status")
    link = data.get("link")
    
    if status == 'none_yet' or not status:
        trip.accommodation_status = None
        trip.accommodation_link = None
    else:
        trip.accommodation_status = status
        trip.accommodation_link = link

    db.session.commit()
    return jsonify({"status": "success"})


@app.route("/api/trip/<int:trip_id>/equipment-override", methods=["POST"])
@login_required
def update_trip_equipment_override(trip_id):
    """Update equipment override status (owner-only)."""
    trip = db.session.get(SkiTrip, trip_id)
    if not trip:
        return jsonify({"status": "error", "message": "Trip not found"}), 404
    
    if trip.user_id != current_user.id:
        return jsonify({"status": "error", "message": "Only the trip organizer can manage equipment overrides"}), 403

    data = request.json
    status = data.get("status") # use_default, have_own_equipment, renting
    
    if status == 'use_default' or not status:
        trip.equipment_override = None
    else:
        trip.equipment_override = status

    db.session.commit()
    
    # Update organizer's participant record to match if they are on the trip
    participant = SkiTripParticipant.query.filter_by(trip_id=trip.id, user_id=current_user.id).first()
    if participant:
        if status == 'have_own_equipment':
            participant.equipment_status = ParticipantEquipment.OWN
        elif status == 'renting':
            participant.equipment_status = ParticipantEquipment.RENTING
        else:
            # Revert to profile logic in the display helper usually, but let's sync the enum if possible
            # ParticipantEquipment doesn't have a 'PROFILE' option, it usually stores the explicit state.
            # For now, we'll let the template/model display property handle the 'None' case.
            participant.equipment_status = None
        db.session.commit()

    return jsonify({"status": "success"})


@app.route("/trips/<int:trip_id>/invite/cancel", methods=["POST"])
@login_required
def cancel_trip_invite(trip_id):
    """Cancel a pending invite (trip owner only)."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Only trip owner can cancel invites
    if trip.user_id != current_user.id:
        abort(403)
    
    user_id = request.form.get("user_id", type=int)
    if not user_id:
        flash("Invalid request.", "error")
        return redirect(url_for("trip_detail", trip_id=trip_id))
    
    # Find the pending invite
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=user_id, status=GuestStatus.INVITED
    ).first()
    
    if participant:
        db.session.delete(participant)
        db.session.commit()
        flash("Invite cancelled.", "info")
    
    return redirect(url_for("trip_detail", trip_id=trip_id))


@app.route("/trips/<int:trip_id>/invite", methods=["POST"])
@login_required
def send_trip_invites(trip_id):
    """Send trip invites to selected friends."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Only trip owner can invite
    if trip.user_id != current_user.id:
        abort(403)
    
    friend_ids = request.form.getlist("friend_ids")
    if not friend_ids:
        flash("Please select at least one friend to invite.", "error")
        return redirect(url_for("trip_detail", trip_id=trip_id))
    
    # Validate that all selected users are connected friends
    friend_links = Friend.query.filter_by(user_id=current_user.id).all()
    connected_friend_ids = {f.friend_id for f in friend_links}
    
    invites_sent = 0
    for friend_id_str in friend_ids:
        try:
            friend_id = int(friend_id_str)
        except ValueError:
            continue
        
        # Skip if not a connected friend
        if friend_id not in connected_friend_ids:
            continue
        
        # Skip if user is the trip owner
        if friend_id == current_user.id:
            continue
        
        # Check for existing participant record (idempotency)
        existing = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=friend_id
        ).first()
        
        if not existing:
            participant = SkiTripParticipant(
                trip_id=trip_id,
                user_id=friend_id,
                status=GuestStatus.INVITED
            )
            db.session.add(participant)
            # Emit activity for the invited user
            emit_trip_invite_received_activity(trip, current_user.id, friend_id)
            invites_sent += 1
    
    if invites_sent > 0:
        # Mark trip as group trip if not already
        if not trip.is_group_trip:
            trip.is_group_trip = True
        db.session.commit()
        flash(f"Invite{'s' if invites_sent > 1 else ''} sent to {invites_sent} friend{'s' if invites_sent > 1 else ''}.", "success")
    else:
        flash("No new invites were sent.", "info")
    
    return redirect(url_for("trip_detail", trip_id=trip_id))


@app.route("/trips/<int:trip_id>/request-join", methods=["POST"])
@login_required
def request_to_join_trip(trip_id):
    """Create a join request for a trip."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # 1. Trip must not be in the past
    if trip.end_date < date.today():
        return jsonify({"success": False, "error": "This trip has already ended."}), 400
    
    # 2. Requester must not already be an ACCEPTED participant
    is_accepted = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, 
        user_id=current_user.id,
        status=GuestStatus.ACCEPTED
    ).first() is not None
    
    if is_accepted:
        return jsonify({"success": False, "error": "You are already an accepted participant of this trip."}), 400
        
    # 4. Only one pending request per user per trip
    existing_request = Invitation.query.filter_by(
        sender_id=current_user.id,
        receiver_id=trip.user_id,
        trip_id=trip_id,
        invite_type=InviteType.REQUEST,
        status='pending'
    ).first()
    
    if existing_request:
        return jsonify({"success": True, "message": "Request already pending."})
        
    # Create the request
    join_request = Invitation(
        sender_id=current_user.id,
        receiver_id=trip.user_id,
        trip_id=trip_id,
        invite_type=InviteType.REQUEST,
        status='pending'
    )
    db.session.add(join_request)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Request sent to owner."})


@app.route("/trips/requests/<int:request_id>/respond", methods=["POST"])
@login_required
def respond_to_join_request(request_id):
    """
    Accept or decline a join request.
    Feature complete as of 2026-01-09. Backend + UI verified.
    """
    invitation = Invitation.query.get_or_404(request_id)
    
    if invitation.invite_type != InviteType.REQUEST:
        return jsonify({"success": False, "error": "Invalid invitation type."}), 400
        
    trip = SkiTrip.query.get_or_404(invitation.trip_id)
    
    # Only the trip owner can respond
    if trip.user_id != current_user.id:
        return jsonify({"success": False, "error": "Only the trip owner can respond to join requests."}), 403
        
    data = request.get_json() or {}
    action = data.get("action")
    
    if action == "accept":
        invitation.status = 'accepted'
        
        # Add requester as participant
        participant = SkiTripParticipant(
            trip_id=trip.id,
            user_id=invitation.sender_id,
            status=GuestStatus.ACCEPTED,
            role=ParticipantRole.GUEST,
            start_date=trip.start_date,
            end_date=trip.end_date
        )
        db.session.add(participant)
        
        # Mark trip as group trip if not already
        if not trip.is_group_trip:
            trip.is_group_trip = True
            
        db.session.commit()
        return jsonify({"success": True, "message": "Request accepted."})
        
    elif action == "decline":
        invitation.status = 'declined'
        db.session.commit()
        return jsonify({"success": True, "message": "Request declined."})
        
    return jsonify({"success": False, "error": "Invalid action."}), 400


@app.route("/trips/requests/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_join_request(request_id):
    """Cancel a pending join request."""
    invitation = Invitation.query.get_or_404(request_id)
    
    if invitation.sender_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    if invitation.invite_type != InviteType.REQUEST:
        return jsonify({"success": False, "error": "Invalid request type"}), 400
        
    if invitation.status != 'pending':
        return jsonify({"success": False, "error": "Only pending requests can be cancelled"}), 400
        
    db.session.delete(invitation)
    db.session.commit()
    
    flash("Join request cancelled.", "info")
    return redirect(url_for("my_trips"))

@app.route("/trips/<int:trip_id>/respond", methods=["POST"])
@login_required
def respond_to_trip_invite(trip_id):
    """Accept or decline a trip invite."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Find the user's participant record
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=current_user.id
    ).first()
    
    if not participant or participant.status != GuestStatus.INVITED:
        return jsonify({"success": False, "error": "No pending invite found"}), 404
    
    # Support both form data and JSON
    if request.is_json:
        data = request.get_json() or {}
        action = data.get("response") or data.get("action")
    else:
        action = request.form.get("action")
    
    if action == "accept":
        participant.status = GuestStatus.ACCEPTED
        
        # Archive solo trip if it exists
        solo_trip = SkiTrip.query.filter(
            SkiTrip.user_id == current_user.id,
            SkiTrip.id != trip_id,
            SkiTrip.start_date == trip.start_date,
            SkiTrip.end_date == trip.end_date,
            db.or_(
                SkiTrip.resort_id == trip.resort_id,
                SkiTrip.mountain == trip.mountain
            )
        ).first()
        
        if solo_trip:
            # Carry over equipment details from solo trip (SkiTrip doesn't have transportation_status)
            if solo_trip.equipment_override and solo_trip.equipment_override != 'use_default':
                participant.equipment_status = ParticipantEquipment.OWN if solo_trip.equipment_override == 'have_own_equipment' else ParticipantEquipment.RENTING
            
            db.session.delete(solo_trip)
            
        emit_trip_invite_accepted_activity(trip, current_user.id, trip.user_id)
        emit_friend_joined_trip_activities(trip, current_user.id)
        db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": "You're going"})
        flash("You're going", "success")
        return redirect(url_for("trip_detail", trip_id=trip_id))
    elif action == "decline":
        participant.status = GuestStatus.DECLINED
        emit_trip_invite_declined_activity(trip, current_user.id, trip.user_id)
        db.session.commit()
        if request.is_json:
            return jsonify({"success": True, "message": "Invite declined"})
        flash("Invite declined.", "info")
        return redirect(url_for("my_trips"))
    else:
        return jsonify({"success": False, "error": "Invalid action"}), 400


@app.route("/api/trips/<int:trip_id>/participant/signals", methods=["POST"])
@login_required
def update_participant_signals(trip_id):
    """Update current user's transportation, equipment, carpool, and lesson signals for a trip."""
    trip = SkiTrip.query.get_or_404(trip_id)
    
    # Find the user's participant record
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip_id, user_id=current_user.id
    ).first()
    
    if not participant:
        return jsonify({"success": False, "error": "You are not a participant of this trip."}), 404
    
    # Only accepted participants or owners can update their signals
    if participant.status != GuestStatus.ACCEPTED and participant.role != ParticipantRole.OWNER:
        return jsonify({"success": False, "error": "You must accept the invite first."}), 403
    
    data = request.get_json() or {}
    
    # Update transportation status
    transportation = data.get("transportation_status")
    if transportation:
        try:
            participant.transportation_status = ParticipantTransportation(transportation)
        except ValueError:
            pass
    
    # Update equipment status
    equipment = data.get("equipment_status")
    if equipment:
        try:
            participant.equipment_status = ParticipantEquipment(equipment)
        except ValueError:
            pass
    elif equipment == "":
        participant.equipment_status = None
    
    # Update carpool role
    carpool = data.get("carpool_role")
    if carpool:
        try:
            participant.carpool_role = CarpoolRole(carpool)
        except ValueError:
            pass
    elif carpool == "":
        participant.carpool_role = None
    
    # Update lesson status
    lesson = data.get("taking_lesson")
    if lesson:
        try:
            participant.taking_lesson = LessonChoice(lesson)
        except ValueError:
            pass
    
    db.session.commit()
    
    # Build display values for response
    carpool_display = None
    if participant.carpool_role:
        carpool_labels = {
            CarpoolRole.DRIVER_WITH_SPACE: "I can drive and have space",
            CarpoolRole.DRIVER_NO_SPACE: "I can drive but have no space",
            CarpoolRole.NEEDS_RIDE: "I need a ride",
            CarpoolRole.NOT_CARPOOLING: "Not carpooling",
            CarpoolRole.OTHER: "Other",
        }
        carpool_display = carpool_labels.get(participant.carpool_role, "Add")
    
    lesson_display = None
    if participant.taking_lesson:
        lesson_labels = {
            LessonChoice.NO: "No",
            LessonChoice.MAYBE: "Considering",
            LessonChoice.YES: "Yes",
        }
        lesson_display = lesson_labels.get(participant.taking_lesson, "Not set")
    
    return jsonify({
        "success": True,
        "transportation_display": participant.get_display_transportation(),
        "equipment_display": participant.get_display_equipment(),
        "carpool_display": carpool_display or "Add",
        "lesson_display": lesson_display or "Not set",
    })


@app.route("/trips/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete_trip_form(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        abort(403)

    delete_activities_for_trip(trip_id)
    db.session.delete(trip)
    db.session.commit()
    flash("Trip deleted.", "trip")
    return redirect(url_for("my_trips"))

@app.route("/mountains-visited", methods=["GET", "POST"])
@login_required
def mountains_visited():
    user = current_user
    
    # Get all resorts from database (source of truth, exclude region-level entities)
    all_resorts = Resort.query.filter_by(is_active=True, is_region=False).order_by(
        Resort.country_code, Resort.state_code, Resort.name
    ).all()
    
    if request.method == "POST":
        # Get selected resort IDs from form
        selected_resort_ids = request.form.getlist("resort_ids")
        
        resort_ids = []
        mountain_names = []
        seen_ids = set()
        
        for rid_str in selected_resort_ids:
            try:
                rid = int(rid_str)
                if rid not in seen_ids:
                    resort = Resort.query.get(rid)
                    if resort:
                        resort_ids.append(rid)
                        mountain_names.append(resort.name)
                        seen_ids.add(rid)
            except (ValueError, TypeError):
                pass
        
        user.visited_resort_ids = resort_ids
        user.mountains_visited = mountain_names
        
        try:
            db.session.commit()
            return redirect(url_for("settings"))
        except Exception as e:
            db.session.rollback()
            print(f"Error saving mountains visited: {e}")
            flash("Something went wrong while saving. Please try again.", "error")
            return redirect(url_for("mountains_visited"))
    
    # Build set of selected resort IDs
    selected_resort_ids = set()
    
    # Include resort IDs from visited_resort_ids
    if user.visited_resort_ids:
        selected_resort_ids.update(user.visited_resort_ids)
    
    # Also try to match legacy mountains_visited names to resort IDs
    if user.mountains_visited:
        for name in user.mountains_visited:
            for resort in all_resorts:
                if resort.name.lower() == name.lower() and resort.id not in selected_resort_ids:
                    selected_resort_ids.add(resort.id)
                    break
    
    mountains_visited_count = len(selected_resort_ids)
    
    # Get selected resort objects for server-side pill rendering
    selected_resorts = []
    if selected_resort_ids:
        selected_resorts = Resort.query.filter(Resort.id.in_(selected_resort_ids)).all()
    
    # Group and sort selected resorts for display
    grouped_selected = group_resorts_for_display(selected_resorts)
    
    # Get canonical countries for dropdown from the shared COUNTRIES mapping
    # Safeguard: Dropdown options MUST come from canonical country list, not resort data
    from utils.countries import COUNTRIES
    countries_list = sorted(COUNTRIES.keys(), key=lambda c: (c != 'US', COUNTRIES[c]))
    
    return render_template(
        "mountains_visited.html",
        resorts=all_resorts,
        selected_resort_ids=list(selected_resort_ids),
        selected_resorts=selected_resorts,
        grouped_selected=grouped_selected,
        mountains_visited_count=mountains_visited_count,
        countries=countries_list,
    )

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth"))

@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))
        
        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return redirect(url_for("change_password"))
        
        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))
        
        current_user.set_password(new_password)
        try:
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(url_for("change_password"))
        except Exception as e:
            db.session.rollback()
            print(f"Error changing password: {e}")
            flash("Something went wrong while updating your password. Please try again.", "error")
            return redirect(url_for("change_password"))
    
    return render_template("change_password.html")

@app.route("/skip-pass-prompt")
@login_required
def skip_pass_prompt():
    session["pass_prompt_skipped"] = True
    return redirect(url_for("home"))

@app.route("/select-pass", methods=["GET", "POST"])
@login_required
def select_pass():
    major_passes = ["Epic", "Ikon", "Indy", "Mountain Collective"]
    regional_passes = ["Power Pass", "Boyne Pass", "A-Basin Pass", "Loveland Pass"]
    other_passes = ["Other", "None"]

    if request.method == "POST":
        chosen = request.form.get("pass_type")
        current_user.pass_type = chosen
        try:
            db.session.commit()
            session["pass_prompt_skipped"] = False
            return redirect(url_for("home"))
        except Exception as e:
            db.session.rollback()
            print(f"Error saving pass selection: {e}")
            flash("Something went wrong while saving your pass. Please try again.", "error")
            return redirect(url_for("select_pass"))

    return render_template(
        "select_pass.html",
        major=major_passes,
        regional=regional_passes,
        other=other_passes
    )

@app.route("/generate-dummy-users")
@login_required
@admin_required
def generate_dummy_users():
    rider_types = ["Skier", "Snowboarder", "Cross-country", "Telemark", "Adaptive", "Other"]
    skill_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
    pass_types = ["Epic", "Ikon", "Indy", "Mountain Collective", "Other", "None"]
    mountains_pool = [
        "Vail", "Breckenridge", "Keystone", "Park City", "Heavenly",
        "Copper Mountain", "Winter Park", "Aspen", "Alta", "Snowbird",
        "Jackson Hole", "Brighton", "Big Sky", "Palisades Tahoe",
        "Loveland", "Arapahoe Basin"
    ]

    created_users = []

    for i in range(30):
        email = f"dummy{i+1}@example.com"
        existing = User.query.filter_by(email=email).first()
        if existing:
            continue

        u = User(
            first_name="User",
            last_name=f"Test{i+1}",
            email=email,
            primary_rider_type=random.choice(rider_types),
            secondary_rider_types=[],
            skill_level=random.choice(skill_levels),
            pass_type=random.choice(pass_types)
        )
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()

        chosen_mountains = random.sample(mountains_pool, random.randint(2, 8))
        if hasattr(u, "mountains_visited"):
            u.mountains_visited = chosen_mountains
        db.session.commit()

        for _ in range(random.randint(1, 3)):
            start = datetime.utcnow() + timedelta(days=random.randint(5, 60))
            end = start + timedelta(days=2)
            mountain_choice = random.choice(mountains_pool)
            trip = SkiTrip(
                user_id=u.id,
                state="Colorado",
                mountain=mountain_choice,
                start_date=start,
                end_date=end
            )
            db.session.add(trip)

        db.session.commit()
        created_users.append(email)

    return {"status": "success", "dummy_users_created": created_users}

@app.route("/connect-jonathan-to-dummies")
@login_required
@admin_required
def connect_jonathan_to_dummies():
    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()

    if not richard or not jonathan:
        return "One or both main users not found.", 400

    dummy_users = User.query.filter(User.email.like("dummy%@example.com")).all()
    linked = []

    for u in dummy_users:
        if not Friend.query.filter_by(user_id=richard.id, friend_id=u.id).first():
            db.session.add(Friend(user_id=richard.id, friend_id=u.id))
        if not Friend.query.filter_by(user_id=u.id, friend_id=richard.id).first():
            db.session.add(Friend(user_id=u.id, friend_id=richard.id))

        if not Friend.query.filter_by(user_id=jonathan.id, friend_id=u.id).first():
            db.session.add(Friend(user_id=jonathan.id, friend_id=u.id))
        if not Friend.query.filter_by(user_id=u.id, friend_id=jonathan.id).first():
            db.session.add(Friend(user_id=u.id, friend_id=jonathan.id))

        linked.append(u.email)

    db.session.commit()

    return {
        "status": "success",
        "dummy_users_linked_to_richard_and_jonathan": linked,
        "count": len(linked)
    }

@app.route("/migrate-trips-to-resorts")
@login_required
@admin_required
def migrate_trips_to_resorts():
    """Backfill resort_id for all existing trips based on mountain name."""
    trips = SkiTrip.query.all()
    migrated = 0
    not_found = []

    for trip in trips:
        if trip.resort_id:
            continue

        # Best-effort lookup by mountain name
        resort = Resort.query.filter(
            db.func.lower(Resort.name) == trip.mountain.lower()
        ).first()

        if resort:
            trip.resort_id = resort.id
            migrated += 1
        else:
            if trip.mountain and trip.mountain not in not_found:
                not_found.append(trip.mountain)

    db.session.commit()

    return {
        "status": "success",
        "trips_migrated": migrated,
        "mountains_not_found": not_found
    }

@app.route("/create-extra-dummy-users")
@login_required
@admin_required
def create_extra_dummy_users():
    """Create 10 additional dummy users (Test31-40) with overlapping trips."""
    main_email = "richardbattlebaxter@gmail.com"
    jon_email = "jonathanmschmitz@gmail.com"

    main_user = User.query.filter_by(email=main_email).first()
    jon_user = User.query.filter_by(email=jon_email).first()

    if not main_user or not jon_user:
        return {"error": f"Anchor users not found. main={bool(main_user)}, jon={bool(jon_user)}"}, 400

    # Load anchor trips separately for each user to ensure coverage
    main_trips = SkiTrip.query.filter_by(user_id=main_user.id).all()
    jon_trips = SkiTrip.query.filter_by(user_id=jon_user.id).all()

    if not main_trips and not jon_trips:
        return {"error": "No anchor trips found to create overlaps."}, 400

    rider_types = ["Skier", "Snowboarder", "Telemark", "Adaptive", "Other"]
    pass_types = ["Epic", "Epic Local", "Ikon", "Ikon Base", "Indy", "Other", "None"]
    skill_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]

    created_users = []
    for idx in range(31, 41):
        email = f"usertest{idx}@example.com"
        existing = User.query.filter_by(email=email).first()
        if existing:
            continue

        u = User(
            first_name="User",
            last_name=f"Test{idx}",
            email=email,
            primary_rider_type=random.choice(rider_types),
            secondary_rider_types=[],
            pass_type=random.choice(pass_types),
            skill_level=random.choice(skill_levels),
        )
        u.set_password("skitest123")
        db.session.add(u)
        created_users.append(u)

    db.session.commit()

    if not created_users:
        return {"status": "success", "message": "All dummy users Test31-Test40 already exist.", "created": 0}

    # Create overlapping trips ensuring coverage for both anchor users
    for u in created_users:
        # Ensure at least one trip overlaps with main_user
        if main_trips:
            template_trip = random.choice(main_trips)
            overlap_trip = SkiTrip(
                user_id=u.id,
                state=template_trip.state,
                mountain=template_trip.mountain,
                start_date=template_trip.start_date,
                end_date=template_trip.end_date,
                is_public=True,
            )
            if template_trip.resort_id:
                overlap_trip.resort_id = template_trip.resort_id
            db.session.add(overlap_trip)

        # Ensure at least one trip overlaps with jon_user
        if jon_trips:
            template_trip = random.choice(jon_trips)
            overlap_trip = SkiTrip(
                user_id=u.id,
                state=template_trip.state,
                mountain=template_trip.mountain,
                start_date=template_trip.start_date,
                end_date=template_trip.end_date,
                is_public=True,
            )
            if template_trip.resort_id:
                overlap_trip.resort_id = template_trip.resort_id
            db.session.add(overlap_trip)

        # Add 0-1 additional random trips from either account
        all_anchor_trips = main_trips + jon_trips
        if all_anchor_trips and random.random() > 0.5:
            template_trip = random.choice(all_anchor_trips)
            overlap_trip = SkiTrip(
                user_id=u.id,
                state=template_trip.state,
                mountain=template_trip.mountain,
                start_date=template_trip.start_date,
                end_date=template_trip.end_date,
                is_public=True,
            )
            if template_trip.resort_id:
                overlap_trip.resort_id = template_trip.resort_id
            db.session.add(overlap_trip)

    db.session.commit()

    # Add bidirectional friendships to both main accounts
    def ensure_friendship(a, b):
        existing = Friend.query.filter_by(user_id=a.id, friend_id=b.id).first()
        if not existing:
            db.session.add(Friend(user_id=a.id, friend_id=b.id))

        existing_rev = Friend.query.filter_by(user_id=b.id, friend_id=a.id).first()
        if not existing_rev:
            db.session.add(Friend(user_id=b.id, friend_id=a.id))

    for u in created_users:
        ensure_friendship(main_user, u)
        ensure_friendship(jon_user, u)

    db.session.commit()

    return {
        "status": "success",
        "message": f"Created {len(created_users)} extra dummy users with overlapping trips and friendships.",
        "created_users": [u.email for u in created_users]
    }

@app.route("/delete-account-data")
@login_required
@admin_required
def delete_account_data():
    target_emails = [
        "richardbattlebaxter@gmail.com",
        "jonathanmschmitz@gmail.com"
    ]

    deleted_summary = {}

    for email in target_emails:
        user = User.query.filter_by(email=email).first()
        if not user:
            deleted_summary[email] = "User not found"
            continue

        SkiTrip.query.filter_by(user_id=user.id).delete()

        Friend.query.filter_by(user_id=user.id).delete()
        Friend.query.filter_by(friend_id=user.id).delete()

        if hasattr(user, "mountains_visited"):
            user.mountains_visited = []
        
        db.session.delete(user)
        db.session.commit()

        deleted_summary[email] = "All associated data deleted"

    return {
        "status": "success",
        "details": deleted_summary
    }

@app.route("/create-real-users-and-connect")
@login_required
@admin_required
def create_real_users_and_connect():
    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    if not richard:
        richard = User(
            first_name="Richard",
            last_name="Battle",
            email="richardbattlebaxter@gmail.com"
        )
        richard.set_password("123456")
        db.session.add(richard)
        db.session.commit()

    jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
    if not jonathan:
        jonathan = User(
            first_name="Jonathan",
            last_name="Schmitz",
            email="jonathanmschmitz@gmail.com"
        )
        jonathan.set_password("123456")
        db.session.add(jonathan)
        db.session.commit()

    dummy_users = User.query.filter(User.email.like("dummy%@example.com")).all()

    linked_richard = []
    linked_jonathan = []

    for u in dummy_users:
        if not Friend.query.filter_by(user_id=richard.id, friend_id=u.id).first():
            db.session.add(Friend(user_id=richard.id, friend_id=u.id))
        if not Friend.query.filter_by(user_id=u.id, friend_id=richard.id).first():
            db.session.add(Friend(user_id=u.id, friend_id=richard.id))
        linked_richard.append(u.email)

        if not Friend.query.filter_by(user_id=jonathan.id, friend_id=u.id).first():
            db.session.add(Friend(user_id=jonathan.id, friend_id=u.id))
        if not Friend.query.filter_by(user_id=u.id, friend_id=jonathan.id).first():
            db.session.add(Friend(user_id=u.id, friend_id=jonathan.id))
        linked_jonathan.append(u.email)

    db.session.commit()

    return {
        "status": "success",
        "richard_connected_to": linked_richard,
        "jonathan_connected_to": linked_jonathan,
        "dummy_count": len(dummy_users)
    }

@app.route("/force-create-base-users")
def force_create_base_users():
    created = {}

    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    if not richard:
        richard = User(
            first_name="Richard",
            last_name="Battle",
            email="richardbattlebaxter@gmail.com"
        )
        richard.set_password("123456")
        db.session.add(richard)
        db.session.commit()
        created["richard"] = "created"
    else:
        created["richard"] = "already existed"

    jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
    if not jonathan:
        jonathan = User(
            first_name="Jonathan",
            last_name="Schmitz",
            email="jonathanmschmitz@gmail.com"
        )
        jonathan.set_password("123456")
        db.session.add(jonathan)
        db.session.commit()
        created["jonathan"] = "created"
    else:
        created["jonathan"] = "already existed"

    return {"status": "success", "result": created}

@app.route("/admin/init-db", methods=["POST"])
@login_required
@admin_required
def init_db_http():
    """
    HTTP endpoint for database initialization (backup method for deployment).
    Can be called after deployment to initialize the database.
    
    Usage after deployment:
    POST https://yourapp.replit.dev/admin/init-db
    
    This will:
    - Seed all resorts (idempotent)
    - Be idempotent (safe to call multiple times)
    """
    try:
        with app.app_context():
            # Create all tables
            # Schema creation disabled for Supabase migration.
    # Use 'flask db upgrade' instead.
    # db.create_all()
            
            messages = []
            
            # Seed resorts from xlsx if none exist
            resort_count = Resort.query.count()
            if resort_count == 0:
                from utils.resort_import import import_resorts_from_xlsx
                xlsx_path = os.path.join(os.path.dirname(__file__), 'prod_resorts_full.xlsx')
                if os.path.exists(xlsx_path):
                    stats = import_resorts_from_xlsx(xlsx_path, db, Resort, generate_resort_slug, STATE_ABBR_MAP)
                    total = stats['added'] + stats['updated']
                    messages.append(f"Imported {total} resorts from xlsx ({stats['added']} new, {stats['updated']} updated)")
                else:
                    messages.append("WARNING: prod_resorts_full.xlsx not found — resort seeding skipped")
            else:
                messages.append(f"Resorts already exist ({resort_count})")
            
            return jsonify({
                "status": "success",
                "message": "✅ Database initialized",
                "details": messages
            }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to initialize database: {str(e)}"
        }), 500


MOUNTAIN_NAME_ALIASES = {
    "Crystal Mountain MI": "Crystal Mountain MI",
    "Whitefish Mountain": "Whitefish",
    "Brundage Mountain": "Brundage",
    "Red Lodge Mountain": "Red Lodge",
    "Wildcat Mountain": "Wildcat",
    "Windham Mountain": "Windham",
}

def find_resort_by_name(mountain_name, state_code=None):
    """
    Find a Resort by legacy mountain name with case-insensitive matching.
    Returns Resort or None if no match found.
    
    Matching strategy:
    1. Check hardcoded alias map first
    2. Exact case-insensitive match
    3. Match with common suffix variations (Resort, Mountain, Ski Area)
    """
    from sqlalchemy import func
    
    if not mountain_name:
        return None
    
    aliased_name = MOUNTAIN_NAME_ALIASES.get(mountain_name, mountain_name)
    
    query = Resort.query.filter(Resort.is_active == True)
    if state_code:
        query = query.filter(Resort.state == state_code)
    
    exact_match = query.filter(func.lower(Resort.name) == aliased_name.lower()).first()
    if exact_match:
        return exact_match
    
    suffix_variations = [
        aliased_name,
        f"{aliased_name} Resort",
        f"{aliased_name} Mountain",
        f"{aliased_name} Mountain Resort",
        f"{aliased_name} Ski Area",
        aliased_name.replace(" Resort", ""),
        aliased_name.replace(" Mountain", ""),
        aliased_name.replace(" Ski Area", ""),
    ]
    
    for variation in suffix_variations:
        match = query.filter(func.lower(Resort.name) == variation.lower()).first()
        if match:
            return match
    
    return None


def build_mountain_to_resort_mapping():
    """
    Build a complete mapping of MOUNTAINS_BY_STATE strings to Resort IDs.
    Returns: (mapping_dict, unmatched_list)
    """
    mapping = {}
    unmatched = []
    
    for state_code, mountains in MOUNTAINS_BY_STATE.items():
        for mountain_name in mountains:
            resort = find_resort_by_name(mountain_name, state_code)
            if resort:
                mapping[mountain_name] = resort.id
            else:
                unmatched.append({"name": mountain_name, "state": state_code})
    
    return mapping, unmatched


@app.route("/admin/backfill-resort-ids", methods=["GET", "POST"])
def backfill_resort_ids_endpoint():
    """
    Backfill visited_resort_ids and home_resort_id from legacy string data.
    Idempotent - safe to run multiple times.
    
    GET: Preview mode - shows what would be migrated
    POST: Execute mode - performs the migration
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-resort-ids
    """
    try:
        mapping, unmatched = build_mountain_to_resort_mapping()
        
        is_preview = request.method == "GET"
        
        users_with_visited = User.query.filter(
            db.or_(
                User.mountains_visited.isnot(None),
                User.home_mountain.isnot(None)
            )
        ).all()
        
        results = {
            "mapping_stats": {
                "total_mountains": sum(len(m) for m in MOUNTAINS_BY_STATE.values()),
                "mapped": len(mapping),
                "unmatched": len(unmatched)
            },
            "unmatched_mountains": unmatched,
            "users_processed": 0,
            "visited_mountains_migrated": 0,
            "home_mountains_migrated": 0,
            "unmapped_visited_names": [],
            "unmapped_home_names": []
        }
        
        for user in users_with_visited:
            legacy_visited = user.mountains_visited or []
            legacy_home = user.home_mountain
            
            if legacy_visited and (not user.visited_resort_ids or len(user.visited_resort_ids) == 0):
                new_ids = []
                for mountain_name in legacy_visited:
                    if mountain_name in mapping:
                        new_ids.append(mapping[mountain_name])
                    else:
                        resort = find_resort_by_name(mountain_name)
                        if resort:
                            new_ids.append(resort.id)
                        elif mountain_name not in results["unmapped_visited_names"]:
                            results["unmapped_visited_names"].append(mountain_name)
                
                if new_ids:
                    if not is_preview:
                        user.visited_resort_ids = list(set(new_ids))
                    results["visited_mountains_migrated"] += len(new_ids)
            
            if legacy_home and not user.home_resort_id:
                if legacy_home in mapping:
                    if not is_preview:
                        user.home_resort_id = mapping[legacy_home]
                    results["home_mountains_migrated"] += 1
                else:
                    resort = find_resort_by_name(legacy_home)
                    if resort:
                        if not is_preview:
                            user.home_resort_id = resort.id
                        results["home_mountains_migrated"] += 1
                    elif legacy_home not in results["unmapped_home_names"]:
                        results["unmapped_home_names"].append(legacy_home)
            
            results["users_processed"] += 1
        
        if not is_preview:
            db.session.commit()
        
        return jsonify({
            "status": "success",
            "mode": "preview" if is_preview else "executed",
            "message": f"{'Preview' if is_preview else 'Executed'} backfill for {results['users_processed']} users",
            "results": results
        }), 200
        
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Backfill failed: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-test-users", methods=["GET", "POST"])
def seed_test_users_endpoint():
    """
    HTTP endpoint to seed test users for demo/testing.
    Creates Richard + 20 friends with complete profiles, trips, and friendships.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-test-users
    
    This is idempotent - safe to call multiple times.
    """
    try:
        from seed_test_users import seed_test_data
        from models import EquipmentSetup, EquipmentSlot, EquipmentDiscipline
        
        results = seed_test_data(
            app, db, User, Friend, SkiTrip, Resort,
            EquipmentSetup, EquipmentSlot, EquipmentDiscipline
        )
        
        return jsonify({
            "status": "success",
            "message": "Test users seeded successfully",
            "details": results
        }), 200
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": f"Failed to seed test users: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-narrative-states", methods=["GET", "POST"])
def seed_narrative_states_endpoint():
    """
    HTTP endpoint to seed 4 test users for narrative state validation.
    Creates users for State 1, 2, 3, and 4 for testing NBA behavior.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-narrative-states
    
    Test user logins (password: testpass123):
    - state1.test@baselodge.dev (State 1: Early Onboarding)
    - state2.test@baselodge.dev (State 2: Profile Complete, Not Planning)
    - state3.test@baselodge.dev (State 3: Planning Started, Not Fully Active)
    - state4.test@baselodge.dev (State 4: Active User)
    """
    try:
        from seed_test_users import seed_narrative_state_users
        
        results = seed_narrative_state_users(app, db, User, SkiTrip, Resort)
        
        return jsonify({
            "status": "success",
            "message": "Narrative state test users seeded",
            "details": results
        }), 200
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": f"Failed to seed narrative state users: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/backfill-planning-timestamp", methods=["GET", "POST"])
def backfill_planning_timestamp_endpoint():
    """
    HTTP endpoint to backfill first_planning_timestamp for existing users.
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-planning-timestamp
    
    This is idempotent and safe to run multiple times.
    Only updates users who have trips but no first_planning_timestamp set.
    """
    try:
        from backfill_first_planning_timestamp import backfill_first_planning_timestamp
        
        try:
            from models import TripGuest
        except ImportError:
            TripGuest = None
        
        results = backfill_first_planning_timestamp(app, db, User, SkiTrip, TripGuest)
        
        return jsonify({
            "status": "success",
            "message": "Backfill completed",
            "details": results
        }), 200
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "message": f"Backfill failed: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/backfill-primary-rider-type", methods=["GET", "POST"])
def backfill_primary_rider_type_endpoint():
    """
    HTTP endpoint to backfill primary_rider_type from legacy rider_type for existing users.
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-primary-rider-type
    
    This is idempotent and safe to run multiple times.
    Only updates users who have rider_type but no primary_rider_type set.
    """
    try:
        users_updated = 0
        users_skipped = 0
        
        users = User.query.all()
        for user in users:
            if user.rider_type and not user.primary_rider_type:
                user.primary_rider_type = user.rider_type
                user.secondary_rider_types = []
                users_updated += 1
            else:
                users_skipped += 1
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Backfill completed",
            "details": {
                "users_updated": users_updated,
                "users_skipped": users_skipped
            }
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Backfill failed: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/backfill-organizers-as-participants", methods=["GET", "POST"])
def backfill_organizers_as_participants():
    """
    HTTP endpoint to backfill trip organizers as participants.
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-organizers-as-participants
    
    This is idempotent - safe to run multiple times.
    Only creates participant records for trips where the owner is not already a participant.
    """
    try:
        trips_updated = 0
        trips_skipped = 0
        
        all_trips = SkiTrip.query.all()
        for trip in all_trips:
            # Check if owner already has a participant record
            existing = SkiTripParticipant.query.filter_by(
                trip_id=trip.id,
                user_id=trip.user_id
            ).first()
            
            if existing:
                trips_skipped += 1
            else:
                # Add owner as participant with OWNER role
                trip.add_owner_as_participant()
                trips_updated += 1
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": "Backfill completed",
            "details": {
                "trips_updated": trips_updated,
                "trips_skipped": trips_skipped,
                "total_trips": len(all_trips)
            }
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Backfill failed: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/open-data-debug")
@login_required
def open_data_debug():
    """
    Debug endpoint to verify open date matching logic.
    Returns JSON with all open date matches for the current user.
    """
    matches = get_open_date_matches(current_user)
    
    return jsonify({
        "user_id": current_user.id,
        "user_email": current_user.email,
        "user_open_dates": current_user.open_dates or [],
        "user_pass_type": current_user.pass_type,
        "matches_count": len(matches),
        "matches": matches
    })


# ============================================================================
# GroupTrip Social Functionality
# ============================================================================

@app.route("/api/group-trip/create", methods=["POST"])
@login_required
def create_group_trip():
    """Create a new GroupTrip."""
    data = request.get_json()
    
    title = data.get("title", "").strip() or None
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    
    # Validate dates
    if not start_date_str or not end_date_str:
        return jsonify({"success": False, "error": "Start and end dates are required"}), 400
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "error": "Invalid date format. Use YYYY-MM-DD"}), 400
    
    if end_date < start_date:
        return jsonify({"success": False, "error": "End date cannot be before start date"}), 400
    
    # Create GroupTrip
    trip = GroupTrip(
        host_id=current_user.id,
        title=title,
        start_date=start_date,
        end_date=end_date
    )
    db.session.add(trip)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "trip_id": trip.id,
        "redirect_url": url_for("view_group_trip", trip_id=trip.id)
    })


@app.route("/group-trip/<int:trip_id>")
@login_required
def view_group_trip(trip_id):
    """View GroupTrip details with invite form (host only)."""
    trip = GroupTrip.query.get_or_404(trip_id)
    
    # Explicit permission check: only host or guests can view
    is_host = trip.host_id == current_user.id
    is_guest = TripGuest.query.filter_by(trip_id=trip_id, user_id=current_user.id).first() is not None
    
    if not is_host and not is_guest:
        abort(403)
    
    # Get guests with their details
    guests = TripGuest.query.filter_by(trip_id=trip_id).all()
    
    # Get user's friends for invite form (host only)
    user_friends = Friend.query.filter_by(user_id=current_user.id).all()
    friend_ids = [f.friend_id for f in user_friends]
    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    
    # Filter out already invited/joined friends
    invited_ids = {g.user_id for g in guests}
    available_friends = [f for f in friends if f.id not in invited_ids]
    
    return render_template(
        "group_trip_detail.html",
        trip=trip,
        is_host=is_host,
        guests=guests,
        available_friends=available_friends
    )


@app.route("/group-trip/<int:trip_id>/invite", methods=["POST"])
@login_required
def invite_to_group_trip(trip_id):
    """Host invites a friend to GroupTrip."""
    # Authentication guard (already protected by @login_required)
    if not current_user.is_authenticated:
        abort(401)
    
    # Validate trip exists
    trip = GroupTrip.query.get_or_404(trip_id)
    
    # Permission check: only host can invite
    if trip.host_id != current_user.id:
        abort(403)
    
    # Safe form data handling
    friend_id = request.form.get("friend_id", type=int)
    if not friend_id:
        flash("No friend selected.", "error")
        return redirect(url_for("view_group_trip", trip_id=trip_id))
    
    # Validate target user exists
    friend = User.query.get(friend_id)
    if not friend:
        flash("User not found.", "error")
        return redirect(url_for("view_group_trip", trip_id=trip_id))
    
    # Check if user is actually a friend
    is_friend = Friend.query.filter_by(user_id=current_user.id, friend_id=friend_id).first()
    if not is_friend:
        flash("User is not in your friends list.", "error")
        return redirect(url_for("view_group_trip", trip_id=trip_id))
    
    # Prevent duplicate invites
    existing = TripGuest.query.filter_by(trip_id=trip_id, user_id=friend_id).first()
    if existing:
        flash(f"{friend.first_name} is already invited.", "error")
        return redirect(url_for("view_group_trip", trip_id=trip_id))
    
    # Database write safety
    try:
        guest = TripGuest(trip_id=trip_id, user_id=friend_id, status=GuestStatus.INVITED)
        db.session.add(guest)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Invite to group trip failed")
        flash("An error occurred while inviting. Please try again.", "error")
        return redirect(url_for("view_group_trip", trip_id=trip_id))
    
    flash(f"Invited {friend.first_name} to the trip!", "success")
    return redirect(url_for("view_group_trip", trip_id=trip_id))


@app.route("/group-trip/<int:trip_id>/accept", methods=["POST"])
@login_required
def accept_group_trip_invite(trip_id):
    """Accept GroupTrip invite and create global friend connection."""
    # Authentication guard (already protected by @login_required)
    if not current_user.is_authenticated:
        abort(401)
    
    # Validate trip exists
    trip = GroupTrip.query.get_or_404(trip_id)
    
    # Validate guest exists
    guest = TripGuest.query.filter_by(trip_id=trip_id, user_id=current_user.id).first_or_404()
    
    # Only allow if invited (not already accepted)
    if guest.status != GuestStatus.INVITED:
        flash("You've already accepted or this invite is invalid.", "error")
        return redirect(url_for("home"))
    
    # Database write safety
    try:
        # Accept the invite
        guest.status = GuestStatus.ACCEPTED
        
        # Mark planning started (lifecycle signal)
        current_user.mark_planning_started()
        
        db.session.commit()
        
        # Create bidirectional friend connection with trip host if not already friends
        host = trip.host
        existing = Friend.query.filter_by(user_id=current_user.id, friend_id=host.id).first()
        if not existing:
            f1 = Friend(user_id=current_user.id, friend_id=host.id)
            f2 = Friend(user_id=host.id, friend_id=current_user.id)
            db.session.add(f1)
            db.session.add(f2)
            db.session.commit()
            flash(f"Trip accepted! You're now connected with {host.first_name}.", "success")
        else:
            flash("Trip accepted!", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Accept group trip invite failed")
        flash("An error occurred while accepting the invite. Please try again.", "error")
        return redirect(url_for("home"))
    
    return redirect(url_for("home"))


@app.route("/group-trip/<int:trip_id>/leave", methods=["POST"])
@login_required
def leave_group_trip(trip_id):
    """Guest leaves GroupTrip (deletes TripGuest row)."""
    trip = GroupTrip.query.get_or_404(trip_id)
    guest = TripGuest.query.filter_by(trip_id=trip_id, user_id=current_user.id).first_or_404()
    
    # Delete the guest record
    db.session.delete(guest)
    db.session.commit()
    
    flash("You've left the trip.", "success")
    return redirect(url_for("home"))


@app.route("/group-trip/<int:trip_id>/remove-guest/<int:guest_id>", methods=["POST"])
@login_required
def remove_trip_guest(trip_id, guest_id):
    """Host removes a guest from GroupTrip."""
    trip = GroupTrip.query.get_or_404(trip_id)
    
    # Only host can remove
    if trip.host_id != current_user.id:
        return abort(403)
    
    guest = TripGuest.query.filter_by(id=guest_id, trip_id=trip_id).first_or_404()
    guest_user = guest.user
    
    db.session.delete(guest)
    db.session.commit()
    
    flash(f"Removed {guest_user.first_name} from the trip.", "success")
    return redirect(url_for("view_group_trip", trip_id=trip_id))


@app.route("/connect-from-trip/<int:user_id>", methods=["POST"])
@login_required
def connect_from_trip(user_id):
    """Connect with a user via shared GroupTrip (create global friendship)."""
    user_to_connect = User.query.get_or_404(user_id)
    
    # Check eligibility
    if not check_shared_upcoming_trip(current_user.id, user_to_connect.id):
        flash("You don't share an upcoming trip with this user.", "error")
        return redirect(url_for("friend_profile", friend_id=user_id))
    
    # Check if already friends
    existing = Friend.query.filter_by(user_id=current_user.id, friend_id=user_id).first()
    if existing:
        flash("You're already connected with this user.", "info")
        return redirect(url_for("friend_profile", friend_id=user_id))
    
    # Create bidirectional friend connection
    f1 = Friend(user_id=current_user.id, friend_id=user_to_connect.id)
    f2 = Friend(user_id=user_to_connect.id, friend_id=current_user.id)
    db.session.add(f1)
    db.session.add(f2)
    db.session.commit()
    
    flash(f"Connected with {user_to_connect.first_name}!", "success")
    return redirect(url_for("friend_profile", friend_id=user_id))


# ============================================================================
# Equipment & GroupTrip Status Management
# ============================================================================

@app.route("/profile/equipment/delete", methods=["POST"])
@login_required
def delete_equipment():
    """Delete equipment setup by slot (Primary/Secondary)."""
    data = request.get_json()
    
    slot_name = data.get("slot", "").upper()  # "PRIMARY" or "SECONDARY"
    
    if slot_name not in ["PRIMARY", "SECONDARY"]:
        return jsonify({"success": False, "error": "Invalid slot"}), 400
    
    try:
        slot = EquipmentSlot[slot_name]
    except KeyError:
        return jsonify({"success": False, "error": "Invalid slot"}), 400
    
    # Find equipment - explicit permission check
    equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=slot).first()
    
    if not equipment:
        return jsonify({"success": False, "error": "Equipment not found"}), 404
    
    if equipment.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    # Delete
    db.session.delete(equipment)
    db.session.commit()
    
    return jsonify({"success": True, "message": f"{slot.value} equipment deleted"})


@app.route("/profile/equipment", methods=["POST"])
@login_required
def save_equipment():
    """Save or update equipment setup (Primary/Secondary)."""
    data = request.get_json()
    
    slot_name = data.get("slot", "").upper()  # "PRIMARY" or "SECONDARY"
    discipline_name = data.get("discipline", "").upper()  # "SKIER" or "SNOWBOARDER"
    brand = data.get("brand", "").strip()
    length_cm = data.get("length_cm")
    width_mm = data.get("width_mm")
    
    # Validate
    if not brand or slot_name not in ["PRIMARY", "SECONDARY"] or discipline_name not in ["SKIER", "SNOWBOARDER"]:
        return jsonify({"success": False, "error": "Invalid input"}), 400
    
    # Convert to enums
    try:
        slot = EquipmentSlot[slot_name]
        discipline = EquipmentDiscipline[discipline_name]
    except KeyError:
        return jsonify({"success": False, "error": "Invalid slot or discipline"}), 400
    
    # Explicit permission check: only owner can edit
    equipment = EquipmentSetup.query.filter_by(user_id=current_user.id, slot=slot).first()
    if equipment and equipment.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    # Find or create equipment
    if not equipment:
        equipment = EquipmentSetup(user_id=current_user.id, slot=slot)
    
    equipment.discipline = discipline
    equipment.brand = brand
    equipment.length_cm = int(length_cm) if length_cm else None
    equipment.width_mm = int(width_mm) if width_mm else None
    
    db.session.add(equipment)
    db.session.commit()
    
    return jsonify({"success": True, "message": f"{slot.value} equipment saved"})


@app.route("/group-trip/<int:trip_id>/transportation", methods=["POST"])
@login_required
def update_group_trip_transportation(trip_id):
    """Update transportation status (host-only)."""
    trip = GroupTrip.query.get_or_404(trip_id)
    
    if trip.host_id != current_user.id:
        return jsonify({"success": False, "error": "Only host can update"}), 403
    
    data = request.get_json()
    status_name = data.get("transportation_status", "").upper()
    
    if status_name == "":
        trip.transportation_status = None
    elif status_name in ["HAVE_TRANSPORT", "NEED_TRANSPORT", "NOT_SURE"]:
        try:
            trip.transportation_status = TransportationStatus[status_name]
        except KeyError:
            return jsonify({"success": False, "error": "Invalid status"}), 400
    else:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    
    db.session.commit()
    return jsonify({"success": True})


# ============================================================================
# CANONICAL PASS BRAND MAPPINGS (for backfill)
# ============================================================================

EPIC_RESORT_NAMES = {
    "Heavenly Mountain Resort", "Kirkwood Mountain Resort", "Northstar California Resort",
    "Vail Mountain", "Beaver Creek", "Breckenridge Ski Resort", "Keystone Resort",
    "Crested Butte Mountain Resort", "Mt. Brighton", "Afton Alps", "Hidden Valley Ski Resort",
    "Attitash Mountain Resort", "Wildcat Mountain", "Hunter Mountain", "Boston Mills",
    "Brandywine", "Mad River Mountain", "Jack Frost Big Boulder", "Roundtop Mountain Resort",
    "Whitetail Resort", "Liberty Mountain Resort", "Park City Mountain", "Mount Snow",
    "Okemo Mountain Resort", "Stowe Mountain Resort", "Stevens Pass", "Wilmot Mountain"
}

INDY_RESORT_NAMES = {
    "Bear Valley", "China Peak", "Dodge Ridge", "Sunlight Mountain Resort",
    "Powderhorn Mountain Resort", "Ski Cooper", "Brundage Mountain", "Tamarack Resort",
    "Lookout Pass", "Saddleback Mountain", "Marquette Mountain", "Blacktail Mountain",
    "Lost Trail Powder Mountain", "Red Lodge Mountain", "Cannon Mountain", "Ski Santa Fe",
    "Titus Mountain", "Willamette Pass", "Blue Knob All Seasons Resort", "Beaver Mountain",
    "Eagle Point Resort", "Bolton Valley", "Magic Mountain", "White Pass", "Snow King Mountain"
}

MOUNTAIN_COLLECTIVE_RESORT_NAMES = {
    "Aspen Snowmass", "Alta Ski Area", "Snowbird", "Jackson Hole Mountain Resort",
    "Sun Valley", "Sugarbush Resort", "Taos Ski Valley"
}


@app.cli.command("backfill-pass-brands")
@click.option("--force", is_flag=True, help="Force re-run even if already populated")
def backfill_pass_brands(force):
    """Backfill pass_brands column for all resorts. Idempotent by default."""
    created = 0
    updated = 0
    skipped = 0
    null_count = 0

    with app.app_context():
        resorts = Resort.query.all()

        for resort in resorts:
            # Skip if already populated and not forcing
            if resort.pass_brands and not force:
                skipped += 1
                continue

            original_pass_brands = resort.pass_brands
            new_pass_brands = None

            # Priority 1: Mountain Collective (Ikon overlap)
            if resort.name in MOUNTAIN_COLLECTIVE_RESORT_NAMES:
                new_pass_brands = "Ikon,MountainCollective"
                resort.brand = "Ikon"

            # Priority 2: Epic
            elif resort.name in EPIC_RESORT_NAMES:
                new_pass_brands = "Epic"
                resort.brand = "Epic"

            # Priority 3: Indy
            elif resort.name in INDY_RESORT_NAMES:
                new_pass_brands = "Indy"
                resort.brand = "Other"

            # Priority 4: Existing Ikon (default)
            elif resort.brand == "Ikon":
                new_pass_brands = "Ikon"

            # Fallback: Use existing brand
            else:
                new_pass_brands = resort.brand or "Other"

            # Update if changed
            if new_pass_brands != original_pass_brands:
                resort.pass_brands = new_pass_brands
                db.session.commit()
                if original_pass_brands is None:
                    created += 1
                    print(f"  ✨ CREATED: {resort.name} ({resort.state}) → {new_pass_brands}")
                else:
                    updated += 1
                    print(f"  ✏️  UPDATED: {resort.name} ({resort.state}) → {new_pass_brands} (was: {original_pass_brands})")
            else:
                skipped += 1

        # Verify no nulls
        null_check = Resort.query.filter(Resort.pass_brands.is_(None)).count()

        print("\n" + "=" * 70)
        print("BACKFILL SUMMARY")
        print("=" * 70)
        print(f"Total resorts: {len(resorts)}")
        print(f"Pass brands created: {created}")
        print(f"Pass brands updated: {updated}")
        print(f"Pass brands skipped: {skipped}")
        print(f"Resorts with NULL pass_brands: {null_check}")
        print()

        # Distribution by pass
        epic_count = Resort.query.filter(Resort.pass_brands.contains("Epic")).count()
        ikon_count = Resort.query.filter(Resort.pass_brands.contains("Ikon")).count()
        indy_count = Resort.query.filter(Resort.pass_brands.contains("Indy")).count()
        mountain_collective_count = Resort.query.filter(Resort.pass_brands.contains("MountainCollective")).count()

        print("Distribution:")
        print(f"  - Epic: {epic_count}")
        print(f"  - Ikon: {ikon_count}")
        print(f"  - Indy: {indy_count}")
        print(f"  - MountainCollective: {mountain_collective_count}")
        print()

        # Sample resorts
        print("Sample Results (before/after):")
        samples = [
            ("Park City Mountain", "Epic"),
            ("Bolton Valley", "Indy"),
            ("Aspen Snowmass", "Ikon,MountainCollective"),
            ("Jackson Hole Mountain Resort", "Ikon,MountainCollective"),
        ]
        for name, expected_brands in samples:
            resort = Resort.query.filter_by(name=name).first()
            if resort:
                status = "✓" if resort.pass_brands == expected_brands else "✗"
                print(f"  {status} {name}: {resort.pass_brands} (expected: {expected_brands})")
            else:
                print(f"  ✗ {name}: NOT FOUND")

        print()
        print("✅ Backfill complete!")
        print("=" * 70)


# ============================================================================
# DEMO DATA SEEDING (FULL WORLD)
# ============================================================================

SKIER_BRANDS = ['Atomic', 'Black Crows', 'Blizzard', 'Dynastar', 'Elan', 'Faction', 'Fischer', 'Head', 'K2', 'Line', 'Nordica', 'Rossignol', 'Salomon', 'Scott', 'Volkl']
SNOWBOARDER_BRANDS = ['Arbor', 'Bataleon', 'Burton', 'Capita', 'DC', 'GNU', 'Jones', 'K2', 'Lib Tech', 'Nitro', 'Ride', 'Rome', 'Salomon', 'Yes']
PASS_OPTIONS_SEEDING = ["Epic", "Ikon", "MountainCollective", "Indy", "PowderAlliance", "Freedom", "SkiCalifornia", "Other", "None"]

FIRST_NAMES = ["Alex", "Jordan", "Sam", "Casey", "Riley", "Morgan", "Jamie", "Taylor", "Jesse", "Charlie", "Skylar", "Quinn", "Dakota", "Avery", "Blake", "Parker", "Rowan", "Drew", "Phoenix", "River", "Jade", "Connor", "Reese", "Emerson", "Sage", "Justice", "Scout", "Lex", "Hayden", "Aspen", "Storm", "Finley", "Devyn", "Canyon", "Sierra", "Teton", "Range", "Peak", "Boulder", "Summit", "Ridge", "Trail", "Alpine", "Powder", "Mogul", "Gnar", "Shred", "Carve", "Slate", "Blake", "Bailey", "Cameron"]

LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"]

TRIP_TITLES = ["powder day mission", "spring corn runs", "lake tahoe adventure", "utah powder week", "colorado peaks", "backcountry tour", "resort lap day", "mogul practice", "tree skiing", "alpine exploration"]


@app.cli.command("seed-full-demo-world")
def seed_full_demo_world():
    """Seed comprehensive demo data for end-to-end testing."""
    print("🌍 SEEDING FULL DEMO WORLD...")
    print("=" * 70)
    
    with app.app_context():
        # ====== FIXED USERS ======
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if not richard:
            richard = User(
                first_name="Richard", last_name="Battle-Baxter",
                email="richardbattlebaxter@gmail.com",
                primary_rider_type="Skier", secondary_rider_types=[],
                pass_type="Epic", skill_level="Advanced",
                home_state="Colorado", birth_year=1985, profile_setup_complete=True
            )
            richard.set_password("12345678")
            db.session.add(richard)
            print("✨ Created: Richard Battle-Baxter")
        else:
            print("⊘ Skipped: Richard (already exists)")
        
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        if not jonathan:
            jonathan = User(
                first_name="Jonathan", last_name="Schmitz",
                email="jonathanmschmitz@gmail.com",
                primary_rider_type="Skier", secondary_rider_types=[],
                pass_type="Ikon,MountainCollective", skill_level="Advanced",
                home_state="Utah", birth_year=1990, profile_setup_complete=True
            )
            jonathan.set_password("12345678")
            db.session.add(jonathan)
            print("✨ Created: Jonathan Schmitz")
        else:
            print("⊘ Skipped: Jonathan (already exists)")
        
        db.session.commit()
        
        # ====== DUMMY USERS (50) ======
        dummy_users = []
        for i in range(50):
            email = f"user{i+1}@baselodge.local"
            if User.query.filter_by(email=email).first():
                print(f"⊘ Skipped: {email} (already exists)")
                dummy_users.append(User.query.filter_by(email=email).first())
                continue
            
            primary_rt = random.choice(["Skier", "Snowboarder"])
            user = User(
                first_name=random.choice(FIRST_NAMES),
                last_name=random.choice(LAST_NAMES),
                email=email,
                primary_rider_type=primary_rt,
                secondary_rider_types=[],
                skill_level=random.choice(["Beginner", "Intermediate", "Advanced", "Expert"]),
                home_state=random.choice(["Colorado", "Utah", "California", "Wyoming", "Montana", "Idaho", "Washington"]),
                birth_year=random.randint(1970, 2005),
                profile_setup_complete=True
            )
            
            # 70% single pass, 30% multi-pass
            if random.random() < 0.7:
                user.pass_type = random.choice(["Epic", "Ikon", "Indy", "Other"])
            else:
                user.pass_type = ",".join(sorted(set(random.sample(PASS_OPTIONS_SEEDING[:-2], 2))))
            
            user.set_password("12345678")
            db.session.add(user)
            dummy_users.append(user)
        
        db.session.commit()
        print(f"✨ Created: {len(dummy_users)} dummy users")
        
        # ====== EQUIPMENT ======
        all_users = [richard, jonathan] + dummy_users
        equipment_count = 0
        for user in all_users:
            if EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.PRIMARY).first():
                continue
            
            user_rt = user.primary_rider_type or user.rider_type or "Skier"
            discipline = EquipmentDiscipline.SKIER if user_rt == "Skier" else EquipmentDiscipline.SNOWBOARDER
            brands = SKIER_BRANDS if user_rt == "Skier" else SNOWBOARDER_BRANDS
            
            primary = EquipmentSetup(
                user_id=user.id,
                slot=EquipmentSlot.PRIMARY,
                discipline=discipline,
                brand=random.choice(brands),
                length_cm=random.randint(160, 190) if user_rt == "Skier" else random.randint(150, 165),
                width_mm=random.randint(80, 105) if user_rt == "Skier" else None
            )
            db.session.add(primary)
            equipment_count += 1
            
            if random.random() < 0.5:
                secondary = EquipmentSetup(
                    user_id=user.id,
                    slot=EquipmentSlot.SECONDARY,
                    discipline=discipline,
                    brand=random.choice(brands),
                    length_cm=random.randint(160, 190) if user_rt == "Skier" else random.randint(150, 165),
                    width_mm=random.randint(80, 105) if user_rt == "Skier" else None
                )
                db.session.add(secondary)
                equipment_count += 1
        
        db.session.commit()
        print(f"✨ Created: {equipment_count} equipment setups")
        
        # ====== SKI TRIPS ======
        resorts = Resort.query.all()
        trip_count = 0
        today = date.today()
        for user in all_users:
            existing_trips = SkiTrip.query.filter_by(user_id=user.id).count()
            if existing_trips >= 4:
                continue
            
            for _ in range(4 - existing_trips):
                start = today + timedelta(days=random.randint(5, 120))
                end = start + timedelta(days=random.randint(1, 5))
                
                trip = SkiTrip(
                    user_id=user.id,
                    resort_id=random.choice(resorts).id,
                    start_date=start,
                    end_date=end,
                    pass_type=random.choice(user.pass_type.split(",")),
                    is_public=True
                )
                db.session.add(trip)
                trip_count += 1
        
        db.session.commit()
        print(f"✨ Created: {trip_count} ski trips")
        
        # ====== FRIEND CONNECTIONS ======
        friend_count = 0
        for user in dummy_users:
            if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first():
                continue
            
            f1 = Friend(user_id=user.id, friend_id=richard.id)
            f2 = Friend(user_id=richard.id, friend_id=user.id)
            db.session.add_all([f1, f2])
            friend_count += 2
            
            if not Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first():
                f3 = Friend(user_id=user.id, friend_id=jonathan.id)
                f4 = Friend(user_id=jonathan.id, friend_id=user.id)
                db.session.add_all([f3, f4])
                friend_count += 2
        
        db.session.commit()
        print(f"✨ Created: {friend_count} friend connections")
        
        # ====== GROUP TRIPS ======
        grouptrip_count = 0
        tripguest_count = 0
        for i in range(5):
            host = richard if i % 2 == 0 else jonathan
            title = f"{random.choice(['March', 'April', 'May'])} {random.choice(TRIP_TITLES)}"
            start = today + timedelta(days=random.randint(10, 60))
            end = start + timedelta(days=random.randint(2, 5))
            
            trip = GroupTrip(
                host_id=host.id,
                title=title,
                start_date=start,
                end_date=end
            )
            db.session.add(trip)
            db.session.flush()
            
            # Add host as accepted guest
            host_guest = TripGuest(trip_id=trip.id, user_id=host.id, status=GuestStatus.ACCEPTED)
            db.session.add(host_guest)
            tripguest_count += 1
            
            # Add jonathan/richard
            other_host = jonathan if host == richard else richard
            other_guest = TripGuest(trip_id=trip.id, user_id=other_host.id, status=GuestStatus.ACCEPTED)
            db.session.add(other_guest)
            tripguest_count += 1
            
            # Add 5-10 random dummy users
            selected_guests = random.sample(dummy_users, min(random.randint(5, 10), len(dummy_users)))
            for guest_user in selected_guests:
                guest = TripGuest(trip_id=trip.id, user_id=guest_user.id, status=GuestStatus.ACCEPTED)
                db.session.add(guest)
                tripguest_count += 1
            
            grouptrip_count += 1
        
        db.session.commit()
        print(f"✨ Created: {grouptrip_count} group trips, {tripguest_count} trip guests")
        
        # ====== OPEN DATES ======
        open_dates_count = 0
        for user in all_users:
            if user.open_dates:
                continue
            
            num_ranges = random.randint(6, 10) if user in [richard, jonathan] else random.randint(3, 6)
            open_dates = []
            for _ in range(num_ranges):
                start = today + timedelta(days=random.randint(5, 180))
                for j in range(random.randint(1, 4)):
                    date_str = (start + timedelta(days=j)).strftime("%Y-%m-%d")
                    if date_str not in open_dates:
                        open_dates.append(date_str)
            
            user.open_dates = sorted(open_dates)
            open_dates_count += len(open_dates)
        
        db.session.commit()
        print(f"✨ Created: {open_dates_count} open dates")
        
        # ====== VERIFICATION ======
        print("\n" + "=" * 70)
        print("VERIFICATION REPORT")
        print("=" * 70)
        print(f"Total users: {User.query.count()}")
        print(f"  - Fixed: 2 (Richard, Jonathan)")
        print(f"  - Dummy: {len(dummy_users)}")
        print(f"Total SkiTrips: {SkiTrip.query.count()}")
        print(f"Total GroupTrips: {GroupTrip.query.count()}")
        print(f"Total TripGuests: {TripGuest.query.count()}")
        print(f"Total EquipmentSetup: {EquipmentSetup.query.count()}")
        print(f"Total Friend connections: {Friend.query.count()}")
        
        # Sample data
        print(f"\nSample Users:")
        for user in random.sample(all_users, min(5, len(all_users))):
            trips = SkiTrip.query.filter_by(user_id=user.id).count()
            equipment = EquipmentSetup.query.filter_by(user_id=user.id).count()
            open_dates = len(user.open_dates) if user.open_dates else 0
            friends_richard = 1 if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first() else 0
            friends_jonathan = 1 if Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first() else 0
            
            print(f"  {user.email}: passes={user.pass_type}, trips={trips}, equipment={equipment}, open_dates={open_dates}, connected_to_richard={friends_richard}, connected_to_jonathan={friends_jonathan}")
        
        print("\n✅ SEEDING COMPLETE!")
        print("=" * 70)


# ============================================================================
# REPAIR DEMO DATA
# ============================================================================

@app.cli.command("repair-demo-data")
def repair_demo_data():
    """Repair seeded demo data: fix passwords and friend connections."""
    print("🔧 REPAIRING DEMO DATA...")
    print("=" * 70)
    
    with app.app_context():
        # ====== FIX PASSWORDS ======
        password_fixes = 0
        
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if richard:
            richard.set_password("12345678")
            db.session.add(richard)
            password_fixes += 1
            print("✨ Reset password: Richard Battle-Baxter")
        
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        if jonathan:
            jonathan.set_password("12345678")
            db.session.add(jonathan)
            password_fixes += 1
            print("✨ Reset password: Jonathan Schmitz")
        
        db.session.commit()
        
        # ====== FIX FRIEND CONNECTIONS ======
        friend_fixes = 0
        
        # Get all dummy users
        dummy_users = User.query.filter(
            User.email.like("user%@baselodge.local")
        ).all()
        
        print(f"\nProcessing {len(dummy_users)} dummy users...")
        
        for user in dummy_users:
            # Connect to Richard
            if richard:
                existing_1 = Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first()
                existing_2 = Friend.query.filter_by(user_id=richard.id, friend_id=user.id).first()
                
                if not existing_1:
                    f1 = Friend(user_id=user.id, friend_id=richard.id)
                    db.session.add(f1)
                    friend_fixes += 1
                
                if not existing_2:
                    f2 = Friend(user_id=richard.id, friend_id=user.id)
                    db.session.add(f2)
                    friend_fixes += 1
            
            # Connect to Jonathan
            if jonathan:
                existing_3 = Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first()
                existing_4 = Friend.query.filter_by(user_id=jonathan.id, friend_id=user.id).first()
                
                if not existing_3:
                    f3 = Friend(user_id=user.id, friend_id=jonathan.id)
                    db.session.add(f3)
                    friend_fixes += 1
                
                if not existing_4:
                    f4 = Friend(user_id=jonathan.id, friend_id=user.id)
                    db.session.add(f4)
                    friend_fixes += 1
        
        db.session.commit()
        print(f"✨ Added/verified: {friend_fixes} friend connections")
        
        # ====== VERIFICATION ======
        print("\n" + "=" * 70)
        print("VERIFICATION REPORT")
        print("=" * 70)
        
        # Check passwords
        test_richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        test_jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        
        print(f"\nPassword Status:")
        if test_richard and test_richard.check_password("12345678"):
            print(f"  ✓ Richard can log in with 12345678")
        else:
            print(f"  ✗ Richard password FAILED")
        
        if test_jonathan and test_jonathan.check_password("12345678"):
            print(f"  ✓ Jonathan can log in with 12345678")
        else:
            print(f"  ✗ Jonathan password FAILED")
        
        # Check friend connections
        print(f"\nFriend Connection Status:")
        total_dummy = len(dummy_users)
        richard_connections = Friend.query.filter_by(friend_id=richard.id).count() if richard else 0
        jonathan_connections = Friend.query.filter_by(friend_id=jonathan.id).count() if jonathan else 0
        
        print(f"  Dummy users connected to Richard: {richard_connections}/{total_dummy}")
        print(f"  Dummy users connected to Jonathan: {jonathan_connections}/{total_dummy}")
        
        # Sample verification
        print(f"\nSample User Connections:")
        for user in random.sample(dummy_users, min(3, len(dummy_users))):
            friends_richard = 1 if Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first() else 0
            friends_jonathan = 1 if Friend.query.filter_by(user_id=user.id, friend_id=jonathan.id).first() else 0
            
            print(f"  {user.email}: richard_friend={friends_richard}, jonathan_friend={friends_jonathan}")
        
        print("\n✅ REPAIR COMPLETE!")
        print("=" * 70)


@app.cli.command("fix-seeded-users")
def fix_seeded_users():
    """Fix seeded users: reset passwords and ensure friend connections."""
    from werkzeug.security import generate_password_hash
    
    print("🔐 FIXING SEEDED USERS...")
    print("=" * 70)
    
    TARGET_USERS = [
        {
            "email": "richardbattlebaxter@gmail.com",
            "first_name": "Richard",
            "last_name": "Battle-Baxter",
            "password": "12345678"
        },
        {
            "email": "jonathanmschmitz@gmail.com",
            "first_name": "Jonathan",
            "last_name": "Schmitz",
            "password": "12345678"
        }
    ]

    users = {}

    # Step 1: Create or update target users with correct passwords
    print("\n📝 STEP 1: Creating/Updating Target Users")
    for u in TARGET_USERS:
        user = User.query.filter(
            db.func.lower(User.email) == u["email"].lower()
        ).first()

        if not user:
            user = User(
                email=u["email"],
                first_name=u["first_name"],
                last_name=u["last_name"],
                password_hash=generate_password_hash(u["password"])
            )
            db.session.add(user)
            print(f"  ✨ CREATED user {u['email']}")
        else:
            user.password_hash = generate_password_hash(u["password"])
            print(f"  ✏️  RESET password for {u['email']}")

        users[u["email"]] = user

    db.session.commit()

    # Step 2: Fix friend connections
    print("\n🤝 STEP 2: Fixing Friend Connections")
    richard = users["richardbattlebaxter@gmail.com"]
    jonathan = users["jonathanmschmitz@gmail.com"]

    all_users = User.query.all()
    connections_added = 0

    for user in all_users:
        if user.id in (richard.id, jonathan.id):
            continue

        for core in (richard, jonathan):
            exists = Friend.query.filter_by(
                user_id=core.id,
                friend_id=user.id
            ).first()

            if not exists:
                db.session.add(Friend(user_id=core.id, friend_id=user.id))
                db.session.add(Friend(user_id=user.id, friend_id=core.id))
                connections_added += 2

    db.session.commit()
    print(f"  ✨ Added {connections_added} friend connections")

    # Step 3: Fix pass_type cleanup (convert "both" to "epic" for seeded users)
    print("\n🎿 STEP 3: Cleaning up pass_type values")
    seeded_users_with_both = User.query.filter(
        User.is_seeded == True,
        (User.pass_type.ilike('%both%') | (User.pass_type == 'both'))
    ).all()
    
    both_count = 0
    for user in seeded_users_with_both:
        if user.pass_type and 'both' in user.pass_type.lower():
            user.pass_type = user.pass_type.replace('Both', 'Epic').replace('both', 'Epic')
            both_count += 1
    
    if both_count > 0:
        db.session.commit()
        print(f"  ✨ Converted {both_count} seeded users from 'both' to 'epic'")
    else:
        print(f"  ✓ No seeded users with pass_type='both' found")

    # Step 4: Verification
    print("\n" + "=" * 70)
    print("✅ VERIFICATION")
    print("=" * 70)
    
    richard_friends = Friend.query.filter_by(user_id=richard.id).count()
    jonathan_friends = Friend.query.filter_by(user_id=jonathan.id).count()
    
    print(f"Richard friends: {richard_friends}")
    print(f"Jonathan friends: {jonathan_friends}")
    
    # Test password
    richard_pwd_ok = richard.check_password("12345678")
    jonathan_pwd_ok = jonathan.check_password("12345678")
    
    print(f"Richard password check: {richard_pwd_ok}")
    print(f"Jonathan password check: {jonathan_pwd_ok}")
    
    # Check for any remaining "both" values
    users_with_both = User.query.filter(
        User.pass_type.ilike('%both%') | (User.pass_type == 'both')
    ).count()
    print(f"Users with pass_type containing 'both': {users_with_both}")
    
    print("\n✅ FIX COMPLETE!")
    print("=" * 70)


@app.route("/admin/version", methods=["GET"])
@login_required
@admin_required
def admin_version():
    """Simple version check endpoint to verify production deployment."""
    return jsonify({
        "version": "2025-12-25-v5",
        "status": "ok",
        "endpoints_available": [
            "/admin/version",
            "/admin/backfill-country-codes",
            "/admin/resorts-audit",
            "/admin/init-db",
            "/admin/sync-from-canonical"
        ]
    })


@app.route("/admin/debug-users", methods=["GET"])
@login_required
@admin_required
def debug_users():
    """Inspect production database: user count, first 20 users, and DB URI in use."""
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "not set")
    # Mask password from URI for safe display
    import re
    safe_uri = re.sub(r'(:)[^:@]+(@)', r'\1***\2', db_uri)
    users = User.query.order_by(User.id).limit(20).all()
    total = User.query.count()
    return jsonify({
        "database_uri": safe_uri,
        "total_user_count": total,
        "first_20_users": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
            }
            for u in users
        ]
    })


@app.route("/admin/export-live-data", methods=["GET"])
@login_required
@admin_required
def export_live_data():
    """Read-only full data rescue export. Returns all critical user-linked table rows as JSON."""
    import enum as _enum

    def _val(v):
        """Serialize a column value to a JSON-safe primitive."""
        if v is None:
            return None
        if isinstance(v, _enum.Enum):
            return v.value
        if hasattr(v, 'isoformat'):
            return v.isoformat()
        return v

    def _row(obj, exclude=None):
        exclude = set(exclude or [])
        return {
            c.name: _val(getattr(obj, c.name))
            for c in obj.__table__.columns
            if c.name not in exclude
        }

    users           = User.query.order_by(User.id).all()
    trips           = SkiTrip.query.order_by(SkiTrip.id).all()
    friends         = Friend.query.order_by(Friend.id).all()
    participants    = SkiTripParticipant.query.order_by(SkiTripParticipant.id).all()
    invitations     = Invitation.query.order_by(Invitation.id).all()
    invite_tokens   = InviteToken.query.order_by(InviteToken.id).all()
    group_trips     = GroupTrip.query.order_by(GroupTrip.id).all()
    trip_guests     = TripGuest.query.order_by(TripGuest.id).all()

    return jsonify({
        "exported_at": datetime.utcnow().isoformat(),
        "database_uri": re.sub(r'(:)[^:@]+(@)', r'\1***\2',
                               app.config.get("SQLALCHEMY_DATABASE_URI", "not set")),
        "counts": {
            "users":            len(users),
            "ski_trips":        len(trips),
            "friends":          len(friends),
            "ski_trip_participants": len(participants),
            "invitations":      len(invitations),
            "invite_tokens":    len(invite_tokens),
            "group_trips":      len(group_trips),
            "trip_guests":      len(trip_guests),
        },
        "users":            [_row(u, exclude=["password_hash"]) for u in users],
        "ski_trips":        [_row(t) for t in trips],
        "friends":          [_row(f) for f in friends],
        "ski_trip_participants": [_row(p) for p in participants],
        "invitations":      [_row(i) for i in invitations],
        "invite_tokens":    [_row(t) for t in invite_tokens],
        "group_trips":      [_row(g) for g in group_trips],
        "trip_guests":      [_row(g) for g in trip_guests],
    })


@app.route("/admin/resorts-audit", methods=["GET"])
@login_required
@admin_required
def resorts_audit():
    """Read-only endpoint to fetch all resorts for audit comparison."""
    resorts = Resort.query.all()
    return jsonify({
        "total": len(resorts),
        "resorts": [
            {
                "name": r.name,
                "state_code": r.state_code or r.state,
                "country_code": r.country_code or r.country,
                "pass_brands": r.pass_brands or r.brand
            }
            for r in resorts
        ]
    })


@app.route("/admin/backfill-country-codes", methods=["GET", "POST"])
@login_required
@admin_required
def backfill_country_codes():
    """
    Backfill country_code and state_code for resorts based on state field.
    v2 - Updated 2025-12-25
    
    Usage: GET https://yourapp.replit.dev/admin/backfill-country-codes
    
    This is idempotent - safe to call multiple times.
    """
    US_STATES = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'
    }
    
    CA_PROVINCES = {
        'AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'
    }
    
    try:
        resorts = Resort.query.all()
        updated = []
        skipped = []
        
        for r in resorts:
            state = r.state_code or r.state
            if not state:
                skipped.append(f"{r.name}: no state")
                continue
            
            state_upper = state.upper().strip()
            
            if state_upper in US_STATES:
                if r.country_code != 'US' or r.state_code != state_upper:
                    r.country_code = 'US'
                    r.country = 'US'
                    r.state_code = state_upper
                    updated.append(f"{r.name} -> US/{state_upper}")
            elif state_upper in CA_PROVINCES:
                if r.country_code != 'CA' or r.state_code != state_upper:
                    r.country_code = 'CA'
                    r.country = 'CA'
                    r.state_code = state_upper
                    updated.append(f"{r.name} -> CA/{state_upper}")
            else:
                skipped.append(f"{r.name}: unknown state '{state}'")
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Updated {len(updated)} resorts, skipped {len(skipped)}",
            "updated": updated[:50],
            "skipped": skipped[:20],
            "total_resorts": len(resorts)
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500



# ============================================================================
# ADMIN COUNTRIES ENDPOINT
# ============================================================================

@app.route("/admin/countries", methods=["POST"])
@login_required
@admin_required
def admin_add_country():
    """Add a new country to the reference table."""
    from models import Country
    
    data = request.get_json()
    name = (data.get("name") or "").strip()
    code = (data.get("code") or "").strip().upper()
    
    if not name or not code:
        return jsonify({"status": "error", "message": "Name and code are required"}), 400
    
    if len(code) != 2:
        return jsonify({"status": "error", "message": "Country code must be 2 letters"}), 400
    
    existing = Country.query.filter(db.func.lower(Country.code) == code.lower()).first()
    if existing:
        return jsonify({"status": "success", "id": existing.id, "code": existing.code, "name": existing.name})
    
    country = Country(code=code, name=name, is_active=True)
    db.session.add(country)
    db.session.commit()
    
    COUNTRY_NAMES[code] = name
    
    return jsonify({"status": "success", "id": country.id, "code": country.code, "name": country.name})


# ============================================================================
# ADMIN RESORTS CURATION PAGE
# ============================================================================

@app.route("/admin/resorts")
@login_required
@admin_required
def admin_resorts():
    """
    Admin page for curating resort data.
    DEV is the source of truth. PROD sync via canonical JSON export.
    """
    import os
    import json
    
    # Get all resorts sorted by country, state, name
    resorts = Resort.query.order_by(Resort.country_code, Resort.state_code, Resort.name).all()
    
    # Get unique countries for filters (from existing resorts)
    resort_countries = db.session.query(Resort.country_code).distinct().order_by(Resort.country_code).all()
    resort_countries = set(c[0] for c in resort_countries if c[0])
    
    # Get all countries from Country table for the dropdown
    from models import Country
    db_countries = Country.query.filter_by(is_active=True).order_by(Country.name).all()
    
    # Build unified country list
    dropdown_countries = sorted(COUNTRIES.items(), key=lambda x: x[1])
    
    # Keep countries list for filters (just codes from resorts)
    countries = sorted(resort_countries)
    
    # Check last canonical export timestamp
    canonical_file = os.path.join(os.path.dirname(__file__), 'data', 'canonical_resorts.json')
    last_export_info = None
    if os.path.exists(canonical_file):
        try:
            with open(canonical_file, 'r') as f:
                canonical_data = json.load(f)
            last_export_info = {
                'version': canonical_data.get('version', 'unknown'),
                'exported_at': canonical_data.get('exported_at', 'unknown'),
                'count': len(canonical_data.get('resorts', []))
            }
        except Exception:
            pass
    
    return render_template('admin_resorts.html',
                         resorts=resorts,
                         countries=countries,
                         dropdown_countries=dropdown_countries,
                         last_export_info=last_export_info,
                         total_count=len(resorts))


@app.route("/admin/resorts/export-excel")
@login_required
@admin_required
def admin_export_resorts_excel():
    """Export filtered resort list to Excel."""
    from io import BytesIO
    from openpyxl import Workbook
    from datetime import datetime
    
    # Trust query params ONLY for Excel export
    search_query = request.args.get('search', '').lower().strip()
    country_filter = request.args.get('country', '').strip()
    state_filter = request.args.get('state', '').strip()
    status_filter = request.args.get('status', '').lower().strip()
    pass_brand_filter = request.args.get('pass_brand', '').lower().strip()
    
    # Base query
    query = Resort.query
    
    # Apply country filter
    if country_filter:
        query = query.filter(Resort.country_code == country_filter)
        
    # Apply state filter
    if state_filter:
        query = query.filter((Resort.state_code == state_filter) | (Resort.state == state_filter))

    # Apply status filter
    if status_filter == 'active':
        query = query.filter(Resort.is_active == True)
    elif status_filter == 'inactive':
        query = query.filter(Resort.is_active == False)
        
    # Apply pass brand filter
    if pass_brand_filter:
        if pass_brand_filter == 'none':
            query = query.filter((Resort.pass_brands == None) | (Resort.pass_brands == '') | (Resort.pass_brands == 'None'))
        else:
            query = query.filter(Resort.pass_brands.ilike(f'%{pass_brand_filter}%'))

    resorts = query.all()
    
    # Apply search filter in-memory to match JS logic
    if search_query:
        resorts = [r for r in resorts if 
                   (r.name and search_query in r.name.lower()) or 
                   (r.state_code and search_query in r.state_code.lower()) or
                   (r.state and search_query in r.state.lower())]

    try:
        # Create workbook
        wb = Workbook()
        ws = wb.active
        if ws is None:
            return jsonify({'status': 'error', 'message': 'Failed to initialize Excel worksheet'}), 500
            
        ws.title = "Resorts Export"
        
        # Headers explicitly defined - use country_code and country_name (exact DB columns)
        headers = [
            "ID",
            "Name",
            "country_code",
            "country_name",
            "State / Region",
            "Pass Brands",
            "Status"
        ]
        
        # Write headers by numeric index ONLY
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            from openpyxl.styles import Font
            cell.font = Font(bold=True)
        
        # Data starts at row 2 - export exactly as stored in DB
        for row_idx, r in enumerate(resorts, start=2):
            ws.cell(row=row_idx, column=1, value=r.id)
            ws.cell(row=row_idx, column=2, value=r.name or '')
            ws.cell(row=row_idx, column=3, value=r.country_code or '')
            ws.cell(row=row_idx, column=4, value=r.country_name or '')
            ws.cell(row=row_idx, column=5, value=r.state_code or r.state or '')
            ws.cell(row=row_idx, column=6, value=r.pass_brands or r.brand or '')
            ws.cell(row=row_idx, column=7, value="ACTIVE" if r.is_active else "INACTIVE")
            
        # Adjust column widths
        for col_idx in range(1, len(headers) + 1):
            column_letter = ws.cell(row=1, column=col_idx).column_letter
            max_length = 0
            for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                for cell in row:
                    try:
                        val = str(cell.value) if cell.value is not None else ""
                        if len(val) > max_length:
                            max_length = len(val)
                    except:
                        pass
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

        # Save to memory
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        filename = f"resorts_export_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        # Log the error for admin debugging
        print(f"Excel Export Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Export failed: {str(e)}'}), 500


@app.route("/api/admin/resorts/update-pass-brand", methods=["POST"])
@login_required
@admin_required
def admin_update_pass_brand():
    """Update a single resort's pass brands (supports array)."""
    data = request.get_json()
    resort_id = data.get('resort_id')
    pass_brands = data.get('pass_brands')
    
    # Handle legacy single value format
    if pass_brands is None:
        pass_brands = data.get('pass_brand')
    if isinstance(pass_brands, str):
        pass_brands = [pass_brands] if pass_brands else []
    
    # Valid values
    valid_brands = {'Epic', 'Ikon', 'Mountain Collective', 'Indy', 'Other', 'None'}
    
    # Validation
    for brand in pass_brands:
        if brand not in valid_brands:
            return jsonify({'status': 'error', 'message': f'Invalid pass brand: {brand}'}), 400
    
    # Handle "None" semantics - mutually exclusive with all other passes
    if 'None' in pass_brands:
        pass_brands = ['None']  # Preserve as explicit marker, not empty list
        
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({'status': 'error', 'message': 'Resort not found'}), 404
    
    resort.pass_brands_json = pass_brands
    db.session.commit()
    return jsonify({'success': True, 'pass_brands': resort.get_pass_brands_list()})


@app.route("/api/admin/resorts/update-field", methods=["POST"])
@login_required
@admin_required
def admin_update_resort_field():
    """Update a single field on a resort (inline editing)."""
    data = request.get_json()
    resort_id = data.get('resort_id')
    field = data.get('field')
    value = data.get('value', '').strip()
    
    allowed_fields = ['name', 'country_code', 'state_code']
    if field not in allowed_fields:
        return jsonify({'success': False, 'message': f'Field {field} not allowed'}), 400
    
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({'success': False, 'message': 'Resort not found'}), 404
    
    if field == 'name':
        resort.name = value
    elif field == 'country_code':
        resort.country_code = value.upper() if value else None
        resort.country = value.upper() if value else None
    elif field == 'state_code':
        resort.state_code = value
        resort.state = value
    
    db.session.commit()
    return jsonify({'success': True})


@app.route("/api/admin/resorts/update-country-name", methods=["POST"])
@login_required
@admin_required
def admin_update_country_name():
    """Update a resort's country name override."""
    data = request.get_json()
    resort_id = data.get('resort_id')
    country_name_override = data.get('country_name_override', '').strip()
    
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({'success': False, 'message': 'Resort not found'}), 404
    
    # Set to None if empty (falls back to COUNTRIES lookup)
    resort.country_name_override = country_name_override if country_name_override else None
    db.session.commit()
    
    return jsonify({'success': True, 'display_country_name': resort.display_country_name})


@app.route("/api/admin/resorts/toggle-active", methods=["POST"])
@login_required
@admin_required
def admin_toggle_resort_active():
    """Toggle a resort's active status."""
    data = request.get_json()
    resort_id = data.get('resort_id')
    is_active = data.get('is_active', True)
    
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({'success': False, 'message': 'Resort not found'}), 404
    
    resort.is_active = is_active
    db.session.commit()
    return jsonify({'success': True})


@app.route("/api/admin/resorts/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_resort_post():
    """Delete a single resort via POST (for frontend compatibility)."""
    data = request.get_json()
    resort_id = data.get('resort_id')
    
    resort = Resort.query.get(resort_id)
    if not resort:
        return jsonify({'success': False, 'message': 'Resort not found'}), 404
    
    trip_count = SkiTrip.query.filter_by(resort_id=resort_id).count()
    home_count = User.query.filter_by(home_resort_id=resort_id).count()
    
    visited_count = 0
    wishlist_count = 0
    users = User.query.all()
    for user in users:
        if user.visited_resort_ids and resort_id in user.visited_resort_ids:
            visited_count += 1
        if user.wish_list_resorts and resort_id in user.wish_list_resorts:
            wishlist_count += 1
    
    total_refs = trip_count + home_count + visited_count + wishlist_count
    
    if total_refs > 0:
        return jsonify({
            'success': False,
            'message': f'Cannot delete: resort has {total_refs} references. Deactivate instead or merge first.'
        }), 400
    
    resort_name = resort.name
    db.session.delete(resort)
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Deleted resort: {resort_name}'})


@app.route("/api/admin/resorts/bulk-update-pass-brand", methods=["POST"])
@login_required
@admin_required
def admin_bulk_update_pass_brand():
    """Bulk update resorts' pass brands (supports array)."""
    data = request.get_json()
    resort_ids = data.get('resort_ids', [])
    pass_brands = data.get('pass_brands')
    
    # Handle legacy single value format
    if pass_brands is None:
        pass_brands = data.get('pass_brand')
    if isinstance(pass_brands, str):
        pass_brands = [pass_brands] if pass_brands else []
    
    # Valid values
    valid_brands = {'Epic', 'Ikon', 'Mountain Collective', 'Indy', 'Other', 'None'}
    
    # Validation
    for brand in pass_brands:
        if brand not in valid_brands:
            return jsonify({'status': 'error', 'message': f'Invalid pass brand: {brand}'}), 400
        
    if not resort_ids:
        return jsonify({'status': 'error', 'message': 'No resorts selected'}), 400
    
    # Handle "None" semantics - mutually exclusive with all other passes
    if 'None' in pass_brands:
        pass_brands = ['None']  # Preserve as explicit marker, not empty list
    
    # Update each resort (bulk update for JSON column)
    resorts = Resort.query.filter(Resort.id.in_(resort_ids)).all()
    for resort in resorts:
        resort.pass_brands_json = pass_brands
    
    db.session.commit()
    return jsonify({'updated_count': len(resorts)})


@app.route("/admin/resorts/import-excel", methods=["POST"])
@login_required
@admin_required
def admin_import_resorts_excel():
    """Import resort updates from Excel. Supports CREATE (blank ID) and UPDATE (existing ID).
    
    Country field normalization (Section 4 compliant):
    - CASE A: country_code ONLY → validate, derive country_name from mapping
    - CASE B: country_name ONLY → reverse-map to code if unique, else reject
    - CASE C: BOTH provided → validate they match, reject if mismatch
    - CASE D: NEITHER provided → leave unchanged (for updates), reject (for creates)
    """
    from openpyxl import load_workbook
    from io import BytesIO
    from utils.countries import is_valid_country_code, country_name_from_code, country_code_from_name
    
    def normalize_country_fields(code_val, name_val, resort_name):
        """Normalize country fields per Section 4 rules.
        Returns (country_code, country_name, error_message).
        If error_message is not None, the row should be rejected.
        """
        code_str = str(code_val).strip().upper() if code_val and str(code_val).strip() else None
        name_str = str(name_val).strip() if name_val and str(name_val).strip() else None
        
        # CASE D: Neither provided
        if not code_str and not name_str:
            return (None, None, None)  # No error, just leave unchanged
        
        # CASE A: country_code ONLY
        if code_str and not name_str:
            if is_valid_country_code(code_str):
                derived_name = country_name_from_code(code_str)
                return (code_str, derived_name, None)
            else:
                return (None, None, f"Invalid country_code '{code_str}' for resort: {resort_name}")
        
        # CASE B: country_name ONLY
        if name_str and not code_str:
            resolved_code = country_code_from_name(name_str)
            if resolved_code:
                resolved_name = country_name_from_code(resolved_code)
                return (resolved_code, resolved_name, None)
            else:
                return (None, None, f"Could not resolve country_name '{name_str}' to a unique code for resort: {resort_name}")
        
        # CASE C: BOTH provided - validate match
        if code_str and name_str:
            if not is_valid_country_code(code_str):
                return (None, None, f"Invalid country_code '{code_str}' for resort: {resort_name}")
            
            expected_name = country_name_from_code(code_str)
            # Check if names match (case-insensitive, whitespace-normalized)
            if expected_name and expected_name.casefold() == name_str.casefold():
                return (code_str, expected_name, None)
            else:
                return (None, None, f"Country code/name mismatch for resort: {resort_name} (code={code_str}, name={name_str}, expected={expected_name})")
        
        return (None, None, None)
    
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'}), 400
        
    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'status': 'error', 'message': 'Invalid file format. Please upload .xlsx'}), 400
        
    try:
        wb = load_workbook(BytesIO(file.read()))
        ws = wb.active
        
        rows_processed = 0
        rows_created = 0
        rows_updated = 0
        rows_skipped = 0
        errors = []
        
        # Detect header row (row 1 now contains headers)
        # Format: ID, Name, country_code, country_name, State/Region, Pass Brands, Status
        header_row = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0] if ws.max_row >= 1 else None
        has_country_name_col = False
        if header_row:
            headers_lower = [str(h).lower().strip() if h else '' for h in header_row]
            has_country_name_col = 'country_name' in headers_lower or 'country name' in headers_lower
        
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or not any(row):
                continue
                
            rows_processed += 1
            resort_id = row[0]
            name = row[1]
            country_code_val = row[2] if len(row) > 2 else None
            
            # Parse based on detected schema
            if has_country_name_col:
                # New 7-column format: ID, Name, country_code, country_name, State/Region, Pass Brands, Status
                country_name_val = row[3] if len(row) > 3 else None
                state_region = row[4] if len(row) > 4 else None
                pass_brands = row[5] if len(row) > 5 else None
                status = str(row[6]).upper() if len(row) > 6 and row[6] else None
            else:
                # Legacy 6-column format (no country_name column)
                country_name_val = None
                state_region = row[3] if len(row) > 3 else None
                pass_brands = row[4] if len(row) > 4 else None
                status = str(row[5]).upper() if len(row) > 5 and row[5] else None
            
            # Validation for status
            if status and status not in ['ACTIVE', 'INACTIVE']:
                rows_skipped += 1
                errors.append({'row': row_idx, 'reason': f'Invalid status: {status}'})
                continue
            
            # Normalize country fields using Section 4 rules
            resort_name_str = str(name).strip() if name else f'Row {row_idx}'
            normalized_code, normalized_name, country_error = normalize_country_fields(
                country_code_val, country_name_val, resort_name_str
            )
            
            # CREATE MODE: ID is blank/null
            if not resort_id:
                # Required fields for creation
                if not name or not str(name).strip():
                    rows_skipped += 1
                    errors.append({'row': row_idx, 'reason': 'Missing required field: name'})
                    continue
                
                # CASE D for CREATE: country is required
                if not normalized_code:
                    if country_error:
                        rows_skipped += 1
                        errors.append({'row': row_idx, 'reason': country_error})
                    else:
                        rows_skipped += 1
                        errors.append({'row': row_idx, 'reason': 'Missing required country_code for new resort'})
                    continue
                
                # Generate slug from name
                resort_name = str(name).strip()
                try:
                    base_slug = generate_resort_slug(resort_name)
                except ValueError as e:
                    rows_skipped += 1
                    errors.append({'row': row_idx, 'reason': str(e)})
                    continue
                
                # Ensure slug is unique by appending suffix if needed
                slug = base_slug
                suffix = 1
                while Resort.query.filter_by(slug=slug).first():
                    slug = f"{base_slug}-{suffix}"
                    suffix += 1
                
                # Create new resort with normalized country fields
                new_resort = Resort(
                    name=resort_name,
                    slug=slug,
                    country_code=normalized_code,
                    country=normalized_code,
                    country_name=normalized_name,
                    state_code=str(state_region).strip() if state_region else None,
                    state=str(state_region).strip() if state_region else None,
                    pass_brands=str(pass_brands).strip() if pass_brands else None,
                    brand=str(pass_brands).strip().split(',')[0] if pass_brands else 'Other',
                    is_active=True if not status else (status == 'ACTIVE')
                )
                db.session.add(new_resort)
                rows_created += 1
                continue
            
            # UPDATE MODE: ID is present
            resort = Resort.query.get(resort_id)
            if not resort:
                rows_skipped += 1
                errors.append({'row': row_idx, 'reason': f'Resort ID {resort_id} not found'})
                continue
            
            # Check for country field errors (reject row if mismatch/invalid)
            if country_error:
                rows_skipped += 1
                errors.append({'row': row_idx, 'reason': country_error})
                continue
                
            # Apply updates
            updated = False
            if name and str(name).strip() != resort.name:
                resort.name = str(name).strip()
                updated = True
            
            # Apply normalized country fields (CASE D leaves unchanged)
            if normalized_code and normalized_code != resort.country_code:
                resort.country_code = normalized_code
                resort.country = normalized_code
                updated = True
            if normalized_name and normalized_name != resort.country_name:
                resort.country_name = normalized_name
                updated = True
                
            if state_region is not None:
                new_state = str(state_region).strip()
                if new_state != resort.state_code:
                    resort.state_code = new_state
                    resort.state = new_state
                    updated = True
                    
            if pass_brands is not None:
                new_passes = str(pass_brands).strip()
                if new_passes != resort.pass_brands:
                    resort.pass_brands = new_passes
                    resort.brand = new_passes.split(',')[0] if new_passes else 'Other'
                    updated = True
                    
            if status:
                new_active = (status == 'ACTIVE')
                if new_active != resort.is_active:
                    resort.is_active = new_active
                    updated = True
                    
            if updated:
                rows_updated += 1
                
        db.session.commit()
        
        return jsonify({
            'rows_processed': rows_processed,
            'rows_created': rows_created,
            'rows_updated': rows_updated,
            'rows_skipped': rows_skipped,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/api/admin/resorts/<int:resort_id>", methods=["PUT"])
@login_required
@admin_required
def admin_update_resort(resort_id):
    """Update a single resort's editable fields."""
    resort = Resort.query.get_or_404(resort_id)
    data = request.get_json()
    
    # Only allow updating specific fields
    if 'name' in data:
        resort.name = (data.get('name') or '').strip()
    if 'country_code' in data:
        resort.country_code = (data.get('country_code') or '').strip().upper()
        resort.country = resort.country_code
    if 'state_code' in data:
        resort.state_code = (data.get('state_code') or '').strip()
        resort.state = resort.state_code
    if 'pass_brands' in data:
        resort.pass_brands = (data.get('pass_brands') or '').strip() or None
        resort.brand = resort.pass_brands.split(',')[0] if resort.pass_brands else 'Other'
    if 'is_active' in data:
        resort.is_active = bool(data['is_active'])
    
    db.session.commit()
    return jsonify({'status': 'success', 'resort_id': resort_id})


@app.route("/api/admin/resorts/<int:resort_id>", methods=["DELETE"])
@login_required
@admin_required
def admin_delete_resort(resort_id):
    """Hard delete a resort. Checks for FK references first."""
    resort = Resort.query.get_or_404(resort_id)
    
    # Check for existing references
    trip_count = SkiTrip.query.filter_by(resort_id=resort_id).count()
    home_count = User.query.filter_by(home_resort_id=resort_id).count()
    
    # Check JSON arrays for references
    visited_count = 0
    wishlist_count = 0
    users = User.query.all()
    for user in users:
        if user.visited_resort_ids and resort_id in user.visited_resort_ids:
            visited_count += 1
        if user.wish_list_resorts and resort_id in user.wish_list_resorts:
            wishlist_count += 1
    
    total_refs = trip_count + home_count + visited_count + wishlist_count
    
    if total_refs > 0:
        return jsonify({
            'status': 'error',
            'message': f'Cannot delete: resort has {total_refs} references (trips: {trip_count}, home: {home_count}, visited: {visited_count}, wishlist: {wishlist_count}). Deactivate instead or merge first.'
        }), 400
    
    resort_name = resort.name
    db.session.delete(resort)
    db.session.commit()
    
    return jsonify({'status': 'success', 'message': f'Deleted resort: {resort_name}'})


@app.route("/api/admin/resorts/bulk-delete", methods=["POST"])
@login_required
@admin_required
def admin_bulk_delete_resorts():
    """Bulk delete resorts. Returns partial success if some have FK references."""
    data = request.get_json()
    ids = data.get('ids', [])
    
    if not ids:
        return jsonify({'status': 'error', 'message': 'No resorts selected'}), 400
    
    deleted = []
    blocked = []
    
    for resort_id in ids:
        resort = Resort.query.get(resort_id)
        if not resort:
            blocked.append({'id': resort_id, 'name': 'Unknown', 'reason': 'Not found'})
            continue
        
        # Check FK references
        trip_count = SkiTrip.query.filter_by(resort_id=resort_id).count()
        home_count = User.query.filter_by(home_resort_id=resort_id).count()
        
        visited_count = 0
        wishlist_count = 0
        users = User.query.all()
        for user in users:
            if user.visited_resort_ids and resort_id in user.visited_resort_ids:
                visited_count += 1
            if user.wish_list_resorts and resort_id in user.wish_list_resorts:
                wishlist_count += 1
        
        total_refs = trip_count + home_count + visited_count + wishlist_count
        
        if total_refs > 0:
            blocked.append({
                'id': resort_id,
                'name': resort.name,
                'reason': f'Has {total_refs} references (trips: {trip_count}, home: {home_count}, visited: {visited_count}, wishlist: {wishlist_count})'
            })
        else:
            deleted.append({'id': resort_id, 'name': resort.name})
            db.session.delete(resort)
    
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'deleted': deleted,
        'blocked': blocked
    })


@app.route("/api/admin/resorts/bulk-activate", methods=["POST"])
@login_required
@admin_required
def admin_bulk_activate_resorts():
    """Bulk activate resorts."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid request body'}), 400
        
        resort_ids = data.get('resort_ids', [])
        
        if not resort_ids:
            return jsonify({'status': 'error', 'message': 'No resorts selected'}), 400
        
        updated_count = Resort.query.filter(Resort.id.in_(resort_ids)).update(
            {Resort.is_active: True},
            synchronize_session=False
        )
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'updated_count': updated_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/api/admin/resorts/bulk-deactivate", methods=["POST"])
@login_required
@admin_required
def admin_bulk_deactivate_resorts():
    """Bulk deactivate resorts."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid request body'}), 400
        
        resort_ids = data.get('resort_ids', [])
        
        if not resort_ids:
            return jsonify({'status': 'error', 'message': 'No resorts selected'}), 400
        
        updated_count = Resort.query.filter(Resort.id.in_(resort_ids)).update(
            {Resort.is_active: False},
            synchronize_session=False
        )
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'updated_count': updated_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/api/admin/resorts/merge", methods=["POST"])
@login_required
@admin_required
def admin_merge_resorts():
    """
    Merge duplicate resorts into a canonical resort.
    Repoints all FK references atomically, then marks non-canonical resorts as inactive.
    """
    data = request.get_json()
    canonical_id = data.get('canonical_id')
    duplicate_ids = data.get('duplicate_ids', [])
    
    if not canonical_id or not duplicate_ids:
        return jsonify({'status': 'error', 'message': 'Missing canonical_id or duplicate_ids'}), 400
    
    if canonical_id in duplicate_ids:
        return jsonify({'status': 'error', 'message': 'Canonical resort cannot be in duplicate list'}), 400
    
    canonical = Resort.query.get(canonical_id)
    if not canonical:
        return jsonify({'status': 'error', 'message': 'Canonical resort not found'}), 404
    
    duplicates = Resort.query.filter(Resort.id.in_(duplicate_ids)).all()
    if len(duplicates) != len(duplicate_ids):
        return jsonify({'status': 'error', 'message': 'Some duplicate resorts not found'}), 404
    
    try:
        stats = {
            'trips_updated': 0,
            'home_resorts_updated': 0,
            'visited_lists_updated': 0,
            'wishlist_updated': 0,
            'resorts_deactivated': 0
        }
        
        for dup in duplicates:
            dup_id = dup.id
            
            # 1. Update SkiTrip.resort_id
            trips_updated = SkiTrip.query.filter_by(resort_id=dup_id).update({'resort_id': canonical_id})
            stats['trips_updated'] += trips_updated
            
            # 2. Update User.home_resort_id
            home_updated = User.query.filter_by(home_resort_id=dup_id).update({'home_resort_id': canonical_id})
            stats['home_resorts_updated'] += home_updated
            
            # 3. Update User.visited_resort_ids (JSON array)
            # Must use flag_modified to ensure SQLAlchemy detects JSON changes
            from sqlalchemy.orm.attributes import flag_modified
            users_with_visited = User.query.filter(User.visited_resort_ids.isnot(None)).all()
            for user in users_with_visited:
                if user.visited_resort_ids and dup_id in user.visited_resort_ids:
                    new_list = list(user.visited_resort_ids)  # Copy to new list
                    new_list = [rid for rid in new_list if rid != dup_id]
                    if canonical_id not in new_list:
                        new_list.append(canonical_id)
                    user.visited_resort_ids = new_list
                    flag_modified(user, 'visited_resort_ids')
                    stats['visited_lists_updated'] += 1
            
            # 4. Update User.wish_list_resorts (JSON array)
            users_with_wishlist = User.query.filter(User.wish_list_resorts.isnot(None)).all()
            for user in users_with_wishlist:
                if user.wish_list_resorts and dup_id in user.wish_list_resorts:
                    new_list = list(user.wish_list_resorts)  # Copy to new list
                    new_list = [rid for rid in new_list if rid != dup_id]
                    if canonical_id not in new_list:
                        new_list.append(canonical_id)
                    user.wish_list_resorts = new_list
                    flag_modified(user, 'wish_list_resorts')
                    stats['wishlist_updated'] += 1
            
            # 5. Mark duplicate as inactive
            dup.is_active = False
            stats['resorts_deactivated'] += 1
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'canonical_resort': canonical.name,
            'stats': stats
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/api/admin/resorts/add", methods=["POST"])
@login_required
@admin_required
def admin_add_resort():
    """
    Add a new resort via free-form entry.
    No tier logic, no canonical writes, no auto-merge.
    """
    import re
    
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400
    
    name = (data.get('name') or '').strip()
    country_code = (data.get('country_code') or '').strip().upper()
    state_code = (data.get('state_code') or '').strip() or None
    pass_brands_input = data.get('pass_brands')
    
    # Handle pass_brands as array or comma-separated string
    if isinstance(pass_brands_input, list):
        pass_brands_list = pass_brands_input
    elif isinstance(pass_brands_input, str):
        pass_brands_list = [p.strip() for p in pass_brands_input.split(',') if p.strip()]
    else:
        pass_brands_list = []
    
    # Handle "None" semantics - mutually exclusive with all other passes
    if 'None' in pass_brands_list:
        pass_brands_list = ['None']  # Preserve as explicit marker, not empty list
    
    errors = []
    if not name:
        errors.append('Resort name is required')
    elif len(name) < 2:
        errors.append('Name must be at least 2 characters')
    
    if not country_code:
        errors.append('Please select a country')
    elif len(country_code) != 2:
        errors.append('Invalid country code')
    
    if errors:
        return jsonify({'status': 'error', 'message': '; '.join(errors)}), 400
    
    normalized_name = name.lower()
    existing = Resort.query.filter(
        db.func.lower(Resort.name) == normalized_name,
        db.func.upper(Resort.country_code) == country_code
    ).first()
    
    if existing:
        return jsonify({
            'status': 'error',
            'message': f'Resort "{name}" already exists in {country_code} (ID: {existing.id})'
        }), 409
    
    slug_base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    slug = f"{slug_base}-{country_code.lower()}"
    
    slug_exists = Resort.query.filter_by(slug=slug).first()
    if slug_exists:
        slug = f"{slug}-{int(datetime.utcnow().timestamp())}"
    
    new_resort = Resort(
        name=name,
        country=country_code,
        country_code=country_code,
        country_name=COUNTRIES.get(country_code, country_code),
        state=state_code,
        state_code=state_code,
        state_name=state_code,
        state_full=state_code,
        brand=None,
        pass_brands_json=pass_brands_list,
        slug=slug,
        is_active=True,
        is_region=False
    )
    
    try:
        db.session.add(new_resort)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': f'Resort "{name}" added successfully',
            'resort': {
                'id': new_resort.id,
                'name': new_resort.name,
                'country_code': new_resort.country_code,
                'state_code': new_resort.state_code,
                'pass_brands': new_resort.get_pass_brands_list(),
                'pass_brands_json': new_resort.pass_brands_json,
                'slug': new_resort.slug
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/api/admin/resorts/export-canonical", methods=["POST"])
@login_required
@admin_required
def admin_export_canonical():
    """
    Export active resorts to canonical_resorts.json.
    This is the source of truth for PROD sync.
    """
    import os
    import json
    from datetime import datetime
    
    # Get all active resorts
    resorts = Resort.query.filter_by(is_active=True).order_by(Resort.country_code, Resort.state_code, Resort.name).all()
    
    canonical_data = {
        'version': datetime.utcnow().strftime('%Y%m%d_%H%M%S'),
        'exported_at': datetime.utcnow().isoformat() + 'Z',
        'exported_by': current_user.email,
        'total_count': len(resorts),
        'resorts': []
    }
    
    for r in resorts:
        canonical_data['resorts'].append({
            'name': r.name,
            'state_code': r.state_code or r.state,
            'country_code': r.country_code,
            'country_name': r.country_name,
            'pass_brands': r.pass_brands or r.brand or ''
        })
    
    canonical_file = os.path.join(os.path.dirname(__file__), 'data', 'canonical_resorts.json')
    
    try:
        with open(canonical_file, 'w') as f:
            json.dump(canonical_data, f, indent=2)
        
        return jsonify({
            'status': 'success',
            'version': canonical_data['version'],
            'exported_at': canonical_data['exported_at'],
            'count': len(resorts),
            'message': f'Exported {len(resorts)} resorts to canonical_resorts.json'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route("/admin/sync-from-canonical", methods=["GET", "POST"])
@login_required
@admin_required
def admin_sync_from_canonical():
    """
    Sync resorts from canonical_resorts.json into the database.
    Used in production after deploying updated JSON.
    """
    import os
    import json
    
    canonical_file = os.path.join(os.path.dirname(__file__), 'data', 'canonical_resorts.json')
    
    if not os.path.exists(canonical_file):
        if request.method == 'POST':
            return jsonify({'status': 'error', 'message': 'canonical_resorts.json not found'}), 404
        return "No canonical_resorts.json found", 404
    
    with open(canonical_file, 'r') as f:
        canonical_data = json.load(f)
    
    if request.method == 'GET':
        current_count = Resort.query.filter_by(is_active=True).count()
        return f'''
        <html>
        <head><title>Sync Resorts</title>
        <style>
            body {{ font-family: system-ui; padding: 40px; max-width: 600px; margin: 0 auto; }}
            .info {{ background: #f0f0f0; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
            button {{ background: #8F011B; color: white; padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; }}
            button:hover {{ background: #7a0117; }}
            .warning {{ color: #856404; background: #fff3cd; padding: 15px; border-radius: 6px; margin-bottom: 20px; }}
        </style>
        </head>
        <body>
            <h1>Sync Resorts from Canonical JSON</h1>
            <div class="info">
                <p><strong>JSON Version:</strong> {canonical_data.get('version', 'unknown')}</p>
                <p><strong>Exported:</strong> {canonical_data.get('exported_at', 'unknown')}</p>
                <p><strong>Resorts in JSON:</strong> {canonical_data.get('total_count', len(canonical_data.get('resorts', [])))}</p>
                <p><strong>Current DB Count:</strong> {current_count}</p>
            </div>
            <div class="warning">
                This will update/insert resorts from the canonical JSON. Existing resorts not in the JSON will be deactivated.
            </div>
            <form method="POST">
                <button type="submit">Sync Now</button>
            </form>
        </body>
        </html>
        '''
    
    # POST - do the sync
    try:
        stats = {'added': 0, 'updated': 0, 'deactivated': 0}
        
        canonical_keys = set()
        
        # Build a lookup of existing resorts by normalized key
        all_existing = Resort.query.all()
        existing_by_key = {}
        for r in all_existing:
            key = f"{r.name}|{r.state_code or r.state or ''}|{r.country_code or r.country or 'US'}".lower()
            existing_by_key[key] = r
        
        for r_data in canonical_data.get('resorts', []):
            name = (r_data.get('name') or '').strip()
            state_code = (r_data.get('state_code') or '').strip()
            country_code = (r_data.get('country_code') or 'US').strip()
            country_name = (r_data.get('country_name') or '').strip()
            pass_brands = (r_data.get('pass_brands') or '').strip()
            is_region = r_data.get('is_region', False)

            # Derive state_name from STATE_ABBR_MAP for US/CA codes, else use as-is
            state_name = STATE_ABBR_MAP.get(state_code.upper()) if state_code else None
            if not state_name and state_code:
                state_name = state_code

            # Derive pass_brands_json from comma-separated string
            if pass_brands and pass_brands != 'None':
                pass_brands_json = [p.strip() for p in pass_brands.split(',') if p.strip()]
            else:
                pass_brands_json = ['None']
            brand = pass_brands_json[0] if pass_brands_json else 'Other'

            canonical_key = f"{name}|{state_code}|{country_code}".lower()
            canonical_keys.add(canonical_key)
            
            existing = existing_by_key.get(canonical_key)
            
            if existing:
                existing.name = name
                existing.state_code = state_code
                existing.state = state_code
                existing.state_name = state_name
                existing.country_code = country_code
                existing.country = country_code
                existing.country_name = country_name
                existing.pass_brands = pass_brands
                existing.pass_brands_json = pass_brands_json
                existing.brand = brand
                existing.is_active = True
                existing.is_region = is_region
                stats['updated'] += 1
            else:
                import re
                base_slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
                base_slug = f"{base_slug}-{state_code.lower()}" if state_code else base_slug
                slug = base_slug
                counter = 1
                while Resort.query.filter_by(slug=slug).first():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                new_resort = Resort(
                    name=name,
                    state=state_code,
                    state_code=state_code,
                    state_name=state_name,
                    country=country_code,
                    country_code=country_code,
                    country_name=country_name,
                    pass_brands=pass_brands,
                    pass_brands_json=pass_brands_json,
                    brand=brand,
                    slug=slug,
                    is_active=True,
                    is_region=is_region
                )
                db.session.add(new_resort)
                stats['added'] += 1
        
        # Deactivate resorts not in canonical
        for key, resort in existing_by_key.items():
            if key not in canonical_keys and resort.is_active:
                resort.is_active = False
                stats['deactivated'] += 1
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'version': canonical_data.get('version'),
            'stats': stats,
            'message': f"Sync complete: {stats['added']} added, {stats['updated']} updated, {stats['deactivated']} deactivated"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# TEMP DEBUG ROUTE — safe to remove after use
@app.route("/admin/debug-resort-duplicates", methods=["GET"])
@login_required
@admin_required
def debug_resort_duplicates():
    """Temporary route to detect duplicate resorts by (name, state_code, country_code)."""
    from sqlalchemy import func

    rows = (
        db.session.query(
            Resort.name,
            Resort.state_code,
            Resort.country_code,
            func.count(Resort.id).label("cnt")
        )
        .group_by(Resort.name, Resort.state_code, Resort.country_code)
        .having(func.count(Resort.id) > 1)
        .order_by(func.count(Resort.id).desc())
        .all()
    )

    if not rows:
        return jsonify({"status": "ok", "duplicates": []})

    return jsonify([
        {
            "name": row.name,
            "state_code": row.state_code,
            "country_code": row.country_code,
            "count": row.cnt
        }
        for row in rows
    ])


@app.route("/admin/resorts/duplicates", methods=["GET"])
@login_required
@admin_required
def admin_resorts_duplicates():
    """Find duplicate resorts grouped by normalized (name, state_code, country_code)."""
    try:
        norm_name = func.lower(func.trim(Resort.name))
        norm_state = func.upper(func.trim(Resort.state_code))
        norm_country = func.upper(func.trim(func.coalesce(Resort.country_code, 'US')))

        groups = (
            db.session.query(
                func.lower(func.trim(Resort.name)).label("norm_name"),
                func.upper(func.trim(Resort.state_code)).label("norm_state"),
                func.upper(func.trim(func.coalesce(Resort.country_code, 'US'))).label("norm_country"),
                func.count(Resort.id).label("cnt")
            )
            .group_by(
                func.lower(func.trim(Resort.name)),
                func.upper(func.trim(Resort.state_code)),
                func.upper(func.trim(func.coalesce(Resort.country_code, 'US')))
            )
            .having(func.count(Resort.id) > 1)
            .order_by(func.count(Resort.id).desc())
            .all()
        )

        result_groups = []
        total_duplicate_rows = 0

        for g in groups:
            matches = Resort.query.filter(
                func.lower(func.trim(Resort.name)) == g.norm_name,
                func.upper(func.trim(Resort.state_code)) == g.norm_state,
                func.upper(func.trim(func.coalesce(Resort.country_code, 'US'))) == g.norm_country
            ).all()

            total_duplicate_rows += len(matches)
            result_groups.append({
                "name": g.norm_name,
                "state_code": g.norm_state,
                "country_code": g.norm_country,
                "count": g.cnt,
                "resorts": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "state_code": r.state_code,
                        "country_code": r.country_code,
                        "slug": r.slug,
                        "is_active": r.is_active
                    }
                    for r in matches
                ]
            })

        return jsonify({
            "status": "success",
            "duplicate_group_count": len(result_groups),
            "total_duplicate_rows": total_duplicate_rows,
            "groups": result_groups
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
