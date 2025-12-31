import os
import secrets
from datetime import datetime, date, timedelta
import sqlalchemy as sa
from sqlalchemy import func
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation, InviteToken, Resort, GroupTrip, TripGuest, GuestStatus, check_shared_upcoming_trip, EquipmentSetup, EquipmentSlot, EquipmentDiscipline, AccommodationStatus, TransportationStatus, DismissedNudge, Event, SkiTripParticipant, ParticipantRole, ParticipantTransportation, ParticipantEquipment, Activity, ActivityType
from debug_routes import debug_bp
from services.open_dates import get_open_date_matches
from io import BytesIO
import segno
import random
import click
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# ============================================================================
# PROFILE CONSOLIDATION NOTE:
# The app no longer uses /profile or profile.html.
# All profile-related UI lives under /more.
# Do NOT reintroduce profile routes or templates.
# ============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Session configuration for Replit iframe environment
# In production, Replit proxies through HTTPS even if backend is HTTP
is_production = os.environ.get("DATABASE_URL") is not None and "postgresql" in os.environ.get("DATABASE_URL", "")
app.config['SESSION_COOKIE_SECURE'] = is_production  # HTTPS in production, HTTP in dev
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Works with HTTP/HTTPS and allows iframe context
app.config['SESSION_COOKIE_DOMAIN'] = None  # Let the browser handle domain
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Refresh session on each request

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth"
login_manager.login_message = None

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ============================================================================
# CENTRALIZED IDENTITY FORMATTER
# Single source of truth for user identity display across all templates.
# Format: Rider Type · Passes · Skill Level
# Never shows "Both" - all passes listed individually.
# ============================================================================

@app.route("/")
def root():
    import sys
    print("=== ROOT REDIRECT DIAGNOSTIC ===", file=sys.stderr)
    print(f"current_user.is_authenticated: {current_user.is_authenticated}", file=sys.stderr)
    print(f"session contents: {dict(session)}", file=sys.stderr)
    print(f"cookies: {dict(request.cookies)}", file=sys.stderr)
    print("================================", file=sys.stderr)
    return redirect(url_for("auth"))

@app.template_filter('identity_line')
def identity_line_filter(user):
    """
    Centralized identity formatter for user profile display.
    Format: Rider Type · Passes · Skill Level
    - Rider types: First rider type only (e.g., "Skier")
    - Passes: Up to 2 passes joined with " + " as single segment (e.g., "Epic + Ikon")
    - Skill level: Last if present
    - If no passes, omit pass segment entirely
    """
    try:
        if not user:
            return ''
        
        parts = []
        
        # Rider type (first type only for hero line brevity)
        rider_types = getattr(user, 'rider_types', None)
        if rider_types and len(rider_types) > 0:
            parts.append(rider_types[0])
        else:
            # Legacy fallback
            primary = getattr(user, 'primary_rider_type', None) or getattr(user, 'rider_type', None)
            if primary:
                parts.append(primary)
        
        # Passes (up to 2, joined with " + " as single segment)
        passes = []
        pass_type = getattr(user, 'pass_type', None)
        if pass_type:
            pass_str = pass_type.strip()
            if ',' in pass_str:
                passes = [p.strip() for p in pass_str.split(',') if p.strip() and p.strip().lower() not in ('both', 'no pass')]
            else:
                passes = [pass_str] if pass_str.lower() not in ('both', 'no pass') else []
        # Limit to 2 passes, preserve stored order
        passes = passes[:2]
        if passes:
            parts.append(' + '.join(passes))
        
        # Skill level (last)
        skill_level = getattr(user, 'skill_level', None)
        if skill_level:
            parts.append(skill_level)
        
        return ' · '.join(parts) if parts else ''
    except Exception:
        return ''

@app.template_filter('pass_display')
def pass_display_filter(pass_type):
    """
    Displays passes individually, never showing "Both".
    Use for standalone pass display in stats cards and settings.
    """
    if not pass_type:
        return ''
    pass_str = pass_type.strip()
    if ',' in pass_str:
        passes = [p.strip() for p in pass_str.split(',') if p.strip() and p.strip().lower() != 'both']
        return ' · '.join(passes) if passes else ''
    return pass_str if pass_str.lower() != 'both' else ''


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
    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24
    
    if seconds < 60:
        return 'Just now'
    elif minutes < 60:
        m = int(minutes)
        return f'{m}m ago'
    elif hours < 24:
        h = int(hours)
        return f'{h}h ago'
    elif days < 2:
        return 'Yesterday'
    elif days < 7:
        d = int(days)
        return f'{d}d ago'
    else:
        return dt.strftime('%b %d')


@app.before_request
def before_request_handlers():
    import sys
    
    # Make sessions permanent for Replit iframe compatibility
    session.permanent = True
    
    # DIAGNOSTIC: before_request
    if request.endpoint and request.endpoint not in ['static']:
        print("=== BEFORE_REQUEST ===", file=sys.stderr)
        print("endpoint:", request.endpoint, file=sys.stderr)
        print("current_user.is_authenticated:", current_user.is_authenticated, file=sys.stderr)
        print("session:", dict(session), file=sys.stderr)
        print("cookies:", dict(request.cookies), file=sys.stderr)
        print("=====================", file=sys.stderr)
    
    # Require profile setup for authenticated users
    excluded_endpoints = {'auth', 'identity_setup', 'setup_profile', 'logout', 'static', 'invite_token_landing', 'test_login_direct', 'forgot_password', 'reset_password'}
    if request.endpoint in excluded_endpoints:
        return None
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


app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///baselodge.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)
app.register_blueprint(debug_bp)

# ============================================================================
# PRODUCTION DIAGNOSTICS - Print on startup
# ============================================================================
def log_startup_diagnostics():
    """Log database and user counts on startup for debugging."""
    try:
        with app.app_context():
            db_url = os.environ.get("DATABASE_URL", "NOT SET")
            
            # Mask credentials
            if db_url and db_url != "NOT SET" and "@" in db_url:
                safe_db = db_url.split("@")[-1]
            else:
                safe_db = "SQLite (baselodge.db)"
            
            print("=" * 70)
            print("🔧 BASELODGE STARTUP DIAGNOSTICS")
            print("=" * 70)
            print(f"DATABASE: {safe_db}")
            print(f"PRODUCTION MODE: {is_production}")
            
            # Count records
            user_count = User.query.count()
            friend_count = Friend.query.count()
            trip_count = SkiTrip.query.count()
            
            print(f"USER COUNT: {user_count}")
            print(f"FRIEND COUNT: {friend_count}")
            print(f"TRIP COUNT: {trip_count}")
            
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
# ERROR HANDLER - Full stack trace for debugging
# ============================================================================
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found errors with user-friendly template."""
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors with full traceback logging."""
    import traceback
    print("=" * 70)
    print("🚨 INTERNAL SERVER ERROR (500)")
    print("=" * 70)
    print(f"Error: {error}")
    print("Full traceback:")
    traceback.print_exc()
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
    print("=" * 70)
    print(f"🚨 UNHANDLED EXCEPTION: {type(e).__name__}")
    print("=" * 70)
    print(f"Message: {str(e)}")
    print("Full traceback:")
    traceback.print_exc()
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
    Frontend JS derives all geography from this single list.
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

RIDER_TYPES = ["Skier", "Snowboarder", "Telemark", "Cross-Country", "Adaptive"]

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
                # Production base URL
                BASE_URL = "https://base-lodge-app--rbattleb.replit.app"
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
                return render_template("auth.html")
            
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return render_template("auth.html")
            
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("An account with this email already exists.", "error")
                return render_template("auth.html")
            
            new_user = User(
                first_name=first_name,
                last_name=last_name,
                email=email
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.commit()
            
            login_user(new_user, remember=True)
            session.modified = True
            
            return redirect(url_for("identity_setup"))
        
        elif form_type == "login":
            email = request.form.get("email", "").lower().strip()
            password = request.form.get("password", "")
            
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user, remember=True)
                session.modified = True
                db.session.commit()
                return redirect("/my-trips")
            
            flash("Invalid email or password.", "error")

    return render_template("auth.html")


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
        pass_types = request.form.getlist("pass_types")
        
        # Validate required fields
        if not rider_types:
            flash("Please select at least one rider type.", "error")
            return render_template("identity_setup.html")
        
        if not skill_level:
            flash("Please select your skill level.", "error")
            return render_template("identity_setup.html")
        
        if not pass_types:
            flash("Please select at least one pass option.", "error")
            return render_template("identity_setup.html")
        
        # Save identity data
        current_user.rider_types = rider_types
        current_user.skill_level = skill_level
        # Store pass_type as comma-separated for backward compatibility, or first pass if single
        if len(pass_types) == 1:
            current_user.pass_type = pass_types[0]
        else:
            current_user.pass_type = ", ".join(pass_types)
        
        db.session.commit()
        
        # Redirect to location setup (step 2 of onboarding)
        return redirect(url_for("location_setup"))
    
    return render_template("identity_setup.html")


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
    if not invite or invite.is_expired():
        session.pop("invite_token", None)
        return False

    inviter = User.query.get(invite.inviter_id)
    connected = False
    if inviter and inviter.id != user.id:
        existing = Friend.query.filter_by(user_id=user.id, friend_id=inviter.id).first()
        if not existing:
            f1 = Friend(user_id=user.id, friend_id=inviter.id)
            f2 = Friend(user_id=inviter.id, friend_id=user.id)
            db.session.add_all([f1, f2])
            user.invited_by_user_id = inviter.id
            db.session.commit()
            connected = True
            app.logger.info(f"Connected {user.id} with inviter {inviter.id} via token {invite_token_str}")
    
    session.pop("invite_token", None)
    return connected


@app.route("/invite/<token>")
def invite_token_landing(token):
    """Time-limited invite landing page."""
    invite = InviteToken.query.filter_by(token=token).first()
    
    if not invite or invite.is_expired():
        return render_template("invite_expired.html")
        
    # Store token in session for post-auth connection
    session["invite_token"] = token
    
    # Get inviter for landing page display
    inviter = User.query.get(invite.inviter_id)
    inviter_trips_count = SkiTrip.query.filter_by(user_id=inviter.id).count()
    
    return render_template("invite_landing.html", 
                           inviter=inviter, 
                           inviter_trips_count=inviter_trips_count)


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

@app.route("/profile")
def deprecated_profile():
    """Defensive redirect: /profile no longer exists, redirect to /more."""
    return redirect(url_for("more"))

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
        user.skill_level = request.form.get("skill_level") or None
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
                    my_mountain = my.mountain if my.mountain else (my.resort.name if my.resort else None)
                    friend_mountain = friend_trip.mountain if friend_trip.mountain else (friend_trip.resort.name if friend_trip.resort else None)
                    if my_mountain and friend_mountain and my_mountain == friend_mountain:
                        if my.start_date and my.end_date and friend_trip.start_date and friend_trip.end_date:
                            if date_ranges_overlap(my.start_date, my.end_date, friend_trip.start_date, friend_trip.end_date):
                                resort = my.resort or friend_trip.resort
                                friend_first_name = friend_trip.user.first_name if friend_trip.user else "Friend"
                                overlaps.append({
                                    "my_trip_id": my.id,
                                    "friend_name": friend_first_name,
                                    "friend_first_name": friend_first_name,
                                    "friend_id": friend_trip.user_id,
                                    "mountain": resort.name if resort else my_mountain,
                                    "state": resort.state if resort else (my.state or ""),
                                    "brand": resort.brand if resort else None,
                                    "resort_id": resort.id if resort else None,
                                    "start_date": max(my.start_date, friend_trip.start_date),
                                    "end_date": min(my.end_date, friend_trip.end_date)
                                })
    except Exception:
        overlaps = []

    # Open dates from JSON field (wrapped for production safety)
    user_open_dates = []
    try:
        my_open_dates = set(user.open_dates or [])
        my_open_dates = {d for d in my_open_dates if d >= today.strftime('%Y-%m-%d')}
        user_open_dates = sorted(my_open_dates) if my_open_dates else []
    except Exception:
        my_open_dates = set()
        user_open_dates = []

    # Build open date matches (wrapped for production safety)
    open_date_matches = []
    try:
        if my_open_dates and friend_ids:
            friends_with_open = User.query.filter(User.id.in_(friend_ids)).all()
            for date_str in sorted(my_open_dates):
                matching_friends = []
                for friend in friends_with_open:
                    friend_dates = set(friend.open_dates or [])
                    if date_str in friend_dates:
                        matching_friends.append({
                            "name": friend.first_name or "Friend",
                            "id": friend.id,
                            "pass_type": friend.pass_type or "",
                            "skill_level": friend.skill_level or ""
                        })
                if matching_friends:
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                        open_date_matches.append({
                            "date_str": date_str,
                            "date_obj": date_obj,
                            "day_name": date_obj.strftime('%A'),
                            "display_date": date_obj.strftime('%b %d'),
                            "friends": matching_friends
                        })
                    except ValueError:
                        pass
    except Exception:
        open_date_matches = []

    # Format user's open dates for display
    try:
        user_open_dates_display = format_open_dates_summary(user_open_dates) if user_open_dates else None
    except Exception:
        user_open_dates_display = None

    # Get equipment for profile card (wrapped for production safety)
    try:
        primary_equipment = EquipmentSetup.query.filter_by(
            user_id=current_user.id,
            slot=EquipmentSlot.PRIMARY
        ).first()
    except Exception:
        primary_equipment = None

    try:
        secondary_equipment = EquipmentSetup.query.filter_by(
            user_id=current_user.id,
            slot=EquipmentSlot.SECONDARY
        ).first()
    except Exception:
        secondary_equipment = None

    # Get Resort objects for profile card (wrapped for production safety)
    try:
        visited_resorts = current_user.get_visited_resorts()
    except Exception:
        visited_resorts = []

    try:
        wishlist_resorts = current_user.get_wishlist_resorts()
    except Exception:
        wishlist_resorts = []

    return render_template(
        "my_trips.html",
        user=user,
        upcoming_trips=upcoming_trips or [],
        past_trips=past_trips or [],
        active_tab=active_tab,
        show_connected_banner=show_connected_banner,
        friends=friends or [],
        friend_trips=friend_trips or [],
        overlaps=overlaps or [],
        open_date_matches=open_date_matches or [],
        user_open_dates=user_open_dates or [],
        user_open_dates_display=user_open_dates_display,
        primary_equipment=primary_equipment,
        secondary_equipment=secondary_equipment,
        visited_resorts=visited_resorts or [],
        wishlist_resorts=wishlist_resorts or []
    )

@app.route("/api/mountains/<state>")
def get_mountains(state):
    state_code = state.upper()
    mountains = MOUNTAINS_BY_STATE.get(state_code, [])
    return jsonify(mountains)

