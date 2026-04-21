"""
Seed script for fullseed@gmail.com dev account.
Creates realistic test data covering all home card scenarios.

SAFETY GUARD: Only runs when FLASK_ENV == 'development' (default).
"""
import os
import sys
from datetime import date, datetime

# Safety guard
if os.environ.get("FLASK_ENV", "development") != "development":
    print("GUARD: FLASK_ENV is not 'development'. Aborting seed.")
    sys.exit(0)

from app import app
from models import db, User, Friend, SkiTrip

TODAY = date.today()
print(f"Running seed_fullseed.py — today is {TODAY}")

FULLSEED_EMAIL = "fullseed@gmail.com"

# Resort IDs (all confirmed active in the DB)
VAIL         = 8
BRECKENRIDGE = 6
BEAVER_CREEK = 5
PARK_CITY    = 28
MAMMOTH      = 42
JACKSON_HOLE = 51
STOWE        = 74
SNOWBIRD     = 25
ALTA         = 24
SUN_VALLEY   = 103
TELLURIDE    = 12
STEAMBOAT    = 17
BIG_SKY      = 55
WHISTLER     = 143
KEYSTONE     = 7
COPPER       = 9
ARAPAHOE     = 15
CRESTED_BUTTE= 18
DEER_VALLEY  = 29
PALISADES    = 38
NORTHSTAR    = 39
HEAVENLY     = 40
KIRKWOOD     = 41

VISITED_RESORT_IDS = [
    VAIL, BRECKENRIDGE, BEAVER_CREEK, PARK_CITY, MAMMOTH,
    JACKSON_HOLE, STOWE, SNOWBIRD, ALTA, SUN_VALLEY,
    TELLURIDE, STEAMBOAT, BIG_SKY, WHISTLER, KEYSTONE,
    COPPER, ARAPAHOE, CRESTED_BUTTE, DEER_VALLEY, PALISADES,
    NORTHSTAR, HEAVENLY, KIRKWOOD,
]  # 23 unique mountains

WISHLIST_RESORT_IDS = [PARK_CITY, BIG_SKY, STOWE]

# Seeded user IDs
SEEDED_USER_IDS = [
    175, 176, 177, 178, 179, 180, 181, 182,
    183, 184, 185, 186, 187, 188, 189, 190, 191, 192,
]


def ensure_mutual_friendship(session, user_a_id, user_b_id):
    """Create A→B and B→A Friend rows if they don't exist."""
    for (uid, fid) in [(user_a_id, user_b_id), (user_b_id, user_a_id)]:
        exists = Friend.query.filter_by(user_id=uid, friend_id=fid).first()
        if not exists:
            session.add(Friend(user_id=uid, friend_id=fid, is_seeded=True))


def add_trip_if_missing(session, user_id, resort_id, start_date, end_date, status):
    """Add a trip if no existing trip for user+resort overlaps the same date range."""
    existing = SkiTrip.query.filter_by(
        user_id=user_id,
        resort_id=resort_id,
        start_date=start_date,
        end_date=end_date,
    ).first()
    if not existing:
        trip = SkiTrip(
            user_id=user_id,
            resort_id=resort_id,
            start_date=start_date,
            end_date=end_date,
            trip_status=status,
        )
        session.add(trip)
        return True
    return False


