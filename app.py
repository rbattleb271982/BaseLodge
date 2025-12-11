import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation
from debug_routes import debug_bp

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth"))
        user = User.query.get(session["user_id"])
        if not user:
            session.pop("user_id", None)
            return redirect(url_for("auth"))
        return f(*args, **kwargs)
    return decorated_function

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
    "Alaska": sorted(["Alyeska Resort"]),
    "California": sorted(["Mammoth Mountain", "Palisades Tahoe", "Northstar", "Heavenly", "Kirkwood", "Big Bear", "June Mountain"]),
    "Colorado": sorted(["Vail", "Breckenridge", "Keystone", "Copper Mountain", "Arapahoe Basin", "Loveland", "Winter Park", "Steamboat", "Aspen Snowmass", "Telluride", "Crested Butte", "Eldora"]),
    "Idaho": sorted(["Sun Valley", "Schweitzer", "Bogus Basin", "Brundage Mountain"]),
    "Maine": sorted(["Sugarloaf", "Sunday River", "Saddleback"]),
    "Michigan": sorted(["Boyne Mountain", "Crystal Mountain MI", "Nubs Nob"]),
    "Montana": sorted(["Big Sky", "Whitefish Mountain", "Bridger Bowl", "Red Lodge Mountain"]),
    "New Hampshire": sorted(["Bretton Woods", "Cannon Mountain", "Loon Mountain", "Wildcat Mountain"]),
    "New Mexico": sorted(["Taos Ski Valley", "Ski Santa Fe", "Angel Fire"]),
    "New York": sorted(["Whiteface", "Gore Mountain", "Hunter Mountain", "Windham Mountain"]),
    "Oregon": sorted(["Mt. Hood Meadows", "Timberline", "Mt. Bachelor", "Anthony Lakes"]),
    "Utah": sorted(["Park City", "Deer Valley", "Snowbird", "Alta", "Brighton", "Solitude", "Snowbasin", "Powder Mountain"]),
    "Vermont": sorted(["Stowe", "Killington", "Sugarbush", "Jay Peak", "Stratton", "Mount Snow", "Okemo"]),
    "Washington": sorted(["Crystal Mountain", "Stevens Pass", "Mt. Baker", "Snoqualmie"]),
    "Wyoming": sorted(["Jackson Hole", "Grand Targhee", "Snow King"])
}

@app.route("/")
def index():
    return redirect(url_for("auth"))

@app.route("/auth", methods=["GET", "POST"])
def auth():
    if request.method == "POST":
        form_type = request.form.get("form_type")
        
        if form_type == "signup":
            first_name = request.form.get("first_name")
            last_name = request.form.get("last_name")
            email = request.form.get("email")
            password = request.form.get("password")
            inviter_id = request.args.get("ref")
            
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
            
            if inviter_id:
                try:
                    inviter = User.query.get(int(inviter_id))
                    if inviter:
                        invitation = Invitation(sender_id=inviter.id, receiver_id=user.id, status='pending')
                        db.session.add(invitation)
                        db.session.commit()
                except (ValueError, TypeError):
                    pass
            
            session["user_id"] = user.id
            return redirect(url_for("setup_profile"))
        
        elif form_type == "login":
            email = request.form.get("email")
            password = request.form.get("password")
            
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                if user.profile_setup_complete:
                    return redirect(url_for("home"))
                else:
                    return redirect(url_for("setup_profile"))
            else:
                flash("Invalid email or password.", "error")
                return render_template("auth.html")
    
    return render_template("auth.html")

@app.route("/setup-profile", methods=["GET", "POST"])
def setup_profile():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    step = request.args.get("step", "1")
    
    if request.method == "POST":
        if step == "1":
            rider_type = request.form.get("rider_type")
            user.rider_type = rider_type
            db.session.commit()
            return redirect(url_for("setup_profile", step="2"))
        elif step == "2":
            pass_type = request.form.get("pass_type")
            user.pass_type = pass_type
            db.session.commit()
            return redirect(url_for("setup_profile", step="3"))
        elif step == "3":
            home_state = request.form.get("home_state")
            birth_year = request.form.get("birth_year")
            skill_level = request.form.get("skill_level")
            user.home_state = home_state
            user.birth_year = int(birth_year) if birth_year else None
            user.skill_level = skill_level
            user.profile_setup_complete = True
            db.session.commit()
            return redirect(url_for("home"))
    
    return render_template("setup_profile.html", step=step, user=user)

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    if not user.profile_setup_complete:
        return redirect(url_for("setup_profile"))
    
    if request.method == "POST":
        user.pass_type = request.form.get("pass_type") or user.pass_type
        user.skill_level = request.form.get("skill_level") or user.skill_level
        user.rider_type = request.form.get("rider_type") or user.rider_type
        user.gender = request.form.get("gender") or user.gender
        db.session.commit()
        return redirect(url_for("profile"))
    
    mountains_visited = user.mountains_visited or []
    mountains_visited_count = len(mountains_visited)
    trips_count = 0
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    
    return render_template(
        "profile.html", 
        user=user,
        mountains_visited=mountains_visited,
        mountains_visited_count=mountains_visited_count,
        trips_count=trips_count,
        friends_count=friends_count
    )

