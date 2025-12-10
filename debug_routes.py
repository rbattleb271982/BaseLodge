from flask import Blueprint, jsonify
from werkzeug.security import generate_password_hash
from models import db, User, SkiTrip, Friend
from datetime import datetime, timedelta
import random

debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

# Realistic ski data
SKI_STATES = ["CO", "UT", "CA", "VT", "NH", "WY", "MT", "ID"]
SKI_MOUNTAINS = {
    "CO": ["Aspen", "Vail", "Breckenridge", "Telluride", "Keystone"],
    "UT": ["Snowbird", "Alta", "Park City", "Powder Mountain", "Brighton"],
    "CA": ["Mammoth Mountain", "Squaw Valley", "Heavenly", "Kirkwood"],
    "VT": ["Stowe", "Killington", "Mad River Glen", "Sugarbush"],
    "NH": ["Cannon", "Tuckerman", "Attitash", "Wildcat"],
    "WY": ["Jackson Hole", "Grand Targhee"],
    "MT": ["Whitefish", "Big Sky", "Bridger Bowl"],
    "ID": ["Schweitzer", "Bogus Basin", "Tamarack"]
}
PASS_TYPES = ["Epic", "Ikon", "Other", "No Pass"]
RIDER_TYPES = ["Skier", "Snowboarder"]

@debug_bp.route('/seed_friends', methods=['GET'])
def seed_friends_and_trips():
    """
    Create 10 dummy users with 3 trips each and bidirectional friend connections to main user.
    For manual testing in the browser to visualize friends and trips.
    """
    try:
        # Main user lookup by email
        main_user_email = "me@example.com"
        main_user = User.query.filter_by(email=main_user_email).first()
        
        if not main_user:
            return jsonify({"error": f"User with email '{main_user_email}' not found. Sign up first."}), 404
        
        main_user_id = main_user.id

        first_names = ["Ava", "Liam", "Mia", "Noah", "Zoe", "Ethan", "Emma", "Lucas", "Nora", "Levi"]
        last_names = ["Snow", "Powder", "Slope", "Ridge", "Peak", "Chute", "Ice", "Glide", "Trail", "Drop"]

        # Create 10 dummy users
        users = []
        for i in range(10):
            user = User(
                first_name=first_names[i],
                last_name=last_names[i],
                email=f"{first_names[i].lower()}{i}@example.com",
                password_hash=generate_password_hash("test123"),
                rider_type=random.choice(RIDER_TYPES),
                pass_type=random.choice(PASS_TYPES),
                profile_setup_complete=True
            )
            db.session.add(user)
            users.append(user)
        db.session.commit()

        # Create 3 trips per dummy user
        for user in users:
            for j in range(3):
                state = random.choice(SKI_STATES)
                mountain = random.choice(SKI_MOUNTAINS[state])
                
                # Generate future dates within 60 days
                trip_start = datetime.today() + timedelta(days=random.randint(3, 45))
                trip_end = trip_start + timedelta(days=random.randint(1, 7))
                
                trip = SkiTrip(
                    user_id=user.id,
                    state=state,
                    mountain=mountain,
                    start_date=trip_start.date(),
                    end_date=trip_end.date(),
                    pass_type=random.choice(PASS_TYPES),
                    is_public=random.choice([True, True, False])  # 2/3 chance of public
                )
                db.session.add(trip)
        db.session.commit()

        # Create bidirectional Friend connections with main user
        for user in users:
            # main_user → friend
            friendship1 = Friend(user_id=main_user_id, friend_id=user.id)
            db.session.add(friendship1)
            
            # friend → main_user (reverse direction)
            friendship2 = Friend(user_id=user.id, friend_id=main_user_id)
            db.session.add(friendship2)
        
        db.session.commit()

        return jsonify({
            "message": "✅ Seeded successfully!",
            "details": {
                "dummy_users": 10,
                "trips_per_user": 3,
                "total_trips": 30,
                "bidirectional_friendships": 10,
                "main_user_email": main_user_email,
                "main_user_id": main_user_id
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
