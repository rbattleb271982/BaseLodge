"""
Seed 20 new realistic fake users and connect them as friends with Richard, Jonathan, and Sam.
Run with: python scripts/seed_more_users.py
"""

import sys
import os
import random
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, Friend

MAIN_USER_EMAILS = [
    "richardbattlebaxter@gmail.com",
    "jonathanmschmitz@gmail.com", 
    "samstookes@gmail.com"
]

NEW_USERS = [
    ("Marcus", "Reynolds"),
    ("Elena", "Vasquez"),
    ("Tyler", "Nakamura"),
    ("Brianna", "O'Sullivan"),
    ("Derek", "Fitzgerald"),
    ("Mia", "Sorenson"),
    ("Brandon", "Kapoor"),
    ("Alyssa", "Chen"),
    ("Garrett", "Lindstrom"),
    ("Nicole", "Brennan"),
    ("Trevor", "Matsuda"),
    ("Hannah", "Kowalski"),
    ("Cameron", "Delgado"),
    ("Sierra", "Hoffman"),
    ("Ethan", "Bergstrom"),
    ("Alexis", "Moreno"),
    ("Colin", "Sutherland"),
    ("Jade", "Fernandez"),
    ("Nathan", "Carmichael"),
    ("Brooke", "Whitfield"),
]

