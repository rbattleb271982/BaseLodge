import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_file
from flask_login import LoginManager, login_required, current_user, login_user
from functools import wraps
from flask_migrate import Migrate
from models import db, User, SkiTrip, Friend, Invitation, InviteToken
from debug_routes import debug_bp
from io import BytesIO
import segno

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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
    # Capture inviter reference from URL parameter
    ref = request.args.get("ref")
    if ref:
        session["invited_by"] = ref
    
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
            
            # --- FRIEND CONNECTION VIA INVITE TOKEN ---
            token_value = request.args.get("token") or session.get("invite_token")

            if token_value:
                token_obj = InviteToken.query.filter_by(token=token_value).first()

                if token_obj and not token_obj.used:
                    inviter = User.query.get(token_obj.inviter_user_id)

                    if inviter:
                        friendship1 = Friend(user_id=inviter.id, friend_id=user.id)
                        friendship2 = Friend(user_id=user.id, friend_id=inviter.id)
                        db.session.add(friendship1)
                        db.session.add(friendship2)

                    token_obj.used = True
                    token_obj.used_by = user.id
                    db.session.commit()

                session.pop("invite_token", None)
            
            login_user(user)
            session["user_id"] = user.id
            
            next_url = request.args.get("next")
            if next_url:
                session["next_after_setup"] = next_url
            
            return redirect(url_for("setup_profile"))
        
        elif form_type == "login":
            email = request.form.get("email")
            password = request.form.get("password")
            
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                login_user(user)
                session["user_id"] = user.id
                
                next_url = request.args.get("next")
                if next_url and user.profile_setup_complete:
                    return redirect(next_url)
                elif user.profile_setup_complete:
                    return redirect(url_for("home"))
                else:
                    if next_url:
                        session["next_after_setup"] = next_url
                    return redirect(url_for("setup_profile"))
            else:
                flash("Invalid email or password.", "error")
                return render_template("auth.html")
    
    return render_template("auth.html")

