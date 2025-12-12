import os
import secrets
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from flask_login import LoginManager, login_required, current_user, login_user, logout_user
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation, InviteToken, Resort
from debug_routes import debug_bp
from services.open_dates import get_open_date_matches
from io import BytesIO
import segno
import random

# ============================================================================
# PROFILE CONSOLIDATION NOTE:
# The app no longer uses /profile or profile.html.
# All profile-related UI lives under /more.
# Do NOT reintroduce profile routes or templates.
# ============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Session configuration for development
# In Replit's iframe environment, we need relaxed cookie settings
app.config['SESSION_COOKIE_SECURE'] = False  # Allow HTTP in development
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # Allow in iframes (requires sending with every request)
app.config['SESSION_COOKIE_DOMAIN'] = None  # Let the browser handle domain
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Refresh session on each request

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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

with app.app_context():
    db.create_all()
    
    # ✅ HARD GUARANTEE: Ensure primary user exists and is valid
    primary_user = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    if not primary_user:
        # Create primary user if missing
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
        app.logger.info("✅ PRIMARY USER CREATED: richardbattlebaxter@gmail.com")
    else:
        # Verify password is correct
        if not primary_user.check_password("12345678"):
            # Repair password if incorrect
            primary_user.set_password("12345678")
            db.session.commit()
            app.logger.warning("⚠️ PRIMARY USER PASSWORD REPAIRED: richardbattlebaxter@gmail.com")
        else:
            app.logger.info("✅ PRIMARY USER VERIFIED: richardbattlebaxter@gmail.com (ID=%d)", primary_user.id)

def get_or_create_invite_token(user):
    """Get existing invite token for user or create a new one."""
    existing = InviteToken.query.filter_by(inviter_id=user.id).first()
    if existing:
        return existing
    
    token = secrets.token_urlsafe(16)
    invite = InviteToken(token=token, inviter_id=user.id)
    db.session.add(invite)
    db.session.commit()
    return invite

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

RIDER_TYPES = ["Skier", "Snowboarder", "Both", "Other"]

PASS_OPTIONS = [
    "Epic",
    "Epic & Ikon",
    "Epic 4-day",
    "Epic Local",
    "Ikon",
    "Ikon Base",
    "Ikon Plus",
    "Ikon Session",
    "Loveland",
    "No Pass",
    "Other"
]

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
    if inviter_id and inviter_id != user.id:
        inviter = User.query.get(inviter_id)
        if inviter:
            # Check if already friends
            existing = Friend.query.filter(
                db.or_(
                    db.and_(Friend.user_id == user.id, Friend.friend_id == inviter.id),
                    db.and_(Friend.user_id == inviter.id, Friend.friend_id == user.id),
                )
            ).first()
            if not existing:
                f1 = Friend(user_id=user.id, friend_id=inviter.id)
                f2 = Friend(user_id=inviter.id, friend_id=user.id)
                db.session.add_all([f1, f2])
                
                # Update invite token used_at timestamp
                invite_token = InviteToken.query.filter_by(inviter_id=inviter.id).first()
                if invite_token:
                    invite_token.used_at = datetime.utcnow()
                
                db.session.commit()
        session.pop("pending_inviter_id", None)


@app.route("/r/<token>")
def invite_token_landing(token):
    """Landing page for invite token links."""
    invite = InviteToken.query.filter_by(token=token).first()

    if not invite:
        return render_template("invite_invalid.html")

    inviter = invite.inviter
    if not inviter:
        return render_template("invite_invalid.html")

    # Store inviter in session so auth flow can use it
    session["pending_inviter_id"] = inviter.id

    # If user is already logged in, connect immediately
    if current_user.is_authenticated and current_user.id != inviter.id:
        existing = Friend.query.filter(
            db.or_(
                db.and_(Friend.user_id == current_user.id, Friend.friend_id == inviter.id),
                db.and_(Friend.user_id == inviter.id, Friend.friend_id == current_user.id),
            )
        ).first()
        if not existing:
            f1 = Friend(user_id=current_user.id, friend_id=inviter.id)
            f2 = Friend(user_id=inviter.id, friend_id=current_user.id)
            db.session.add_all([f1, f2])
            # Update invite token used_at timestamp
            invite.used_at = datetime.utcnow()
            db.session.commit()
        session.pop("pending_inviter_id", None)
        return redirect(url_for("friends"))

    # Otherwise render the landing page for signup / login
    return render_template("invite_landing.html", inviter=inviter)


