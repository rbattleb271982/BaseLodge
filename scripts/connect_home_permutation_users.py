"""
Connect all Home permutation test users (P01–P16) as mutual friends
with each other and with richardbat@gmail.com.

Run:  python scripts/connect_home_permutation_users.py

Idempotent — safe to re-run; skips links that already exist.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, Friend
import sqlalchemy as sa

TARGET_EMAIL = "richardbat@gmail.com"

SCENARIO_EMAILS = [
    "p01.emptyonly@test.com",
    "p02.emptybanner@test.com",
    "p03.owntripnofriends@test.com",
    "p04.guesttrip@test.com",
    "p05.friendtrip@test.com",
    "p06.overlapnudge@test.com",
    "p07.connectinvite@test.com",
    "p08.bestmatch@test.com",
    "p09.tripbanner@test.com",
    "p10.bannermatch@test.com",
    "p11.noequipment@test.com",
    "p12.noidentity@test.com",
    "p13.multiinvite@test.com",
    "p14.multioverlap@test.com",
    "p15.bothtrips@test.com",
    "p16.nooverlap@test.com",
]


def connect_all():
    with app.app_context():
        # Load target user
        target = User.query.filter_by(email=TARGET_EMAIL).first()
        if not target:
            print(f"❌  {TARGET_EMAIL} not found — run the main seed first.")
            return
        print(f"  Target: {target.first_name} {target.last_name} ({TARGET_EMAIL})")

        # Load all scenario users in one query
        users = User.query.filter(User.email.in_(SCENARIO_EMAILS)).all()
        found_emails = {u.email for u in users}
        missing = [e for e in SCENARIO_EMAILS if e not in found_emails]
        if missing:
            print("⚠️  Missing (run seed_home_permutations.py first):")
            for e in missing:
                print(f"    {e}")
        if not users:
            return

        all_ids = [u.id for u in users] + [target.id]

        # Load ALL existing friend links among this group in one query
        existing = set(
            db.session.execute(
                sa.select(Friend.user_id, Friend.friend_id).where(
                    Friend.user_id.in_(all_ids),
                    Friend.friend_id.in_(all_ids),
                )
            ).fetchall()
        )
        print(f"  {len(existing)} existing links among this group")

        # Build full desired set: bidirectional between every pair
        desired = set()
        group = [target] + users
        for i, u1 in enumerate(group):
            for u2 in group[i + 1:]:
                desired.add((u1.id, u2.id))
                desired.add((u2.id, u1.id))

        to_add = desired - existing
        print(f"  {len(to_add)} new links to insert …")

        if to_add:
            now = datetime.utcnow()
            db.session.execute(
                Friend.__table__.insert(),
                [
                    {"user_id": uid, "friend_id": fid,
                     "is_seeded": True, "created_at": now}
                    for uid, fid in to_add
                ]
            )
            db.session.commit()

        total = Friend.query.filter_by(user_id=target.id).count()
        print()
        print("=" * 55)
        print(f"  Inserted {len(to_add)} new friend links.")
        print(f"  {target.first_name} now has {total} friends total.")
        print("=" * 55)


if __name__ == "__main__":
    connect_all()