@app.route("/setup-profile", methods=["GET", "POST"])
@login_required
def setup_profile():
    if request.method == "POST":
        rider_type = request.form.get("rider_type")
        skill_level = request.form.get("skill_level")

        # Validate required fields
        if not rider_type or not skill_level:
            flash("Please select one option for each field.", "error")
            return redirect(url_for("setup_profile"))

        # Save fields to user
        current_user.rider_type = rider_type
        current_user.skill_level = skill_level
        current_user.profile_setup_complete = True
        db.session.commit()

        next_url = session.pop("next_after_setup", None)
        if next_url:
            return redirect(next_url)
        return redirect(url_for("home"))

    return render_template("setup_profile.html")

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
    today = date.today()
    upcoming_trips_count = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.end_date >= today
    ).count()
    friends_count = Friend.query.filter_by(user_id=user.id).count()
    
    return render_template(
        "profile.html", 
        user=user,
        mountains_visited=mountains_visited,
        mountains_visited_count=mountains_visited_count,
        trips_count=upcoming_trips_count,
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
    
    mountains = friend.mountains_visited or []
    friend_mountains_count = len(mountains)
    
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
    invite = InviteToken.generate(current_user.id)
    invite_url = f"{request.host_url}auth?token={invite.token}"
    return render_template("invite.html", user=current_user, invite_url=invite_url)

@app.route("/my-qr")
@login_required
def my_qr():
    invite = InviteToken.generate(current_user.id)
    qr_url = f"{request.host_url}auth?token={invite.token}"
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
                        overlaps.append({
                            "friend_name": friend_trip.user.first_name + " " + friend_trip.user.last_name,
                            "friend_id": friend_trip.user_id,
                            "mountain": my.mountain,
                            "state": my.state,
                            "start_date": max(my.start_date, friend_trip.start_date),
                            "end_date": min(my.end_date, friend_trip.end_date)
                        })
    
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
        state_abbr=STATE_ABBR
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

@app.route("/add_trip", methods=["GET", "POST"])
@login_required
def add_trip():
    if request.method == "POST":
        state = request.form.get("state")
        mountain = request.form.get("mountain")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"

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
            return render_template(
                "add_trip.html",
                trip=None,
                form_action=url_for("add_trip"),
            )

        trip = SkiTrip(
            user_id=current_user.id,
            state=state,
            mountain=mountain,
            start_date=start_date,
            end_date=end_date,
            is_public=is_public,
        )
        db.session.add(trip)
        db.session.commit()
        flash("Trip added.", "success")
        return redirect(url_for("my_trips"))

    # GET
    return render_template(
        "add_trip.html",
        trip=None,
        form_action=url_for("add_trip"),
    )

@app.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@login_required
def edit_trip_form(trip_id):
    trip = SkiTrip.query.get_or_404(trip_id)
    if trip.user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        state = request.form.get("state")
        mountain = request.form.get("mountain")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        is_public = request.form.get("is_public") == "on"

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
            return render_template(
                "add_trip.html",
                trip=trip,
                form_action=url_for("edit_trip_form", trip_id=trip.id),
            )

        trip.state = state
        trip.mountain = mountain
        trip.start_date = start_date
        trip.end_date = end_date
        trip.is_public = is_public

        db.session.commit()
        flash("Trip updated.", "success")
        return redirect(url_for("my_trips"))

    # GET
    return render_template(
        "add_trip.html",
        trip=trip,
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
    flash("Trip deleted.", "success")
    return redirect(url_for("my_trips"))

@app.route("/mountains-visited", methods=["GET", "POST"])
@login_required
def mountains_visited():
    user = current_user
    
    all_mountains = []
    for state_mountains in MOUNTAINS_BY_STATE.values():
        all_mountains.extend(state_mountains)
    all_mountains = sorted(list(set(all_mountains)))
    
    if request.method == "POST":
        selected_mountains = request.form.getlist("mountains")
        user.mountains_visited = selected_mountains
        db.session.commit()
        return redirect(url_for("profile"))
    
    selected_mountains = user.mountains_visited or []
    mountains_visited_count = len(selected_mountains)
    
    return render_template(
        "mountains_visited.html",
        all_mountains=all_mountains,
        selected_mountains=selected_mountains,
        mountains_visited_count=mountains_visited_count,
    )

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("auth"))

@app.route("/seed_dummy_data")
def seed_dummy_data():
    from datetime import timedelta
    import random

    # Get the main user
    main_user = User.query.filter_by(email="me@example.com").first()
    if not main_user:
        return "Main user me@example.com not found."

    # 1. Delete all users except main_user
    other_users = User.query.filter(User.email != "me@example.com").all()
    for u in other_users:
        db.session.delete(u)
    db.session.commit()

    # Data pools
    all_mountains = [
        "Vail", "Beaver Creek", "Breckenridge", "Keystone", "Aspen",
        "Snowmass", "Copper Mountain", "Winter Park", "Steamboat",
        "Park City", "Deer Valley", "Jackson Hole", "Big Sky",
        "Mammoth", "Heavenly", "Northstar"
    ]

    rider_types = ["Skier", "Snowboarder"]
    pass_types = ["Epic", "Ikon", "Other"]
    skill_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]
    states = ["Colorado", "Utah", "California", "Wyoming", "Montana", "Idaho"]

    created = 0
    trips_created = 0

    for i in range(1, 31):
        email = f"testuser{i}@example.com"

        user = User(
            first_name=f"Test{i}",
            last_name="User",
            email=email,
            rider_type=random.choice(rider_types),
            pass_type=random.choice(pass_types),
            skill_level=random.choice(skill_levels),
            home_state=random.choice(states),
            birth_year=random.randint(1980, 2002),
            profile_setup_complete=True,
            mountains_visited=[]
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        # Mountains visited
        user.mountains_visited = random.sample(all_mountains, random.randint(2, 8))
        db.session.commit()

        # Create trips
        today = date.today()

        # 1–3 upcoming
        for _ in range(random.randint(1, 3)):
            start = today + timedelta(days=random.randint(5, 60))
            end = start + timedelta(days=random.randint(2, 5))
            mtn = random.choice(all_mountains)

            trip = SkiTrip(
                user_id=user.id,
                state="Colorado",
                mountain=mtn,
                start_date=start,
                end_date=end,
                is_public=True,
            )
            db.session.add(trip)
            trips_created += 1

        # 1–2 past
        for _ in range(random.randint(1, 2)):
            end = today - timedelta(days=random.randint(10, 120))
            start = end - timedelta(days=random.randint(2, 5))
            mtn = random.choice(all_mountains)

            trip = SkiTrip(
                user_id=user.id,
                state="Colorado",
                mountain=mtn,
                start_date=start,
                end_date=end,
                is_public=True,
            )
            db.session.add(trip)
            trips_created += 1

        db.session.commit()

        # Mutual friendships
        def add_friend(u1, u2):
            if not Friend.query.filter_by(user_id=u1.id, friend_id=u2.id).first():
                db.session.add(Friend(user_id=u1.id, friend_id=u2.id))

        add_friend(main_user, user)
        add_friend(user, main_user)
        db.session.commit()

        created += 1

    return f"Created {created} dummy users and {trips_created} trips."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
