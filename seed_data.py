"""
Database seeding module.
Run with: python seed_data.py
Creates test users and demo data for development/testing.
"""

import random
from datetime import datetime, date, timedelta
from app import app, db
from models import User, Friend, SkiTrip, Resort


def create_jonathan_and_connect():
    """Create Jonathan user and connect them as friends to all existing users."""
    with app.app_context():
        JONATHAN_FIRST = "Jonathan"
        JONATHAN_LAST = "Schmitz"
        JONATHAN_EMAIL = "jonathanmschmitz@gmail.com"
        JONATHAN_PASSWORD = "12345678"
        
        jonathan = User.query.filter_by(email=JONATHAN_EMAIL).first()
        
        if jonathan:
            print(f"✓ Jonathan already exists (ID: {jonathan.id})")
        else:
            jonathan = User(
                first_name=JONATHAN_FIRST,
                last_name=JONATHAN_LAST,
                email=JONATHAN_EMAIL
            )
            jonathan.set_password(JONATHAN_PASSWORD)
            db.session.add(jonathan)
            db.session.commit()
            print(f"✓ Created Jonathan (ID: {jonathan.id})")
        
        other_users = User.query.filter(User.id != jonathan.id).all()
        print(f"✓ Found {len(other_users)} existing users to connect")
        
        connections_created = 0
        connections_skipped = 0
        
        for other_user in other_users:
            friendship_1 = Friend.query.filter_by(user_id=jonathan.id, friend_id=other_user.id).first()
            if not friendship_1:
                friendship_1 = Friend(user_id=jonathan.id, friend_id=other_user.id)
                db.session.add(friendship_1)
                connections_created += 1
            else:
                connections_skipped += 1
            
            friendship_2 = Friend.query.filter_by(user_id=other_user.id, friend_id=jonathan.id).first()
            if not friendship_2:
                friendship_2 = Friend(user_id=other_user.id, friend_id=jonathan.id)
                db.session.add(friendship_2)
                connections_created += 1
            else:
                connections_skipped += 1
        
        db.session.commit()
        
        print(f"\n✓ Friendship connections created: {connections_created}")
        print(f"✓ Friendship connections skipped (already exist): {connections_skipped}")