@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    if not user.profile_setup_complete:
        return redirect(url_for("setup_profile"))
    
    if request.method == "POST":
        user.gender = request.form.get("gender") or None
        birth_year_raw = request.form.get("birth_year")
        user.birth_year = int(birth_year_raw) if birth_year_raw else None
        user.rider_type = request.form.get("rider_type") or None
        user.pass_type = request.form.get("pass_type") or None
        user.home_state = request.form.get("home_state") or None
        user.skill_level = request.form.get("skill_level") or None
        user.gear = request.form.get("gear") or None
        
        db.session.commit()
        return redirect(url_for("profile"))
    
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    
    return render_template("edit_profile.html", user=user, friends_count=friends_count, state_abbr=STATE_ABBR, pass_options=PASS_OPTIONS)

@app.route("/my-trips")
def my_trips():
    # Deprecated: Redirect to home which is now the authoritative trips page
    return redirect(url_for("home"))

@app.route("/api/mountains/<state>")
def get_mountains(state):
    mountains = MOUNTAINS_BY_STATE.get(state, [])
    return jsonify(mountains)

@app.route("/api/trip/create", methods=["POST"])
def create_trip():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
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
def edit_trip(trip_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != session["user_id"]:
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
        SkiTrip.user_id == session["user_id"],
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
def delete_trip(trip_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != session["user_id"]:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    db.session.delete(trip)
    db.session.commit()
    
    return jsonify({"success": True})

@app.route("/api/friends/invite", methods=["POST"])
def invite_friend():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    data = request.get_json()
    friend_email = data.get("friend_email")
    
    if not friend_email:
        return jsonify({"success": False, "error": "Friend email is required"}), 400
    
    friend = User.query.filter_by(email=friend_email).first()
    if not friend:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    if friend.id == user_id:
        return jsonify({"success": False, "error": "Cannot add yourself as a friend"}), 400
    
    existing_friendship = Friend.query.filter_by(user_id=user_id, friend_id=friend.id).first()
    if existing_friendship:
        return jsonify({"success": False, "error": "Already friends"}), 409
    
    existing_invitation = Invitation.query.filter_by(sender_id=user_id, receiver_id=friend.id, status='pending').first()
    if existing_invitation:
        return jsonify({"success": False, "error": "Invitation already sent"}), 409
    
    invitation = Invitation(sender_id=user_id, receiver_id=friend.id, status='pending')
    db.session.add(invitation)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Invitation sent"}), 201

@app.route("/api/friends", methods=["GET"])
def get_friends():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    friends = Friend.query.filter_by(user_id=user_id).all()
    
    friends_list = [{
        "id": f.friend.id,
        "name": f"{f.friend.first_name} {f.friend.last_name}",
        "email": f.friend.email,
        "pass_type": f.friend.pass_type or "No Pass"
    } for f in friends]
    
    return jsonify({"success": True, "friends": friends_list}), 200

@app.route("/api/friends/<int:friend_id>", methods=["GET"])
def get_friend_profile(friend_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
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
def accept_invitation(invitation_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    invitation = Invitation.query.get(invitation_id)
    
    if not invitation:
        return jsonify({"success": False, "error": "Invitation not found"}), 404
    
    if invitation.receiver_id != user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    
    invitation.status = 'accepted'
    
    friend_relationship = Friend(user_id=user_id, friend_id=invitation.sender_id)
    reverse_friend = Friend(user_id=invitation.sender_id, friend_id=user_id)
    
    db.session.add(friend_relationship)
    db.session.add(reverse_friend)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Friend added"}), 200

@app.route("/api/friends/<int:friend_id>", methods=["DELETE"])
def remove_friend(friend_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user_id = session["user_id"]
    
    friend1 = Friend.query.filter_by(user_id=user_id, friend_id=friend_id).first()
    friend2 = Friend.query.filter_by(user_id=friend_id, friend_id=user_id).first()
    
    if not friend1 and not friend2:
        return jsonify({"success": False, "error": "Friendship not found"}), 404
    
    if friend1:
        db.session.delete(friend1)
    if friend2:
        db.session.delete(friend2)
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Friend removed"}), 200

@app.route("/friends")
@login_required
def friends():
    user = current_user
    
    if not user.profile_setup_complete:
        return redirect(url_for("setup_profile"))
    
    friends_list = Friend.query.filter_by(user_id=user.id).all()
    friend_ids = [f.friend_id for f in friends_list]
    
    friend_trips = {}
    if friend_ids:
        today = date.today()
        trips = SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.start_date >= today,
            SkiTrip.is_public == True
        ).order_by(SkiTrip.start_date.asc()).all()
        
        for trip in trips:
            if trip.user_id not in friend_trips:
                friend_trips[trip.user_id] = []
            friend_trips[trip.user_id].append(trip)
    
    return render_template("friends.html", user=user, friends=friends_list, friend_trips=friend_trips, state_abbr=STATE_ABBR)

@app.route("/friends/<int:friend_id>")
@login_required
def friend_profile(friend_id):
    friend = User.query.get_or_404(friend_id)
    
    if hasattr(friend, "mountains_visited"):
        friend_mountains_count = len(friend.mountains_visited)
    else:
        friend_mountains_count = 0
    
    today = date.today()
    trips = (
        SkiTrip.query
        .filter_by(user_id=friend.id, is_public=True)
        .filter(SkiTrip.end_date >= today)
        .order_by(SkiTrip.start_date.asc())
        .all()
    )
    
    return render_template(
        "friend_profile.html",
        friend=friend,
        friend_mountains_count=friend_mountains_count,
        trips=trips
    )

@app.route("/profile/<int:user_id>")
def friend_profile_legacy(user_id):
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    current_user = User.query.get(session["user_id"])
    if not current_user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    # Check if viewing own profile
    if user_id == current_user.id:
        return redirect(url_for("profile"))
    
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
def update_profile():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
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
def create_trip_page():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user or not user.profile_setup_complete:
        return redirect(url_for("auth"))
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    return render_template("create_trip.html", user=user, states=states, mountains_by_state=MOUNTAINS_BY_STATE, pass_options=PASS_OPTIONS)

@app.route("/invite")
@login_required
def invite():
    return render_template("invite.html")

@app.route("/home")
def home():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    if not user.profile_setup_complete:
        return redirect(url_for("setup_profile"))
    
    today = date.today()
    
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
    
    # Combined list for All Trips (upcoming only)
    all_trips = (my_trips or []) + (friend_trips or [])
    try:
        all_trips = sorted(all_trips, key=lambda t: t.start_date)
    except Exception:
        pass
    
    return render_template(
        'home.html',
        user=user,
        my_trips=my_trips,
        friend_trips=friend_trips,
        all_trips=all_trips,
        state_abbr=STATE_ABBR
    )

@app.route("/more")
@login_required
def more():
    if hasattr(current_user, "mountains_visited"):
        mountains_visited_count = len(current_user.mountains_visited)
    else:
        mountains_visited_count = 0
    
    return render_template("more.html", mountains_visited_count=mountains_visited_count)

@app.route("/more_info")
@login_required
def more_info():
    if hasattr(current_user, "mountains_visited"):
        mountains_visited_count = len(current_user.mountains_visited)
    else:
        mountains_visited_count = 0
    
    return render_template("more_info.html", mountains_visited_count=mountains_visited_count)

@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")

@app.route("/add_trip", methods=["GET", "POST"])
@login_required
def add_trip():
    user = User.query.get(session["user_id"])
    if not user:
        return redirect(url_for("auth"))
    
    if request.method == "POST":
        state = request.form.get("state")
        mountain = request.form.get("mountain")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"
        
        # Validation
        errors = []
        if not state:
            errors.append("Please select a state.")
        if not mountain:
            errors.append("Please select a mountain.")
        if not start_date_str:
            errors.append("Please select a start date.")
        if not end_date_str:
            errors.append("Please select an end date.")
        
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
            return render_template("add_trip.html")
        
        trip = SkiTrip(
            user_id=user.id,
            state=state,
            mountain=mountain,
            start_date=start_date,
            end_date=end_date,
            is_public=is_public
        )
        db.session.add(trip)
        db.session.commit()
        flash("Trip added!", "success")
        return redirect(url_for("home"))
    
    return render_template("add_trip.html", MOUNTAINS_BY_STATE=MOUNTAINS_BY_STATE)

@app.route("/mountains-visited", methods=["GET", "POST"])
@login_required
def mountains_visited():
    user = User.query.get(session["user_id"])
    if not user:
        return redirect(url_for("auth"))
    
    mountains_by_state = {
        "California": [
            "Heavenly",
            "Kirkwood",
            "Mammoth Mountain",
            "Northstar",
            "Palisades Tahoe",
        ],
        "Colorado": [
            "Arapahoe Basin",
            "Aspen Highlands",
            "Aspen Snowmass",
            "Beaver Creek",
            "Breckenridge",
            "Copper Mountain",
            "Keystone",
            "Steamboat",
            "Telluride",
            "Vail",
            "Winter Park",
        ],
        "Utah": [
            "Alta",
            "Brighton",
            "Deer Valley",
            "Park City",
            "Snowbird",
            "Solitude",
        ],
        "Wyoming": ["Jackson Hole"],
    }
    
    if request.method == "POST":
        selected_mountains = request.form.getlist("mountains")
        user.mountains_visited = selected_mountains
        db.session.commit()
        return redirect(url_for("profile"))
    
    selected_mountains = user.mountains_visited or []
    mountains_visited_count = len(selected_mountains)
    
    return render_template(
        "mountains_visited.html",
        mountains_by_state=mountains_by_state,
        selected_mountains=selected_mountains,
        mountains_visited_count=mountains_visited_count,
    )

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("auth"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