@app.route("/api/trip/create", methods=["POST"])
@login_required
def create_trip():
    user = current_user
    
    data = request.get_json()
    state = data.get("state")
    mountain = data.get("mountain")
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    pass_type = data.get("pass_type", user.pass_type or "No Pass")
    is_public = data.get("is_public", True)
    
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
        state=state,
        mountain=mountain,
        start_date=start_date,
        end_date=end_date,
        pass_type=pass_type,
        is_public=is_public,
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
    
    # Get tab parameter (updates or friends)
    active_tab = request.args.get("tab", "updates")
    filter_type = request.args.get("filter", "All")
    
    # Load friend relationships
    friend_links = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friend_links]
    all_friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    
    # Load activities for Updates tab
    activities = []
    if active_tab == "updates":
        activities = Activity.query.filter(
            Activity.recipient_user_id == user.id,
            Activity.actor_user_id.in_(friend_ids) if friend_ids else False
        ).order_by(Activity.created_at.desc()).limit(50).all()
    
    # Get user's upcoming trips for overlap detection
    user_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.end_date >= today
    ).all()
    today_str = today.strftime('%Y-%m-%d')
    user_open_dates = set(d for d in (user.open_dates or []) if d >= today_str)
    user_passes = set(p.strip() for p in (user.pass_type or "").split(",") if p.strip())
    
    # Calculate relevance score for each friend
    def calculate_relevance(friend):
        score = 0
        
        # 1. Trip overlap (highest priority) - only count future trips
        friend_trips = SkiTrip.query.filter(
            SkiTrip.user_id == friend.id,
            SkiTrip.is_public == True,
            SkiTrip.end_date >= today
        ).all()
        for ut in user_trips:
            for ft in friend_trips:
                if ut.mountain == ft.mountain and date_ranges_overlap(ut.start_date, ut.end_date, ft.start_date, ft.end_date):
                    score += 100
        
        # 2. Pass compatibility
        friend_passes = set(p.strip() for p in (friend.pass_type or "").split(",") if p.strip())
        if user_passes & friend_passes:
            score += 50
        
        # 3. Shared availability - only count future dates
        friend_open_dates = set(d for d in (friend.open_dates or []) if d >= today_str)
        shared_dates = user_open_dates & friend_open_dates
        score += len(shared_dates) * 10
        
        return score
    
    # Default sort: same-state friends first, then alphabetical by name
    user_home_state = user.home_state
    same_state_friends = [f for f in all_friends if f.home_state == user_home_state]
    other_state_friends = [f for f in all_friends if f.home_state != user_home_state]
    
    same_state_friends.sort(key=lambda f: f.first_name.lower())
    other_state_friends.sort(key=lambda f: f.first_name.lower())
    
    all_friends_sorted = same_state_friends + other_state_friends
    
    # Build a lookup for friendship data (including trip_invites_allowed)
    friendship_lookup = {f.friend_id: f for f in friend_links}
    
    # Calculate upcoming trip count for each friend and attach friendship data
    for friend in all_friends_sorted:
        upcoming_count = SkiTrip.query.filter(
            SkiTrip.user_id == friend.id,
            SkiTrip.is_public == True,
            SkiTrip.end_date >= today
        ).count()
        friend._upcoming_trip_count = upcoming_count
        # Attach friendship permission
        friendship = friendship_lookup.get(friend.id)
        friend._trip_invites_allowed = friendship.trip_invites_allowed if friendship else False
    
    # Get multi-select filter params
    selected_riders = request.args.getlist("rider")
    selected_skills = request.args.getlist("skill")
    selected_passes = request.args.getlist("pass")
    
    # Apply optional filters
    friends_list = all_friends_sorted
    active_filter_count = 0
    
    # Pass filtering (using pass_category helper)
    if selected_passes and len(selected_passes) < 3:  # Less than all options
        friends_list = [f for f in friends_list if pass_category(f.pass_type) in selected_passes]
        active_filter_count += 1
    
    # Skill filtering
    if selected_skills and len(selected_skills) < 4:  # Less than all skill levels
        friends_list = [f for f in friends_list if f.skill_level in selected_skills]
        active_filter_count += 1
    
    # Rider type filtering using primary_rider_type with fallback
    if selected_riders and len(selected_riders) < len(RIDER_TYPES):
        def matches_rider_filter(friend):
            primary = friend.primary_rider_type or friend.rider_type
            if not primary:
                return False
            # Check primary type
            if primary in selected_riders:
                return True
            # Check secondary types
            secondaries = friend.secondary_rider_types or []
            for secondary in secondaries:
                if secondary in selected_riders:
                    return True
            return False
        friends_list = [f for f in friends_list if matches_rider_filter(f)]
        active_filter_count += 1
    
    return render_template(
        "friends.html",
        user=user,
        friends=friends_list,
        count_all=len(all_friends_sorted),
        active_filter_count=active_filter_count,
        selected_riders=selected_riders,
        selected_skills=selected_skills,
        selected_passes=selected_passes,
        rider_types=RIDER_TYPES,
        active_tab=active_tab,
        activities=activities
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
            if trip.mountain == user_trip.mountain:
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
        overlap_context=overlap_context
    )

@app.route("/profile/<int:user_id>")
@login_required
def friend_profile_legacy(user_id):
    
    # Check if viewing own profile
    if user_id == current_user.id:
        return redirect(url_for("more"))
    
    friend_user = User.query.get_or_404(user_id)
    
    # Verify friendship
    friendship = Friend.query.filter_by(user_id=current_user.id, friend_id=user_id).first()
    if not friendship:
        flash("You can only view profiles of your friends.", "error")
        return redirect(url_for("friends"))
    
    today = date.today()
    upcoming_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user_id,
        SkiTrip.start_date >= today,
        SkiTrip.is_public == True
    ).order_by(SkiTrip.start_date.asc()).all()
    
    past_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user_id,
        SkiTrip.start_date < today,
        SkiTrip.is_public == True
    ).order_by(SkiTrip.start_date.desc()).all()
    
    return render_template("friend_profile.html", user=current_user, friend=friend_user, upcoming_trips=upcoming_trips, past_trips=past_trips, state_abbr=STATE_ABBR)

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
    user = current_user
    
    # Get pre-filled parameters from "Propose a trip" flow
    prefill_friend_id = request.args.get('friend_id', type=int)
    prefill_start_date = request.args.get('start_date')
    prefill_end_date = request.args.get('end_date')
    is_group = request.args.get('is_group') == '1'
    
    prefill_friend = None
    if prefill_friend_id:
        prefill_friend = User.query.get(prefill_friend_id)
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    return render_template(
        "create_trip.html", 
        user=user, 
        states=states, 
        mountains_by_state=MOUNTAINS_BY_STATE, 
        pass_options=PASS_OPTIONS,
        prefill_start_date=prefill_start_date,
        prefill_end_date=prefill_end_date,
        prefill_friend=prefill_friend,
        is_group=is_group
    )

@app.route("/invite")
@login_required
def invite():
    # Check if user has reached their invite accept limit
    if not can_sender_accept_more_invites(current_user):
        return render_template("invite_limit_reached.html", user=current_user)
    
    invite_token = get_or_create_invite_token(current_user)
    invite_url = url_for("invite_token_landing", token=invite_token.token, _external=True)
    
    return render_template("invite.html", user=current_user, invite_url=invite_url, remaining_invites=None)

