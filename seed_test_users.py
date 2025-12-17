"""
Seed test users for demo/testing purposes.
Creates Richard + 20 friends with complete profiles, trips, and bidirectional friendships.
"""
from datetime import date, timedelta
import random
from werkzeug.security import generate_password_hash

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery",
    "Cameron", "Dylan", "Parker", "Sage", "Skyler", "Reese", "Jamie", "Drew",
    "Blake", "Finley", "Hayden", "Logan"
]

LAST_NAMES = [
    "Snow", "Frost", "Winter", "Summit", "Peak", "Slope", "Alpine", "Ridge",
    "Valley", "Brooks", "Stone", "Woods", "Lake", "Rivers", "Hills", "Meadow",
    "Sterling", "Chase", "Blake", "Reed"
]

STATES = ["CO", "CA", "UT", "VT", "WY", "MT"]
RIDER_TYPES = ["Skier", "Snowboarder"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]
PASS_TYPES = ["Epic", "Ikon", "Epic,Ikon", "Indy", "MountainCollective"]

SKI_BRANDS = ["Atomic", "Rossignol", "Volkl", "K2", "Blizzard", "Head", "Nordica", "Salomon", "Fischer", "Line"]
SNOWBOARD_BRANDS = ["Burton", "Lib Tech", "Capita", "Jones", "GNU", "Ride", "Never Summer", "Arbor", "Rome", "K2"]
BOOT_BRANDS = ["Tecnica", "Salomon", "Atomic", "Nordica", "Lange", "Head", "Dalbello", "K2", "Full Tilt", "Scarpa"]
BINDING_TYPES_SKI = ["Alpine", "Touring", "Telemark"]
BINDING_TYPES_SNOWBOARD = ["Strap-In", "Step-On", "Rear-Entry"]


def get_resorts_by_state(db_session, Resort):
    """Get dict of state -> list of resort objects."""
    from sqlalchemy import and_
    resorts = db_session.query(Resort).filter(Resort.is_active == True).all()
    by_state = {}
    for r in resorts:
        if r.state not in by_state:
            by_state[r.state] = []
        by_state[r.state].append(r)
    return by_state


def generate_open_dates():
    """Generate 3-8 random open dates in the next 3 months."""
    dates = []
    base = date.today()
    for _ in range(random.randint(3, 8)):
        offset = random.randint(7, 90)
        d = base + timedelta(days=offset)
        dates.append(d.isoformat())
    return sorted(set(dates))


def create_equipment_for_user(db_session, EquipmentSetup, EquipmentSlot, EquipmentDiscipline, user_id, rider_type):
    """Create primary equipment setup for a user."""
    discipline = EquipmentDiscipline.SKIER if rider_type == "Skier" else EquipmentDiscipline.SNOWBOARDER
    
    if rider_type == "Skier":
        brand = random.choice(SKI_BRANDS)
        length = random.randint(160, 185)
        width = random.randint(80, 110)
        binding_type = random.choice(BINDING_TYPES_SKI)
    else:
        brand = random.choice(SNOWBOARD_BRANDS)
        length = random.randint(150, 165)
        width = random.randint(245, 265)
        binding_type = random.choice(BINDING_TYPES_SNOWBOARD)
    
    equipment = EquipmentSetup(
        user_id=user_id,
        slot=EquipmentSlot.PRIMARY,
        discipline=discipline,
        brand=brand,
        length_cm=length,
        width_mm=width,
        binding_type=binding_type,
        boot_brand=random.choice(BOOT_BRANDS),
        boot_flex=random.randint(80, 130)
    )
    db_session.add(equipment)
    return equipment


def create_trips_for_user(db_session, SkiTrip, resorts_by_state, user_id, num_trips, ensure_overlap_dates=None):
    """Create trips for a user. Returns list of (start_date, end_date) tuples."""
    trips_created = []
    states_with_resorts = [s for s in resorts_by_state.keys() if resorts_by_state[s]]
    
    for i in range(num_trips):
        state = random.choice(states_with_resorts)
        resort = random.choice(resorts_by_state[state])
        
        if ensure_overlap_dates and i == 0 and ensure_overlap_dates:
            start_date, end_date = ensure_overlap_dates[0]
        else:
            if i == 0 and random.random() < 0.3:
                offset = random.randint(-60, -7)
            else:
                offset = random.randint(7, 120)
            
            start_date = date.today() + timedelta(days=offset)
            duration = random.randint(2, 7)
            end_date = start_date + timedelta(days=duration)
        
        trip = SkiTrip(
            user_id=user_id,
            resort_id=resort.id,
            state=resort.state,
            mountain=resort.name,
            start_date=start_date,
            end_date=end_date,
            is_public=True,
            ride_intent=random.choice([None, "can_offer", "need_ride"])
        )
        db_session.add(trip)
        trips_created.append((start_date, end_date))
    
    return trips_created