@app.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile():
    user = current_user
    
    if request.method == "POST":
        rider_type = request.form.get("rider_type")
        pass_type = request.form.get("pass_type")

        if not rider_type or not pass_type:
            flash("Please select one option for each field.", "error")
            return redirect(url_for("setup_profile"))

        user.rider_type = rider_type
        user.pass_type = pass_type
        db.session.commit()

        return redirect(url_for("home"))

    return render_template("setup_profile.html", rider_types=RIDER_TYPES)

@app.route("/profile")
def deprecated_profile():
    """Defensive redirect: /profile no longer exists, redirect to /more."""
    return redirect(url_for("more"))

@app.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    user = current_user
    
    if request.method == "POST":
        user.gender = request.form.get("gender") or None
        birth_year_raw = request.form.get("birth_year")
        user.birth_year = int(birth_year_raw) if birth_year_raw else None
        user.rider_type = request.form.get("rider_type") or None
        user.pass_type = request.form.get("pass_type") or None
        user.home_state = request.form.get("home_state") or None
        user.skill_level = request.form.get("skill_level") or None
        user.gear = request.form.get("gear") or None
        user.home_mountain = request.form.get("home_mountain") or None
        
        db.session.commit()
        return redirect(url_for("more"))
    
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template("edit_profile.html", user=user, friends_count=friends_count, state_abbr=STATE_ABBR, pass_options=PASS_OPTIONS, rider_types=RIDER_TYPES, states=states)

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
    data = request.get_json()
    friend_email = data.get("friend_email")
    
    if not friend_email:
        return jsonify({"success": False, "error": "Friend email is required"}), 400
    
    friend = User.query.filter_by(email=friend_email).first()
    if not friend:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    if friend.id == current_user.id:
        return jsonify({"success": False, "error": "Cannot add yourself as a friend"}), 400
    
    existing_friendship = Friend.query.filter_by(user_id=current_user.id, friend_id=friend.id).first()
    if existing_friendship:
        return jsonify({"success": False, "error": "Already friends"}), 409
    
    existing_invitation = Invitation.query.filter_by(sender_id=current_user.id, receiver_id=friend.id, status='pending').first()
    if existing_invitation:
        return jsonify({"success": False, "error": "Invitation already sent"}), 409
    
    invitation = Invitation(sender_id=current_user.id, receiver_id=friend.id, status='pending')
    db.session.add(invitation)
    db.session.commit()
    
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
    
    mountains = friend.mountains_visited or []
    friend_mountains_count = len(mountains)
    friend_mountains_sorted = sorted([m.name if hasattr(m, 'name') else m for m in mountains])
    
    today = date.today()
    trips = (
        SkiTrip.query
        .filter_by(user_id=friend.id, is_public=True)
        .filter(SkiTrip.end_date >= today)
        .order_by(SkiTrip.start_date.asc())
        .all()
    )
    
    # Get friend's open dates from JSON field (filter to future dates only)
    today_str = today.strftime('%Y-%m-%d')
    friend_open_dates_raw = friend.open_dates or []
    friend_open_dates = sorted([d for d in friend_open_dates_raw if d >= today_str])
    friend_open_dates_display = format_open_dates_summary(friend_open_dates) if friend_open_dates else None
    
    return render_template(
        "friend_profile.html",
        friend=friend,
        friend_mountains_count=friend_mountains_count,
        friend_mountains=friend_mountains_sorted,
        trips=trips,
        friend_open_dates=friend_open_dates,
        friend_open_dates_display=friend_open_dates_display
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
    invite_token = get_or_create_invite_token(current_user)
    invite_url = url_for("invite_token_landing", token=invite_token.token, _external=True)
    return render_template("invite.html", user=current_user, invite_url=invite_url)

@app.route("/my-qr")
@login_required
def my_qr():
    invite_token = get_or_create_invite_token(current_user)
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

    return render_template(
        "friend_trip_details.html",
        trip=trip,
        friend=friend,
        has_overlap=has_overlap,
        overlap_days=your_overlap_days,
        your_overlap_ranges=your_overlap_ranges
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

@app.cli.command()
def create_jonathan_and_connect():
    """Create Jonathan user and connect them as friends to all existing users."""
    
    JONATHAN_FIRST = "Jonathan"
    JONATHAN_LAST = "Schmitz"
    JONATHAN_EMAIL = "Jonathanmschmitz@gmail.com"
    JONATHAN_PASSWORD = "12345678"
    
    jonathan = User.query.filter_by(email=JONATHAN_EMAIL).first()
    
    if jonathan:
        print(f"✓ Jonathan already exists (ID: {jonathan.id})")
    else:
        jonathan = User(
            first_name=JONATHAN_FIRST,
            last_name=JONATHAN_LAST,
            email=JONATHAN_EMAIL
        )
        jonathan.set_password(JONATHAN_PASSWORD)
        db.session.add(jonathan)
        db.session.commit()
        print(f"✓ Created Jonathan (ID: {jonathan.id})")
    
    other_users = User.query.filter(User.id != jonathan.id).all()
    print(f"✓ Found {len(other_users)} existing users to connect")
    
    connections_created = 0
    connections_skipped = 0
    
    for other_user in other_users:
        friendship_1 = Friend.query.filter_by(user_id=jonathan.id, friend_id=other_user.id).first()
        if not friendship_1:
            friendship_1 = Friend(user_id=jonathan.id, friend_id=other_user.id)
            db.session.add(friendship_1)
            connections_created += 1
        else:
            connections_skipped += 1
        
        friendship_2 = Friend.query.filter_by(user_id=other_user.id, friend_id=jonathan.id).first()
        if not friendship_2:
            friendship_2 = Friend(user_id=other_user.id, friend_id=jonathan.id)
            db.session.add(friendship_2)
            connections_created += 1
        else:
            connections_skipped += 1
    
    db.session.commit()
    
    print(f"\n✓ Friendship connections created: {connections_created}")
    print(f"✓ Friendship connections skipped (already exist): {connections_skipped}")

@app.cli.command()
def seed_database():
    """Comprehensive database seeding: main users, 50 dummy users, friendships, and trips."""
    
    # Realistic names for dummy users
    dummy_names = [
        ("Alex", "Johnson"), ("Blake", "Mitchell"), ("Casey", "Brown"), ("Dana", "Wilson"),
        ("Emma", "Taylor"), ("Fiona", "Garcia"), ("Grace", "Rodriguez"), ("Harper", "Martinez"),
        ("Isabella", "Lee"), ("Jackson", "Hernandez"), ("Jasmine", "Perez"), ("Jordan", "Davis"),
        ("Kai", "Lopez"), ("Kendall", "Gonzalez"), ("Kyle", "Thompson"), ("Leah", "Anderson"),
        ("Logan", "Thomas"), ("Madison", "Moore"), ("Morgan", "Jackson"), ("Natalie", "Martin"),
        ("Noah", "Clark"), ("Olivia", "Sanchez"), ("Owen", "Morris"), ("Piper", "Rogers"),
        ("Quinn", "Peterson"), ("Rachel", "Cooper"), ("Ryan", "Porter"), ("Samantha", "Hunter"),
        ("Samuel", "Hicks"), ("Sophie", "Crawford"), ("Stephen", "Henry"), ("Sydney", "Howell"),
        ("Taylor", "Crawley"), ("Thomas", "Dalton"), ("Uma", "Denton"), ("Unai", "Durant"),
        ("Victoria", "Dupree"), ("Vincent", "Emerson"), ("Violet", "Emory"), ("Vivian", "Fanning"),
        ("Wade", "Farley"), ("Waylon", "Farnsworth"), ("Whitney", "Farrer"), ("Willow", "Farrow"),
        ("Xander", "Faulkner"), ("Xavier", "Fawcett"), ("Ximena", "Fay"), ("Yolanda", "Feild"),
    ]
    
    ski_states = ["CO", "UT", "CA", "WA", "MT", "VT", "NY", "WY"]
    rider_types = ["Skier", "Snowboarder"]
    pass_types = ["Epic", "Ikon"]
    skill_levels = ["Beginner", "Intermediate", "Advanced"]
    
    # Get or create main users
    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    if not richard:
        richard = User(first_name="Richard", last_name="Battle-Baxter", email="richardbattlebaxter@gmail.com")
        richard.set_password("12345678")
        richard.rider_type = "Skier"
        richard.pass_type = "Epic"
        richard.profile_setup_complete = True
        richard.home_state = "CO"
        richard.skill_level = "Advanced"
        richard.birth_year = 1985
        db.session.add(richard)
        print("✓ Created Richard")
    else:
        print("✓ Richard already exists")
    
    jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
    if not jonathan:
        jonathan = User(first_name="Jonathan", last_name="Schmitz", email="jonathanmschmitz@gmail.com")
        jonathan.set_password("12345678")
        jonathan.rider_type = "Skier"
        jonathan.pass_type = "Epic"
        jonathan.profile_setup_complete = True
        jonathan.home_state = "UT"
        jonathan.skill_level = "Advanced"
        jonathan.birth_year = 1987
        db.session.add(jonathan)
        print("✓ Created Jonathan")
    else:
        print("✓ Jonathan already exists")
    
    db.session.commit()
    
    # Create 50 dummy users
    created_dummy = 0
    for i, (first, last) in enumerate(dummy_names, 1):
        email = f"{first.lower()}.{last.lower()}+ski{i:02d}@gmail.com"
        existing = User.query.filter_by(email=email).first()
        if not existing:
            user = User(
                first_name=first,
                last_name=last,
                email=email
            )
            user.set_password("skitest123")
            user.rider_type = random.choice(rider_types)
            user.pass_type = random.choice(pass_types)
            user.skill_level = random.choice(skill_levels)
            user.home_state = random.choice(ski_states)
            user.profile_setup_complete = True
            user.birth_year = random.randint(1980, 2000)
            db.session.add(user)
            created_dummy += 1
    
    db.session.commit()
    print(f"✓ Created {created_dummy} dummy users (50 expected)")
    
    # Get all dummy users
    dummy_users = User.query.filter(
        ~User.email.in_(["richardbattlebaxter@gmail.com", "jonathanmschmitz@gmail.com"])
    ).all()
    
    # Create bidirectional friendships: dummy ↔ richard, dummy ↔ jonathan
    friendship_count = 0
    for dummy in dummy_users:
        for main_user in [richard, jonathan]:
            fwd = Friend.query.filter_by(user_id=dummy.id, friend_id=main_user.id).first()
            if not fwd:
                db.session.add(Friend(user_id=dummy.id, friend_id=main_user.id))
                friendship_count += 1
            
            bwd = Friend.query.filter_by(user_id=main_user.id, friend_id=dummy.id).first()
            if not bwd:
                db.session.add(Friend(user_id=main_user.id, friend_id=dummy.id))
                friendship_count += 1
    
    db.session.commit()
    print(f"✓ Created {friendship_count} bidirectional friendships")
    
    # Get resorts
    resorts = Resort.query.filter_by(is_active=True).all()
    base_date = date.today() + timedelta(days=30)
    
    # Create trips for dummy users (with overlaps)
    trip_count = 0
    overlap_users = set()
    
    # First, create trips for ~30% of users to overlap with richard/jonathan
    for i, dummy in enumerate(dummy_users[:max(15, len(dummy_users)//3)]):
        for _ in range(2):  # 2 trips per user
            resort = random.choice(resorts)
            start = base_date + timedelta(days=random.randint(0, 90))
            end = start + timedelta(days=random.randint(2, 5))
            trip = SkiTrip(
                user_id=dummy.id,
                resort_id=resort.id,
                state=resort.state,
                mountain=resort.name,
                start_date=start,
                end_date=end,
                is_public=True
            )
            db.session.add(trip)
            overlap_users.add(dummy.id)
            trip_count += 1
    
    # Create remaining trips for other dummy users
    for dummy in dummy_users[max(15, len(dummy_users)//3):]:
        for _ in range(2):  # 2 trips per user
            resort = random.choice(resorts)
            start = base_date + timedelta(days=random.randint(0, 90))
            end = start + timedelta(days=random.randint(2, 5))
            trip = SkiTrip(
                user_id=dummy.id,
                resort_id=resort.id,
                state=resort.state,
                mountain=resort.name,
                start_date=start,
                end_date=end,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 1
    
    # Create trips for richard and jonathan (overlapping with dummies)
    overlap_resort = random.choice(resorts)
    overlap_start = base_date + timedelta(days=30)
    overlap_end = overlap_start + timedelta(days=3)
    
    for main_user in [richard, jonathan]:
        trip = SkiTrip(
            user_id=main_user.id,
            resort_id=overlap_resort.id,
            state=overlap_resort.state,
            mountain=overlap_resort.name,
            start_date=overlap_start,
            end_date=overlap_end,
            is_public=True
        )
        db.session.add(trip)
        trip_count += 2
    
    db.session.commit()
    print(f"✓ Created {trip_count} trips")
    print(f"✓ {len(overlap_users)} users have overlapping dates with Richard & Jonathan")
    
    print(f"\n✅ Database seeding complete!")
    print(f"   Main users: Richard & Jonathan")
    print(f"   Dummy users: {len(dummy_users)}")
    print(f"   Friendships: {friendship_count}")
    print(f"   Trips: {trip_count}")

@app.cli.command()
def add_sam_stookesberry():
    """Add Sam Stookesberry as main user and connect to all existing users with trips."""
    
    # Step 1: Create or fetch Sam
    sam = User.query.filter_by(email="samstookes@gmail.com").first()
    if sam:
        print(f"✓ Sam already exists (ID: {sam.id})")
    else:
        sam = User(
            first_name="Sam",
            last_name="Stookesberry",
            email="samstookes@gmail.com"
        )
        sam.set_password("12345678")
        sam.rider_type = "Skier"
        sam.pass_type = "Epic"
        sam.skill_level = "Advanced"
        sam.home_state = "WY"
        sam.birth_year = 1988
        sam.profile_setup_complete = True
        db.session.add(sam)
        db.session.commit()
        print(f"✓ Created Sam (ID: {sam.id})")
    
    # Step 2: Fetch Richard and Jonathan
    richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
    
    # Step 3: Fetch all dummy users
    dummy_users = User.query.filter(
        ~User.email.in_(["richardbattlebaxter@gmail.com", "jonathanmschmitz@gmail.com", "samstookes@gmail.com"])
    ).all()
    
    # Step 4: Create bidirectional friendships
    friendship_count = 0
    
    # Sam ↔ Richard
    if richard:
        f1 = Friend.query.filter_by(user_id=sam.id, friend_id=richard.id).first()
        if not f1:
            db.session.add(Friend(user_id=sam.id, friend_id=richard.id))
            friendship_count += 1
        
        f2 = Friend.query.filter_by(user_id=richard.id, friend_id=sam.id).first()
        if not f2:
            db.session.add(Friend(user_id=richard.id, friend_id=sam.id))
            friendship_count += 1
    
    # Sam ↔ Jonathan
    if jonathan:
        f1 = Friend.query.filter_by(user_id=sam.id, friend_id=jonathan.id).first()
        if not f1:
            db.session.add(Friend(user_id=sam.id, friend_id=jonathan.id))
            friendship_count += 1
        
        f2 = Friend.query.filter_by(user_id=jonathan.id, friend_id=sam.id).first()
        if not f2:
            db.session.add(Friend(user_id=jonathan.id, friend_id=sam.id))
            friendship_count += 1
    
    # Sam ↔ All dummy users
    for dummy in dummy_users:
        f1 = Friend.query.filter_by(user_id=sam.id, friend_id=dummy.id).first()
        if not f1:
            db.session.add(Friend(user_id=sam.id, friend_id=dummy.id))
            friendship_count += 1
        
        f2 = Friend.query.filter_by(user_id=dummy.id, friend_id=sam.id).first()
        if not f2:
            db.session.add(Friend(user_id=dummy.id, friend_id=sam.id))
            friendship_count += 1
    
    db.session.commit()
    print(f"✓ Created {friendship_count} bidirectional friendships")
    
    # Step 5: Create trips for Sam with overlaps
    resorts = Resort.query.filter_by(is_active=True).all()
    base_date = date.today() + timedelta(days=30)
    trip_count = 0
    
    # Get existing trips from Richard and Jonathan for overlap
    richard_trips = SkiTrip.query.filter_by(user_id=richard.id).all() if richard else []
    jonathan_trips = SkiTrip.query.filter_by(user_id=jonathan.id).all() if jonathan else []
    dummy_trips = []
    for dummy in dummy_users[:10]:  # Sample some dummy trips
        dummy_trips.extend(SkiTrip.query.filter_by(user_id=dummy.id).all())
    
    # Trip 1: Overlap with Richard
    if richard_trips:
        overlap_trip = richard_trips[0]
        trip = SkiTrip(
            user_id=sam.id,
            resort_id=overlap_trip.resort_id,
            state=overlap_trip.state,
            mountain=overlap_trip.mountain,
            start_date=overlap_trip.start_date,
            end_date=overlap_trip.end_date,
            is_public=True
        )
        db.session.add(trip)
        trip_count += 1
    
    # Trip 2: Overlap with Jonathan
    if jonathan_trips:
        overlap_trip = jonathan_trips[0]
        trip = SkiTrip(
            user_id=sam.id,
            resort_id=overlap_trip.resort_id,
            state=overlap_trip.state,
            mountain=overlap_trip.mountain,
            start_date=overlap_trip.start_date,
            end_date=overlap_trip.end_date,
            is_public=True
        )
        db.session.add(trip)
        trip_count += 1
    
    # Trip 3: Overlap with dummy users
    if dummy_trips:
        overlap_trip = dummy_trips[0]
        trip = SkiTrip(
            user_id=sam.id,
            resort_id=overlap_trip.resort_id,
            state=overlap_trip.state,
            mountain=overlap_trip.mountain,
            start_date=overlap_trip.start_date,
            end_date=overlap_trip.end_date,
            is_public=True
        )
        db.session.add(trip)
        trip_count += 1
    
    # Trip 4-5: Random future trips
    for i in range(2):
        resort = random.choice(resorts)
        start = base_date + timedelta(days=random.randint(0, 90))
        end = start + timedelta(days=random.randint(2, 5))
        trip = SkiTrip(
            user_id=sam.id,
            resort_id=resort.id,
            state=resort.state,
            mountain=resort.name,
            start_date=start,
            end_date=end,
            is_public=True
        )
        db.session.add(trip)
        trip_count += 1
    
    db.session.commit()
    print(f"✓ Created {trip_count} trips for Sam")
    
    print(f"\n✅ Sam Stookesberry successfully added!")
    print(f"   Email: samstookes@gmail.com")
    print(f"   Friendships: {friendship_count}")
    print(f"   Trips: {trip_count}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
