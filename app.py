import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from models import db, User, SkiTrip, Friend, Invitation

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///baselodge.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

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
            birthday_str = request.form.get("birthday")
            
            if not birthday_str:
                flash("Please enter a valid date of birth.", "error")
                return render_template("auth.html")
            
            try:
                birthday = datetime.strptime(birthday_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Please enter a valid date of birth.", "error")
                return render_template("auth.html")
            
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash("An account with this email already exists.", "error")
                return render_template("auth.html")
            
            user = User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                birthday=birthday
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            session["user_id"] = user.id
            return redirect(url_for("setup_profile"))
        
        elif form_type == "login":
            email = request.form.get("email")
            password = request.form.get("password")
            
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                session["user_id"] = user.id
                if user.profile_setup_complete:
                    return redirect(url_for("profile"))
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
            user.profile_setup_complete = True
            db.session.commit()
            return redirect(url_for("profile"))
    
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
    
    today = date.today()
    upcoming_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date >= today
    ).order_by(SkiTrip.start_date.asc()).all()
    
    past_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date < today
    ).order_by(SkiTrip.start_date.desc()).all()
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template("profile.html", user=user, upcoming_trips=upcoming_trips, past_trips=past_trips, states=states, mountains_by_state=MOUNTAINS_BY_STATE, state_abbr=STATE_ABBR, pass_options=PASS_OPTIONS)

@app.route("/my-trips")
def my_trips():
    if "user_id" not in session:
        return redirect(url_for("auth"))
    
    user = User.query.get(session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("auth"))
    
    if not user.profile_setup_complete:
        return redirect(url_for("setup_profile"))
    
    today = date.today()
    upcoming_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date >= today
    ).order_by(SkiTrip.start_date.asc()).all()
    
    past_trips = SkiTrip.query.filter(
        SkiTrip.user_id == user.id,
        SkiTrip.start_date < today
    ).order_by(SkiTrip.start_date.desc()).all()
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template("my_trips.html", user=user, upcoming_trips=upcoming_trips, past_trips=past_trips, states=states, mountains_by_state=MOUNTAINS_BY_STATE, state_abbr=STATE_ABBR, pass_options=PASS_OPTIONS)

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

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("auth"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
