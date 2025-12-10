from flask import Blueprint, jsonify
from werkzeug.security import generate_password_hash
from models import db, User, SkiTrip, Friend
from datetime import datetime, timedelta
import random

debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

# Realistic ski data
SKI_STATES = ["CO", "UT", "CA", "VT", "NH", "BC"]
SKI_MOUNTAINS = {
    "CO": ["Vail", "Breckenridge", "Aspen"],
    "UT": ["Park City", "Snowbird", "Alta"],
    "CA": ["Mammoth", "Squaw Valley", "Heavenly"],
    "VT": ["Stowe", "Killington"],
    "NH": ["Cannon", "Wildcat"],
    "BC": ["Whistler Blackcomb"]
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


@debug_bp.route('/seed_social_data', methods=['GET'])
def seed_social_data():
    """
    Create/update social data for testing:
    1. Look up main user by email "me@example.com"
    2. Create up to 10 fake users (if fewer than 10 exist)
    3. Create bidirectional friendship records (skip if already exist)
    4. Create 1–3 fake SkiTrip entries per friend
    """
    try:
        main_user_email = "me@example.com"
        main_user = User.query.filter_by(email=main_user_email).first()
        
        if not main_user:
            return jsonify({"error": f"User with email '{main_user_email}' not found. Sign up first."}), 404
        
        main_user_id = main_user.id
        
        # Names for fake users
        first_names = ["Alex", "Jordan", "Casey", "Morgan", "Riley", "Avery", "Taylor", "Skyler", "Parker", "Quinn"]
        last_names = ["Peak", "Slope", "Ridge", "Trail", "Run", "Bowl", "Chute", "Powder", "Glide", "Drop"]
        pass_types = ["Epic", "Ikon", "Other", "None"]
        rider_types = ["Skier", "Snowboarder"]
        
        # Step 1: Create up to 10 fake users (only if fewer than 10 exist)
        existing_fake_users = User.query.filter(User.email.like("fake%@example.com")).all()
        fake_users = []
        
        if len(existing_fake_users) < 10:
            users_to_create = 10 - len(existing_fake_users)
            for i in range(users_to_create):
                user_idx = len(existing_fake_users) + i
                fake_user = User(
                    first_name=first_names[user_idx % len(first_names)],
                    last_name=last_names[user_idx % len(last_names)],
                    email=f"fake{user_idx + 1}@example.com",
                    password_hash=generate_password_hash("test123"),
                    rider_type=random.choice(rider_types),
                    pass_type=random.choice(pass_types),
                    profile_setup_complete=True
                )
                db.session.add(fake_user)
                fake_users.append(fake_user)
            db.session.commit()
        
        # Get all fake users
        all_fake_users = User.query.filter(User.email.like("fake%@example.com")).all()
        
        # Step 2 & 3: Create bidirectional friendships (only if they don't exist)
        friendships_created = 0
        for fake_user in all_fake_users:
            # Check if friendship already exists (both directions)
            exists_forward = Friend.query.filter_by(user_id=main_user_id, friend_id=fake_user.id).first()
            exists_backward = Friend.query.filter_by(user_id=fake_user.id, friend_id=main_user_id).first()
            
            if not exists_forward:
                friendship1 = Friend(user_id=main_user_id, friend_id=fake_user.id)
                db.session.add(friendship1)
                friendships_created += 1
            
            if not exists_backward:
                friendship2 = Friend(user_id=fake_user.id, friend_id=main_user_id)
                db.session.add(friendship2)
                friendships_created += 1
        
        db.session.commit()
        
        # Step 4: Create 1-3 trips per friend
        trips_created = 0
        for fake_user in all_fake_users:
            num_trips = random.randint(1, 3)
            for _ in range(num_trips):
                state = random.choice(SKI_STATES)
                mountain = random.choice(SKI_MOUNTAINS[state])
                
                # Generate future dates within next 120 days
                trip_start = datetime.today() + timedelta(days=random.randint(1, 120))
                trip_end = trip_start + timedelta(days=random.randint(1, 3))
                
                trip = SkiTrip(
                    user_id=fake_user.id,
                    state=state,
                    mountain=mountain,
                    start_date=trip_start.date(),
                    end_date=trip_end.date(),
                    pass_type=random.choice(pass_types),
                    is_public=random.choice([True, True, False])  # 2/3 chance of public
                )
                db.session.add(trip)
                trips_created += 1
        
        db.session.commit()
        
        return jsonify({
            "message": "✅ Seeded friends, profiles, and trips.",
            "details": {
                "fake_users_total": len(all_fake_users),
                "new_fake_users": len(fake_users),
                "friendships_created": friendships_created,
                "trips_created": trips_created,
                "main_user_email": main_user_email,
                "main_user_id": main_user_id
            }
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