@app.route("/my-qr")
@login_required
def my_qr():
    invite_token = get_or_create_invite_token(current_user)
    if not invite_token:
        return render_template("invite_limit_reached.html", user=current_user)
    qr_url = url_for("invite_token_landing", token=invite_token.token, _external=True)
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
    return redirect("/my-trips")
    
    # My upcoming trips (owned + accepted participations)
    my_trips = SkiTrip.query.filter(
        db.or_(
            SkiTrip.user_id == user.id,
            SkiTrip.id.in_(accepted_participation_trip_ids)
        ),
        SkiTrip.start_date >= today
    ).order_by(SkiTrip.start_date.asc()).all()
    
    # Friends' upcoming trips
    friends = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friends]
    
    friend_trips = []
    if friend_ids:
        friend_trips = SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.start_date >= today,
            SkiTrip.is_public == True
        ).order_by(SkiTrip.start_date.asc()).all()
    
    # Build overlaps list
    overlaps = []
    for my in my_trips:
        for friend_trip in friend_trips:
            if my.user_id != friend_trip.user_id:
                if my.mountain == friend_trip.mountain:
                    if date_ranges_overlap(my.start_date, my.end_date, friend_trip.start_date, friend_trip.end_date):
                        # Get resort info from my trip (or friend's trip if mine doesn't have it)
                        resort = my.resort or friend_trip.resort
                        friend_full_name = friend_trip.user.first_name
                        if friend_trip.user.last_name:
                            friend_full_name += " " + friend_trip.user.last_name
                        overlaps.append({
                            "my_trip_id": my.id,
                            "friend_name": friend_full_name,
                            "friend_first_name": friend_trip.user.first_name,
                            "friend_id": friend_trip.user_id,
                            "mountain": resort.name if resort else my.mountain,
                            "state": resort.state if resort else my.state,
                            "brand": resort.brand if resort else None,
                            "resort_id": resort.id if resort else None,
                            "start_date": max(my.start_date, friend_trip.start_date),
                            "end_date": min(my.end_date, friend_trip.end_date)
                        })
    
    # Calculate friends who can ski at each of user's trips (pass compatibility)
    friends_data = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    for trip in my_trips:
        trip.friends_can_ski = 0
        if trip.resort:
            # Use pass_brands if available, fallback to brand
            resort_pass_str = trip.resort.pass_brands or trip.resort.brand
            if resort_pass_str:
                resort_passes = set(p.strip() for p in resort_pass_str.split(','))
                for friend in friends_data:
                    if friend.pass_type:
                        friend_passes = set(p.strip() for p in friend.pass_type.split(','))
                        if friend_passes & resort_passes:
                            trip.friends_can_ski += 1
    
    # Open dates from JSON field (list of YYYY-MM-DD strings)
    my_open_dates = set(user.open_dates or [])
    # Filter to only future/today dates
    my_open_dates = {d for d in my_open_dates if d >= today.strftime('%Y-%m-%d')}
    
    # Build open date overlaps grouped by date
    open_date_matches = []  # List of {date, friends: [{name, id, pass_type}]}
    
    if my_open_dates and friend_ids:
        friends_with_open = User.query.filter(User.id.in_(friend_ids)).all()
        
        for date_str in sorted(my_open_dates):
            matching_friends = []
            for friend in friends_with_open:
                friend_dates = set(friend.open_dates or [])
                if date_str in friend_dates:
                    # Determine pass compatibility (safely handle None/empty)
                    user_pass = user.pass_type.strip() if user.pass_type else None
                    friend_pass = friend.pass_type.strip() if friend.pass_type else None
                    
                    if user_pass and friend_pass:
                        if user_pass == friend_pass:
                            pass_info = user_pass
                        else:
                            pass_info = f"{user_pass} · {friend_pass} (different passes)"
                    elif user_pass or friend_pass:
                        # Only one has a pass
                        pass_info = user_pass or friend_pass
                    else:
                        pass_info = None
                    
                    matching_friends.append({
                        "name": friend.first_name,
                        "id": friend.id,
                        "pass_type": friend.pass_type,
                        "skill_level": friend.skill_level,
                        "pass_info": pass_info,
                        "can_propose_trip": check_trip_invite_eligibility(user.id, friend.id)
                    })
            
            if matching_friends:
                # Parse date for display
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                open_date_matches.append({
                    "date_str": date_str,
                    "date_obj": date_obj,
                    "day_name": date_obj.strftime('%A'),  # Saturday, Sunday, etc.
                    "display_date": date_obj.strftime('%b %d'),  # Dec 14
                    "friends": matching_friends
                })
    
    # Format user's open dates for display
    user_open_dates_display = format_open_dates_summary(sorted(my_open_dates)) if my_open_dates else None
    
    # Get user's mountains visited
    user_mountains = user.mountains_visited or []
    user_mountains_sorted = sorted([m.name if hasattr(m, 'name') else m for m in user_mountains])
    
    # Get Resort objects for profile card (new unified component)
    visited_resorts = user.get_visited_resorts()
    wishlist_resorts = user.get_wishlist_resorts()
    
    # Count friends with open date overlaps
    open_friends_count, user_has_open_dates = count_friends_open_on_same_dates(user)
    
    # Combined list for All Trips (upcoming only)
    all_trips = (my_trips or []) + (friend_trips or [])
    try:
        all_trips = sorted(all_trips, key=lambda t: t.start_date)
    except Exception:
        pass
    
    # Get equipment for profile card
    primary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.PRIMARY).first()
    secondary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.SECONDARY).first()
    
    # Sort overlaps by start date and get first for highlight
    overlaps_sorted = sorted(overlaps, key=lambda x: x['start_date']) if overlaps else []
    first_overlap = overlaps_sorted[0] if overlaps_sorted else None
    
    # Countdown to next trip (host or guest) + get next trip object
    next_trip_countdown = None
    next_trip = None
    all_user_trips = []
    trip_objects = {}
    
    # Add user's own trips
    for trip in my_trips:
        all_user_trips.append(trip.start_date)
        trip_objects[trip.start_date] = trip
    
    # Add group trips where user is host
    hosted_trips = GroupTrip.query.filter(
        GroupTrip.host_id == user.id,
        GroupTrip.start_date >= today
    ).all()
    for trip in hosted_trips:
        all_user_trips.append(trip.start_date)
        trip_objects[trip.start_date] = trip
    
    # Add group trips where user is guest (accepted)
    guest_memberships = TripGuest.query.filter(
        TripGuest.user_id == user.id,
        TripGuest.status == GuestStatus.ACCEPTED
    ).all()
    for membership in guest_memberships:
        if membership.trip and membership.trip.start_date >= today:
            all_user_trips.append(membership.trip.start_date)
            trip_objects[membership.trip.start_date] = membership.trip
    
    if all_user_trips:
        next_trip_date = min(all_user_trips)
        days_until = (next_trip_date - today).days
        if days_until == 0:
            next_trip_countdown = "Starts today"
        elif days_until == 1:
            next_trip_countdown = "Your next trip starts in 1 day"
        else:
            next_trip_countdown = f"Your next trip starts in {days_until} days"
        next_trip = trip_objects.get(next_trip_date)
    
    # Availability match nudge
    availability_nudge = None
    if my_open_dates and open_date_matches:
        # Find the best date range with most friends
        best_match = max(open_date_matches, key=lambda m: len(m['friends']))
        if best_match['friends']:
            nudge_date = best_match['date_obj']
            
            # Check if this date range was already dismissed
            dismissed = DismissedNudge.query.filter(
                DismissedNudge.user_id == user.id,
                DismissedNudge.date_range_start <= nudge_date,
                DismissedNudge.date_range_end >= nudge_date
            ).first()
            
            if not dismissed:
                friend_count = len(best_match['friends'])
                top_friend = best_match['friends'][0]
                display_date = best_match['display_date']
                
                if friend_count == 1:
                    nudge_text = f"You and {top_friend['name']} are free {display_date}"
                else:
                    nudge_text = f"You and {friend_count} friends are free {display_date}"
                
                availability_nudge = {
                    'text': nudge_text,
                    'date': nudge_date.isoformat(),
                    'friend_id': top_friend['id']
                }
    
    # Shared Interest calculation
    shared_interests = []
    user_wish_list = user.wish_list_resorts or []
    
    if user_wish_list:
        # Get all users who have any of the same resorts on their wishlist
        all_users = User.query.filter(User.id != user.id).all()
        
        # Count how many users have each resort on their wishlist
        resort_counts = {}
        for resort_id in user_wish_list:
            count = 0
            for other_user in all_users:
                other_wish_list = other_user.wish_list_resorts or []
                if resort_id in other_wish_list:
                    count += 1
            if count > 0:  # At least 1 other user has this resort
                resort_counts[resort_id] = count
        
        # Get resort details and sort by count (desc), then by user's add order (desc)
        if resort_counts:
            for resort_id in user_wish_list:
                if resort_id in resort_counts:
                    resort = Resort.query.get(resort_id)
                    if resort:
                        # Get country display name
                        country_names = {'US': 'USA', 'CA': 'Canada', 'JP': 'Japan', 
                                        'FR': 'France', 'CH': 'Switzerland', 'AT': 'Austria', 'IT': 'Italy'}
                        country_display = country_names.get(resort.country, resort.country)
                        
                        shared_interests.append({
                            'resort_id': resort_id,
                            'name': resort.name,
                            'country': country_display,
                            'count': resort_counts[resort_id]
                        })
            
            # Sort by count (desc) - user's add order is preserved as secondary
            shared_interests.sort(key=lambda x: -x['count'])
    
    # Get wishlist resorts for profile card display
    user_wishlist_resorts = []
    if user_wish_list:
        wishlist_resorts_query = Resort.query.filter(Resort.id.in_(user_wish_list)).all()
        user_wishlist_resorts = [{'id': r.id, 'name': r.name} for r in wishlist_resorts_query]
    
    # Weekend day-trip signal for home screen
    weekend_daytrip_signal = None
    if friend_ids:
        # Calculate weekend window
        # Mon-Thu: upcoming Fri-Sun; Fri-Sun: current Fri-Sun
        weekday = today.weekday()  # 0 = Monday, 6 = Sunday
        
        if weekday <= 3:  # Mon-Thu: use upcoming Fri-Sun
            days_to_friday = 4 - weekday
            weekend_friday = today + timedelta(days=days_to_friday)
        else:  # Fri-Sun: use current Fri-Sun
            # Friday = weekday 4, Saturday = 5, Sunday = 6
            days_since_friday = weekday - 4
            weekend_friday = today - timedelta(days=days_since_friday)
        
        weekend_sunday = weekend_friday + timedelta(days=2)
        
        # Find friends' day trips within this weekend
        weekend_daytrips = SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.is_public == True,
            SkiTrip.trip_duration == 'day_trip',
            SkiTrip.start_date >= weekend_friday,
            SkiTrip.start_date <= weekend_sunday,
            SkiTrip.end_date >= today  # Must be active
        ).all()
        
        if weekend_daytrips:
            # Group by resort to find the most popular destination
            resort_counts = {}
            for trip in weekend_daytrips:
                resort_name = trip.resort.name if trip.resort else trip.mountain
                if resort_name not in resort_counts:
                    resort_counts[resort_name] = set()
                resort_counts[resort_name].add(trip.user_id)
            
            # Find the resort with the most friends
            if resort_counts:
                top_resort = max(resort_counts.keys(), key=lambda r: len(resort_counts[r]))
                friend_count = len(resort_counts[top_resort])
                if friend_count > 0:
                    weekend_daytrip_signal = {
                        'count': friend_count,
                        'resort': top_resort
                    }
    
    # Welcome modal - shown once after FULL onboarding is complete:
    # Requires: rider_types, pass_type, skill_level (core profile) PLUS home_state
    is_onboarding_complete = user.is_core_profile_complete and bool(user.home_state)
    show_welcome_screen = is_onboarding_complete and not user.welcome_modal_seen_at
    
    # Get pending trip invites for the user
    pending_invites = []
    invite_participants = SkiTripParticipant.query.filter_by(
        user_id=user.id,
        status=GuestStatus.INVITED
    ).all()
    for p in invite_participants:
        trip = p.trip
        if trip and trip.end_date >= today:
            inviter = User.query.get(trip.user_id)
            pending_invites.append({
                'trip': trip,
                'inviter': inviter,
                'participant_id': p.id
            })
    
    return render_template(
        'home.html',
        user=user,
        upcoming_trips=upcoming_trips,
        my_trips=my_trips,
        friend_trips=friend_trips,
        all_trips=all_trips,
        overlaps=overlaps_sorted,
        first_overlap=first_overlap,
        open_date_matches=open_date_matches,
        user_open_dates=sorted(my_open_dates) if my_open_dates else [],
        user_open_dates_display=user_open_dates_display,
        user_mountains=user_mountains_sorted,
        open_friends_count=open_friends_count,
        user_has_open_dates=user_has_open_dates,
        state_abbr=STATE_ABBR,
        primary_equipment=primary_equipment,
        secondary_equipment=secondary_equipment,
        next_trip_countdown=next_trip_countdown,
        next_trip=next_trip,
        availability_nudge=availability_nudge,
        shared_interests=shared_interests,
        weekend_daytrip_signal=weekend_daytrip_signal,
        user_wishlist_resorts=user_wishlist_resorts,
        visited_resorts=visited_resorts,
        wishlist_resorts=wishlist_resorts,
        show_welcome_screen=show_welcome_screen,
        pending_invites=pending_invites
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

    return render_template(
        "friend_trip_details.html",
        trip=trip,
        friend=friend,
        has_overlap=has_overlap,
        overlap_days=your_overlap_days,
        your_overlap_ranges=your_overlap_ranges,
        friends_open_on_trip=[]  # Always empty - privacy protection
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

@app.route("/settings")
@login_required
def settings():
    mountains = current_user.mountains_visited or []
    mountains_visited_count = len(mountains)
    
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
    
    return render_template("settings.html", 
                           mountains_visited_count=mountains_visited_count,
                           has_equipment=has_equipment,
                           equipment_summary=equipment_summary,
                           wish_list_count=wish_list_count,
                           wish_list_resorts=wish_list_resorts)

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
    
    # Get distinct countries for dropdown (only from resorts, excluding regions)
    countries = db.session.query(Resort.country_code).distinct().filter(
        Resort.country_code.isnot(None),
        Resort.country_code != '',
        Resort.is_region == False
    ).all()
    countries_list = []
    for (code,) in countries:
        if code:
            countries_list.append({'code': code, 'name': COUNTRY_NAMES.get(code, code)})
    # Sort: US first, then alphabetically by display name
    countries_list.sort(key=lambda c: (c['name'] != 'United States', c['name']))
    
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
        return redirect(url_for("home", tab="open"))
    
    # Pre-populate with existing dates
    existing_dates = current_user.open_dates or []
    return render_template("add_open_dates.html", existing_dates=existing_dates)

@app.route("/add_trip", methods=["GET", "POST"])
@login_required
def add_trip():
    # Single source of truth: Resort table
    resorts = get_resorts_for_trip_form()
    print(f"[add_trip] Loaded {len(resorts)} resorts")
    
    user_passes = [p.strip() for p in (current_user.pass_type or "").split(",") if p.strip()]
    print(f"[add_trip] User passes: {user_passes}")
    
    # Get prefill parameters for "Propose a trip" flow
    prefill_friend_id = request.args.get('friend_id', type=int)
    prefill_start_date = request.args.get('start_date')
    prefill_end_date = request.args.get('end_date')
    is_group = request.args.get('is_group') == '1'
    
    prefill_friend = None
    if prefill_friend_id:
        prefill_friend = User.query.get(prefill_friend_id)
    
    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        ride_intent = request.form.get("ride_intent") or None
        trip_equipment_status = request.form.get("trip_equipment_status") or "use_default"
        accommodation_status = request.form.get("accommodation_status") or None
        accommodation_link = request.form.get("accommodation_link") or None
        if accommodation_status == "none_yet":
            accommodation_link = None
        
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
                user=current_user,
                form_action=url_for("add_trip"),
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
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
                user=current_user,
                form_action=url_for("add_trip"),
                overlap_trip=overlapping,
                overlap_resort_name=resort.name,
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
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
            ride_intent=ride_intent,
            trip_duration=trip_duration,
            trip_equipment_status=trip_equipment_status if trip_equipment_status != 'use_default' else None,
            accommodation_status=accommodation_status if accommodation_status != 'none_yet' else None,
            accommodation_link=accommodation_link,
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
                user=current_user,
                form_action=url_for("add_trip"),
                user_passes=user_passes,
                prefill_friend=prefill_friend,
                prefill_start_date=prefill_start_date,
                prefill_end_date=prefill_end_date,
                is_group=is_group,
            )

    # GET - render the add trip form
    print(f"[add_trip GET] Resorts count: {len(resorts)}")
    
    return render_template(
        "add_trip.html",
        trip=None,
        resorts=resorts,
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

    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        ride_intent = request.form.get("ride_intent") or None
        trip_equipment_status = request.form.get("trip_equipment_status") or "use_default"
        accommodation_status = request.form.get("accommodation_status") or None
        accommodation_link = request.form.get("accommodation_link") or None
        if accommodation_status == "none_yet":
            accommodation_link = None

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
                "add_trip.html",
                trip=trip,
                resorts=resorts,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                user_passes=user_passes,
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
            return render_template(
                "add_trip.html",
                trip=trip,
                resorts=resorts,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                overlap_trip=overlapping,
                overlap_resort_name=resort.name,
                user_passes=user_passes,
            )

        dates_changed = (start_date != original_start or end_date != original_end)
        
        trip.resort_id = resort.id
        trip.state = resort.state_code or resort.state
        trip.mountain = resort.name
        trip.start_date = start_date
        trip.end_date = end_date
        trip.is_public = is_public
        trip.ride_intent = ride_intent
        trip.trip_equipment_status = trip_equipment_status if trip_equipment_status != 'use_default' else None
        trip.accommodation_status = accommodation_status if accommodation_status != 'none_yet' else None
        trip.accommodation_link = accommodation_link
        trip.trip_duration = SkiTrip.calculate_duration(start_date, end_date)
        
        try:
            emit_trip_updated_activities(trip, current_user.id, dates_changed=dates_changed)
            db.session.commit()
            return redirect(url_for("my_trips"))
        except Exception as e:
            db.session.rollback()
            print(f"Error updating trip: {e}")
            flash("Something went wrong while saving your trip. Please try again.", "error")
            return render_template(
                "add_trip.html",
                trip=trip,
                resorts=resorts,
                user=current_user,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
                user_passes=user_passes,
            )

    return render_template(
        "add_trip.html",
        trip=trip,
        resorts=resorts,
        user=current_user,
        form_action=url_for("edit_trip_form", trip_id=trip.id),
        user_passes=user_passes,
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
    all_participants = trip.get_all_participants()
    
    # Get current user's participant record for inline editing
    current_user_participant = participant
    if is_owner:
        # Owner needs their own participant record
        current_user_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=current_user.id, role=ParticipantRole.OWNER
        ).first()
    
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
    )


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
        abort(404)
    
    action = request.form.get("action")
    
    if action == "accept":
        participant.status = GuestStatus.ACCEPTED
        emit_trip_invite_accepted_activity(trip, current_user.id, trip.user_id)
        emit_friend_joined_trip_activities(trip, current_user.id)
        db.session.commit()
        flash("You've joined the trip!", "success")
        return redirect(url_for("trip_detail", trip_id=trip_id))
    elif action == "decline":
        participant.status = GuestStatus.DECLINED
        db.session.commit()
        flash("Invite declined.", "info")
        return redirect(url_for("home"))
    else:
        abort(400)


@app.route("/api/trips/<int:trip_id>/participant/signals", methods=["POST"])
@login_required
def update_participant_signals(trip_id):
    """Update current user's transportation and equipment signals for a trip."""
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
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "transportation_display": participant.get_display_transportation(),
        "equipment_display": participant.get_display_equipment(),
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
    
    # Get distinct countries for dropdown (only from resorts, excluding regions)
    countries = db.session.query(Resort.country_code).distinct().filter(
        Resort.country_code.isnot(None),
        Resort.country_code != '',
        Resort.is_region == False
    ).all()
    countries_list = []
    for (code,) in countries:
        if code:
            countries_list.append({'code': code, 'name': COUNTRY_NAMES.get(code, code)})
    # Sort: US first, then alphabetically by display name
    countries_list.sort(key=lambda c: (c['name'] != 'United States', c['name']))
    
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

@app.route("/seed_dummy_data")
def seed_dummy_data():
    from datetime import timedelta
    import random

    # Realistic name pools
    first_names = [
        "Alex", "Jordan", "Sam", "Casey", "Riley", "Morgan", "Jamie", "Taylor",
        "Jesse", "Charlie", "Skylar", "Quinn", "Dakota", "Avery", "Blake", "Parker",
        "Rowan", "Drew", "Phoenix", "River", "Jordan", "Morgan", "Bailey", "Cameron",
        "Jade", "Connor", "Reese", "Emerson", "Sage", "Justice", "Scout", "Parker",
        "Lex", "Hayden", "Aspen", "Storm", "Finley", "Devyn", "Canyon", "Sierra",
        "Teton", "Range", "Peak", "Boulder", "Summit", "Ridge", "Trail", "Alpine",
        "Powder", "Backcountry", "Mogul", "Gnar", "Shred", "Carve"
    ]
    
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Young",
        "Skinner", "Powder", "Steep", "Shred", "Carve", "Peak", "Summit", "Ridge"
    ]

    rider_types = ["Skier", "Snowboarder"]
    pass_types = ["Epic", "Ikon", "Indy", "None"]
    skill_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
    states = ["Colorado", "Utah", "California", "Wyoming", "Montana", "Idaho", "Washington"]
    
    # Popular resorts for overlaps
    popular_resorts = ["Vail", "Breckenridge", "Park City", "Heavenly", "Whistler"]
    all_resorts = [
        "Vail", "Breckenridge", "Keystone", "Copper Mountain", "Winter Park", "Aspen",
        "Snowmass", "Telluride", "Park City", "Deer Valley", "Snowbird", "Alta",
        "Jackson Hole", "Big Sky", "Heavenly", "Mammoth", "Northstar", "Palisades Tahoe",
        "Whistler", "Lake Louise", "Banff", "Steamboat", "Loveland", "Eldora"
    ]
    
    state_map = {
        "Vail": "Colorado", "Breckenridge": "Colorado", "Keystone": "Colorado",
        "Copper Mountain": "Colorado", "Winter Park": "Colorado", "Aspen": "Colorado",
        "Snowmass": "Colorado", "Telluride": "Colorado", "Steamboat": "Colorado",
        "Park City": "Utah", "Deer Valley": "Utah", "Snowbird": "Utah", "Alta": "Utah",
        "Jackson Hole": "Wyoming", "Big Sky": "Montana", "Heavenly": "California",
        "Mammoth": "California", "Northstar": "California", "Palisades Tahoe": "California",
        "Whistler": "British Columbia", "Lake Louise": "Alberta", "Banff": "Alberta",
        "Loveland": "Colorado", "Eldora": "Colorado"
    }

    # Ensure Richard Battle-Baxter exists
    richard_email = "richardbattlebaxter@gmail.com"
    richard = User.query.filter_by(email=richard_email).first()
    
    if not richard:
        richard = User(
            first_name="Richard",
            last_name="Battle-Baxter",
            email=richard_email,
            primary_rider_type="Skier",
            secondary_rider_types=[],
            pass_type="Epic",
            skill_level="Advanced",
            home_state="Colorado",
            birth_year=1985
        )
        richard.set_password("12345678")
        db.session.add(richard)
        db.session.commit()

    # Delete all dummy users (keep Richard)
    other_users = User.query.filter(User.email != richard_email).all()
    for u in other_users:
        db.session.delete(u)
    db.session.commit()

    # Create Richard's trips as anchors for overlaps
    today = date.today()
    richard_trips = []
    
    richard_trip_dates = [
        (today + timedelta(days=15), today + timedelta(days=22)),  # Jan 27 - Feb 3
        (today + timedelta(days=35), today + timedelta(days=42)),  # Feb 16 - Feb 23
        (today + timedelta(days=60), today + timedelta(days=67)),  # Mar 12 - Mar 19
    ]
    
    for start, end in richard_trip_dates:
        resort = random.choice(popular_resorts)
        state = state_map.get(resort, "Colorado")
        
        trip = SkiTrip(
            user_id=richard.id,
            mountain=resort,
            state=state,
            start_date=start,
            end_date=end,
            pass_type="Epic",
            is_public=True
        )
        db.session.add(trip)
        richard_trips.append((start, end, resort, state))
    
    db.session.commit()

    # Create 50 dummy users
    users_created = 0
    friendships_created = 0
    trips_created = 0
    overlaps_with_richard = 0

    dummy_users = []
    
    for i in range(50):
        first = random.choice(first_names)
        last = random.choice(last_names)
        email = f"user_{i}_{first.lower()}_{last.lower()}@example.com".replace(" ", "_")
        
        # Ensure unique email
        existing = User.query.filter_by(email=email).first()
        if existing:
            email = f"user_{i}_{random.randint(1000, 9999)}@example.com"
        
        primary_rt = random.choice(rider_types)
        user = User(
            first_name=first,
            last_name=last,
            email=email,
            primary_rider_type=primary_rt,
            secondary_rider_types=[],
            pass_type=random.choice(pass_types),
            skill_level=random.choice(skill_levels),
            home_state=random.choice(states),
            birth_year=random.randint(1975, 2003),
            mountains_visited=random.sample(all_resorts, random.randint(2, 6))
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()
        
        dummy_users.append(user)
        users_created += 1

    db.session.commit()

    # Create friendships: all 50 dummy users → Richard (bidirectional)
    for user in dummy_users:
        if not Friend.query.filter_by(user_id=richard.id, friend_id=user.id).first():
            db.session.add(Friend(user_id=richard.id, friend_id=user.id))
            friendships_created += 1
        if not Friend.query.filter_by(user_id=user.id, friend_id=richard.id).first():
            db.session.add(Friend(user_id=user.id, friend_id=richard.id))
            friendships_created += 1
    
    db.session.commit()

    # Create trips: ensure overlaps
    overlap_count = 0
    
    for idx, user in enumerate(dummy_users):
        # First 20 users get guaranteed overlaps with Richard
        if idx < 20:
            richard_trip = random.choice(richard_trips)
            start_richard, end_richard, resort, state = richard_trip
            
            # Create overlapping trip
            overlap_start = start_richard + timedelta(days=random.randint(-2, 2))
            overlap_end = overlap_start + timedelta(days=random.randint(2, 7))
            
            trip = SkiTrip(
                user_id=user.id,
                mountain=resort,
                state=state,
                start_date=overlap_start,
                end_date=overlap_end,
                pass_type=user.pass_type or "No Pass",
                is_public=True
            )
            db.session.add(trip)
            trips_created += 1
            overlap_count += 1
        
        # Create 1-2 additional trips (some may overlap with other users)
        for _ in range(random.randint(1, 2)):
            start = today + timedelta(days=random.randint(5, 90))
            end = start + timedelta(days=random.randint(2, 6))
            resort = random.choice(all_resorts)
            state = state_map.get(resort, "Colorado")
            
            trip = SkiTrip(
                user_id=user.id,
                mountain=resort,
                state=state,
                start_date=start,
                end_date=end,
                pass_type=user.pass_type or "No Pass",
                is_public=True
            )
            db.session.add(trip)
            trips_created += 1
    
    db.session.commit()

    # Summary
    total_overlaps = SkiTrip.query.filter(
        SkiTrip.user_id != richard.id
    ).all()
    richard_resort_dates = [(r[2], r[0], r[1]) for r in richard_trips]
    actual_overlaps = 0
    
    for trip in total_overlaps:
        for resort, rstart, rend in richard_resort_dates:
            if trip.mountain == resort and not (trip.end_date < rstart or trip.start_date > rend):
                actual_overlaps += 1
                break

    summary = f"""
    ✅ SEED DATA COMPLETE
    
    Users Created: {users_created}
    Friendships Created: {friendships_created}
    Trips Created: {trips_created}
    Guaranteed Overlaps with Richard: {overlap_count}
    Actual Overlaps Detected: {actual_overlaps}
    
    Richard's Email: {richard_email}
    Password: 12345678
    
    Dummy User Password: password123
    
    Test accounts are ready for trip/friend/overlap testing!
    """
    
    return summary

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

@app.route("/debug/trip-form-data")
def debug_trip_form_data():
    """Debug endpoint to verify trip form data."""
    countries = get_all_countries()
    states = get_all_states_by_country()
    resorts_objs = Resort.query.filter_by(is_active=True).limit(10).all()
    resorts_sample = [{"id": r.id, "name": r.name, "state": r.state, "country": r.country} for r in resorts_objs]
    return {
        "data_source": "CANONICAL (not resort-derived)",
        "countries": countries,
        "countries_count": len(countries),
        "states_by_country_keys": list(states.keys()) if states else [],
        "US_states_count": len(states.get("US", [])),
        "US_states_sample": states.get("US", [])[:10] if states else [],
        "CA_provinces_count": len(states.get("CA", [])),
        "resorts_sample": resorts_sample,
        "resort_count": Resort.query.filter_by(is_active=True).count()
    }

@app.route("/force-reset-passwords")
def force_reset_passwords():
    results = {}

    users_to_reset = {
        "richardbattlebaxter@gmail.com": "123456",
        "jonathanmschmitz@gmail.com": "123456"
    }

    for email, new_pw in users_to_reset.items():
        user = User.query.filter_by(email=email).first()
        if user:
            user.set_password(new_pw)
            db.session.commit()
            results[email] = "password reset"
        else:
            results[email] = "user not found"

    return {"status": "success", "results": results}

@app.route("/admin/init-db", methods=["GET", "POST"])
def init_db_http():
    """
    HTTP endpoint for database initialization (backup method for deployment).
    Can be called after deployment to initialize the database.
    
    Usage after deployment:
    GET https://yourapp.replit.dev/admin/init-db
    
    This will:
    - Create all database tables
    - Seed all resorts (idempotent)
    - Create/verify primary user (Richard)
    - Be idempotent (safe to call multiple times)
    """
    try:
        with app.app_context():
            # Create all tables
            db.create_all()
            
            messages = []
            
            # Seed resorts if none exist
            resort_count = Resort.query.count()
            if resort_count == 0:
                RESORTS_DATA = [
                    {"name": "Aspen Snowmass", "state": "CO", "brand": "Ikon"},
                    {"name": "Aspen Highlands", "state": "CO", "brand": "Ikon"},
                    {"name": "Buttermilk", "state": "CO", "brand": "Ikon"},
                    {"name": "Snowmass", "state": "CO", "brand": "Ikon"},
                    {"name": "Beaver Creek", "state": "CO", "brand": "Epic"},
                    {"name": "Breckenridge", "state": "CO", "brand": "Epic"},
                    {"name": "Keystone", "state": "CO", "brand": "Epic"},
                    {"name": "Vail", "state": "CO", "brand": "Epic"},
                    {"name": "Copper Mountain", "state": "CO", "brand": "Ikon"},
                    {"name": "Winter Park", "state": "CO", "brand": "Ikon"},
                    {"name": "Eldora", "state": "CO", "brand": "Ikon"},
                    {"name": "Telluride", "state": "CO", "brand": "Ikon"},
                    {"name": "Monarch", "state": "CO", "brand": "Other"},
                    {"name": "Sunlight", "state": "CO", "brand": "Other"},
                    {"name": "Arapahoe Basin", "state": "CO", "brand": "Ikon"},
                    {"name": "Loveland", "state": "CO", "brand": "Other"},
                    {"name": "Steamboat", "state": "CO", "brand": "Ikon"},
                    {"name": "Crested Butte", "state": "CO", "brand": "Epic"},
                    {"name": "Purgatory", "state": "CO", "brand": "Other"},
                    {"name": "Wolf Creek", "state": "CO", "brand": "Other"},
                    {"name": "Ski Cooper", "state": "CO", "brand": "Other"},
                    {"name": "Powderhorn", "state": "CO", "brand": "Other"},
                    {"name": "Silverton Mountain", "state": "CO", "brand": "Other"},
                    {"name": "Alta", "state": "UT", "brand": "Ikon"},
                    {"name": "Snowbird", "state": "UT", "brand": "Ikon"},
                    {"name": "Solitude", "state": "UT", "brand": "Ikon"},
                    {"name": "Brighton", "state": "UT", "brand": "Ikon"},
                    {"name": "Park City", "state": "UT", "brand": "Epic"},
                    {"name": "Deer Valley", "state": "UT", "brand": "Ikon"},
                    {"name": "Snowbasin", "state": "UT", "brand": "Other"},
                    {"name": "Powder Mountain", "state": "UT", "brand": "Other"},
                    {"name": "Brian Head", "state": "UT", "brand": "Other"},
                    {"name": "Sundance", "state": "UT", "brand": "Other"},
                    {"name": "Nordic Valley", "state": "UT", "brand": "Other"},
                    {"name": "Cherry Peak", "state": "UT", "brand": "Other"},
                    {"name": "Eagle Point", "state": "UT", "brand": "Other"},
                    {"name": "Beaver Mountain", "state": "UT", "brand": "Other"},
                    {"name": "Palisades Tahoe", "state": "CA", "brand": "Ikon"},
                    {"name": "Northstar", "state": "CA", "brand": "Epic"},
                    {"name": "Heavenly", "state": "CA", "brand": "Epic"},
                    {"name": "Kirkwood", "state": "CA", "brand": "Epic"},
                    {"name": "Mammoth Mountain", "state": "CA", "brand": "Ikon"},
                    {"name": "June Mountain", "state": "CA", "brand": "Ikon"},
                    {"name": "Big Bear", "state": "CA", "brand": "Ikon"},
                    {"name": "Sugar Bowl", "state": "CA", "brand": "Other"},
                    {"name": "Sierra-at-Tahoe", "state": "CA", "brand": "Ikon"},
                    {"name": "Boreal", "state": "CA", "brand": "Other"},
                    {"name": "Homewood", "state": "CA", "brand": "Other"},
                    {"name": "Diamond Peak", "state": "CA", "brand": "Other"},
                    {"name": "Mt. Rose", "state": "CA", "brand": "Other"},
                    {"name": "Jackson Hole", "state": "WY", "brand": "Ikon"},
                    {"name": "Grand Targhee", "state": "WY", "brand": "Ikon"},
                    {"name": "Snow King", "state": "WY", "brand": "Other"},
                    {"name": "Snowy Range", "state": "WY", "brand": "Other"},
                    {"name": "Big Sky", "state": "MT", "brand": "Ikon"},
                    {"name": "Whitefish Mountain", "state": "MT", "brand": "Other"},
                    {"name": "Bridger Bowl", "state": "MT", "brand": "Other"},
                    {"name": "Red Lodge Mountain", "state": "MT", "brand": "Other"},
                    {"name": "Discovery", "state": "MT", "brand": "Other"},
                    {"name": "Crystal Mountain", "state": "WA", "brand": "Ikon"},
                    {"name": "Snoqualmie", "state": "WA", "brand": "Other"},
                    {"name": "Mission Ridge", "state": "WA", "brand": "Other"},
                    {"name": "Stevens Pass", "state": "WA", "brand": "Epic"},
                    {"name": "Mt. Baker", "state": "WA", "brand": "Other"},
                    {"name": "White Pass", "state": "WA", "brand": "Other"},
                    {"name": "49 Degrees North", "state": "WA", "brand": "Other"},
                    {"name": "Mt. Hood Meadows", "state": "OR", "brand": "Other"},
                    {"name": "Timberline", "state": "OR", "brand": "Other"},
                    {"name": "Mt. Bachelor", "state": "OR", "brand": "Ikon"},
                    {"name": "Anthony Lakes", "state": "OR", "brand": "Other"},
                    {"name": "Mt. Ashland", "state": "OR", "brand": "Other"},
                    {"name": "Killington", "state": "VT", "brand": "Ikon"},
                    {"name": "Sugarbush", "state": "VT", "brand": "Ikon"},
                    {"name": "Stowe", "state": "VT", "brand": "Epic"},
                    {"name": "Stratton", "state": "VT", "brand": "Ikon"},
                    {"name": "Jay Peak", "state": "VT", "brand": "Other"},
                    {"name": "Smugglers Notch", "state": "VT", "brand": "Other"},
                    {"name": "Mount Snow", "state": "VT", "brand": "Epic"},
                    {"name": "Okemo", "state": "VT", "brand": "Epic"},
                    {"name": "Bolton Valley", "state": "VT", "brand": "Other"},
                    {"name": "Mad River Glen", "state": "VT", "brand": "Other"},
                    {"name": "Bromley", "state": "VT", "brand": "Other"},
                    {"name": "Loon Mountain", "state": "NH", "brand": "Ikon"},
                    {"name": "Cannon Mountain", "state": "NH", "brand": "Other"},
                    {"name": "Waterville Valley", "state": "NH", "brand": "Other"},
                    {"name": "Bretton Woods", "state": "NH", "brand": "Ikon"},
                    {"name": "Wildcat Mountain", "state": "NH", "brand": "Other"},
                    {"name": "Cranmore", "state": "NH", "brand": "Other"},
                    {"name": "Sunday River", "state": "ME", "brand": "Ikon"},
                    {"name": "Sugarloaf", "state": "ME", "brand": "Ikon"},
                    {"name": "Saddleback", "state": "ME", "brand": "Other"},
                    {"name": "Black Mountain", "state": "ME", "brand": "Other"},
                    {"name": "Shawnee Peak", "state": "ME", "brand": "Other"},
                    {"name": "Whiteface", "state": "NY", "brand": "Ikon"},
                    {"name": "Gore Mountain", "state": "NY", "brand": "Other"},
                    {"name": "Belleayre", "state": "NY", "brand": "Other"},
                    {"name": "Hunter Mountain", "state": "NY", "brand": "Epic"},
                    {"name": "Windham Mountain", "state": "NY", "brand": "Epic"},
                    {"name": "Taos Ski Valley", "state": "NM", "brand": "Ikon"},
                    {"name": "Ski Santa Fe", "state": "NM", "brand": "Other"},
                    {"name": "Angel Fire", "state": "NM", "brand": "Other"},
                    {"name": "Red River", "state": "NM", "brand": "Other"},
                    {"name": "Sun Valley", "state": "ID", "brand": "Epic"},
                    {"name": "Schweitzer", "state": "ID", "brand": "Ikon"},
                    {"name": "Bogus Basin", "state": "ID", "brand": "Other"},
                    {"name": "Brundage Mountain", "state": "ID", "brand": "Other"},
                    {"name": "Tamarack", "state": "ID", "brand": "Other"},
                    {"name": "Lookout Pass", "state": "ID", "brand": "Other"},
                    {"name": "Boyne Mountain", "state": "MI", "brand": "Other"},
                    {"name": "Crystal Mountain MI", "state": "MI", "brand": "Other"},
                    {"name": "Nubs Nob", "state": "MI", "brand": "Other"},
                    {"name": "Boyne Highlands", "state": "MI", "brand": "Other"},
                    {"name": "Shanty Creek", "state": "MI", "brand": "Other"},
                    {"name": "Alyeska Resort", "state": "AK", "brand": "Ikon"},
                    {"name": "Eaglecrest", "state": "AK", "brand": "Other"},
                    {"name": "Seven Springs", "state": "PA", "brand": "Other"},
                    {"name": "Blue Mountain PA", "state": "PA", "brand": "Other"},
                    {"name": "Snowshoe", "state": "WV", "brand": "Ikon"},
                ]
                
                STATE_FULL = {
                    "AK": "Alaska", "CA": "California", "CO": "Colorado", "ID": "Idaho",
                    "ME": "Maine", "MI": "Michigan", "MT": "Montana", "NH": "New Hampshire",
                    "NM": "New Mexico", "NY": "New York", "OR": "Oregon", "PA": "Pennsylvania",
                    "UT": "Utah", "VT": "Vermont", "WA": "Washington", "WV": "West Virginia", "WY": "Wyoming"
                }
                
                for r in RESORTS_DATA:
                    slug = r["name"].lower().replace(" ", "-").replace(".", "")
                    resort = Resort(
                        name=r["name"],
                        state=r["state"],
                        state_full=STATE_FULL.get(r["state"], r["state"]),
                        brand=r["brand"],
                        slug=slug,
                        is_active=True
                    )
                    db.session.add(resort)
                
                db.session.commit()
                messages.append(f"Seeded {len(RESORTS_DATA)} resorts")
            else:
                messages.append(f"Resorts already exist ({resort_count})")
            
            # Ensure primary user exists and is valid
            primary_user = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
            if not primary_user:
                primary_user = User(
                    first_name="Richard",
                    last_name="Battle-Baxter",
                    email="richardbattlebaxter@gmail.com",
                    primary_rider_type="Skier",
                    secondary_rider_types=[],
                    pass_type="Epic",
                    skill_level="Advanced",
                    home_state="Colorado",
                    birth_year=1985
                )
                primary_user.set_password("12345678")
                db.session.add(primary_user)
                db.session.commit()
                messages.append("Primary user created")
            else:
                messages.append("Primary user verified")
            
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


@app.route("/admin/seed-colorado-resorts", methods=["GET", "POST"])
def seed_colorado_resorts_endpoint():
    """
    HTTP endpoint to add missing Colorado ski resorts.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-colorado-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        colorado_resorts = [
            {"name": "Beaver Creek", "slug": "beaver-creek", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Telluride", "slug": "telluride", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Wolf Creek", "slug": "wolf-creek", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Monarch Mountain", "slug": "monarch-mountain", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Ski Cooper", "slug": "ski-cooper", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Purgatory Resort", "slug": "purgatory-resort", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Silverton Mountain", "slug": "silverton-mountain", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Howelsen Hill", "slug": "howelsen-hill", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Echo Mountain", "slug": "echo-mountain", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
            {"name": "Hoedown Hill", "slug": "hoedown-hill", "state": "CO", "state_full": "Colorado", "country": "US", "brand": "Other", "pass_brands": None},
        ]
        
        created = []
        existed = []
        
        for resort_data in colorado_resorts:
            existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
            if existing:
                existed.append(resort_data["name"])
            else:
                new_resort = Resort(
                    name=resort_data["name"],
                    slug=resort_data["slug"],
                    state=resort_data["state"],
                    state_full=resort_data["state_full"],
                    country=resort_data["country"],
                    brand=resort_data["brand"],
                    pass_brands=resort_data["pass_brands"],
                    is_active=True
                )
                db.session.add(new_resort)
                created.append(resort_data["name"])
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed Colorado resorts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-utah-resorts", methods=["GET", "POST"])
def seed_utah_resorts_endpoint():
    """
    HTTP endpoint to add missing Utah ski resorts.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-utah-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        utah_resorts = [
            {"name": "Park City", "slug": "park-city", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Alta", "slug": "alta", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Snowbird", "slug": "snowbird", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Deer Valley", "slug": "deer-valley", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Solitude", "slug": "solitude", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Brighton", "slug": "brighton", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Snowbasin", "slug": "snowbasin", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Powder Mountain", "slug": "powder-mountain", "brand": "Indy", "pass_brands": "Indy"},
            {"name": "Brian Head", "slug": "brian-head", "brand": "Indy", "pass_brands": "Indy"},
            {"name": "Sundance", "slug": "sundance", "brand": "Other", "pass_brands": None},
            {"name": "Nordic Valley", "slug": "nordic-valley", "brand": "Other", "pass_brands": None},
            {"name": "Cherry Peak", "slug": "cherry-peak", "brand": "Other", "pass_brands": None},
            {"name": "Eagle Point", "slug": "eagle-point", "brand": "Other", "pass_brands": None},
            {"name": "Beaver Mountain", "slug": "beaver-mountain", "brand": "Other", "pass_brands": None},
        ]
        
        created = []
        existed = []
        
        for resort_data in utah_resorts:
            existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
            if existing:
                existed.append(resort_data["name"])
            else:
                new_resort = Resort(
                    name=resort_data["name"],
                    slug=resort_data["slug"],
                    state="UT",
                    state_full="Utah",
                    country="US",
                    brand=resort_data["brand"],
                    pass_brands=resort_data["pass_brands"],
                    is_active=True
                )
                db.session.add(new_resort)
                created.append(resort_data["name"])
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed Utah resorts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-wa-ca-resorts", methods=["GET", "POST"])
def seed_wa_ca_resorts_endpoint():
    """
    HTTP endpoint to add missing Washington and California ski resorts.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-wa-ca-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        wa_resorts = [
            {"name": "Stevens Pass", "slug": "stevens-pass", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Crystal Mountain", "slug": "crystal-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "The Summit at Snoqualmie", "slug": "the-summit-at-snoqualmie", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Mount Baker", "slug": "mount-baker", "brand": "Indy", "pass_brands": "Indy"},
            {"name": "Mission Ridge", "slug": "mission-ridge", "brand": "Other", "pass_brands": None},
            {"name": "White Pass", "slug": "white-pass", "brand": "Other", "pass_brands": None},
            {"name": "49 Degrees North", "slug": "49-degrees-north", "brand": "Other", "pass_brands": None},
            {"name": "Mt. Spokane", "slug": "mt-spokane", "brand": "Other", "pass_brands": None},
        ]
        
        ca_resorts = [
            {"name": "Heavenly", "slug": "heavenly", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Northstar", "slug": "northstar", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Kirkwood", "slug": "kirkwood", "brand": "Epic", "pass_brands": "Epic"},
            {"name": "Palisades Tahoe", "slug": "palisades-tahoe", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Mammoth Mountain", "slug": "mammoth-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "June Mountain", "slug": "june-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Big Bear Mountain Resort", "slug": "big-bear-mountain-resort", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Snow Valley", "slug": "snow-valley", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Sierra-at-Tahoe", "slug": "sierra-at-tahoe", "brand": "Ikon", "pass_brands": "Ikon"},
            {"name": "Sugar Bowl", "slug": "sugar-bowl", "brand": "Other", "pass_brands": None},
            {"name": "Mt. Rose", "slug": "mt-rose", "brand": "Other", "pass_brands": None},
            {"name": "Bear Valley", "slug": "bear-valley", "brand": "Other", "pass_brands": None},
            {"name": "China Peak", "slug": "china-peak", "brand": "Other", "pass_brands": None},
            {"name": "Dodge Ridge", "slug": "dodge-ridge", "brand": "Other", "pass_brands": None},
        ]
        
        created = []
        existed = []
        
        for resort_data in wa_resorts:
            existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
            if existing:
                existed.append(resort_data["name"] + " (WA)")
            else:
                new_resort = Resort(
                    name=resort_data["name"],
                    slug=resort_data["slug"],
                    state="WA",
                    state_full="Washington",
                    country="US",
                    brand=resort_data["brand"],
                    pass_brands=resort_data["pass_brands"],
                    is_active=True
                )
                db.session.add(new_resort)
                created.append(resort_data["name"] + " (WA)")
        
        for resort_data in ca_resorts:
            existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
            if existing:
                existed.append(resort_data["name"] + " (CA)")
            else:
                new_resort = Resort(
                    name=resort_data["name"],
                    slug=resort_data["slug"],
                    state="CA",
                    state_full="California",
                    country="US",
                    brand=resort_data["brand"],
                    pass_brands=resort_data["pass_brands"],
                    is_active=True
                )
                db.session.add(new_resort)
                created.append(resort_data["name"] + " (CA)")
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed WA/CA resorts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-western-resorts", methods=["GET", "POST"])
def seed_western_resorts_endpoint():
    """
    HTTP endpoint to add missing ski resorts for OR, ID, MT, WY, AZ, NM, ND, SD.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-western-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        resorts_by_state = {
            "OR": {
                "state_full": "Oregon",
                "resorts": [
                    {"name": "Mt. Bachelor", "slug": "mt-bachelor", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Mt. Hood Meadows", "slug": "mt-hood-meadows", "brand": "Other", "pass_brands": None},
                    {"name": "Timberline Lodge", "slug": "timberline-lodge", "brand": "Other", "pass_brands": None},
                    {"name": "Hoodoo", "slug": "hoodoo", "brand": "Other", "pass_brands": None},
                    {"name": "Willamette Pass", "slug": "willamette-pass", "brand": "Other", "pass_brands": None},
                    {"name": "Anthony Lakes", "slug": "anthony-lakes", "brand": "Other", "pass_brands": None},
                ]
            },
            "ID": {
                "state_full": "Idaho",
                "resorts": [
                    {"name": "Sun Valley", "slug": "sun-valley", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Schweitzer", "slug": "schweitzer", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Brundage", "slug": "brundage", "brand": "Other", "pass_brands": None},
                    {"name": "Tamarack", "slug": "tamarack", "brand": "Other", "pass_brands": None},
                    {"name": "Silver Mountain", "slug": "silver-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Bogus Basin", "slug": "bogus-basin", "brand": "Other", "pass_brands": None},
                    {"name": "Pebble Creek", "slug": "pebble-creek", "brand": "Other", "pass_brands": None},
                    {"name": "Soldier Mountain", "slug": "soldier-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Lookout Pass", "slug": "lookout-pass", "brand": "Other", "pass_brands": None},
                ]
            },
            "MT": {
                "state_full": "Montana",
                "resorts": [
                    {"name": "Big Sky", "slug": "big-sky", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Bridger Bowl", "slug": "bridger-bowl", "brand": "Other", "pass_brands": None},
                    {"name": "Whitefish", "slug": "whitefish", "brand": "Other", "pass_brands": None},
                    {"name": "Red Lodge", "slug": "red-lodge", "brand": "Other", "pass_brands": None},
                    {"name": "Discovery Ski Area", "slug": "discovery-ski-area", "brand": "Other", "pass_brands": None},
                    {"name": "Lost Trail", "slug": "lost-trail", "brand": "Other", "pass_brands": None},
                ]
            },
            "WY": {
                "state_full": "Wyoming",
                "resorts": [
                    {"name": "Jackson Hole", "slug": "jackson-hole", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Grand Targhee", "slug": "grand-targhee", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Snowy Range", "slug": "snowy-range", "brand": "Other", "pass_brands": None},
                    {"name": "Meadowlark", "slug": "meadowlark", "brand": "Other", "pass_brands": None},
                ]
            },
            "AZ": {
                "state_full": "Arizona",
                "resorts": [
                    {"name": "Arizona Snowbowl", "slug": "arizona-snowbowl", "brand": "Other", "pass_brands": None},
                    {"name": "Sunrise Park Resort", "slug": "sunrise-park-resort", "brand": "Other", "pass_brands": None},
                ]
            },
            "NM": {
                "state_full": "New Mexico",
                "resorts": [
                    {"name": "Taos Ski Valley", "slug": "taos-ski-valley", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Angel Fire", "slug": "angel-fire", "brand": "Other", "pass_brands": None},
                    {"name": "Red River", "slug": "red-river", "brand": "Other", "pass_brands": None},
                    {"name": "Ski Santa Fe", "slug": "ski-santa-fe", "brand": "Other", "pass_brands": None},
                    {"name": "Sipapu", "slug": "sipapu", "brand": "Other", "pass_brands": None},
                    {"name": "Pajarito", "slug": "pajarito", "brand": "Other", "pass_brands": None},
                ]
            },
            "ND": {
                "state_full": "North Dakota",
                "resorts": [
                    {"name": "Huff Hills", "slug": "huff-hills", "brand": "Other", "pass_brands": None},
                ]
            },
            "SD": {
                "state_full": "South Dakota",
                "resorts": [
                    {"name": "Terry Peak", "slug": "terry-peak", "brand": "Other", "pass_brands": None},
                ]
            },
        }
        
        created = []
        existed = []
        
        for state_code, state_data in resorts_by_state.items():
            for resort_data in state_data["resorts"]:
                existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
                if existing:
                    existed.append(f"{resort_data['name']} ({state_code})")
                else:
                    new_resort = Resort(
                        name=resort_data["name"],
                        slug=resort_data["slug"],
                        state=state_code,
                        state_full=state_data["state_full"],
                        country="US",
                        brand=resort_data["brand"],
                        pass_brands=resort_data["pass_brands"],
                        is_active=True
                    )
                    db.session.add(new_resort)
                    created.append(f"{resort_data['name']} ({state_code})")
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed western resorts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-eastern-resorts", methods=["GET", "POST"])
def seed_eastern_resorts_endpoint():
    """
    HTTP endpoint to add missing ski resorts for eastern/midwest US states.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-eastern-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        resorts_by_state = {
            "NE": {
                "state_full": "Nebraska",
                "resorts": [
                    {"name": "Mt. Crescent Ski Area", "slug": "mt-crescent-ski-area", "brand": "Other", "pass_brands": None},
                ]
            },
            "KS": {
                "state_full": "Kansas",
                "resorts": [
                    {"name": "Snow Creek", "slug": "snow-creek", "brand": "Other", "pass_brands": None},
                ]
            },
            "MN": {
                "state_full": "Minnesota",
                "resorts": [
                    {"name": "Lutsen Mountains", "slug": "lutsen-mountains", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Afton Alps", "slug": "afton-alps", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Spirit Mountain", "slug": "spirit-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Giants Ridge", "slug": "giants-ridge", "brand": "Other", "pass_brands": None},
                    {"name": "Buck Hill", "slug": "buck-hill", "brand": "Other", "pass_brands": None},
                    {"name": "Welch Village", "slug": "welch-village", "brand": "Other", "pass_brands": None},
                    {"name": "Mount Kato", "slug": "mount-kato", "brand": "Other", "pass_brands": None},
                ]
            },
            "WI": {
                "state_full": "Wisconsin",
                "resorts": [
                    {"name": "Wilmot Mountain", "slug": "wilmot-mountain", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Granite Peak", "slug": "granite-peak", "brand": "Other", "pass_brands": None},
                    {"name": "Cascade Mountain", "slug": "cascade-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Devil's Head", "slug": "devils-head", "brand": "Other", "pass_brands": None},
                    {"name": "Alpine Valley", "slug": "alpine-valley", "brand": "Other", "pass_brands": None},
                    {"name": "Crystal Mountain WI", "slug": "crystal-mountain-wi", "brand": "Other", "pass_brands": None},
                ]
            },
            "MO": {
                "state_full": "Missouri",
                "resorts": [
                    {"name": "Hidden Valley MO", "slug": "hidden-valley-mo", "brand": "Epic", "pass_brands": "Epic"},
                ]
            },
            "MI": {
                "state_full": "Michigan",
                "resorts": [
                    {"name": "Boyne Mountain", "slug": "boyne-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Boyne Highlands", "slug": "boyne-highlands", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Crystal Mountain MI", "slug": "crystal-mountain-mi", "brand": "Other", "pass_brands": None},
                    {"name": "Nubs Nob", "slug": "nubs-nob", "brand": "Other", "pass_brands": None},
                    {"name": "Shanty Creek", "slug": "shanty-creek", "brand": "Other", "pass_brands": None},
                    {"name": "Mount Bohemia", "slug": "mount-bohemia", "brand": "Other", "pass_brands": None},
                ]
            },
            "NY": {
                "state_full": "New York",
                "resorts": [
                    {"name": "Whiteface", "slug": "whiteface", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Gore Mountain", "slug": "gore-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Hunter Mountain", "slug": "hunter-mountain", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Belleayre", "slug": "belleayre", "brand": "Other", "pass_brands": None},
                    {"name": "Windham", "slug": "windham", "brand": "Other", "pass_brands": None},
                    {"name": "Holiday Valley", "slug": "holiday-valley", "brand": "Other", "pass_brands": None},
                    {"name": "Bristol Mountain", "slug": "bristol-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Greek Peak", "slug": "greek-peak", "brand": "Other", "pass_brands": None},
                ]
            },
            "PA": {
                "state_full": "Pennsylvania",
                "resorts": [
                    {"name": "Seven Springs", "slug": "seven-springs", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Hidden Valley PA", "slug": "hidden-valley-pa", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Laurel Mountain", "slug": "laurel-mountain", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Blue Mountain", "slug": "blue-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Camelback", "slug": "camelback", "brand": "Other", "pass_brands": None},
                    {"name": "Jack Frost", "slug": "jack-frost", "brand": "Other", "pass_brands": None},
                    {"name": "Big Boulder", "slug": "big-boulder", "brand": "Other", "pass_brands": None},
                ]
            },
            "VT": {
                "state_full": "Vermont",
                "resorts": [
                    {"name": "Killington", "slug": "killington", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Pico", "slug": "pico", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Sugarbush", "slug": "sugarbush", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Stratton", "slug": "stratton", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Stowe", "slug": "stowe", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Okemo", "slug": "okemo", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Mount Snow", "slug": "mount-snow", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Jay Peak", "slug": "jay-peak", "brand": "Other", "pass_brands": None},
                    {"name": "Smugglers Notch", "slug": "smugglers-notch", "brand": "Other", "pass_brands": None},
                ]
            },
            "NH": {
                "state_full": "New Hampshire",
                "resorts": [
                    {"name": "Attitash", "slug": "attitash", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Wildcat", "slug": "wildcat", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Loon Mountain", "slug": "loon-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Cannon Mountain", "slug": "cannon-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Bretton Woods", "slug": "bretton-woods", "brand": "Other", "pass_brands": None},
                    {"name": "Waterville Valley", "slug": "waterville-valley", "brand": "Other", "pass_brands": None},
                ]
            },
            "ME": {
                "state_full": "Maine",
                "resorts": [
                    {"name": "Sugarloaf", "slug": "sugarloaf", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Sunday River", "slug": "sunday-river", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Saddleback", "slug": "saddleback", "brand": "Other", "pass_brands": None},
                ]
            },
            "MA": {
                "state_full": "Massachusetts",
                "resorts": [
                    {"name": "Wachusett Mountain", "slug": "wachusett-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Berkshire East", "slug": "berkshire-east", "brand": "Other", "pass_brands": None},
                    {"name": "Jiminy Peak", "slug": "jiminy-peak", "brand": "Other", "pass_brands": None},
                ]
            },
            "CT": {
                "state_full": "Connecticut",
                "resorts": [
                    {"name": "Mohawk Mountain", "slug": "mohawk-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
            "NJ": {
                "state_full": "New Jersey",
                "resorts": [
                    {"name": "Mountain Creek", "slug": "mountain-creek", "brand": "Other", "pass_brands": None},
                ]
            },
            "MD": {
                "state_full": "Maryland",
                "resorts": [
                    {"name": "Wisp Resort", "slug": "wisp-resort", "brand": "Other", "pass_brands": None},
                ]
            },
            "VA": {
                "state_full": "Virginia",
                "resorts": [
                    {"name": "Wintergreen", "slug": "wintergreen", "brand": "Other", "pass_brands": None},
                    {"name": "Massanutten", "slug": "massanutten", "brand": "Other", "pass_brands": None},
                ]
            },
            "WV": {
                "state_full": "West Virginia",
                "resorts": [
                    {"name": "Snowshoe Mountain", "slug": "snowshoe-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Timberline Mountain", "slug": "timberline-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
            "NC": {
                "state_full": "North Carolina",
                "resorts": [
                    {"name": "Sugar Mountain", "slug": "sugar-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Beech Mountain", "slug": "beech-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Appalachian Ski Mountain", "slug": "appalachian-ski-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
            "TN": {
                "state_full": "Tennessee",
                "resorts": [
                    {"name": "Ober Mountain", "slug": "ober-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
        }
        
        created = []
        existed = []
        
        for state_code, state_data in resorts_by_state.items():
            for resort_data in state_data["resorts"]:
                existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
                if existing:
                    existed.append(f"{resort_data['name']} ({state_code})")
                else:
                    new_resort = Resort(
                        name=resort_data["name"],
                        slug=resort_data["slug"],
                        state=state_code,
                        state_full=state_data["state_full"],
                        country="US",
                        brand=resort_data["brand"],
                        pass_brands=resort_data["pass_brands"],
                        is_active=True
                    )
                    db.session.add(new_resort)
                    created.append(f"{resort_data['name']} ({state_code})")
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed eastern resorts: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/seed-canadian-resorts", methods=["GET", "POST"])
def seed_canadian_resorts_endpoint():
    """
    HTTP endpoint to add missing Canadian ski resorts.
    
    Usage: GET https://yourapp.replit.dev/admin/seed-canadian-resorts
    
    This is idempotent - safe to call multiple times.
    Only creates resorts that don't already exist (checked by slug).
    """
    try:
        resorts_by_province = {
            "BC": {
                "state_full": "British Columbia",
                "resorts": [
                    {"name": "Whistler Blackcomb", "slug": "whistler-blackcomb", "brand": "Epic", "pass_brands": "Epic"},
                    {"name": "Revelstoke", "slug": "revelstoke", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Sun Peaks", "slug": "sun-peaks", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Red Mountain", "slug": "red-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Panorama", "slug": "panorama", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Cypress Mountain", "slug": "cypress-mountain", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Big White", "slug": "big-white", "brand": "Other", "pass_brands": None},
                    {"name": "SilverStar", "slug": "silverstar", "brand": "Other", "pass_brands": None},
                    {"name": "Fernie", "slug": "fernie", "brand": "Other", "pass_brands": None},
                    {"name": "Kicking Horse", "slug": "kicking-horse", "brand": "Other", "pass_brands": None},
                    {"name": "Whitewater", "slug": "whitewater", "brand": "Other", "pass_brands": None},
                    {"name": "Kimberley", "slug": "kimberley", "brand": "Other", "pass_brands": None},
                    {"name": "Manning Park", "slug": "manning-park", "brand": "Other", "pass_brands": None},
                    {"name": "Sasquatch Mountain", "slug": "sasquatch-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Apex Mountain", "slug": "apex-mountain", "brand": "Indy", "pass_brands": "Indy"},
                ]
            },
            "AB": {
                "state_full": "Alberta",
                "resorts": [
                    {"name": "Lake Louise", "slug": "lake-louise", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Sunshine Village", "slug": "sunshine-village", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Marmot Basin", "slug": "marmot-basin", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Norquay", "slug": "norquay", "brand": "Other", "pass_brands": None},
                    {"name": "Castle Mountain", "slug": "castle-mountain", "brand": "Indy", "pass_brands": "Indy"},
                ]
            },
            "ON": {
                "state_full": "Ontario",
                "resorts": [
                    {"name": "Blue Mountain", "slug": "blue-mountain-on", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Mount St. Louis Moonstone", "slug": "mount-st-louis-moonstone", "brand": "Other", "pass_brands": None},
                    {"name": "Horseshoe Resort", "slug": "horseshoe-resort", "brand": "Other", "pass_brands": None},
                    {"name": "Glen Eden", "slug": "glen-eden", "brand": "Other", "pass_brands": None},
                ]
            },
            "QC": {
                "state_full": "Quebec",
                "resorts": [
                    {"name": "Tremblant", "slug": "tremblant", "brand": "Ikon", "pass_brands": "Ikon"},
                    {"name": "Le Massif", "slug": "le-massif", "brand": "Other", "pass_brands": None},
                    {"name": "Mont Sainte-Anne", "slug": "mont-sainte-anne", "brand": "Other", "pass_brands": None},
                    {"name": "Bromont", "slug": "bromont", "brand": "Other", "pass_brands": None},
                    {"name": "Stoneham", "slug": "stoneham", "brand": "Other", "pass_brands": None},
                    {"name": "Mont Orford", "slug": "mont-orford", "brand": "Other", "pass_brands": None},
                ]
            },
            "NS": {
                "state_full": "Nova Scotia",
                "resorts": [
                    {"name": "Ski Martock", "slug": "ski-martock", "brand": "Other", "pass_brands": None},
                    {"name": "Wentworth", "slug": "wentworth", "brand": "Other", "pass_brands": None},
                ]
            },
            "NL": {
                "state_full": "Newfoundland",
                "resorts": [
                    {"name": "Marble Mountain", "slug": "marble-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
            "MB": {
                "state_full": "Manitoba",
                "resorts": [
                    {"name": "Holiday Mountain", "slug": "holiday-mountain", "brand": "Other", "pass_brands": None},
                    {"name": "Asessippi", "slug": "asessippi", "brand": "Other", "pass_brands": None},
                ]
            },
            "SK": {
                "state_full": "Saskatchewan",
                "resorts": [
                    {"name": "Table Mountain", "slug": "table-mountain", "brand": "Other", "pass_brands": None},
                ]
            },
            "YT": {
                "state_full": "Yukon",
                "resorts": [
                    {"name": "Mount Sima", "slug": "mount-sima", "brand": "Other", "pass_brands": None},
                ]
            },
        }
        
        created = []
        existed = []
        
        for province_code, province_data in resorts_by_province.items():
            for resort_data in province_data["resorts"]:
                existing = Resort.query.filter_by(slug=resort_data["slug"]).first()
                if existing:
                    existed.append(f"{resort_data['name']} ({province_code})")
                else:
                    new_resort = Resort(
                        name=resort_data["name"],
                        slug=resort_data["slug"],
                        state=province_code,
                        state_full=province_data["state_full"],
                        country="CA",
                        brand=resort_data["brand"],
                        pass_brands=resort_data["pass_brands"],
                        is_active=True
                    )
                    db.session.add(new_resort)
                    created.append(f"{resort_data['name']} ({province_code})")
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Created {len(created)} resorts, {len(existed)} already existed",
            "created": created,
            "already_existed": existed
        }), 200
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Failed to seed Canadian resorts: {str(e)}",
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


@app.route("/group-trip/<int:trip_id>/accommodation", methods=["POST"])
@login_required
def update_group_trip_accommodation(trip_id):
    """Update accommodation status (host-only)."""
    trip = GroupTrip.query.get_or_404(trip_id)
    
    if trip.host_id != current_user.id:
        return jsonify({"success": False, "error": "Only host can update"}), 403
    
    data = request.get_json()
    status_name = data.get("accommodation_status", "").upper()
    
    if status_name == "":
        trip.accommodation_status = None
    elif status_name in ["BOOKED", "NOT_YET", "STAYING_WITH_FRIENDS"]:
        try:
            trip.accommodation_status = AccommodationStatus[status_name]
        except KeyError:
            return jsonify({"success": False, "error": "Invalid status"}), 400
    else:
        return jsonify({"success": False, "error": "Invalid status"}), 400
    
    db.session.commit()
    return jsonify({"success": True})


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
def admin_version():
    """Simple version check endpoint to verify production deployment."""
    return jsonify({
        "version": "2025-12-25-v5",
        "status": "ok",
        "endpoints_available": [
            "/admin/version",
            "/admin/backfill-country-codes",
            "/admin/resorts-audit",
            "/admin/sync-resorts-from-dev (deprecated)",
            "/admin/sync-resorts-from-canonical",
            "/admin/init-db"
        ]
    })


@app.route("/admin/resorts-audit", methods=["GET"])
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


@app.route("/admin/sync-resorts-from-dev", methods=["GET", "POST"])
def sync_resorts_from_dev():
    """
    Sync resorts from development canonical list to production.
    IDEMPOTENT - safe to run multiple times.
    
    Behavior:
    - INSERT: Resorts in DEV but missing in PROD
    - UPDATE: pass_brands mismatches (DEV wins)
    - SKIP: Matching resorts
    - NO DELETES: PROD-only resorts left untouched
    
    Matching key: (name.lower().strip(), state_code.upper(), country_code.upper())
    """
    
    # Canonical resort data from DEVELOPMENT (source of truth)
    # This list represents the 266 resorts in development
    CANONICAL_RESORTS = [
        # === UNITED STATES (200 resorts) ===
        # Colorado
        {"name": "Vail", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Beaver Creek", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Breckenridge", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Keystone", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Crested Butte", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Aspen Snowmass", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon,MountainCollective"},
        {"name": "Aspen Highlands", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Aspen Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Buttermilk", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Winter Park", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Steamboat", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Copper Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Eldora", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Arapahoe Basin", "state_code": "CO", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Loveland", "state_code": "CO", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Monarch Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Ski Cooper", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Wolf Creek", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Telluride", "state_code": "CO", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Purgatory Resort", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Silverton Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Sunlight Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Howelsen Hill", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        {"name": "Echo Mountain", "state_code": "CO", "country_code": "US", "pass_brands": "Other"},
        # Utah
        {"name": "Park City", "state_code": "UT", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Deer Valley", "state_code": "UT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Snowbird", "state_code": "UT", "country_code": "US", "pass_brands": "Ikon,MountainCollective"},
        {"name": "Alta", "state_code": "UT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Brighton", "state_code": "UT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Solitude", "state_code": "UT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Snowbasin", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Powder Mountain", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Brian Head", "state_code": "UT", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Sundance", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Nordic Valley", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Cherry Peak", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Eagle Point", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Beaver Mountain", "state_code": "UT", "country_code": "US", "pass_brands": "Other"},
        # California
        {"name": "Mammoth Mountain", "state_code": "CA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Palisades Tahoe", "state_code": "CA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Heavenly", "state_code": "CA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Kirkwood", "state_code": "CA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Northstar", "state_code": "CA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Sugar Bowl", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Rose", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Bear Valley", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "China Peak", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Dodge Ridge", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "June Mountain", "state_code": "CA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Big Bear", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mountain High", "state_code": "CA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Snow Summit", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Snow Valley", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Baldy", "state_code": "CA", "country_code": "US", "pass_brands": "Other"},
        # Wyoming
        {"name": "Jackson Hole Mountain Resort", "state_code": "WY", "country_code": "US", "pass_brands": "Ikon,MountainCollective"},
        {"name": "Grand Targhee", "state_code": "WY", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Snow King", "state_code": "WY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Snowy Range", "state_code": "WY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Hogadon", "state_code": "WY", "country_code": "US", "pass_brands": "Other"},
        {"name": "White Pine", "state_code": "WY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Meadowlark", "state_code": "WY", "country_code": "US", "pass_brands": "Other"},
        # Montana
        {"name": "Big Sky", "state_code": "MT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Whitefish Mountain", "state_code": "MT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Bridger Bowl", "state_code": "MT", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Red Lodge Mountain", "state_code": "MT", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Lost Trail", "state_code": "MT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Lookout Pass", "state_code": "MT", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Showdown", "state_code": "MT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Blacktail Mountain", "state_code": "MT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Great Divide", "state_code": "MT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Maverick Mountain", "state_code": "MT", "country_code": "US", "pass_brands": "Other"},
        # Idaho
        {"name": "Sun Valley", "state_code": "ID", "country_code": "US", "pass_brands": "Ikon,MountainCollective"},
        {"name": "Schweitzer", "state_code": "ID", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Brundage Mountain", "state_code": "ID", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Tamarack", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Silver Mountain", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Bogus Basin", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Pebble Creek", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Kelly Canyon", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Soldier Mountain", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        {"name": "Magic Mountain", "state_code": "ID", "country_code": "US", "pass_brands": "Other"},
        # Washington
        {"name": "Crystal Mountain", "state_code": "WA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Stevens Pass", "state_code": "WA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Mt. Baker", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Snoqualmie", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mission Ridge", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "White Pass", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "49 Degrees North", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Spokane", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Loup Loup", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Bluewood", "state_code": "WA", "country_code": "US", "pass_brands": "Other"},
        # Oregon
        {"name": "Mt. Bachelor", "state_code": "OR", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Mt. Hood Meadows", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        {"name": "Timberline Lodge", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        {"name": "Ski Bowl", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        {"name": "Hoodoo", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        {"name": "Willamette Pass", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        {"name": "Anthony Lakes", "state_code": "OR", "country_code": "US", "pass_brands": "Other"},
        # New Mexico
        {"name": "Taos Ski Valley", "state_code": "NM", "country_code": "US", "pass_brands": "Ikon,MountainCollective"},
        {"name": "Ski Santa Fe", "state_code": "NM", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Angel Fire", "state_code": "NM", "country_code": "US", "pass_brands": "Other"},
        {"name": "Red River", "state_code": "NM", "country_code": "US", "pass_brands": "Other"},
        {"name": "Sipapu", "state_code": "NM", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Ski Apache", "state_code": "NM", "country_code": "US", "pass_brands": "Other"},
        {"name": "Pajarito", "state_code": "NM", "country_code": "US", "pass_brands": "Other"},
        # Vermont
        {"name": "Stowe", "state_code": "VT", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Killington", "state_code": "VT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Sugarbush", "state_code": "VT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Okemo", "state_code": "VT", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Mount Snow", "state_code": "VT", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Stratton", "state_code": "VT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Jay Peak", "state_code": "VT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Smugglers Notch", "state_code": "VT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Pico Mountain", "state_code": "VT", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Burke Mountain", "state_code": "VT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Magic Mountain", "state_code": "VT", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Suicide Six", "state_code": "VT", "country_code": "US", "pass_brands": "Other"},
        # New Hampshire
        {"name": "Loon Mountain", "state_code": "NH", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Cannon Mountain", "state_code": "NH", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Bretton Woods", "state_code": "NH", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Attitash", "state_code": "NH", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Wildcat Mountain", "state_code": "NH", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Waterville Valley", "state_code": "NH", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Gunstock", "state_code": "NH", "country_code": "US", "pass_brands": "Other"},
        {"name": "Ragged Mountain", "state_code": "NH", "country_code": "US", "pass_brands": "Other"},
        {"name": "Pats Peak", "state_code": "NH", "country_code": "US", "pass_brands": "Other"},
        {"name": "King Pine", "state_code": "NH", "country_code": "US", "pass_brands": "Other"},
        # Maine
        {"name": "Sunday River", "state_code": "ME", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Sugarloaf", "state_code": "ME", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Saddleback", "state_code": "ME", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Big Rock", "state_code": "ME", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Abram", "state_code": "ME", "country_code": "US", "pass_brands": "Other"},
        {"name": "Shawnee Peak", "state_code": "ME", "country_code": "US", "pass_brands": "Other"},
        {"name": "Lost Valley", "state_code": "ME", "country_code": "US", "pass_brands": "Other"},
        {"name": "Camden Snow Bowl", "state_code": "ME", "country_code": "US", "pass_brands": "Other"},
        # New York
        {"name": "Whiteface", "state_code": "NY", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Gore Mountain", "state_code": "NY", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Hunter Mountain", "state_code": "NY", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Windham Mountain", "state_code": "NY", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Holiday Valley", "state_code": "NY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Belleayre", "state_code": "NY", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Greek Peak", "state_code": "NY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Peek'n Peak", "state_code": "NY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Bristol Mountain", "state_code": "NY", "country_code": "US", "pass_brands": "Other"},
        {"name": "Plattekill", "state_code": "NY", "country_code": "US", "pass_brands": "Indy"},
        # Pennsylvania
        {"name": "Seven Springs", "state_code": "PA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Camelback", "state_code": "PA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Blue Mountain", "state_code": "PA", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Jack Frost", "state_code": "PA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Big Boulder", "state_code": "PA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Elk Mountain", "state_code": "PA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Shawnee Mountain", "state_code": "PA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Hidden Valley", "state_code": "PA", "country_code": "US", "pass_brands": "Epic"},
        # Michigan
        {"name": "Boyne Mountain", "state_code": "MI", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Boyne Highlands", "state_code": "MI", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Crystal Mountain", "state_code": "MI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Shanty Creek", "state_code": "MI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Nubs Nob", "state_code": "MI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Brighton", "state_code": "MI", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Mt. Bohemia", "state_code": "MI", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Caberfae Peaks", "state_code": "MI", "country_code": "US", "pass_brands": "Other"},
        # Wisconsin
        {"name": "Granite Peak", "state_code": "WI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Devil's Head", "state_code": "WI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Cascade Mountain", "state_code": "WI", "country_code": "US", "pass_brands": "Other"},
        {"name": "Wilmot Mountain", "state_code": "WI", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Whitecap Mountain", "state_code": "WI", "country_code": "US", "pass_brands": "Other"},
        # West Virginia
        {"name": "Snowshoe Mountain", "state_code": "WV", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Canaan Valley", "state_code": "WV", "country_code": "US", "pass_brands": "Other"},
        {"name": "Timberline Mountain", "state_code": "WV", "country_code": "US", "pass_brands": "Other"},
        {"name": "Winterplace", "state_code": "WV", "country_code": "US", "pass_brands": "Other"},
        # Alaska
        {"name": "Alyeska", "state_code": "AK", "country_code": "US", "pass_brands": "Ikon"},
        # Nevada
        {"name": "Lee Canyon", "state_code": "NV", "country_code": "US", "pass_brands": "Other"},
        # Arizona
        {"name": "Arizona Snowbowl", "state_code": "AZ", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Sunrise Park", "state_code": "AZ", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mt. Lemmon", "state_code": "AZ", "country_code": "US", "pass_brands": "Other"},
        # Minnesota
        {"name": "Lutsen Mountains", "state_code": "MN", "country_code": "US", "pass_brands": "Ikon"},
        {"name": "Spirit Mountain", "state_code": "MN", "country_code": "US", "pass_brands": "Other"},
        {"name": "Giants Ridge", "state_code": "MN", "country_code": "US", "pass_brands": "Other"},
        {"name": "Afton Alps", "state_code": "MN", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Wild Mountain", "state_code": "MN", "country_code": "US", "pass_brands": "Other"},
        # Massachusetts
        {"name": "Wachusett", "state_code": "MA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Jiminy Peak", "state_code": "MA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Berkshire East", "state_code": "MA", "country_code": "US", "pass_brands": "Indy"},
        {"name": "Ski Butternut", "state_code": "MA", "country_code": "US", "pass_brands": "Other"},
        # Connecticut
        {"name": "Mohawk Mountain", "state_code": "CT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Mount Southington", "state_code": "CT", "country_code": "US", "pass_brands": "Other"},
        {"name": "Ski Sundown", "state_code": "CT", "country_code": "US", "pass_brands": "Other"},
        # North Carolina
        {"name": "Beech Mountain", "state_code": "NC", "country_code": "US", "pass_brands": "Other"},
        {"name": "Sugar Mountain", "state_code": "NC", "country_code": "US", "pass_brands": "Other"},
        {"name": "Appalachian Ski Mountain", "state_code": "NC", "country_code": "US", "pass_brands": "Other"},
        {"name": "Cataloochee", "state_code": "NC", "country_code": "US", "pass_brands": "Other"},
        # Tennessee
        {"name": "Ober Mountain", "state_code": "TN", "country_code": "US", "pass_brands": "Other"},
        # Virginia
        {"name": "Wintergreen", "state_code": "VA", "country_code": "US", "pass_brands": "Epic"},
        {"name": "Massanutten", "state_code": "VA", "country_code": "US", "pass_brands": "Other"},
        {"name": "The Homestead", "state_code": "VA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Bryce Resort", "state_code": "VA", "country_code": "US", "pass_brands": "Other"},
        # Maryland
        {"name": "Wisp Resort", "state_code": "MD", "country_code": "US", "pass_brands": "Other"},
        # New Jersey
        {"name": "Mountain Creek", "state_code": "NJ", "country_code": "US", "pass_brands": "Ikon"},
        # South Dakota
        {"name": "Terry Peak", "state_code": "SD", "country_code": "US", "pass_brands": "Other"},
        # North Dakota
        {"name": "Huff Hills", "state_code": "ND", "country_code": "US", "pass_brands": "Other"},
        # Iowa
        {"name": "Sundown Mountain", "state_code": "IA", "country_code": "US", "pass_brands": "Other"},
        {"name": "Seven Oaks", "state_code": "IA", "country_code": "US", "pass_brands": "Other"},
        
        # === CANADA (43 resorts) ===
        # British Columbia
        {"name": "Whistler Blackcomb", "state_code": "BC", "country_code": "CA", "pass_brands": "Epic"},
        {"name": "Revelstoke Mountain Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Sun Peaks Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Big White Ski Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "SilverStar Mountain Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Kicking Horse Mountain Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Epic"},
        {"name": "Fernie Alpine Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Epic"},
        {"name": "Panorama Mountain Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Red Mountain Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Red Mountain", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Whitewater Ski Resort", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Whitewater", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Cypress Mountain", "state_code": "BC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Apex Mountain", "state_code": "BC", "country_code": "CA", "pass_brands": "Indy"},
        {"name": "Kimberley", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Manning Park", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Sasquatch Mountain", "state_code": "BC", "country_code": "CA", "pass_brands": "Other"},
        # Alberta
        {"name": "Lake Louise Ski Resort", "state_code": "AB", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Banff Sunshine Village", "state_code": "AB", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Sunshine Village", "state_code": "AB", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Nakiska Ski Area", "state_code": "AB", "country_code": "CA", "pass_brands": "Epic"},
        {"name": "Marmot Basin", "state_code": "AB", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Mt. Norquay", "state_code": "AB", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Norquay", "state_code": "AB", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Castle Mountain", "state_code": "AB", "country_code": "CA", "pass_brands": "Indy"},
        # Ontario
        {"name": "Blue Mountain Resort", "state_code": "ON", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Mount St. Louis Moonstone", "state_code": "ON", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Horseshoe Resort", "state_code": "ON", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Glen Eden", "state_code": "ON", "country_code": "CA", "pass_brands": "Other"},
        # Quebec
        {"name": "Tremblant", "state_code": "QC", "country_code": "CA", "pass_brands": "Ikon"},
        {"name": "Le Massif de Charlevoix", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Le Massif", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Mont-Sainte-Anne", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Stoneham Mountain Resort", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Bromont", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Mont Orford", "state_code": "QC", "country_code": "CA", "pass_brands": "Other"},
        # Nova Scotia
        {"name": "Ski Martock", "state_code": "NS", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Wentworth", "state_code": "NS", "country_code": "CA", "pass_brands": "Other"},
        # Newfoundland
        {"name": "Marble Mountain", "state_code": "NL", "country_code": "CA", "pass_brands": "Other"},
        # Manitoba
        {"name": "Holiday Mountain", "state_code": "MB", "country_code": "CA", "pass_brands": "Other"},
        {"name": "Asessippi", "state_code": "MB", "country_code": "CA", "pass_brands": "Other"},
        # Saskatchewan
        {"name": "Table Mountain", "state_code": "SK", "country_code": "CA", "pass_brands": "Other"},
        # Yukon
        {"name": "Mount Sima", "state_code": "YT", "country_code": "CA", "pass_brands": "Other"},
        
        # === JAPAN (6 resorts) ===
        {"name": "Niseko", "state_code": "Hokkaido", "country_code": "JP", "pass_brands": "Ikon"},
        {"name": "Rusutsu", "state_code": "Hokkaido", "country_code": "JP", "pass_brands": "Ikon"},
        {"name": "Hakuba", "state_code": "Nagano", "country_code": "JP", "pass_brands": "Epic"},
        {"name": "Nozawa Onsen", "state_code": "Nagano", "country_code": "JP", "pass_brands": "Other"},
        {"name": "Myoko Kogen", "state_code": "Niigata", "country_code": "JP", "pass_brands": "Other"},
        {"name": "Furano", "state_code": "Hokkaido", "country_code": "JP", "pass_brands": "Other"},
        
        # === FRANCE (9 resorts) ===
        {"name": "Chamonix", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Ikon"},
        {"name": "Val d'Isère", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Ikon"},
        {"name": "Courchevel", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "Méribel", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "Val Thorens", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "Les Arcs", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "La Plagne", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "Megève", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        {"name": "Les Deux Alpes", "state_code": "Auvergne-Rhône-Alpes", "country_code": "FR", "pass_brands": "Other"},
        
        # === SWITZERLAND (4 resorts) ===
        {"name": "Zermatt", "state_code": "Valais", "country_code": "CH", "pass_brands": "Ikon"},
        {"name": "Verbier", "state_code": "Valais", "country_code": "CH", "pass_brands": "Other"},
        {"name": "St. Moritz", "state_code": "Graubünden", "country_code": "CH", "pass_brands": "Other"},
        {"name": "Gstaad", "state_code": "Bern", "country_code": "CH", "pass_brands": "Other"},
        
        # === AUSTRIA (3 resorts) ===
        {"name": "St. Anton am Arlberg", "state_code": "Tyrol", "country_code": "AT", "pass_brands": "Ikon"},
        {"name": "Kitzbühel", "state_code": "Tyrol", "country_code": "AT", "pass_brands": "Other"},
        {"name": "Ischgl", "state_code": "Tyrol", "country_code": "AT", "pass_brands": "Other"},
        
        # === ITALY (1 resort) ===
        {"name": "Dolomiti Superski", "state_code": "Trentino-Alto Adige", "country_code": "IT", "pass_brands": "Other"},
    ]
    
    def normalize_key(name, state_code, country_code):
        return (
            (name or '').strip().lower(),
            (state_code or '').strip().upper(),
            (country_code or '').strip().upper()
        )
    
    try:
        # Build lookup of existing resorts in production by normalized key
        existing_resorts = Resort.query.all()
        prod_by_key = {}
        for r in existing_resorts:
            key = normalize_key(r.name, r.state_code or r.state, r.country_code or r.country)
            prod_by_key[key] = r
        
        inserted = 0
        updated = 0
        skipped = 0
        details = {"inserted": [], "updated": [], "skipped": []}
        
        for canonical in CANONICAL_RESORTS:
            name = (canonical.get("name") or "").strip()
            state_code = (canonical.get("state_code") or "").strip()
            country_code = (canonical.get("country_code") or "US").strip()
            pass_brands = (canonical.get("pass_brands") or "").strip()
            
            key = normalize_key(name, state_code, country_code)
            
            if key in prod_by_key:
                # Resort exists - check if update needed
                existing = prod_by_key[key]
                existing_pass_brands = existing.pass_brands or existing.brand or ""
                
                if existing_pass_brands != pass_brands:
                    # Update pass_brands
                    existing.pass_brands = pass_brands
                    existing.brand = pass_brands.split(',')[0] if pass_brands else "Other"
                    updated += 1
                    details["updated"].append(f"{name} ({state_code}): {existing_pass_brands} -> {pass_brands}")
                else:
                    skipped += 1
                    if len(details["skipped"]) < 10:
                        details["skipped"].append(f"{name} ({state_code})")
            else:
                # Resort missing - INSERT with unique slug
                import re
                base_slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace("'", ""))
                slug = f"{base_slug}-{state_code.lower()}-{country_code.lower()}"
                
                # Check if slug exists, add suffix if needed
                existing_slug = Resort.query.filter_by(slug=slug).first()
                if existing_slug:
                    slug = f"{slug}-2"
                
                new_resort = Resort(
                    name=name,
                    slug=slug,
                    state=state_code,
                    state_code=state_code,
                    state_full=state_code,
                    country=country_code,
                    country_code=country_code,
                    brand=pass_brands.split(',')[0] if pass_brands else "Other",
                    pass_brands=pass_brands
                )
                db.session.add(new_resort)
                db.session.flush()  # Flush each insert to avoid bulk constraint issues
                inserted += 1
                details["inserted"].append(f"{name} ({state_code}, {country_code})")
        
        db.session.commit()
        
        # Final count
        final_count = Resort.query.count()
        
        return jsonify({
            "status": "success",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "deleted": 0,
            "final_resort_count": final_count,
            "details": {
                "inserted": details["inserted"][:50],
                "updated": details["updated"],
                "skipped_sample": details["skipped"]
            }
        }), 200
        
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route("/admin/sync-resorts-from-canonical", methods=["GET", "POST"])
def sync_resorts_from_canonical():
    """
    Sync resorts from canonical JSON file to production.
    IDEMPOTENT - safe to run multiple times.
    
    Query params / POST body:
    - dry_run: if true, compute diff but don't write (default: true for GET, false for POST)
    
    Behavior:
    - INSERT: Resorts in canonical but missing in DB
    - UPDATE: pass_brands mismatches (canonical wins)
    - SKIP: Matching resorts
    - NO DELETES: DB-only resorts left untouched
    
    Matching key: (name.lower().strip(), state_code.upper(), country_code.upper())
    """
    import os
    import re
    import json
    
    # Determine dry_run mode (default: true for safety)
    if request.method == 'POST':
        dry_run = request.json.get('dry_run', False) if request.is_json else request.args.get('dry_run', 'false').lower() == 'true'
    else:
        dry_run = request.args.get('dry_run', 'true').lower() != 'false'
    
    # Load canonical data from JSON file
    canonical_file = os.path.join(os.path.dirname(__file__), 'data', 'canonical_resorts.json')
    
    if not os.path.exists(canonical_file):
        return jsonify({
            "status": "error",
            "message": f"Canonical file not found: {canonical_file}",
            "dry_run": dry_run
        }), 404
    
    try:
        with open(canonical_file, 'r') as f:
            canonical_data = json.load(f)
        
        canonical_resorts = canonical_data.get('resorts', [])
        canonical_version = canonical_data.get('version', 'unknown')
        
        if not canonical_resorts:
            return jsonify({
                "status": "error",
                "message": "No resorts found in canonical file",
                "dry_run": dry_run
            }), 400
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to load canonical file: {str(e)}",
            "dry_run": dry_run
        }), 500
    
    def normalize_key(name, state_code, country_code):
        return (
            (name or '').strip().lower(),
            (state_code or '').strip().upper(),
            (country_code or '').strip().upper()
        )
    
    try:
        # Build lookup of existing resorts in DB by normalized key
        existing_resorts = Resort.query.all()
        db_by_key = {}
        for r in existing_resorts:
            key = normalize_key(r.name, r.state_code or r.state, r.country_code or r.country)
            db_by_key[key] = r
        
        # Track which DB resorts were matched
        matched_keys = set()
        
        inserted = 0
        updated = 0
        skipped = 0
        details = {"inserted": [], "updated": [], "skipped": []}
        
        for canonical in canonical_resorts:
            name = (canonical.get("name") or "").strip()
            state_code = (canonical.get("state_code") or "").strip()
            country_code = (canonical.get("country_code") or "US").strip()
            pass_brands = (canonical.get("pass_brands") or "").strip()
            is_region = canonical.get("is_region", False)
            
            key = normalize_key(name, state_code, country_code)
            matched_keys.add(key)
            
            if key in db_by_key:
                # Resort exists - check if update needed
                existing = db_by_key[key]
                existing_pass_brands = existing.pass_brands or existing.brand or ""
                
                if existing_pass_brands != pass_brands:
                    # Update pass_brands (only if not dry_run)
                    if not dry_run:
                        existing.pass_brands = pass_brands
                        existing.brand = pass_brands.split(',')[0] if pass_brands else "Other"
                    updated += 1
                    if len(details["updated"]) < 10:
                        details["updated"].append(f"{name} ({state_code}): '{existing_pass_brands}' -> '{pass_brands}'")
                else:
                    skipped += 1
                    if len(details["skipped"]) < 10:
                        details["skipped"].append(f"{name} ({state_code})")
            else:
                # Resort missing - INSERT
                if not dry_run:
                    base_slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-').replace("'", ""))
                    slug = f"{base_slug}-{state_code.lower()}-{country_code.lower()}"
                    
                    # Check if slug exists, add suffix if needed
                    existing_slug = Resort.query.filter_by(slug=slug).first()
                    if existing_slug:
                        slug = f"{slug}-2"
                    
                    new_resort = Resort(
                        name=name,
                        slug=slug,
                        state=state_code,
                        state_code=state_code,
                        state_full=state_code,
                        country=country_code,
                        country_code=country_code,
                        brand=pass_brands.split(',')[0] if pass_brands else "Other",
                        pass_brands=pass_brands
                    )
                    db.session.add(new_resort)
                    db.session.flush()
                
                inserted += 1
                if len(details["inserted"]) < 10:
                    details["inserted"].append(f"{name} ({state_code}, {country_code})")
        
        # Count DB-only resorts (not in canonical)
        untouched_prod_only = len(db_by_key) - len(matched_keys & set(db_by_key.keys()))
        
        if not dry_run:
            db.session.commit()
        
        # Final count
        final_count = Resort.query.count() if not dry_run else len(existing_resorts) + inserted
        
        return jsonify({
            "status": "success",
            "dry_run": dry_run,
            "canonical_version": canonical_version,
            "canonical_count": len(canonical_resorts),
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "untouched_prod_only": untouched_prod_only,
            "deleted": 0,
            "final_resort_count": final_count,
            "details": {
                "inserted_sample": details["inserted"],
                "updated_sample": details["updated"],
                "skipped_sample": details["skipped"]
            }
        }), 200
        
    except Exception as e:
        import traceback
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc(),
            "dry_run": dry_run
        }), 500


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
    
    # Get unique countries and states for filters
    countries = db.session.query(Resort.country_code).distinct().order_by(Resort.country_code).all()
    countries = [c[0] for c in countries if c[0]]
    
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
                         last_export_info=last_export_info,
                         total_count=len(resorts))


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
    pass_brands = (data.get('pass_brands') or '').strip() or None
    
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
    
    country_names = {
        'US': 'United States', 'CA': 'Canada', 'FR': 'France',
        'CH': 'Switzerland', 'AT': 'Austria', 'IT': 'Italy',
        'JP': 'Japan', 'NZ': 'New Zealand', 'AU': 'Australia',
        'CL': 'Chile', 'AR': 'Argentina', 'NO': 'Norway',
        'SE': 'Sweden', 'ES': 'Spain', 'AD': 'Andorra', 'DE': 'Germany'
    }
    
    new_resort = Resort(
        name=name,
        country=country_code,
        country_code=country_code,
        country_name=country_names.get(country_code, country_code),
        state=state_code,
        state_code=state_code,
        state_name=state_code,
        state_full=state_code,
        brand=None,
        pass_brands=pass_brands,
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
                'pass_brands': new_resort.pass_brands,
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
            'country_code': r.country_code or r.country or 'US',
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
            pass_brands = (r_data.get('pass_brands') or '').strip()
            is_region = r_data.get('is_region', False)
            
            canonical_key = f"{name}|{state_code}|{country_code}".lower()
            canonical_keys.add(canonical_key)
            
            existing = existing_by_key.get(canonical_key)
            
            if existing:
                existing.name = name
                existing.state_code = state_code
                existing.state = state_code
                existing.country_code = country_code
                existing.country = country_code
                existing.pass_brands = pass_brands
                existing.brand = pass_brands.split(',')[0] if pass_brands else 'Other'
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
                    country=country_code,
                    country_code=country_code,
                    pass_brands=pass_brands,
                    brand=pass_brands.split(',')[0] if pass_brands else 'Other',
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