def seed_test_data(app, db, User, Friend, SkiTrip, Resort, EquipmentSetup, EquipmentSlot, EquipmentDiscipline):
    """
    Main seeding function. Creates Richard + 20 friends with full data.
    Returns dict with summary of what was created.
    """
    with app.app_context():
        results = {
            "richard_created": False,
            "richard_id": None,
            "friends_created": 0,
            "trips_created": 0,
            "friendships_created": 0,
            "equipment_created": 0,
            "errors": []
        }
        
        richard = User.query.filter_by(email="richard@richard.com").first()
        if richard:
            results["richard_created"] = False
            results["richard_id"] = richard.id
        else:
            richard = User(
                first_name="Richard",
                last_name="Richard",
                email="richard@richard.com",
                password_hash=generate_password_hash("12345678"),
                rider_type="Skier",
                skill_level="Advanced",
                pass_type="Epic,Ikon",
                home_state="CO",
                birth_year=1990,
                gender="Male",
                gear="Volkl Mantra 177cm, Tecnica Mach1 130",
                home_mountain="Breckenridge",
                mountains_visited=["Breckenridge", "Vail", "Aspen Snowmass", "Park City", "Mammoth Mountain"],
                open_dates=generate_open_dates(),
                profile_setup_complete=True
            )
            db.session.add(richard)
            db.session.flush()
            results["richard_created"] = True
            results["richard_id"] = richard.id
            
            create_equipment_for_user(
                db.session, EquipmentSetup, EquipmentSlot, EquipmentDiscipline,
                richard.id, "Skier"
            )
            results["equipment_created"] += 1
        
        resorts_by_state = get_resorts_by_state(db.session, Resort)
        
        if results["richard_created"]:
            richard_trips = create_trips_for_user(
                db.session, SkiTrip, resorts_by_state, richard.id, 4
            )
            results["trips_created"] += 4
        else:
            existing_trips = SkiTrip.query.filter_by(user_id=richard.id).all()
            richard_trips = [(t.start_date, t.end_date) for t in existing_trips] if existing_trips else []
        
        friend_ids = []
        
        for i in range(20):
            first_name = FIRST_NAMES[i]
            last_name = LAST_NAMES[i]
            email = f"{first_name.lower()}.{last_name.lower()}@test.com"
            
            existing = User.query.filter_by(email=email).first()
            if existing:
                friend_ids.append(existing.id)
                continue
            
            rider_type = random.choice(RIDER_TYPES)
            home_state = random.choice(STATES)
            
            friend = User(
                first_name=first_name,
                last_name=last_name,
                email=email,
                password_hash=generate_password_hash("12345678"),
                rider_type=rider_type,
                skill_level=random.choice(SKILL_LEVELS),
                pass_type=random.choice(PASS_TYPES),
                home_state=home_state,
                birth_year=random.randint(1975, 2005),
                gender=random.choice(GENDERS),
                gear=f"{random.choice(SKI_BRANDS if rider_type == 'Skier' else SNOWBOARD_BRANDS)} setup",
                home_mountain=None,
                mountains_visited=random.sample(
                    ["Vail", "Park City", "Mammoth", "Breckenridge", "Jackson Hole", "Stowe"],
                    k=random.randint(1, 4)
                ),
                open_dates=generate_open_dates(),
                profile_setup_complete=True
            )
            db.session.add(friend)
            db.session.flush()
            friend_ids.append(friend.id)
            results["friends_created"] += 1
            
            create_equipment_for_user(
                db.session, EquipmentSetup, EquipmentSlot, EquipmentDiscipline,
                friend.id, rider_type
            )
            results["equipment_created"] += 1
            
            overlap_dates = richard_trips[:1] if richard_trips and random.random() < 0.4 else None
            num_trips = random.randint(1, 3)
            create_trips_for_user(
                db.session, SkiTrip, resorts_by_state, friend.id, num_trips, 
                ensure_overlap_dates=overlap_dates
            )
            results["trips_created"] += num_trips
        
        for friend_id in friend_ids:
            existing_r_to_f = Friend.query.filter_by(user_id=richard.id, friend_id=friend_id).first()
            if not existing_r_to_f:
                db.session.add(Friend(user_id=richard.id, friend_id=friend_id))
                results["friendships_created"] += 1
            
            existing_f_to_r = Friend.query.filter_by(user_id=friend_id, friend_id=richard.id).first()
            if not existing_f_to_r:
                db.session.add(Friend(user_id=friend_id, friend_id=richard.id))
                results["friendships_created"] += 1
        
        db.session.commit()
        
        final_friend_count = Friend.query.filter_by(user_id=richard.id).count()
        results["richard_friend_count"] = final_friend_count
        
        richard_trip_count = SkiTrip.query.filter_by(user_id=richard.id).count()
        results["richard_trip_count"] = richard_trip_count
        
        return results