with app.app_context():
    # ── Step 1: Ensure fullseed user is set up ─────────────────────────
    fs = User.query.filter_by(email=FULLSEED_EMAIL).first()
    if not fs:
        print("ERROR: fullseed@gmail.com not found. Create the account first.")
        sys.exit(1)

    if not fs.first_name or fs.first_name == "Full":
        fs.first_name = "Full"
        fs.last_name = "Seed"

    fs.is_seeded = True
    fs.lifecycle_stage = "active"
    fs.is_verified = True
    db.session.flush()
    print(f"  fullseed user id={fs.id} confirmed.")

    # ── Step 2: Mutual friendships with all seeded users ───────────────
    print("  Setting up mutual friendships...")
    for seed_uid in SEEDED_USER_IDS:
        ensure_mutual_friendship(db.session, fs.id, seed_uid)
    db.session.flush()
    print(f"    Done — fullseed now friends with {len(SEEDED_USER_IDS)} seeded users.")

    # ── Step 3a: fullseed visited mountains ────────────────────────────
    print("  Setting visited_resort_ids...")
    fs.visited_resort_ids = VISITED_RESORT_IDS
    print(f"    {len(VISITED_RESORT_IDS)} mountains set.")

    # ── Step 3b: fullseed wishlist ─────────────────────────────────────
    print("  Setting wish_list_resorts...")
    fs.wish_list_resorts = WISHLIST_RESORT_IDS
    print(f"    Wishlist: {WISHLIST_RESORT_IDS}")

    # ── Step 3c: fullseed trips (5 total) ──────────────────────────────
    print("  Adding fullseed trips...")

    # 1. Past confirmed trip — Mammoth, Feb 2025
    added = add_trip_if_missing(
        db.session, fs.id, MAMMOTH,
        date(2025, 2, 1), date(2025, 2, 5), "going",
    )
    print(f"    [1] Past (Mammoth): {'added' if added else 'already exists'}")

    # 2. TODAY confirmed trip — Vail (triggers real-time overlap card)
    added = add_trip_if_missing(
        db.session, fs.id, VAIL,
        date(2026, 4, 19), date(2026, 4, 24), "going",
    )
    print(f"    [2] Today (Vail): {'added' if added else 'already exists'}")

    # 3. Upcoming confirmed — Park City (in wishlist; Jake has past trip there)
    added = add_trip_if_missing(
        db.session, fs.id, PARK_CITY,
        date(2026, 5, 15), date(2026, 5, 19), "going",
    )
    print(f"    [3] Upcoming confirmed (Park City): {'added' if added else 'already exists'}")

    # 4. Upcoming planning — Big Sky (in wishlist)
    added = add_trip_if_missing(
        db.session, fs.id, BIG_SKY,
        date(2027, 1, 10), date(2027, 1, 16), "planning",
    )
    print(f"    [4] Upcoming planning (Big Sky): {'added' if added else 'already exists'}")

    # 5. Upcoming planning — Stowe (in wishlist)
    added = add_trip_if_missing(
        db.session, fs.id, STOWE,
        date(2027, 2, 5), date(2027, 2, 9), "planning",
    )
    print(f"    [5] Upcoming planning (Stowe): {'added' if added else 'already exists'}")

    # ── Step 4: Expand seeded scenarios ────────────────────────────────
    print("  Seeding scenario trips for friends...")

    # Scenario 2 & 3: TODAY OVERLAP — Sam (177) + Chris (178) at Vail today
    # → fullseed sees multi-friend card: "You're at Vail today. See who else is there."
    added = add_trip_if_missing(
        db.session, 177, VAIL,
        date(2026, 4, 19), date(2026, 4, 24), "going",
    )
    print(f"    Sam at Vail today: {'added' if added else 'already exists'}")

    added = add_trip_if_missing(
        db.session, 178, VAIL,
        date(2026, 4, 21), date(2026, 4, 25), "going",
    )
    print(f"    Chris at Vail today: {'added' if added else 'already exists'}")

    # Scenario 4: WISHLIST MATCH — Jake (182) past trip to Park City
    # → fullseed sees: "Jake [last name] has been to your wishlist mountain, Park City."
    added = add_trip_if_missing(
        db.session, 182, PARK_CITY,
        date(2025, 1, 5), date(2025, 1, 9), "going",
    )
    print(f"    Jake past trip to Park City: {'added' if added else 'already exists'}")

    # Scenario 5: MIXED SIGNALS — Tyler (180) has PAST trip at Vail
    # → Vail today: Sam + Chris there now; Tyler was there before
    added = add_trip_if_missing(
        db.session, 180, VAIL,
        date(2025, 3, 1), date(2025, 3, 5), "going",
    )
    print(f"    Tyler past trip to Vail: {'added' if added else 'already exists'}")

    # Bonus: for Richard's account — single friend overlap at Telluride
    # Jordan (175) + Richard (138) both at Telluride today (trips 249/250 already exist)
    # Verify they exist:
    r_telluride = SkiTrip.query.filter(
        SkiTrip.user_id == 138,
        SkiTrip.resort_id == TELLURIDE,
        SkiTrip.start_date <= TODAY,
        SkiTrip.end_date >= TODAY,
    ).first()
    j_telluride = SkiTrip.query.filter(
        SkiTrip.user_id == 175,
        SkiTrip.resort_id == TELLURIDE,
        SkiTrip.start_date <= TODAY,
        SkiTrip.end_date >= TODAY,
    ).first()
    print(f"    Richard at Telluride today: {'YES' if r_telluride else 'MISSING'}")
    print(f"    Jordan at Telluride today: {'YES' if j_telluride else 'MISSING'}")

    # For Richard's wishlist match: Jordan (175) has past trip at Telluride (already seeded, trip 248)
    # Richard's wishlist includes Telluride (12) — so card fires for Richard too

    # ── Commit everything ───────────────────────────────────────────────
    db.session.commit()
    print("\n  ✓ All seed data committed.")

    # ── Verification summary ────────────────────────────────────────────
    print("\n── VERIFICATION ──────────────────────────────────────────")
    fs = User.query.filter_by(email=FULLSEED_EMAIL).first()
    friend_count = Friend.query.filter_by(user_id=fs.id).count()
    trip_count = SkiTrip.query.filter_by(user_id=fs.id).count()
    print(f"  fullseed friends: {friend_count}")
    print(f"  fullseed trips: {trip_count}")
    print(f"  fullseed visited: {len(fs.visited_resort_ids or [])} mountains")
    print(f"  fullseed wishlist: {fs.wish_list_resorts}")

    # Check today trips
    today_trips = SkiTrip.query.filter(
        SkiTrip.user_id == fs.id,
        SkiTrip.start_date <= TODAY,
        SkiTrip.end_date >= TODAY,
    ).all()
    print(f"  fullseed trips spanning today: {[(t.resort_id, t.start_date, t.end_date) for t in today_trips]}")

    # Check card scenarios
    from app import build_trip_overlap_today_card, build_friend_at_mountain_card
    fs_friend_ids = [f.friend_id for f in Friend.query.filter_by(user_id=fs.id).all()]

    overlap_card = build_trip_overlap_today_card(fs, TODAY, fs_friend_ids)
    print(f"\n  SCENARIO — Trip overlap today card (fullseed): {overlap_card}")

    wishlist_card = build_friend_at_mountain_card(fs, TODAY, fs_friend_ids)
    print(f"  SCENARIO — Friend at mountain card (fullseed): {wishlist_card}")

    # Check Richard's cards
    richard = User.query.filter_by(email='richardbattlebaxter@gmail.com').first()
    r_friend_ids = [f.friend_id for f in Friend.query.filter_by(user_id=richard.id).all()]
    r_overlap = build_trip_overlap_today_card(richard, TODAY, r_friend_ids)
    r_wishlist = build_friend_at_mountain_card(richard, TODAY, r_friend_ids)
    print(f"\n  SCENARIO — Trip overlap today card (Richard): {r_overlap}")
    print(f"  SCENARIO — Friend at mountain card (Richard): {r_wishlist}")
    print("\n── DONE ──────────────────────────────────────────────────")