def seed_database():
    """Comprehensive database seeding: main users, 50 dummy users, friendships, and trips."""
    with app.app_context():
        dummy_names = [
            ("Alex", "Johnson"), ("Blake", "Mitchell"), ("Casey", "Brown"), ("Dana", "Wilson"),
            ("Emma", "Taylor"), ("Fiona", "Garcia"), ("Grace", "Rodriguez"), ("Harper", "Martinez"),
            ("Isabella", "Lee"), ("Jackson", "Hernandez"), ("Jasmine", "Perez"), ("Jordan", "Davis"),
            ("Kai", "Lopez"), ("Kendall", "Gonzalez"), ("Kyle", "Thompson"), ("Leah", "Anderson"),
            ("Logan", "Thomas"), ("Madison", "Moore"), ("Morgan", "Jackson"), ("Natalie", "Martin"),
            ("Noah", "Clark"), ("Olivia", "Sanchez"), ("Owen", "Morris"), ("Piper", "Rogers"),
            ("Quinn", "Peterson"), ("Rachel", "Cooper"), ("Ryan", "Porter"), ("Samantha", "Hunter"),
            ("Samuel", "Hicks"), ("Sophie", "Crawford"), ("Stephen", "Henry"), ("Sydney", "Howell"),
            ("Taylor", "Crawley"), ("Thomas", "Dalton"), ("Uma", "Denton"), ("Unai", "Durant"),
            ("Victoria", "Dupree"), ("Vincent", "Emerson"), ("Violet", "Emory"), ("Vivian", "Fanning"),
            ("Wade", "Farley"), ("Waylon", "Farnsworth"), ("Whitney", "Farrer"), ("Willow", "Farrow"),
            ("Xander", "Faulkner"), ("Xavier", "Fawcett"), ("Ximena", "Fay"), ("Yolanda", "Feild"),
        ]
        
        ski_states = ["CO", "UT", "CA", "WA", "MT", "VT", "NY", "WY"]
        rider_types = ["Skier", "Snowboarder"]
        pass_types = ["Epic", "Ikon"]
        skill_levels = ["Beginner", "Intermediate", "Advanced"]
        
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        if not richard:
            richard = User(first_name="Richard", last_name="Battle-Baxter", email="richardbattlebaxter@gmail.com")
            richard.set_password("12345678")
            richard.rider_type = "Skier"
            richard.pass_type = "Epic"
            richard.profile_setup_complete = True
            richard.home_state = "CO"
            richard.skill_level = "Advanced"
            richard.birth_year = 1985
            db.session.add(richard)
            print("✓ Created Richard")
        else:
            print("✓ Richard already exists")
        
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        if not jonathan:
            jonathan = User(first_name="Jonathan", last_name="Schmitz", email="jonathanmschmitz@gmail.com")
            jonathan.set_password("12345678")
            jonathan.rider_type = "Skier"
            jonathan.pass_type = "Epic"
            jonathan.profile_setup_complete = True
            jonathan.home_state = "UT"
            jonathan.skill_level = "Advanced"
            jonathan.birth_year = 1987
            db.session.add(jonathan)
            print("✓ Created Jonathan")
        else:
            print("✓ Jonathan already exists")
        
        db.session.commit()
        
        created_dummy = 0
        for i, (first, last) in enumerate(dummy_names, 1):
            email = f"{first.lower()}.{last.lower()}+ski{i:02d}@gmail.com"
            existing = User.query.filter_by(email=email).first()
            if not existing:
                user = User(
                    first_name=first,
                    last_name=last,
                    email=email
                )
                user.set_password("skitest123")
                user.rider_type = random.choice(rider_types)
                user.pass_type = random.choice(pass_types)
                user.skill_level = random.choice(skill_levels)
                user.home_state = random.choice(ski_states)
                user.profile_setup_complete = True
                user.birth_year = random.randint(1980, 2000)
                db.session.add(user)
                created_dummy += 1
        
        db.session.commit()
        print(f"✓ Created {created_dummy} dummy users (50 expected)")
        
        dummy_users = User.query.filter(
            ~User.email.in_(["richardbattlebaxter@gmail.com", "jonathanmschmitz@gmail.com"])
        ).all()
        
        friendship_count = 0
        for dummy in dummy_users:
            for main_user in [richard, jonathan]:
                fwd = Friend.query.filter_by(user_id=dummy.id, friend_id=main_user.id).first()
                if not fwd:
                    db.session.add(Friend(user_id=dummy.id, friend_id=main_user.id))
                    friendship_count += 1
                
                bwd = Friend.query.filter_by(user_id=main_user.id, friend_id=dummy.id).first()
                if not bwd:
                    db.session.add(Friend(user_id=main_user.id, friend_id=dummy.id))
                    friendship_count += 1
        
        db.session.commit()
        print(f"✓ Created {friendship_count} bidirectional friendships")
        
        resorts = Resort.query.filter_by(is_active=True).all()
        base_date = date.today() + timedelta(days=30)
        
        trip_count = 0
        overlap_users = set()
        
        for i, dummy in enumerate(dummy_users[:max(15, len(dummy_users)//3)]):
            for _ in range(2):
                resort = random.choice(resorts)
                start = base_date + timedelta(days=random.randint(0, 90))
                end = start + timedelta(days=random.randint(2, 5))
                trip = SkiTrip(
                    user_id=dummy.id,
                    resort_id=resort.id,
                    state=resort.state,
                    mountain=resort.name,
                    start_date=start,
                    end_date=end,
                    is_public=True
                )
                db.session.add(trip)
                overlap_users.add(dummy.id)
                trip_count += 1
        
        for dummy in dummy_users[max(15, len(dummy_users)//3):]:
            for _ in range(2):
                resort = random.choice(resorts)
                start = base_date + timedelta(days=random.randint(0, 90))
                end = start + timedelta(days=random.randint(2, 5))
                trip = SkiTrip(
                    user_id=dummy.id,
                    resort_id=resort.id,
                    state=resort.state,
                    mountain=resort.name,
                    start_date=start,
                    end_date=end,
                    is_public=True
                )
                db.session.add(trip)
                trip_count += 1
        
        overlap_resort = random.choice(resorts)
        overlap_start = base_date + timedelta(days=30)
        overlap_end = overlap_start + timedelta(days=3)
        
        for main_user in [richard, jonathan]:
            trip = SkiTrip(
                user_id=main_user.id,
                resort_id=overlap_resort.id,
                state=overlap_resort.state,
                mountain=overlap_resort.name,
                start_date=overlap_start,
                end_date=overlap_end,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 2
        
        db.session.commit()
        print(f"✓ Created {trip_count} trips")
        print(f"✓ {len(overlap_users)} users have overlapping dates with Richard & Jonathan")
        
        print(f"\n✅ Database seeding complete!")
        print(f"   Main users: Richard & Jonathan")
        print(f"   Dummy users: {len(dummy_users)}")
        print(f"   Friendships: {friendship_count}")
        print(f"   Trips: {trip_count}")


def add_sam_stookesberry():
    """Add Sam Stookesberry as main user and connect to all existing users with trips."""
    with app.app_context():
        sam = User.query.filter_by(email="samstookes@gmail.com").first()
        if sam:
            print(f"✓ Sam already exists (ID: {sam.id})")
        else:
            sam = User(
                first_name="Sam",
                last_name="Stookesberry",
                email="samstookes@gmail.com"
            )
            sam.set_password("12345678")
            sam.rider_type = "Skier"
            sam.pass_type = "Epic"
            sam.skill_level = "Advanced"
            sam.home_state = "WY"
            sam.birth_year = 1988
            sam.profile_setup_complete = True
            db.session.add(sam)
            db.session.commit()
            print(f"✓ Created Sam (ID: {sam.id})")
        
        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        
        dummy_users = User.query.filter(
            ~User.email.in_(["richardbattlebaxter@gmail.com", "jonathanmschmitz@gmail.com", "samstookes@gmail.com"])
        ).all()
        
        friendship_count = 0
        
        if richard:
            f1 = Friend.query.filter_by(user_id=sam.id, friend_id=richard.id).first()
            if not f1:
                db.session.add(Friend(user_id=sam.id, friend_id=richard.id))
                friendship_count += 1
            
            f2 = Friend.query.filter_by(user_id=richard.id, friend_id=sam.id).first()
            if not f2:
                db.session.add(Friend(user_id=richard.id, friend_id=sam.id))
                friendship_count += 1
        
        if jonathan:
            f1 = Friend.query.filter_by(user_id=sam.id, friend_id=jonathan.id).first()
            if not f1:
                db.session.add(Friend(user_id=sam.id, friend_id=jonathan.id))
                friendship_count += 1
            
            f2 = Friend.query.filter_by(user_id=jonathan.id, friend_id=sam.id).first()
            if not f2:
                db.session.add(Friend(user_id=jonathan.id, friend_id=sam.id))
                friendship_count += 1
        
        for dummy in dummy_users:
            f1 = Friend.query.filter_by(user_id=sam.id, friend_id=dummy.id).first()
            if not f1:
                db.session.add(Friend(user_id=sam.id, friend_id=dummy.id))
                friendship_count += 1
            
            f2 = Friend.query.filter_by(user_id=dummy.id, friend_id=sam.id).first()
            if not f2:
                db.session.add(Friend(user_id=dummy.id, friend_id=sam.id))
                friendship_count += 1
        
        db.session.commit()
        print(f"✓ Created {friendship_count} bidirectional friendships")
        
        resorts = Resort.query.filter_by(is_active=True).all()
        base_date = date.today() + timedelta(days=30)
        trip_count = 0
        
        richard_trips = SkiTrip.query.filter_by(user_id=richard.id).all() if richard else []
        jonathan_trips = SkiTrip.query.filter_by(user_id=jonathan.id).all() if jonathan else []
        dummy_trips = []
        for dummy in dummy_users[:10]:
            dummy_trips.extend(SkiTrip.query.filter_by(user_id=dummy.id).all())
        
        if richard_trips:
            overlap_trip = richard_trips[0]
            trip = SkiTrip(
                user_id=sam.id,
                resort_id=overlap_trip.resort_id,
                state=overlap_trip.state,
                mountain=overlap_trip.mountain,
                start_date=overlap_trip.start_date,
                end_date=overlap_trip.end_date,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 1
        
        if jonathan_trips:
            overlap_trip = jonathan_trips[0]
            trip = SkiTrip(
                user_id=sam.id,
                resort_id=overlap_trip.resort_id,
                state=overlap_trip.state,
                mountain=overlap_trip.mountain,
                start_date=overlap_trip.start_date,
                end_date=overlap_trip.end_date,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 1
        
        if dummy_trips:
            overlap_trip = dummy_trips[0]
            trip = SkiTrip(
                user_id=sam.id,
                resort_id=overlap_trip.resort_id,
                state=overlap_trip.state,
                mountain=overlap_trip.mountain,
                start_date=overlap_trip.start_date,
                end_date=overlap_trip.end_date,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 1
        
        for i in range(2):
            resort = random.choice(resorts)
            start = base_date + timedelta(days=random.randint(0, 90))
            end = start + timedelta(days=random.randint(2, 5))
            trip = SkiTrip(
                user_id=sam.id,
                resort_id=resort.id,
                state=resort.state,
                mountain=resort.name,
                start_date=start,
                end_date=end,
                is_public=True
            )
            db.session.add(trip)
            trip_count += 1
        
        db.session.commit()
        print(f"✓ Created {trip_count} trips for Sam")
        
        print(f"\n✅ Sam Stookesberry successfully added!")
        print(f"   Email: samstookes@gmail.com")
        print(f"   Friendships: {friendship_count}")
        print(f"   Trips: {trip_count}")


if __name__ == "__main__":
    print("Choose an operation:")
    print("1. seed_database() - Full seed with 50 users")
    print("2. create_jonathan_and_connect() - Create Jonathan")
    print("3. add_sam_stookesberry() - Add Sam")
    print("\nRun with: python -c 'from seed_data import seed_database; seed_database()'")
    print("Or:       python -c 'from seed_data import create_jonathan_and_connect; create_jonathan_and_connect()'")
