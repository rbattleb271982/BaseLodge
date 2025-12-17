import os
import secrets
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation, InviteToken, Resort, GroupTrip, TripGuest, GuestStatus, check_shared_upcoming_trip, EquipmentSetup, EquipmentSlot, EquipmentDiscipline, AccommodationStatus, TransportationStatus
from debug_routes import debug_bp
from services.open_dates import get_open_date_matches
from io import BytesIO
import segno
import random
import click

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

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.before_request
def before_request_handlers():
    # Make sessions permanent for Replit iframe compatibility
    session.permanent = True
    
    # Require profile setup for authenticated users
    excluded_endpoints = {'auth', 'setup_profile', 'logout', 'static', 'invite_token_landing', 'test_login_direct'}
    if request.endpoint in excluded_endpoints:
        return None
    if current_user.is_authenticated:
        if not current_user.rider_type or not current_user.pass_type:
            return redirect(url_for('setup_profile'))
    return None

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        admin_email = "richardbattlebaxter@gmail.com"
        if not current_user.is_authenticated or current_user.email != admin_email:
            return "Admin privileges required.", 403
        return f(*args, **kwargs)
    return wrapper

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
    return "An internal error occurred. Please check logs.", 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle all exceptions with full traceback logging (except HTTP errors)."""
    from werkzeug.exceptions import HTTPException
    
    # Don't catch HTTP errors like 404 - let them return normally
    if isinstance(e, HTTPException):
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
    return f"Error: {str(e)}", 500

def get_or_create_invite_token(user):
    """Get existing valid invite token for user or create a new one.
    
    Returns None if user has reached their max invite accepts limit.
    """
    # Check if user can still accept more invites
    if not can_sender_accept_more_invites(user):
        return None
    
    # Look for existing valid token (most recent first)
    existing = InviteToken.query.filter_by(inviter_id=user.id).order_by(InviteToken.created_at.desc()).all()
    for token_obj in existing:
        if not token_obj.is_expired() and not token_obj.is_fully_used():
            return token_obj
    
    # Create new token with 7-day expiration
    token = secrets.token_urlsafe(16)
    expires_at = datetime.utcnow() + timedelta(days=7)
    invite = InviteToken(token=token, inviter_id=user.id, expires_at=expires_at, max_uses=5, uses_count=0)
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
    "Utah": "UT",
    "Vermont": "VT",
    "Washington": "WA",
    "Wyoming": "WY"
}

RIDER_TYPES = ["Skier", "Snowboarder", "Telemarking", "Snowshoeing", "Adaptive", "Other"]

def normalize_rider_type(rider_type):
    """Map 'Both' to 'Skier' for display. All other values pass through."""
    if rider_type == "Both":
        return "Skier"
    return rider_type

CANONICAL_PASSES = [
    "Epic",
    "Ikon",
    "MountainCollective",
    "Indy",
    "PowderAlliance",
    "Freedom",
    "SkiCalifornia",
    "Other",
    "None"
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

# Make functions available to Jinja2 templates
app.jinja_env.globals['normalize_rider_type'] = normalize_rider_type
app.jinja_env.globals['get_sorted_passes'] = get_sorted_passes

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

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return redirect(url_for("auth"))

@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "POST":
        form_type = request.form.get("form_type")
        
        if form_type == "signup":
            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            email = request.form.get("email", "").lower().strip()
            password = request.form.get("password", "")
            
            # Validate required fields
            if not first_name or not last_name or not email or not password:
                flash("All fields are required.", "error")
                return render_template("auth.html")
            
            # Validate password length
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return render_template("auth.html")
            
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("An account with this email already exists.", "error")
                return render_template("auth.html")
            
            user = User(
                first_name=first_name,
                last_name=last_name,
                email=email
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            login_user(user)
            
            # Connect with inviter if pending_inviter_id exists in session
            _connect_pending_inviter(user)
            
            next_url = request.args.get("next")
            if next_url:
                session["next_after_setup"] = next_url
            
            return redirect(url_for("setup_profile"))
        
        elif form_type == "login":
            email = request.form.get("email", "").lower().strip()
            password = request.form.get("password", "").strip()  # ← STRIP PASSWORD TOO
            
            app.logger.info(f"🔐 LOGIN ATTEMPT: email='{email}' (len={len(email)}), password_len={len(password)}")
            
            user = User.query.filter_by(email=email).first()
            if user:
                pwd_ok = user.check_password(password)
                app.logger.info(f"🔐 USER FOUND: {user.email}, password_check={pwd_ok}")
                
                if pwd_ok:
                    login_user(user)
                    app.logger.info(f"✅ LOGGED IN: user_id={user.id}, authenticated={user.is_authenticated}")
                    
                    # Connect with inviter if pending_inviter_id exists in session
                    _connect_pending_inviter(user)
                    
                    next_url = request.args.get("next")
                    if user.rider_type and user.pass_type:
                        app.logger.info(f"✅ REDIRECTING TO HOME: rider_type={user.rider_type}, pass_type={user.pass_type}")
                        if next_url:
                            return redirect(next_url)
                        return redirect(url_for("home"))
                    else:
                        app.logger.warning(f"⚠️ INCOMPLETE PROFILE: rider_type={user.rider_type}, pass_type={user.pass_type}")
                        if next_url:
                            session["next_after_setup"] = next_url
                        return redirect(url_for("setup_profile"))
                else:
                    app.logger.warning(f"❌ WRONG PASSWORD for {email}")
                    app.logger.warning(f"   Password attempt length: {len(password)}, Hash check failed")
            else:
                app.logger.warning(f"❌ USER NOT FOUND: {email}")
                # Debug: check what users exist
                all_users = User.query.all()
                app.logger.warning(f"   Available users: {[u.email for u in all_users]}")
            
            flash("Invalid email or password.", "error")
            return render_template("auth.html")
    
    return render_template("auth.html")


def _connect_pending_inviter(user):
    """Helper to connect user with pending inviter from session."""
    inviter_id = session.get("pending_inviter_id")
    invite_token_id = session.get("pending_invite_token_id")
    
    if inviter_id and inviter_id != user.id:
        inviter = User.query.get(inviter_id)
        invite_token = InviteToken.query.get(invite_token_id) if invite_token_id else None
        
        if inviter:
            # Check sender limits
            if not can_sender_accept_more_invites(inviter):
                session.pop("pending_inviter_id", None)
                session.pop("pending_invite_token_id", None)
                return
            
            # Check token limits if token exists
            if invite_token:
                if invite_token.is_expired() or invite_token.is_fully_used():
                    session.pop("pending_inviter_id", None)
                    session.pop("pending_invite_token_id", None)
                    return
            
            # Check if already friends
            existing = Friend.query.filter(
                db.or_(
                    db.and_(Friend.user_id == user.id, Friend.friend_id == inviter.id),
                    db.and_(Friend.user_id == inviter.id, Friend.friend_id == user.id),
                )
            ).first()
            if not existing:
                # Create bidirectional connection
                f1 = Friend(user_id=user.id, friend_id=inviter.id)
                f2 = Friend(user_id=inviter.id, friend_id=user.id)
                db.session.add_all([f1, f2])
                
                # Update invite token usage counts
                if invite_token:
                    invite_token.uses_count = (invite_token.uses_count or 0) + 1
                    invite_token.used_at = datetime.utcnow()
                
                db.session.commit()
        
        session.pop("pending_inviter_id", None)
        session.pop("pending_invite_token_id", None)


@app.route("/r/<token>")
def invite_token_landing(token):
    """Landing page for invite token links."""
    invite = InviteToken.query.filter_by(token=token).first()

    # Token doesn't exist
    if not invite:
        return render_template("invite_invalid.html", message="This invite is no longer valid.")

    # Token expired
    if invite.is_expired():
        return render_template("invite_invalid.html", message="This invite is no longer valid.")

    # Token fully used (5 accepts)
    if invite.is_fully_used():
        return render_template("invite_invalid.html", message="This invite has already been fully used. Ask your friend to send you a new one.")

    inviter = invite.inviter
    if not inviter:
        return render_template("invite_invalid.html", message="This invite is no longer valid.")

    # Sender has reached max invite accepts (10 total)
    if not can_sender_accept_more_invites(inviter):
        return render_template("invite_invalid.html", message="This user has reached their invite limit for now.")

    # Store inviter and token in session so auth flow can use it
    session["pending_inviter_id"] = inviter.id
    session["pending_invite_token_id"] = invite.id

    # If user is already logged in, connect immediately
    if current_user.is_authenticated and current_user.id != inviter.id:
        # Check if already friends
        existing = Friend.query.filter(
            db.or_(
                db.and_(Friend.user_id == current_user.id, Friend.friend_id == inviter.id),
                db.and_(Friend.user_id == inviter.id, Friend.friend_id == current_user.id),
            )
        ).first()
        if existing:
            session.pop("pending_inviter_id", None)
            session.pop("pending_invite_token_id", None)
            return render_template("already_friends.html", friend=inviter)
        
        # Create bidirectional connection
        f1 = Friend(user_id=current_user.id, friend_id=inviter.id)
        f2 = Friend(user_id=inviter.id, friend_id=current_user.id)
        db.session.add_all([f1, f2])
        
        # Increment usage counts
        invite.uses_count = (invite.uses_count or 0) + 1
        invite.used_at = datetime.utcnow()
        
        db.session.commit()
        session.pop("pending_inviter_id", None)
        session.pop("pending_invite_token_id", None)
        return redirect(url_for("friends"))

    # Otherwise render the landing page for signup / login
    return render_template("invite_landing.html", inviter=inviter)


@app.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile():
    user = current_user
    
    if request.method == "POST":
        rider_type = request.form.get("rider_type")
        passes = request.form.getlist("pass_type")

        if not rider_type:
            flash("Please select a rider type.", "error")
            return redirect(url_for("setup_profile"))

        user.rider_type = rider_type
        user.pass_type = ",".join(sorted(set(passes))) if passes else "None"
        db.session.commit()

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
        user.rider_type = request.form.get("rider_type") or None
        passes = request.form.getlist("pass_type")
        user.pass_type = ",".join(sorted(set(passes))) if passes else "None"
        user.home_state = request.form.get("home_state") or None
        user.skill_level = request.form.get("skill_level") or None
        user.gear = request.form.get("gear") or None
        user.home_mountain = request.form.get("home_mountain") or None
        
        db.session.commit()
        return redirect(url_for("more"))
    
    primary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.PRIMARY).first()
    secondary_equipment = EquipmentSetup.query.filter_by(user_id=user.id, slot=EquipmentSlot.SECONDARY).first()
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template("edit_profile.html", user=user, friends_count=friends_count, state_abbr=STATE_ABBR, pass_options=CANONICAL_PASSES, rider_types=RIDER_TYPES, states=states, primary_equipment=primary_equipment, secondary_equipment=secondary_equipment)

@app.route("/my-trips")
@login_required
def my_trips():
    today = date.today()

    upcoming_trips = (
        SkiTrip.query
        .filter_by(user_id=current_user.id)
        .filter(SkiTrip.end_date >= today)
        .order_by(SkiTrip.start_date.asc())
        .all()
    )

    past_trips = (
        SkiTrip.query
        .filter_by(user_id=current_user.id)
        .filter(SkiTrip.end_date < today)
        .order_by(SkiTrip.start_date.desc())
        .all()
    )

    return render_template(
        "my_trips.html",
        upcoming_trips=upcoming_trips,
        past_trips=past_trips,
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
    
    trip = SkiTrip(
        user_id=user.id,
        state=state,
        mountain=mountain,
        start_date=start_date,
        end_date=end_date,
        pass_type=pass_type,
        is_public=is_public
    )
    db.session.add(trip)
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
            "rider_type": friend.rider_type or "Not specified"
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
    
    filter_type = request.args.get("filter", "All")
    
    # Load friend relationships
    friend_links = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friend_links]
    all_friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    
    # Categorize friends by pass type
    epic_friends = [f for f in all_friends if pass_category(f.pass_type) == "Epic"]
    ikon_friends = [f for f in all_friends if pass_category(f.pass_type) == "Ikon"]
    other_friends = [f for f in all_friends if pass_category(f.pass_type) == "Other"]
    
    # Apply filter
    if filter_type == "Epic":
        friends_list = epic_friends
    elif filter_type == "Ikon":
        friends_list = ikon_friends
    elif filter_type == "Other":
        friends_list = other_friends
    else:
        friends_list = all_friends
    
    return render_template(
        "friends.html",
        user=user,
        friends=friends_list,
        count_all=len(all_friends),
        count_epic=len(epic_friends),
        count_ikon=len(ikon_friends),
        count_other=len(other_friends),
        filter_type=filter_type
    )

@app.route("/friends/<int:friend_id>")
@login_required
def friend_profile(friend_id):
    friend = User.query.get_or_404(friend_id)
    user = current_user
    
    mountains = friend.mountains_visited or []
    friend_mountains_count = len(mountains)
    friend_mountains_sorted = sorted([m.name if hasattr(m, 'name') else m for m in mountains])
    
    today = date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    # Get friend's trips
    trips = (
        SkiTrip.query
        .filter_by(user_id=friend.id, is_public=True)
        .filter(SkiTrip.end_date >= today)
        .order_by(SkiTrip.start_date.asc())
        .all()
    )
    
    # Get current user's trips (for overlap detection)
    user_trips = (
        SkiTrip.query
        .filter_by(user_id=user.id)
        .filter(SkiTrip.end_date >= today)
        .all()
    )
    
    # Mark trip overlaps (same mountain + date overlap)
    for trip in trips:
        trip.has_trip_overlap = False
        for user_trip in user_trips:
            if trip.mountain == user_trip.mountain:
                if date_ranges_overlap(trip.start_date, trip.end_date, user_trip.start_date, user_trip.end_date):
                    trip.has_trip_overlap = True
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
    
    return render_template(
        "friend_profile.html",
        friend=friend,
        friend_mountains_count=friend_mountains_count,
        friend_mountains=friend_mountains_sorted,
        trips=trips,
        friend_open_dates=friend_open_dates,
        friend_open_dates_display=friend_open_dates_display,
        has_availability_overlap=len(availability_overlaps) > 0,
        availability_display=availability_display,
        availability_remaining=availability_remaining,
        show_connect_button=show_connect_button
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
        user.rider_type = data.get("rider_type", "").strip()
    if "pass_type" in data:
        user.pass_type = data.get("pass_type", "").strip()
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Profile updated"}), 200

@app.route("/create-trip")
@login_required
def create_trip_page():
    user = current_user
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    return render_template("create_trip.html", user=user, states=states, mountains_by_state=MOUNTAINS_BY_STATE, pass_options=PASS_OPTIONS)

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
    """Format a list of YYYY-MM-DD strings into human-readable summary.
    E.g., ['2024-12-14', '2024-12-18', '2024-12-19', '2025-01-03', '2025-01-04'] 
    -> 'Dec 14, Dec 18–19, Jan 3–4'
    """
    if not date_strings:
        return None
    
    from datetime import datetime as dt
    
    # Parse and sort dates
    dates = sorted([dt.strptime(d, '%Y-%m-%d').date() for d in date_strings])
    
    # Group consecutive dates
    groups = []
    current_group = [dates[0]]
    
    for i in range(1, len(dates)):
        if (dates[i] - dates[i-1]).days == 1:
            current_group.append(dates[i])
        else:
            groups.append(current_group)
            current_group = [dates[i]]
    groups.append(current_group)
    
    # Format each group
    formatted = []
    for group in groups:
        if len(group) == 1:
            formatted.append(group[0].strftime('%b %d').replace(' 0', ' '))
        else:
            start = group[0].strftime('%b %d').replace(' 0', ' ')
            end = group[-1].strftime('%d').lstrip('0')
            # If same month, just show "Dec 14–19"
            if group[0].month == group[-1].month:
                formatted.append(f"{start}–{end}")
            else:
                end_full = group[-1].strftime('%b %d').replace(' 0', ' ')
                formatted.append(f"{start}–{end_full}")
    
    return ', '.join(formatted)

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
    
    # Upcoming trips for intro card
    upcoming_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.end_date >= today
    ).order_by(SkiTrip.start_date.asc()).all()
    
    # My upcoming trips
    my_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
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
                        overlaps.append({
                            "friend_name": friend_trip.user.first_name + " " + friend_trip.user.last_name,
                            "friend_id": friend_trip.user_id,
                            "mountain": resort.name if resort else my.mountain,
                            "state": resort.state if resort else my.state,
                            "brand": resort.brand if resort else None,
                            "start_date": max(my.start_date, friend_trip.start_date),
                            "end_date": min(my.end_date, friend_trip.end_date)
                        })
    
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
                        "pass_info": pass_info
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
    
    # Count friends with open date overlaps
    open_friends_count, user_has_open_dates = count_friends_open_on_same_dates(user)
    
    # Combined list for All Trips (upcoming only)
    all_trips = (my_trips or []) + (friend_trips or [])
    try:
        all_trips = sorted(all_trips, key=lambda t: t.start_date)
    except Exception:
        pass
    
    return render_template(
        'home.html',
        user=user,
        upcoming_trips=upcoming_trips,
        my_trips=my_trips,
        friend_trips=friend_trips,
        all_trips=all_trips,
        overlaps=overlaps,
        open_date_matches=open_date_matches,
        user_open_dates=sorted(my_open_dates) if my_open_dates else [],
        user_open_dates_display=user_open_dates_display,
        user_mountains=user_mountains_sorted,
        open_friends_count=open_friends_count,
        user_has_open_dates=user_has_open_dates,
        state_abbr=STATE_ABBR
    )

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

    # Calculate overlapping days with current user's trips
    your_trips = SkiTrip.query.filter_by(user_id=current_user.id).all()

    def overlapping_days(a_start, a_end, b_start, b_end):
        latest_start = max(a_start, b_start)
        earliest_end = min(a_end, b_end)
        delta = (earliest_end - latest_start).days + 1
        return max(0, delta)

    your_overlap_days = 0
    your_overlap_ranges = []

    for yt in your_trips:
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
    
    # Find friends with open dates that overlap the trip dates
    trip_dates = set()
    current_date = trip.start_date
    while current_date <= trip.end_date:
        trip_dates.add(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)
    
    # Fetch all friend users in a single query
    friend_users = (
        db.session.query(User)
        .join(Friend, Friend.friend_id == User.id)
        .filter(Friend.user_id == current_user.id)
        .all()
    )
    
    friends_open_on_trip = []
    for friend_user in friend_users:
        if friend_user.open_dates:
            friend_open_set = set(friend_user.open_dates)
            overlap_dates = trip_dates & friend_open_set
            if overlap_dates:
                friends_open_on_trip.append({
                    'id': friend_user.id,
                    'name': friend_user.first_name,
                    'pass_type': friend_user.pass_type,
                    'overlap_count': len(overlap_dates)
                })
    
    friends_open_on_trip.sort(key=lambda x: x['name'])

    return render_template(
        "friend_trip_details.html",
        trip=trip,
        friend=friend,
        has_overlap=has_overlap,
        overlap_days=your_overlap_days,
        your_overlap_ranges=your_overlap_ranges,
        friends_open_on_trip=friends_open_on_trip
    )

@app.route("/more")
@login_required
def more():
    mountains = current_user.mountains_visited or []
    mountains_visited_count = len(mountains)
    
    return render_template("more.html", mountains_visited_count=mountains_visited_count)

@app.route("/more_info")
@login_required
def more_info():
    mountains = current_user.mountains_visited or []
    mountains_visited_count = len(mountains)
    
    return render_template("more_info.html", mountains_visited_count=mountains_visited_count)

@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")

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
    resorts_objs = Resort.query.filter_by(is_active=True).order_by(Resort.state, Resort.name).all()
    # Convert to dicts for JSON serialization
    resorts = [{"id": r.id, "name": r.name, "state": r.state, "brand": r.brand} for r in resorts_objs]
    
    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        set_home_mountain = request.form.get("set_home_mountain") == "on"

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
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                if end_date < start_date:
                    errors.append("End date cannot be before start date.")
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
            )

        trip = SkiTrip(
            user_id=current_user.id,
            resort_id=resort.id,
            state=resort.state,
            mountain=resort.name,
            start_date=start_date,
            end_date=end_date,
            is_public=is_public,
        )
        db.session.add(trip)
        db.session.commit()

        if set_home_mountain and resort:
            current_user.home_mountain = resort.name
            db.session.commit()

        flash("Trip added.", "trip")
        return redirect(url_for("my_trips"))

    # GET
    return render_template(
        "add_trip.html",
        trip=None,
        resorts=resorts,
        user=current_user,
        form_action=url_for("add_trip"),
    )

@app.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@login_required
def edit_trip_form(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        abort(403)
    
    resorts_objs = Resort.query.filter_by(is_active=True).order_by(Resort.state, Resort.name).all()
    # Convert to dicts for JSON serialization
    resorts = [{"id": r.id, "name": r.name, "state": r.state, "brand": r.brand} for r in resorts_objs]

    if request.method == "POST":
        resort_id = request.form.get("resort_id")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        set_home_mountain = request.form.get("set_home_mountain") == "on"

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
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                if end_date < start_date:
                    errors.append("End date cannot be before start date.")
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
            )

        trip.resort_id = resort.id
        trip.state = resort.state
        trip.mountain = resort.name
        trip.start_date = start_date
        trip.end_date = end_date
        trip.is_public = is_public

        if set_home_mountain and resort:
            current_user.home_mountain = resort.name
        
        db.session.commit()
        flash("Trip updated.", "trip")
        return redirect(url_for("my_trips"))

    # GET
    return render_template(
        "add_trip.html",
        trip=trip,
        resorts=resorts,
        user=current_user,
        form_action=url_for("edit_trip_form", trip_id=trip.id),
    )

@app.route("/trips/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete_trip_form(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        abort(403)

    db.session.delete(trip)
    db.session.commit()
    flash("Trip deleted.", "trip")
    return redirect(url_for("my_trips"))

@app.route("/mountains-visited", methods=["GET", "POST"])
@login_required
def mountains_visited():
    user = current_user
    
    all_mountains = []
    mountains_with_state = {}
    for state, state_mountains in MOUNTAINS_BY_STATE.items():
        for mtn in state_mountains:
            all_mountains.append(mtn)
            mountains_with_state[mtn] = state
    all_mountains = sorted(list(set(all_mountains)))
    
    if request.method == "POST":
        selected_mountains = request.form.getlist("mountains")
        user.mountains_visited = selected_mountains
        db.session.commit()
        return redirect(url_for("more"))
    
    selected_mountains = user.mountains_visited or []
    mountains_visited_count = len(selected_mountains)
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template(
        "mountains_visited.html",
        all_mountains=all_mountains,
        selected_mountains=selected_mountains,
        mountains_visited_count=mountains_visited_count,
        mountains_with_state=mountains_with_state,
        states=states,
    )

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth"))

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
            rider_type="Skier",
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
        
        user = User(
            first_name=first,
            last_name=last,
            email=email,
            rider_type=random.choice(rider_types),
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
        db.session.commit()
        session["pass_prompt_skipped"] = False
        return redirect(url_for("home"))

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
            rider_type=random.choice(rider_types),
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
            rider_type=random.choice(rider_types),
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
    Accessible only to admin. Can be called after deployment if CLI command fails.
    
    Usage after deployment:
    GET https://yourapp.replit.dev/admin/init-db
    
    This will:
    - Create all database tables
    - Create/verify primary user (Richard)
    - Be idempotent (safe to call multiple times)
    """
    # Allow in development OR if admin is authenticated
    if os.environ.get("FLASK_ENV") == "production":
        if not current_user.is_authenticated or current_user.email != "richardbattlebaxter@gmail.com":
            return "Unauthorized: Admin access required", 403
    
    try:
        with app.app_context():
            # Create all tables
            db.create_all()
            
            # Ensure primary user exists and is valid
            primary_user = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
            if not primary_user:
                primary_user = User(
                    first_name="Richard",
                    last_name="Battle-Baxter",
                    email="richardbattlebaxter@gmail.com",
                    rider_type="Skier",
                    pass_type="Epic",
                    skill_level="Advanced",
                    home_state="Colorado",
                    birth_year=1985
                )
                primary_user.set_password("12345678")
                db.session.add(primary_user)
                db.session.commit()
                return jsonify({
                    "status": "success",
                    "message": "✅ Database initialized. Primary user created.",
                    "email": "richardbattlebaxter@gmail.com",
                    "password": "12345678"
                }), 200
            else:
                # Verify/repair password
                if not primary_user.check_password("12345678"):
                    primary_user.set_password("12345678")
                    db.session.commit()
                    return jsonify({
                        "status": "success",
                        "message": "✅ Database already initialized. Primary user password repaired."
                    }), 200
                else:
                    return jsonify({
                        "status": "success",
                        "message": "✅ Database already initialized. Primary user verified."
                    }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to initialize database: {str(e)}"
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
                rider_type="Skier", pass_type="Epic", skill_level="Advanced",
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
                rider_type="Skier", pass_type="Ikon,MountainCollective", skill_level="Advanced",
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
            
            user = User(
                first_name=random.choice(FIRST_NAMES),
                last_name=random.choice(LAST_NAMES),
                email=email,
                rider_type=random.choice(["Skier", "Snowboarder"]),
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
            
            discipline = EquipmentDiscipline.SKIER if user.rider_type == "Skier" else EquipmentDiscipline.SNOWBOARDER
            brands = SKIER_BRANDS if user.rider_type == "Skier" else SNOWBOARDER_BRANDS
            
            primary = EquipmentSetup(
                user_id=user.id,
                slot=EquipmentSlot.PRIMARY,
                discipline=discipline,
                brand=random.choice(brands),
                length_cm=random.randint(160, 190) if user.rider_type == "Skier" else random.randint(150, 165),
                width_mm=random.randint(80, 105) if user.rider_type == "Skier" else None
            )
            db.session.add(primary)
            equipment_count += 1
            
            if random.random() < 0.5:
                secondary = EquipmentSetup(
                    user_id=user.id,
                    slot=EquipmentSlot.SECONDARY,
                    discipline=discipline,
                    brand=random.choice(brands),
                    length_cm=random.randint(160, 190) if user.rider_type == "Skier" else random.randint(150, 165),
                    width_mm=random.randint(80, 105) if user.rider_type == "Skier" else None
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

    # Step 3: Verification
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
    
    print("\n✅ FIX COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
