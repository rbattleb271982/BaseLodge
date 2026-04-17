"""
Seed 10 realistic fake users for empty-state testing.
Run with: python scripts/seed_more_users.py
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, Friend, UserAvailability
from werkzeug.security import generate_password_hash

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

RIDER_TYPES = ["Skier", "Snowboarder", "Social"]
PASS_TYPES = ["Epic", "Ikon", "Indy Pass", "No Pass"]
SKILL_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
HOME_STATES = ["CO", "UT", "CA", "WA", "MT", "VT", "NY", "WY", "OR", "ID"]
HOME_MOUNTAINS = ["Vail", "Breckenridge", "Park City", "Mammoth", "Jackson Hole", "Telluride", "Stowe", "Copper Mountain"]
WISH_LISTS = [
    ["Jackson Hole", "Telluride"],
    ["Vail", "Breckenridge"],
    ["Mammoth", "Palisades Tahoe"],
    ["Park City", "Alta"],
    ["Whistler Blackcomb", "Stowe"],
]


def future_dates(offsets):
    today = date.today()
    return [today + timedelta(days=delta) for delta in offsets]


def set_open_dates(user, offsets):
    dates = [d.isoformat() for d in future_dates(offsets)]
    user.open_dates = dates
    for day in future_dates(offsets):
        db.session.add(UserAvailability(user_id=user.id, date=day, is_available=True))


def seed_more_users():
    with app.app_context():
        existing_emails = {u.email for u in User.query.filter(User.email.like("%@example.com")).all()}
        created = 0
        skipped = 0
        users = []

        for i, (first, last) in enumerate(NEW_USERS):
            email = f"{first.lower()}.{last.lower()}@example.com"
            user = User.query.filter_by(email=email).first()
            if user:
                skipped += 1
                users.append(user)
                continue

            user = User(
                first_name=first,
                last_name=last,
                email=email,
                password_hash=generate_password_hash("seed_pass_1!"),
                rider_type=RIDER_TYPES[i % len(RIDER_TYPES)],
                pass_type=PASS_TYPES[i % len(PASS_TYPES)],
                skill_level=SKILL_LEVELS[i % len(SKILL_LEVELS)],
                home_state=HOME_STATES[i % len(HOME_STATES)],
                home_mountain=HOME_MOUNTAINS[i % len(HOME_MOUNTAINS)],
                gender="Prefer not to say",
                birth_year=1985 + (i % 12),
                profile_setup_complete=True,
                is_seeded=True,
                equipment_status="have_own_equipment",
                wishlist_resorts=WISH_LISTS[i % len(WISH_LISTS)] if hasattr(User, "wishlist_resorts") else None,
                open_dates=[],
            )
            db.session.add(user)
            db.session.flush()
            set_open_dates(user, [7 + i * 3, 14 + i * 2, 28 + i])
            users.append(user)
            created += 1

        db.session.commit()

        richard = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
        jonathan = User.query.filter_by(email="jonathanmschmitz@gmail.com").first()
        sam = User.query.filter_by(email="samstookes@gmail.com").first()
        anchors = [u for u in [richard, jonathan, sam] if u]

        connections = 0
        for user in users:
            for anchor in anchors:
                if not Friend.query.filter_by(user_id=user.id, friend_id=anchor.id).first():
                    db.session.add(Friend(user_id=user.id, friend_id=anchor.id, is_seeded=True))
                    connections += 1
                if not Friend.query.filter_by(user_id=anchor.id, friend_id=user.id).first():
                    db.session.add(Friend(user_id=anchor.id, friend_id=user.id, is_seeded=True))
                    connections += 1

        db.session.commit()
        print(f"Created {created} users, skipped {skipped}, added {connections} friend links.")


if __name__ == "__main__":
    seed_more_users()
