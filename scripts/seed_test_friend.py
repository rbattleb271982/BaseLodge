"""
Seed Test Friend Script
=======================
Creates one clearly-marked test friend and connects them to Richard
(richardbattlebaxter@gmail.com) across all relationship paths the
app actually reads:

  1. Bidirectional Friend rows (both directions)
  2. A SkiTrip owned by the test friend
  3. Test friend added as OWNER participant (ACCEPTED)
  4. Richard added as INVITED participant (GUEST) on that trip
  5. Richard's own trip to the same mountain for overlap testing

Safe to re-run (idempotent).
Run with:  python scripts/seed_test_friend.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta
from app import app
from models import (
    db, User, Friend, SkiTrip, SkiTripParticipant,
    GuestStatus, ParticipantRole
)

RICHARD_EMAIL   = "richardbattlebaxter@gmail.com"
TEST_EMAIL      = "testfriend.devonly@baselodge.dev"
TEST_PASSWORD   = "testpass123"
MOUNTAIN        = "Vail"
MOUNTAIN_STATE  = "CO"


def log(msg):
    print(msg)


def main():
    print("\n" + "=" * 60)
    print("SEED TEST FRIEND")
    print("=" * 60 + "\n")

    with app.app_context():

        # ── 1. Find Richard ─────────────────────────────────────────
        richard = User.query.filter(
            db.func.lower(User.email) == RICHARD_EMAIL.lower()
        ).first()

        if not richard:
            print(f"ERROR: Richard ({RICHARD_EMAIL}) not found.")
            sys.exit(1)

        log(f"✓ Found Richard  id={richard.id}  email={richard.email}")

        # ── 2. Create test friend ────────────────────────────────────
        test_friend = User.query.filter(
            db.func.lower(User.email) == TEST_EMAIL.lower()
        ).first()

        if test_friend:
            log(f"⏭ Test friend already exists  id={test_friend.id}")
        else:
            test_friend = User(
                first_name="Taylor",
                last_name="DevTest",
                email=TEST_EMAIL,
                rider_types=["Skier"],
                primary_rider_type="Skier",
                pass_type="Epic",
                skill_level="Advanced",
                home_state="CO",
                birth_year=1990,
                equipment_status="have_own_equipment",
                lifecycle_stage="active",
                is_seeded=True,
                created_at=datetime.utcnow(),
                login_count=3,
                first_planning_timestamp=datetime.utcnow(),
            )
            test_friend.set_password(TEST_PASSWORD)
            db.session.add(test_friend)
            db.session.flush()
            log(f"✓ Created test friend  id={test_friend.id}  email={TEST_EMAIL}")

        # ── 3. Bidirectional friendship ──────────────────────────────
        created_friends = []

        f_r_to_t = Friend.query.filter_by(
            user_id=richard.id, friend_id=test_friend.id
        ).first()
        if not f_r_to_t:
            f_r_to_t = Friend(user_id=richard.id, friend_id=test_friend.id, is_seeded=True)
            db.session.add(f_r_to_t)
            created_friends.append("richard -> test_friend")

        f_t_to_r = Friend.query.filter_by(
            user_id=test_friend.id, friend_id=richard.id
        ).first()
        if not f_t_to_r:
            f_t_to_r = Friend(user_id=test_friend.id, friend_id=richard.id, is_seeded=True)
            db.session.add(f_t_to_r)
            created_friends.append("test_friend -> richard")

        if created_friends:
            log(f"✓ Friend rows created: {', '.join(created_friends)}")
        else:
            log("⏭ Friend rows already exist")

        db.session.flush()

        # ── 4. Test friend's trip ────────────────────────────────────
        trip_start = date.today() + timedelta(days=45)
        trip_end   = trip_start + timedelta(days=3)

        existing_trip = SkiTrip.query.filter_by(
            user_id=test_friend.id,
            mountain=MOUNTAIN,
            start_date=trip_start
        ).first()

        if existing_trip:
            friend_trip = existing_trip
            log(f"⏭ Test friend's trip already exists  id={friend_trip.id}")
        else:
            friend_trip = SkiTrip(
                user_id=test_friend.id,
                mountain=MOUNTAIN,
                state=MOUNTAIN_STATE,
                start_date=trip_start,
                end_date=trip_end,
                pass_type="Epic",
                is_public=True,
                is_group_trip=True,
                trip_duration=SkiTrip.calculate_duration(trip_start, trip_end),
                created_at=datetime.utcnow(),
            )
            db.session.add(friend_trip)
            db.session.flush()
            log(f"✓ Created friend's trip  id={friend_trip.id}  {MOUNTAIN} {trip_start}–{trip_end}")

        # ── 5. Test friend as OWNER participant (ACCEPTED) ───────────
        owner_participant = SkiTripParticipant.query.filter_by(
            trip_id=friend_trip.id, user_id=test_friend.id
        ).first()
        if not owner_participant:
            owner_participant = SkiTripParticipant(
                trip_id=friend_trip.id,
                user_id=test_friend.id,
                status=GuestStatus.ACCEPTED,
                role=ParticipantRole.OWNER,
            )
            db.session.add(owner_participant)
            log(f"✓ Added test friend as OWNER participant (ACCEPTED)")
        else:
            log(f"⏭ Test friend is already a participant on their trip")

        # ── 6. Richard as INVITED participant ────────────────────────
        richard_participant = SkiTripParticipant.query.filter_by(
            trip_id=friend_trip.id, user_id=richard.id
        ).first()
        if not richard_participant:
            richard_participant = SkiTripParticipant(
                trip_id=friend_trip.id,
                user_id=richard.id,
                status=GuestStatus.INVITED,
                role=ParticipantRole.GUEST,
            )
            db.session.add(richard_participant)
            log(f"✓ Added Richard as INVITED participant (GUEST)")
        else:
            log(f"⏭ Richard is already a participant on that trip")

        # ── 7. Richard's own trip at same mountain (for overlap) ─────
        richard_trip_start = trip_start + timedelta(days=1)
        richard_trip_end   = trip_end

        existing_richard_trip = SkiTrip.query.filter_by(
            user_id=richard.id,
            mountain=MOUNTAIN,
            start_date=richard_trip_start
        ).first()

        if not existing_richard_trip:
            richard_trip = SkiTrip(
                user_id=richard.id,
                mountain=MOUNTAIN,
                state=MOUNTAIN_STATE,
                start_date=richard_trip_start,
                end_date=richard_trip_end,
                pass_type="Epic",
                is_public=True,
                is_group_trip=False,
                trip_duration=SkiTrip.calculate_duration(richard_trip_start, richard_trip_end),
                created_at=datetime.utcnow(),
            )
            db.session.add(richard_trip)
            db.session.flush()
            log(f"✓ Created Richard's trip  id={richard_trip.id}  {MOUNTAIN} {richard_trip_start}–{richard_trip_end}")
        else:
            log(f"⏭ Richard already has a trip at {MOUNTAIN} on that date")

        db.session.commit()

        # ── Summary ──────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Test friend email:  {TEST_EMAIL}")
        print(f"  Test friend password: {TEST_PASSWORD}")
        print(f"  Test friend id:     {test_friend.id}")
        print(f"  Richard id:         {richard.id}")
        print()
        print("  Tables touched:")
        print("    user                 — test friend created/found")
        print("    friend               — 2 bidirectional rows (richard↔test_friend)")
        print("    ski_trip             — 1 trip owned by test_friend, 1 by richard")
        print("    ski_trip_participant — test_friend: ACCEPTED+OWNER, richard: INVITED+GUEST")
        print()
        print("  What this enables:")
        print("    ✓ /friends           — test_friend appears in Richard's friend list")
        print("    ✓ /friends/<id>      — test_friend profile visible with shared trip signal")
        print("    ✓ /home (invited)    — Richard sees pending trip invite on home page")
        print("    ✓ /trips/<id>        — Richard can accept/decline the invite")
        print("    ✓ Trip overlap       — Both at Vail on overlapping dates")
        print()
        print("  ✅ Done — dev environment ready for friend and trip invite testing.")
        print()


if __name__ == "__main__":
    main()
