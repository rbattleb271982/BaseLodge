"""
Seed 10 realistic fake users and connect them as friends with richardbat@gmail.com.
Run with: python scripts/seed_more_users.py

Idempotent — safe to re-run; skips users and friend links that already exist.
"""

import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, Friend, UserAvailability
from werkzeug.security import generate_password_hash

TARGET_EMAIL = "richardbat@gmail.com"

NEW_USERS = [
    ("Ava", "Snow"),
    ("Liam", "Powder"),
    ("Mia", "Ridge"),
    ("Noah", "Peak"),
    ("Zoe", "Chute"),
    ("Ethan", "Glide"),
    ("Emma", "Trail"),
    ("Lucas", "Ice"),
    ("Nora", "Slope"),
    ("Levi", "Drop"),
]

RIDER_TYPES  = ["Skier", "Snowboarder", "Social"]
PASS_TYPES   = ["Epic", "Ikon", "Indy Pass", "No Pass"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
HOME_STATES  = ["CO", "UT", "CA", "WA", "MT", "VT", "NY", "WY", "OR", "ID"]
TODAY = date.today()


def seed_more_users():
    with app.app_context():
        target = User.query.filter_by(email=TARGET_EMAIL).first()
        if not target:
            print(f"❌  {TARGET_EMAIL} not found — run the main seed first.")
            return
        print(f"✓  Found target user: {target.first_name} {target.last_name} (id={target.id})")

        created = 0
        users = []

        for i, (first, last) in enumerate(NEW_USERS):
            email = f"{first.lower()}.{last.lower()}@example.com"
            user = User.query.filter_by(email=email).first()
            if user:
                users.append(user)
                print(f"  ⏭  {first} {last} already exists")
                continue

            user = User(
                first_name=first,
                last_name=last,
                email=email,
                password_hash=generate_password_hash("seed_pass_1!"),
                rider_type=RIDER_TYPES[i % len(RIDER_TYPES)],
                rider_types=[RIDER_TYPES[i % len(RIDER_TYPES)]],
                pass_type=PASS_TYPES[i % len(PASS_TYPES)],
                skill_level=SKILL_LEVELS[i % len(SKILL_LEVELS)],
                home_state=HOME_STATES[i % len(HOME_STATES)],
                profile_setup_complete=True,
                is_seeded=True,
                equipment_status="have_own_equipment",
                open_dates=[],
                wish_list_resorts=[],
                visited_resort_ids=[],
                terrain_preferences=[],
                lifecycle_stage="active",
                created_at=datetime.utcnow(),
            )
            db.session.add(user)
            db.session.flush()

            for delta in [7 + i * 3, 14 + i * 2, 28 + i]:
                d = TODAY + timedelta(days=delta)
                if not UserAvailability.query.filter_by(user_id=user.id, date=d).first():
                    db.session.add(UserAvailability(user_id=user.id, date=d, is_available=True))
            user.open_dates = [(TODAY + timedelta(days=7 + i * 3)).isoformat()]
            users.append(user)
            created += 1
            print(f"  ✓  Created {first} {last}")

        db.session.commit()

        added = 0
        for user in users:
            if not Friend.query.filter_by(user_id=target.id, friend_id=user.id).first():
                db.session.add(Friend(user_id=target.id, friend_id=user.id, is_seeded=True, created_at=datetime.utcnow()))
                added += 1
            if not Friend.query.filter_by(user_id=user.id, friend_id=target.id).first():
                db.session.add(Friend(user_id=user.id, friend_id=target.id, is_seeded=True, created_at=datetime.utcnow()))
                added += 1

        db.session.commit()
        total = Friend.query.filter_by(user_id=target.id).count()
        print(f"\n✅  Created {created} users, added {added} friend links.")
        print(f"    {target.first_name} now has {total} friends.")


if __name__ == "__main__":
    seed_more_users()
