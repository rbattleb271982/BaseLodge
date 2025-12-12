"""
Seed 25 dummy users with overlapping open dates for Open tab QA.

This script:
1. Ensures main user exists (richardbattlebaxter@gmail.com)
2. Creates 25 dummy users with unique emails
3. Creates bidirectional friendships
4. Seeds open dates with strategic overlaps
5. Validates pass matching coverage
6. Is safe to re-run (checks before insert)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import User, Friend
from datetime import datetime

# Anchor dates for seeding
ANCHOR_DATES = [
    "2025-12-18",
    "2025-12-26",
    "2025-12-31",
    "2026-01-03",
    "2026-01-10"
]

# Distribution patterns
DISTRIBUTIONS = {
    # 10 users: Perfect overlap (Dec 18, 26, 31)
    "perfect_overlap": {
        "count": 10,
        "open_dates": ["2025-12-18", "2025-12-26", "2025-12-31"],
        "pass_types": ["Epic"] * 5 + ["Ikon"] * 5
    },
    # 8 users: Partial overlap (Dec 26, Jan 3)
    "partial_overlap": {
        "count": 8,
        "open_dates": ["2025-12-26", "2026-01-03"],
        "pass_types": ["Epic"] * 4 + ["Indy"] * 4
    },
    # 5 users: No overlap (Jan 10 only)
    "no_overlap": {
        "count": 5,
        "open_dates": ["2026-01-10"],
        "pass_types": ["Ikon"] * 5
    },
    # 2 users: Edge case (Dec 18, Jan 10)
    "edge_case": {
        "count": 2,
        "open_dates": ["2025-12-18", "2026-01-10"],
        "pass_types": ["Epic", "Ikon"]
    }
}

NAMES = [
    ("Parker", "Williams"),
    ("Alex", "Johnson"),
    ("Jordan", "Brown"),
    ("Casey", "Davis"),
    ("Morgan", "Wilson"),
    ("Riley", "Martinez"),
    ("Avery", "Taylor"),
    ("Quinn", "Anderson"),
    ("Rowan", "Thomas"),
    ("Skyler", "Garcia"),
    ("Cameron", "Lee"),
    ("Dakota", "Perez"),
    ("Phoenix", "White"),
    ("River", "Harris"),
    ("Sage", "Clark"),
    ("Jules", "Lewis"),
    ("Reese", "Robinson"),
    ("Harper", "Walker"),
    ("Finley", "Hall"),
    ("Blake", "Allen"),
    ("Sawyer", "Young"),
    ("Drew", "King"),
    ("Ariel", "Scott"),
    ("Bailey", "Green"),
    ("Jamie", "Adams"),
]

RIDER_TYPES = ["skier", "snowboarder"]
SKILL_LEVELS = ["Intermediate", "Advanced", "Expert"]
HOME_STATES = ["CO", "UT", "CA", "WY", "MT"]

def ensure_main_user():
    """Ensure main user exists or create them."""
    main_email = "richardbattlebaxter@gmail.com"
    user = User.query.filter_by(email=main_email).first()
    
    if user:
        print(f"✅ Main user exists: {user.email}")
        # Set open dates for testing
        user.open_dates = ["2025-12-18", "2025-12-26", "2025-12-31"]
        user.pass_type = "Epic"  # Set a pass type for comparison
        db.session.commit()
        return user
    
    user = User(
        email=main_email,
        first_name="Richard",
        last_name="Battle-Baxter",
        rider_type="skier",
        pass_type="Epic",
        skill_level="Advanced",
        home_state="CO",
        profile_setup_complete=True,
        open_dates=["2025-12-18", "2025-12-26", "2025-12-31"]
    )
    user.set_password("12345678")
    db.session.add(user)
    db.session.commit()
    print(f"✅ Created main user: {user.email}")
    return user

def are_friends(user1, user2):
    """Check if two users are already friends."""
    return Friend.query.filter(
        Friend.user_id == user1.id,
        Friend.friend_id == user2.id
    ).first() is not None

def create_friendship(user1, user2):
    """Create bidirectional friendship."""
    if not are_friends(user1, user2):
        friendship = Friend(user_id=user1.id, friend_id=user2.id)
        db.session.add(friendship)
    
    if not are_friends(user2, user1):
        friendship = Friend(user_id=user2.id, friend_id=user1.id)
        db.session.add(friendship)

def seed_users(main_user):
    """Create 25 dummy users with overlapping open dates."""
    created_count = 0
    friendships_count = 0
    
    user_index = 0
    for distribution_name, distribution in DISTRIBUTIONS.items():
        for i in range(distribution["count"]):
            user_index += 1
            first_name, last_name = NAMES[user_index - 1]
            email = f"{first_name.lower()}.{last_name.lower()}+{i}@test.com"
            
            # Check if user already exists
            existing = User.query.filter_by(email=email).first()
            if existing:
                print(f"  ⚠️  User already exists: {email}")
                user = existing
            else:
                user = User(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    rider_type=RIDER_TYPES[user_index % 2],
                    pass_type=distribution["pass_types"][i % len(distribution["pass_types"])],
                    skill_level=SKILL_LEVELS[user_index % 3],
                    home_state=HOME_STATES[user_index % 5],
                    profile_setup_complete=True,
                    open_dates=distribution["open_dates"]
                )
                user.set_password("password123")
                db.session.add(user)
                db.session.commit()
                created_count += 1
                print(f"  ✅ Created: {email}")
            
            # Create friendship if not exists
            if not are_friends(main_user, user):
                create_friendship(main_user, user)
                db.session.commit()
                friendships_count += 2  # Bidirectional
                print(f"     ↔️  Friendship created")
            else:
                print(f"     ↔️  Already friends")
    
    return created_count, friendships_count

def validate_coverage(main_user):
    """Validate pass matching coverage."""
    friends = Friend.query.filter_by(user_id=main_user.id).all()
    friend_users = [User.query.get(f.friend_id) for f in friends]
    
    same_pass = sum(1 for u in friend_users if u.pass_type == main_user.pass_type)
    diff_pass = sum(1 for u in friend_users if u.pass_type != main_user.pass_type)
    
    print(f"\n📊 Pass matching coverage:")
    print(f"   Same pass ({main_user.pass_type}): {same_pass} users")
    print(f"   Different pass: {diff_pass} users")
    
    if same_pass >= 10 and diff_pass >= 10:
        print(f"   ✅ Coverage requirement met (10+ each)")
        return True
    else:
        print(f"   ⚠️  Coverage may be low")
        return False

def main():
    """Main seeding function."""
    with app.app_context():
        try:
            print("\n🌱 Starting Open Dates Seeding Script\n")
            
            # Step 1: Ensure main user
            print("Step 1: Ensuring main user...")
            main_user = ensure_main_user()
            print(f"   Main user open_dates: {main_user.open_dates}\n")
            
            # Step 2: Create dummy users
            print("Step 2: Creating 25 dummy users...")
            created, friendships = seed_users(main_user)
            print(f"\n   ✅ Created {created} users")
            print(f"   ✅ Created {friendships} friendships\n")
            
            # Step 3: Validate coverage
            print("Step 3: Validating pass matching coverage...")
            validate_coverage(main_user)
            
            print("\n✅ Seeding complete!\n")
            print("You can now:")
            print("  1. Log in as: richardbattlebaxter@gmail.com / 12345678")
            print("  2. Go to Home → Open tab")
            print("  3. See overlapping friends on Dec 18, Dec 26, Dec 31")
            print("  4. Test 'Same pass' vs 'Different pass' indicators")
            print("  5. Edit open dates\n")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            db.session.rollback()
            sys.exit(1)

if __name__ == "__main__":
    main()
