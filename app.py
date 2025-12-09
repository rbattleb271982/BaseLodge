import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from models import db, User, SkiTrip
from debug_routes import debug_bp

app = Flask(__name__)
app.register_blueprint(debug_bp)
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

MOUNTAINS_BY_STATE = {
    "Colorado": ["Vail", "Breckenridge", "Keystone", "Copper Mountain", "Arapahoe Basin", "Loveland", "Winter Park", "Steamboat", "Aspen Snowmass", "Telluride", "Crested Butte", "Eldora"],
    "Utah": ["Park City", "Deer Valley", "Snowbird", "Alta", "Brighton", "Solitude", "Snowbasin", "Powder Mountain"],
    "California": ["Mammoth Mountain", "Palisades Tahoe", "Northstar", "Heavenly", "Kirkwood", "Big Bear", "June Mountain"],
    "Vermont": ["Stowe", "Killington", "Sugarbush", "Jay Peak", "Stratton", "Mount Snow", "Okemo"],
    "Montana": ["Big Sky", "Whitefish Mountain", "Bridger Bowl", "Red Lodge Mountain"],
    "Wyoming": ["Jackson Hole", "Grand Targhee", "Snow King"],
    "New Mexico": ["Taos Ski Valley", "Ski Santa Fe", "Angel Fire"],
    "Idaho": ["Sun Valley", "Schweitzer", "Bogus Basin", "Brundage Mountain"],
    "Oregon": ["Mt. Hood Meadows", "Timberline", "Mt. Bachelor", "Anthony Lakes"],
    "Washington": ["Crystal Mountain", "Stevens Pass", "Mt. Baker", "Snoqualmie"],
    "New Hampshire": ["Bretton Woods", "Cannon Mountain", "Loon Mountain", "Wildcat Mountain"],
    "Maine": ["Sugarloaf", "Sunday River", "Saddleback"],
    "New York": ["Whiteface", "Gore Mountain", "Hunter Mountain", "Windham Mountain"],
    "Michigan": ["Boyne Mountain", "Crystal Mountain MI", "Nubs Nob"],
    "Wisconsin": ["Granite Peak", "Devil's Head", "Cascade Mountain"],
    "Alaska": ["Alyeska Resort"]
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
    
    states = sorted(MOUNTAINS_BY_STATE.keys())
    
    return render_template("profile.html", user=user, trips=upcoming_trips, states=states, mountains_by_state=MOUNTAINS_BY_STATE)

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
    is_public = data.get("is_public", True)
    
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
    
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
    
    return jsonify({
        "success": True,
        "trip": {
            "id": trip.id,
            "state": trip.state,
            "mountain": trip.mountain,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
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
    trip.is_public = data.get("is_public", True)
    
    trip.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    trip.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "trip": {
            "id": trip.id,
            "state": trip.state,
            "mountain": trip.mountain,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
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

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("auth"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
