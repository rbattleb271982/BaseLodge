#!/usr/bin/env python3
"""
Create Demo Network Script

Creates a realistic demo network with:
- 2 anchor users (Richard Richard, Jonathan Schmitz)
- 50 synthetic users with complete profiles
- Bidirectional friendships between all users and anchors
- 3 upcoming trips per user with at least 1 overlap trip

Safe to re-run (idempotent).
Run with: python scripts/create_demo_network.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date, timedelta
import random

from app import app
from models import db, User, Friend, SkiTrip, Resort

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery",
    "Cameron", "Drew", "Skyler", "Parker", "Blake", "Jamie", "Reese", "Sage",
    "Hayden", "Finley", "Rowan", "Emery", "Dakota", "Charlie", "Kendall", "Peyton",
    "Rory", "Sam", "Jessie", "Logan", "Harper", "Addison", "Elliot", "Sydney",
    "Bailey", "Devon", "Brennan", "Tatum", "Micah", "Marley", "Ashton", "Phoenix",
    "River", "Winter", "Storm", "Aspen", "Lake", "Brook", "Shea", "Kai",
    "Remy", "Nico", "Zoe", "Mia", "Olivia", "Emma", "Noah", "Liam"
]

LAST_NAMES = [
    "Anderson", "Baker", "Clark", "Davis", "Evans", "Foster", "Garcia", "Harris",
    "Ingram", "Jackson", "Kelly", "Lopez", "Miller", "Nelson", "Ortiz", "Patel",
    "Quinn", "Roberts", "Smith", "Thompson", "Underwood", "Vasquez", "Williams",
    "Young", "Zimmerman", "Chen", "Kim", "Nguyen", "Park", "Singh", "Tanaka",
    "Yamamoto", "Mueller", "Schmidt", "Weber", "Wagner", "Fischer", "Becker",
    "Hoffmann", "Schneider", "Meyer", "Larsen", "Olsen", "Berg", "Hansen",
    "Johansson", "Nilsson", "Eriksson", "Karlsson", "Lindberg", "Svensson"
]

STATES = ["CO", "UT", "CA", "VT", "MT", "WY", "NM", "OR", "WA", "ID", "NH", "ME", "NY"]
RIDER_TYPES = ["Skier", "Snowboarder", "Both", "Social"]
PASS_TYPES = ["Epic", "Ikon", "Epic,Ikon", "Indy", "I don't have a pass"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
TERRAIN_OPTIONS = ["Groomers", "Trees", "Steeps", "Park", "First Chair", "Après"]


def get_or_create_user(email, first_name, last_name, password, is_anchor=False):
    """Get existing user or create new one."""
    user = User.query.filter_by(email=email.lower()).first()
    if user:
        print(f"  Found existing user: {email}")
        return user, False
    
    user = User(
        email=email.lower(),
        first_name=first_name,
        last_name=last_name,
        rider_type=random.choice(RIDER_TYPES),
        pass_type=random.choice(["Epic", "Ikon", "Epic,Ikon"]),
        skill_level=random.choice(SKILL_LEVELS),
        home_state=random.choice(STATES),
        terrain_preferences=random.sample(TERRAIN_OPTIONS, 2),
        equipment_status="have_own_equipment",
        is_seeded=not is_anchor,
        created_at=datetime.utcnow(),
        lifecycle_stage="active",
        login_count=random.randint(2, 10),
        first_planning_timestamp=datetime.utcnow()
    )
    user.set_password(password)
    db.session.add(user)
    print(f"  Created user: {first_name} {last_name} ({email})")
    return user, True


def are_friends(user_id, friend_id):
    """Check if friendship exists."""
    return Friend.query.filter_by(user_id=user_id, friend_id=friend_id).first() is not None


def create_bidirectional_friendship(user1, user2):
    """Create bidirectional friendship if not exists."""
    created = 0
    
    if not are_friends(user1.id, user2.id):
        f1 = Friend(user_id=user1.id, friend_id=user2.id, is_seeded=True)
        db.session.add(f1)
        created += 1
    
    if not are_friends(user2.id, user1.id):
        f2 = Friend(user_id=user2.id, friend_id=user1.id, is_seeded=True)
        db.session.add(f2)
        created += 1
    
    return created


def user_has_trip_at_resort_on_date(user_id, resort_id, start_date):
    """Check if user already has a trip to this resort starting on this date."""
    return SkiTrip.query.filter_by(
        user_id=user_id,
        resort_id=resort_id,
        start_date=start_date
    ).first() is not None


def create_trip(user, resort, start_date, end_date):
    """Create a trip if not duplicate."""
    if user_has_trip_at_resort_on_date(user.id, resort.id, start_date):
        return None
    
    trip = SkiTrip(
        user_id=user.id,
        resort_id=resort.id,
        state=resort.state,
        mountain=resort.name,
        start_date=start_date,
        end_date=end_date,
        pass_type=resort.brand or "No Pass",
        is_public=True,
        trip_duration=SkiTrip.calculate_duration(start_date, end_date),
        created_at=datetime.utcnow()
    )
    db.session.add(trip)
    return trip


def main():
    print("\n" + "="*60)
    print("CREATE DEMO NETWORK")
    print("="*60 + "\n")
    
    users_created = 0
    friendships_created = 0
    trips_created = 0
    
    with app.app_context():
        resorts = Resort.query.filter_by(is_active=True).all()
        if not resorts:
            print("ERROR: No resorts found. Please seed resorts first.")
            return
        
        print(f"Found {len(resorts)} active resorts\n")
        
        popular_resorts = [r for r in resorts if r.brand in ("Epic", "Ikon")][:20]
        if len(popular_resorts) < 10:
            popular_resorts = resorts[:20]
        
        print("Step 1: Creating anchor users...")
        richard, created = get_or_create_user(
            email="Richard@Richard.com",
            first_name="Richard",
            last_name="Richard",
            password="12345678",
            is_anchor=True
        )
        if created:
            users_created += 1
        
        jonathan, created = get_or_create_user(
            email="Jonathanmschmitz@gmail.com",
            first_name="Jonathan",
            last_name="Schmitz",
            password="12345678",
            is_anchor=True
        )
        if created:
            users_created += 1
        
        db.session.commit()
        print()
        
        print("Step 2: Creating 50 synthetic users...")
        synthetic_users = []
        used_emails = set()
        
        for i in range(50):
            attempts = 0
            while attempts < 100:
                first = random.choice(FIRST_NAMES)
                last = random.choice(LAST_NAMES)
                email = f"{first.lower()}.{last.lower()}{random.randint(1,99)}@demo.baselodge.dev"
                
                if email not in used_emails:
                    used_emails.add(email)
                    break
                attempts += 1
            
            user, created = get_or_create_user(
                email=email,
                first_name=first,
                last_name=last,
                password="12345678"
            )
            if created:
                users_created += 1
            synthetic_users.append(user)
        
        db.session.commit()
        print(f"  Total synthetic users: {len(synthetic_users)}\n")
        
        print("Step 3: Creating bidirectional friendships...")
        for user in synthetic_users:
            friendships_created += create_bidirectional_friendship(user, richard)
            friendships_created += create_bidirectional_friendship(user, jonathan)
        
        friendships_created += create_bidirectional_friendship(richard, jonathan)
        
        db.session.commit()
        print(f"  Friendships created: {friendships_created}\n")
        
        print("Step 4: Creating trips...")
        
        overlap_resort = random.choice(popular_resorts)
        overlap_start = date.today() + timedelta(days=random.randint(30, 60))
        overlap_end = overlap_start + timedelta(days=3)
        
        print(f"  Overlap trip: {overlap_resort.name} ({overlap_start} - {overlap_end})")
        
        trip = create_trip(richard, overlap_resort, overlap_start, overlap_end)
        if trip:
            trips_created += 1
        
        trip = create_trip(jonathan, overlap_resort, overlap_start, overlap_end)
        if trip:
            trips_created += 1
        
        overlap_participants = random.sample(synthetic_users, min(15, len(synthetic_users)))
        for user in overlap_participants:
            trip = create_trip(user, overlap_resort, overlap_start, overlap_end)
            if trip:
                trips_created += 1
        
        for anchor in [richard, jonathan]:
            for i in range(2):
                resort = random.choice(popular_resorts)
                start = date.today() + timedelta(days=random.randint(14 + i*30, 28 + i*30))
                nights = random.choice([1, 2, 3, 4])
                end = start + timedelta(days=nights)
                
                trip = create_trip(anchor, resort, start, end)
                if trip:
                    trips_created += 1
        
        for user in synthetic_users:
            existing_trips = SkiTrip.query.filter(
                SkiTrip.user_id == user.id,
                SkiTrip.start_date >= date.today()
            ).count()
            
            trips_needed = max(0, 3 - existing_trips)
            
            for i in range(trips_needed):
                resort = random.choice(popular_resorts)
                start = date.today() + timedelta(days=random.randint(7 + i*20, 21 + i*20))
                nights = random.choice([0, 1, 2, 3])
                end = start + timedelta(days=nights)
                
                trip = create_trip(user, resort, start, end)
                if trip:
                    trips_created += 1
        
        db.session.commit()
        print(f"  Trips created: {trips_created}\n")
        
        print("="*60)
        print("SUMMARY")
        print("="*60)
        print(f"  Users created:       {users_created}")
        print(f"  Friendships created: {friendships_created}")
        print(f"  Trips created:       {trips_created}")
        print("="*60)
        
        total_users = User.query.count()
        total_friends = Friend.query.count()
        total_trips = SkiTrip.query.filter(SkiTrip.start_date >= date.today()).count()
        
        print(f"\nCurrent totals:")
        print(f"  Total users:          {total_users}")
        print(f"  Total friendships:    {total_friends}")
        print(f"  Total upcoming trips: {total_trips}")
        print()


if __name__ == "__main__":
    main()