RIDER_TYPES = ["Skier", "Snowboarder", "Telemarking", "Adaptive"]
PASS_TYPES = ["Epic", "Ikon", "Indy Pass", "Mountain Collective", "Powder Alliance", "Freedom Pass", "Ski California Pass", "Other", "None"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
HOME_STATES = ["CO", "UT", "CA", "WA", "MT", "VT", "NY", "WY", "OR", "ID", "NM", "NH", "ME", "MI", "AK"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]

HOME_MOUNTAINS = [
    "Vail", "Breckenridge", "Park City", "Deer Valley", "Aspen", "Snowmass",
    "Mammoth", "Palisades Tahoe", "Steamboat", "Winter Park", "Keystone",
    "Big Sky", "Jackson Hole", "Alta", "Snowbird", "Brighton", "Copper",
    "Telluride", "Crested Butte", "Sun Valley", "Mt. Bachelor", "Crystal Mountain"
]

SKI_BRANDS = ["Volkl", "Rossignol", "Salomon", "Atomic", "Head", "K2", "Nordica", "Blizzard", "Fischer", "Elan", "Line", "Black Crows"]
SNOWBOARD_BRANDS = ["Burton", "Jones", "Lib Tech", "GNU", "Capita", "Ride", "Never Summer", "K2", "Salomon", "Yes."]

MOUNTAINS_VISITED_OPTIONS = [
    ["Vail", "Beaver Creek", "Breckenridge"],
    ["Park City", "Deer Valley", "Brighton", "Snowbird"],
    ["Mammoth", "Palisades Tahoe", "Northstar"],
    ["Jackson Hole", "Grand Targhee"],
    ["Big Sky", "Whitefish"],
    ["Aspen", "Snowmass", "Buttermilk"],
    ["Steamboat", "Winter Park", "Keystone"],
    ["Alta", "Snowbird", "Brighton", "Solitude"],
    ["Telluride", "Crested Butte"],
    ["Sun Valley", "Schweitzer"],
    ["Crystal Mountain", "Stevens Pass", "Mt. Baker"],
    ["Stowe", "Killington", "Sugarbush"],
]


def generate_open_dates(num_dates=None):
    """Generate 3-8 future open dates spread over next 90 days."""
    if num_dates is None:
        num_dates = random.randint(3, 8)
    
    today = date.today()
    dates = set()
    
    while len(dates) < num_dates:
        days_ahead = random.randint(7, 90)
        new_date = today + timedelta(days=days_ahead)
        dates.add(new_date.strftime("%Y-%m-%d"))
    
    return sorted(list(dates))


def seed_more_users():
    """Create 20 new users and connect them as friends with Richard, Jonathan, and Sam."""
    with app.app_context():
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        sam = User.query.filter_by(email="samstookes@gmail.com").first()
        
        main_users = []
        if richard:
            main_users.append(richard)
            print(f"✓ Found Richard (ID: {richard.id})")
        else:
            print("⚠ Richard not found - skipping connections")
        
        if jonathan:
            main_users.append(jonathan)
            print(f"✓ Found Jonathan (ID: {jonathan.id})")
        else:
            print("⚠ Jonathan not found - skipping connections")
        
        if sam:
            main_users.append(sam)
            print(f"✓ Found Sam (ID: {sam.id})")
        else:
            print("⚠ Sam not found - skipping connections")
        
        if not main_users:
            print("❌ No main users found. Please run the main seed first.")
            return
        
        print(f"\n--- Creating 20 new users ---\n")
        
        created_count = 0
        skipped_count = 0
        created_users = []
        
        for i, (first, last) in enumerate(NEW_USERS):
            email = f"{first.lower()}.{last.lower().replace(chr(39), '')}@example.com"
            
            existing = User.query.filter_by(email=email).first()
            if existing:
                print(f"  ⏭ {first} {last} already exists - skipping")
                skipped_count += 1
                created_users.append(existing)
                continue
            
            rider_type = random.choice(RIDER_TYPES)
            
            if rider_type == "Snowboarder":
                gear = random.choice(SNOWBOARD_BRANDS) if random.random() > 0.15 else None
            else:
                gear = random.choice(SKI_BRANDS) if random.random() > 0.15 else None
            
            user = User(
                first_name=first,
                last_name=last,
                email=email
            )
            user.set_password("skibuddy2024")
            user.rider_type = rider_type
            user.pass_type = random.choice(PASS_TYPES)
            user.skill_level = random.choice(SKILL_LEVELS)
            user.home_state = random.choice(HOME_STATES)
            user.home_mountain = random.choice(HOME_MOUNTAINS)
            user.gender = random.choice(GENDERS)
            user.birth_year = random.randint(1970, 2004)
            user.gear = gear
            user.profile_setup_complete = True
            user.open_dates = generate_open_dates()
            user.mountains_visited = random.choice(MOUNTAINS_VISITED_OPTIONS)
            
            db.session.add(user)
            created_users.append(user)
            created_count += 1
            print(f"  ✓ Created {first} {last} ({rider_type}, {user.pass_type})")
        
        db.session.commit()
        
        print(f"\n--- Creating friend connections ---\n")
        
        connections_added = 0
        
        for new_user in created_users:
            for main_user in main_users:
                fwd = Friend.query.filter_by(user_id=new_user.id, friend_id=main_user.id).first()
                if not fwd:
                    db.session.add(Friend(user_id=new_user.id, friend_id=main_user.id))
                    connections_added += 1
                
                bwd = Friend.query.filter_by(user_id=main_user.id, friend_id=new_user.id).first()
                if not bwd:
                    db.session.add(Friend(user_id=main_user.id, friend_id=new_user.id))
                    connections_added += 1
        
        db.session.commit()
        
        print(f"\n{'='*50}")
        print(f"SUMMARY")
        print(f"{'='*50}")
        print(f"Created users: {created_count}")
        print(f"Existing users skipped: {skipped_count}")
        print(f"Friend connections added: {connections_added}")
        print(f"{'='*50}")
        
        print(f"\n✅ Seed complete!")
        print(f"   Richard now has {len(Friend.query.filter_by(user_id=richard.id).all()) if richard else 0} friends")
        print(f"   Jonathan now has {len(Friend.query.filter_by(user_id=jonathan.id).all()) if jonathan else 0} friends")
        print(f"   Sam now has {len(Friend.query.filter_by(user_id=sam.id).all()) if sam else 0} friends")


if __name__ == "__main__":
    seed_more_users()
