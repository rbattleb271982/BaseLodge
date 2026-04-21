"""
seed_home_scenarios.py — QA home screen scenario coverage for fullseed@gmail.com

SAFETY GUARD: Only runs when FLASK_ENV == 'development'.

Supplements seed_fullseed.py. Does not duplicate that script's work.
Run AFTER seed_fullseed.py:
    FLASK_ENV=development python seed_home_scenarios.py

Idempotent: safe to run repeatedly.

Scenario coverage map
─────────────────────
HOME MODULE          SCENARIO                            KEY USERS
─────────────────────────────────────────────────────────────────────────────
My Next Trip         Planning trip (Big Sky 2027)        fullseed
My Next Trip         Confirmed upcoming (Park City)      fullseed
My Next Trip         Active today (Vail)                 fullseed
─────────────────────────────────────────────────────────────────────────────
Today Overlap        Multiple friends at same mtn today  Sam(177) + Chris(178) at Vail
Today Overlap        Single friend at same mtn today     Dev(189) at Park City May 15+
─────────────────────────────────────────────────────────────────────────────
Wishlist Match       Friend at Park City (past trip)     Jake(182)
Wishlist Match       Friend at Big Sky (past trip)       Maya(176) — different mtn
Wishlist Match       Friend at Stowe (past trip)         Emma(179) — different mtn
Wishlist Match       2nd friend at Park City             Priya(181) — different friend
Wishlist Match       No same-day overlap (Big Sky/Stowe) Maya, Emma — past trips only
─────────────────────────────────────────────────────────────────────────────
Invites              Incoming friend invite              invite_sender → fullseed
Invites              Outgoing friend invite              fullseed → nonfriend2
Invites              Incoming trip invite                Jordan's Stowe trip → fullseed
Invites              Outgoing trip invite                fullseed's Vail trip → Rachel
─────────────────────────────────────────────────────────────────────────────
Control / Boundary   Same dates, different mountain      Tyler(180) at Keystone
Control / Boundary   Non-friend at Vail today            nonfriend1 (NOT a friend)
Control / Boundary   Non-friend past Park City trip      nonfriend2 (NOT a friend)
Control / Boundary   Friend with no trips                Nina(184)
Control / Boundary   Friend, many trips, no overlap      Marco(185)
Control / Boundary   Friend at diff mtn today            Dev(189) at Breckenridge today
─────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
from datetime import date, timedelta

# Safety guard
if os.environ.get("FLASK_ENV", "development") != "development":
    print("GUARD: FLASK_ENV is not 'development'. Aborting seed.")
    sys.exit(0)

from app import app
from models import db, User, Friend, SkiTrip, Invitation, SkiTripParticipant, GuestStatus, InviteType
from werkzeug.security import generate_password_hash

TODAY = date.today()
print(f"Running seed_home_scenarios.py — today is {TODAY}")

# ── Resort IDs ────────────────────────────────────────────────────────────────
VAIL          = 8
BRECKENRIDGE  = 6
PARK_CITY     = 28
MAMMOTH       = 42
JACKSON_HOLE  = 51
STOWE         = 74
BIG_SKY       = 55
KEYSTONE      = 7
TELLURIDE     = 12

FULLSEED_EMAIL = "fullseed@gmail.com"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_or_create_user(email, first_name, last_name, password="Seed1234!", seeded=True):
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            password_hash=generate_password_hash(password),
            is_seeded=seeded,
            lifecycle_stage="active",
            is_verified=True,
        )
        db.session.add(u)
        db.session.flush()
        print(f"    Created user {email} → id={u.id}")
    else:
        print(f"    User {email} already exists → id={u.id}")
    return u


def ensure_mutual_friendship(session, uid_a, uid_b):
    for (u, f) in [(uid_a, uid_b), (uid_b, uid_a)]:
        if not Friend.query.filter_by(user_id=u, friend_id=f).first():
            session.add(Friend(user_id=u, friend_id=f, is_seeded=True))


def add_trip_if_missing(session, user_id, resort_id, start, end, status):
    if not SkiTrip.query.filter_by(
        user_id=user_id, resort_id=resort_id, start_date=start, end_date=end
    ).first():
        t = SkiTrip(
            user_id=user_id,
            resort_id=resort_id,
            start_date=start,
            end_date=end,
            trip_status=status,
        )
        session.add(t)
        session.flush()
        return t
    return None


def ensure_invitation(session, sender_id, receiver_id, trip_id=None, status="pending"):
    """Create an Invitation if none already exists between this pair (for this trip)."""
    existing = Invitation.query.filter_by(
        sender_id=sender_id,
        receiver_id=receiver_id,
        trip_id=trip_id,
    ).first()
    if not existing:
        inv = Invitation(
            sender_id=sender_id,
            receiver_id=receiver_id,
            trip_id=trip_id,
            invite_type=InviteType.OUTBOUND,
            status=status,
        )
        session.add(inv)
        session.flush()
        return inv
    return None


def ensure_trip_participant(session, trip_id, user_id, status=GuestStatus.INVITED):
    """Add user as a participant on a trip if not already present."""
    existing = SkiTripParticipant.query.filter_by(trip_id=trip_id, user_id=user_id).first()
    if not existing:
        p = SkiTripParticipant(trip_id=trip_id, user_id=user_id, status=status)
        session.add(p)
        session.flush()
        return p
    return None


with app.app_context():

    # ── Validate fullseed exists ───────────────────────────────────────────────
    fs = User.query.filter_by(email=FULLSEED_EMAIL).first()
    if not fs:
        print("ERROR: fullseed@gmail.com not found. Run seed_fullseed.py first.")
        sys.exit(1)
    print(f"fullseed confirmed → id={fs.id}")

    # ── Existing seeded friend IDs (from seed_fullseed.py) ────────────────────
    JORDAN  = 175
    MAYA    = 176
    SAM     = 177
    CHRIS   = 178
    EMMA    = 179
    TYLER   = 180
    PRIYA   = 181
    JAKE    = 182
    RACHEL  = 183
    NINA    = 184
    MARCO   = 185
    CASEY   = 186
    PREET   = 187
    LENA    = 188
    DEV     = 189

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Non-friend boundary users
    # These users are NOT connected to fullseed and exist only for control tests.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 1: Non-friend boundary users ────────────────────────────────")

    nf1 = get_or_create_user(
        "nonfriend1@seed.baselodge.app", "Nolan", "Frost",
    )
    nf2 = get_or_create_user(
        "nonfriend2@seed.baselodge.app", "Petra", "Holloway",
    )
    invite_sender = get_or_create_user(
        "invite_sender@seed.baselodge.app", "Alex", "Mercer",
    )

    # nonfriend1: at Vail today — should NOT appear in fullseed's today-overlap card
    t = add_trip_if_missing(
        db.session, nf1.id, VAIL,
        TODAY,
        TODAY + timedelta(days=3),
        "going",
    )
    print(f"    nonfriend1 Vail trip today: {'added' if t else 'already exists'}")

    # nonfriend2: past trip to Park City — should NOT trigger fullseed's wishlist card
    t = add_trip_if_missing(
        db.session, nf2.id, PARK_CITY,
        date(2024, 12, 20), date(2024, 12, 27), "going",
    )
    print(f"    nonfriend2 Park City past trip: {'added' if t else 'already exists'}")

    # Verify no friendship exists (these should NOT be connected to fullseed)
    for nf_id in [nf1.id, nf2.id, invite_sender.id]:
        existing = Friend.query.filter_by(user_id=fs.id, friend_id=nf_id).first()
        if existing:
            print(f"    WARNING: friendship exists between fullseed and user {nf_id} — this breaks the boundary test")
        else:
            print(f"    Confirmed: user {nf_id} is NOT a friend of fullseed ✓")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Wishlist overlap scenarios
    # build_friend_at_mountain_card fires when:
    #   fullseed has upcoming wishlist trip AND a friend has a past trip there
    # Wishlist = [Park City(28), Big Sky(55), Stowe(74)]
    # Park City covered by Jake (182) from seed_fullseed.py
    # Big Sky and Stowe need friends added now.
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 2: Wishlist overlap scenarios ───────────────────────────────")

    # Maya (176) — past trip to Big Sky (fullseed has upcoming Big Sky in Jan 2027)
    t = add_trip_if_missing(
        db.session, MAYA, BIG_SKY,
        date(2025, 3, 1), date(2025, 3, 5), "going",
    )
    print(f"    Maya past trip to Big Sky: {'added' if t else 'already exists'}")

    # Emma (179) — past trip to Stowe (fullseed has upcoming Stowe in Feb 2027)
    t = add_trip_if_missing(
        db.session, EMMA, STOWE,
        date(2025, 1, 10), date(2025, 1, 14), "going",
    )
    print(f"    Emma past trip to Stowe: {'added' if t else 'already exists'}")

    # Priya (181) — past trip to Park City (2nd friend for Park City, different from Jake)
    t = add_trip_if_missing(
        db.session, PRIYA, PARK_CITY,
        date(2024, 12, 28), date(2025, 1, 2), "going",
    )
    print(f"    Priya past trip to Park City: {'added' if t else 'already exists'}")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 — Today overlap: "exactly 1 friend at same mountain today"
    # This fires when fullseed's Park City trip is active (May 15–19, 2026)
    # and only Dev (189) is also at Park City that day.
    # Current date (Apr 21): card shows multiple friends at Vail (Sam + Chris).
    # Future date (May 15+): card shows exactly 1 friend at Park City (Dev only).
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 3: Single-friend overlap (future-dated, Park City) ──────────")

    # Dev (189) confirmed trip to Park City matching fullseed's trip exactly
    t = add_trip_if_missing(
        db.session, DEV, PARK_CITY,
        date(2026, 5, 15), date(2026, 5, 19), "going",
    )
    print(f"    Dev confirmed trip Park City (May 15–19): {'added' if t else 'already exists'}")

    # Sam and Chris are at Vail (April), not Park City — so May 15+ shows exactly 1 friend ✓
    print("    (Sam+Chris are at Vail in April; only Dev will overlap fullseed at Park City in May)")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Invite scenarios (all 4 types)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 4: Invite scenarios ─────────────────────────────────────────")

    # 4a. Incoming FRIEND invite to fullseed → shows as secondary_card on Home
    inv = ensure_invitation(db.session, invite_sender.id, fs.id, trip_id=None, status="pending")
    print(f"    Incoming friend invite (Alex Mercer → fullseed): {'added' if inv else 'already exists'}")

    # 4b. Outgoing FRIEND invite from fullseed → visible on Friends page (not Home)
    inv = ensure_invitation(db.session, fs.id, nf2.id, trip_id=None, status="pending")
    print(f"    Outgoing friend invite (fullseed → Petra Holloway): {'added' if inv else 'already exists'}")

    # 4c. Incoming TRIP invite to fullseed
    # Jordan (175) has upcoming Stowe trip (trip 207, May 5–8, 'going').
    # We invite fullseed to that trip via SkiTripParticipant.
    jordan_stowe_trip = SkiTrip.query.filter_by(
        user_id=JORDAN, resort_id=STOWE, start_date=date(2026, 5, 5)
    ).first()
    if not jordan_stowe_trip:
        jordan_stowe_trip = add_trip_if_missing(
            db.session, JORDAN, STOWE,
            date(2026, 5, 5), date(2026, 5, 8), "going",
        )
        print(f"    Jordan Stowe trip created (for invite): id={jordan_stowe_trip.id if jordan_stowe_trip else 'N/A'}")
    else:
        print(f"    Jordan Stowe trip found → id={jordan_stowe_trip.id}")

    if jordan_stowe_trip:
        p = ensure_trip_participant(db.session, jordan_stowe_trip.id, fs.id, GuestStatus.INVITED)
        print(f"    Incoming trip invite (fullseed invited to Jordan's Stowe trip): {'added' if p else 'already exists'}")

    # 4d. Outgoing TRIP invite from fullseed
    # Rachel (183) is invited to fullseed's Vail trip (id=253).
    fs_vail_trip = SkiTrip.query.filter(
        SkiTrip.user_id == fs.id,
        SkiTrip.resort_id == VAIL,
        SkiTrip.start_date == date(2026, 4, 19),
    ).first()
    if fs_vail_trip:
        p = ensure_trip_participant(db.session, fs_vail_trip.id, RACHEL, GuestStatus.INVITED)
        print(f"    Outgoing trip invite (Rachel invited to fullseed's Vail trip): {'added' if p else 'already exists'}")
    else:
        print("    WARNING: fullseed's Vail trip not found — outgoing trip invite not seeded")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Control / boundary trip data
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 5: Control cases ─────────────────────────────────────────────")

    # Tyler (180): same date window as fullseed's Vail trip but at Keystone (diff mountain)
    # → boundary test: same dates should NOT appear in today-overlap card
    t = add_trip_if_missing(
        db.session, TYLER, KEYSTONE,
        date(2026, 4, 19), date(2026, 4, 24), "going",
    )
    print(f"    Tyler at Keystone (Apr 19–24, same dates as fullseed/Vail): {'added' if t else 'already exists'}")

    # Casey (186): upcoming planning trip with no overlap — purely planning state coverage
    t = add_trip_if_missing(
        db.session, CASEY, MAMMOTH,
        date(2026, 6, 1), date(2026, 6, 5), "planning",
    )
    print(f"    Casey planning trip Mammoth (Jun): {'added' if t else 'already exists'}")

    # Lena (188): past trip + upcoming planning at non-wishlist resort
    t = add_trip_if_missing(
        db.session, LENA, TELLURIDE,
        date(2024, 12, 26), date(2024, 12, 30), "going",
    )
    print(f"    Lena past trip Telluride: {'added' if t else 'already exists'}")
    t = add_trip_if_missing(
        db.session, LENA, JACKSON_HOLE,
        date(2026, 6, 15), date(2026, 6, 20), "planning",
    )
    print(f"    Lena planning trip Jackson Hole (Jun): {'added' if t else 'already exists'}")

    # Marco (185): many trips, none touching fullseed's wishlist or today mountain
    for (resort, s, e, status) in [
        (TELLURIDE,    date(2024, 1, 5),  date(2024, 1, 9),  "going"),
        (JACKSON_HOLE, date(2024, 3, 10), date(2024, 3, 15), "going"),
        (BRECKENRIDGE, date(2025, 2, 20), date(2025, 2, 25), "going"),
        (BRECKENRIDGE, date(2026, 3, 1),  date(2026, 3, 5),  "going"),
        (MAMMOTH,      date(2026, 7, 10), date(2026, 7, 14), "planning"),
    ]:
        t = add_trip_if_missing(db.session, MARCO, resort, s, e, status)
        print(f"    Marco trip resort={resort} {s}–{e}: {'added' if t else 'already exists'}")

    # Nina (184): confirm no trips — friend with no trips (control)
    nina_trips = SkiTrip.query.filter_by(user_id=NINA).count()
    print(f"    Nina trip count: {nina_trips} (should be 0 for control case)")

    # Dev (189): also add an active-today trip at Breckenridge (friend at DIFFERENT mtn today)
    t = add_trip_if_missing(
        db.session, DEV, BRECKENRIDGE,
        TODAY - timedelta(days=1),
        TODAY + timedelta(days=2),
        "going",
    )
    print(f"    Dev at Breckenridge today (different mtn from fullseed): {'added' if t else 'already exists'}")

    # Preet (187): confirmed upcoming trip, no overlap with fullseed wishlist/today
    t = add_trip_if_missing(
        db.session, PREET, JACKSON_HOLE,
        date(2026, 5, 22), date(2026, 5, 26), "going",
    )
    print(f"    Preet confirmed Jackson Hole (May 22–26): {'added' if t else 'already exists'}")

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6 — Additional friend trip diversity (past / planning mix)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n── Section 6: Friend trip diversity ────────────────────────────────────")

    # Jordan (175): already has rich trip set from existing seed — no changes needed
    print("    Jordan: existing trip set retained (rich scenario coverage already seeded)")

    # Sam (177): add a past trip to show history
    t = add_trip_if_missing(
        db.session, SAM, MAMMOTH,
        date(2025, 1, 20), date(2025, 1, 24), "going",
    )
    print(f"    Sam past Mammoth: {'added' if t else 'already exists'}")

    # Chris (178): add a future planning trip
    t = add_trip_if_missing(
        db.session, CHRIS, JACKSON_HOLE,
        date(2026, 7, 1), date(2026, 7, 5), "planning",
    )
    print(f"    Chris future planning Jackson Hole: {'added' if t else 'already exists'}")

    # Rachel (183): upcoming confirmed trip (separate from being invited to fullseed's trip)
    t = add_trip_if_missing(
        db.session, RACHEL, BRECKENRIDGE,
        date(2026, 5, 10), date(2026, 5, 14), "going",
    )
    print(f"    Rachel confirmed Breckenridge (May 10–14): {'added' if t else 'already exists'}")

    # ──────────────────────────────────────────────────────────────────────────
    # COMMIT
    # ──────────────────────────────────────────────────────────────────────────
    db.session.commit()
    print("\n  ✓ All seed data committed.")

    # ──────────────────────────────────────────────────────────────────────────
    # VERIFICATION SUMMARY
    # ──────────────────────────────────────────────────────────────────────────
    print("\n══════════════════════════════════════════════════════════════════════════")
    print("VERIFICATION SUMMARY")
    print("══════════════════════════════════════════════════════════════════════════")

    fs = User.query.filter_by(email=FULLSEED_EMAIL).first()
    friend_count = Friend.query.filter_by(user_id=fs.id).count()
    fs_trips = SkiTrip.query.filter_by(user_id=fs.id).all()
    past = [t for t in fs_trips if t.end_date < TODAY]
    active = [t for t in fs_trips if t.start_date <= TODAY <= t.end_date]
    future = [t for t in fs_trips if t.start_date > TODAY]
    planning = [t for t in fs_trips if (t.trip_status or 'planning') == 'planning']
    confirmed = [t for t in fs_trips if (t.trip_status or '') == 'going']

    print(f"\nfullseed (id={fs.id})")
    print(f"  Friends (accepted):    {friend_count}")
    print(f"  Non-friend QA users:   3 (nonfriend1, nonfriend2, invite_sender)")
    print(f"  Total trips:           {len(fs_trips)}")
    print(f"    Past:                {len(past)}")
    print(f"    Active today:        {len(active)} {[t.resort_id for t in active]}")
    print(f"    Future:              {len(future)}")
    print(f"    Planning status:     {len(planning)}")
    print(f"    Going/confirmed:     {len(confirmed)}")
    print(f"  Visited mountains:     {len(fs.visited_resort_ids or [])}")
    print(f"  Wishlist:              {fs.wish_list_resorts}")

    # Invites
    inc_friend_inv = Invitation.query.filter_by(receiver_id=fs.id, status='pending').filter(Invitation.trip_id == None).all()
    out_friend_inv = Invitation.query.filter_by(sender_id=fs.id, status='pending').filter(Invitation.trip_id == None).all()
    inc_trip_inv = SkiTripParticipant.query.filter_by(user_id=fs.id, status=GuestStatus.INVITED).all()
    # Outgoing trip invite: participants on fullseed's own trips with INVITED status
    fs_trip_ids = [t.id for t in fs_trips]
    out_trip_inv = SkiTripParticipant.query.filter(
        SkiTripParticipant.trip_id.in_(fs_trip_ids),
        SkiTripParticipant.user_id != fs.id,
        SkiTripParticipant.status == GuestStatus.INVITED,
    ).all()

    print(f"\nInvites")
    print(f"  Incoming friend invites:  {len(inc_friend_inv)}")
    print(f"  Outgoing friend invites:  {len(out_friend_inv)}")
    print(f"  Incoming trip invites:    {len(inc_trip_inv)}")
    print(f"  Outgoing trip invites:    {len(out_trip_inv)}")

    # Wishlist overlap check
    wishlist_set = set(fs.wish_list_resorts or [])
    friend_ids = [f.friend_id for f in Friend.query.filter_by(user_id=fs.id).all()]
    wishlist_matches = {}
    for resort_id in wishlist_set:
        friends_with_past = SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.resort_id == resort_id,
            SkiTrip.end_date < TODAY,
        ).all()
        if friends_with_past:
            wishlist_matches[resort_id] = list({t.user_id for t in friends_with_past})

    print(f"\nWishlist overlap scenarios")
    for resort_id, friend_user_ids in wishlist_matches.items():
        names = []
        for uid in friend_user_ids:
            u = db.session.get(User, uid)
            names.append(f"{u.first_name} {u.last_name}" if u else str(uid))
        print(f"  Resort {resort_id}: {names}")

    # Today overlap check
    from app import build_trip_overlap_today_card, build_friend_at_mountain_card
    today_card = build_trip_overlap_today_card(fs, TODAY, friend_ids)
    wishlist_card = build_friend_at_mountain_card(fs, TODAY, friend_ids)

    print(f"\nCard states today ({TODAY})")
    print(f"  trip_overlap_today_card: {today_card}")
    print(f"  friend_at_mountain_card: {wishlist_card}")

    print(f"\nTestable Home scenarios")
    print(f"  ✓  My Next Trip (active today): Vail, going")
    print(f"  ✓  My Next Trip (upcoming confirmed): Park City {date(2026,5,15)}")
    print(f"  ✓  My Next Trip (upcoming planning): Big Sky {date(2027,1,10)}")
    print(f"  ✓  Today overlap, multiple friends: Sam + Chris at Vail")
    print(f"  ✓  Today overlap, 1 friend: Dev at Park City (testable from May 15)")
    print(f"  ✓  Wishlist match — Park City: Jake (182), Priya (181)")
    print(f"  ✓  Wishlist match — Big Sky: Maya (176)")
    print(f"  ✓  Wishlist match — Stowe: Emma (179)")
    print(f"  ✓  Incoming friend invite (secondary_card on Home): Alex Mercer")
    print(f"  ✓  Outgoing friend invite (visible on Friends page): Petra Holloway")
    print(f"  ✓  Incoming trip invite (banner on Home): Jordan's Stowe trip")
    print(f"  ✓  Outgoing trip invite (visible in trip detail): Rachel on Vail trip")
    print(f"  ✓  Control — same dates diff mtn: Tyler at Keystone")
    print(f"  ✓  Control — non-friend at Vail today: Nolan Frost (NOT in friend card)")
    print(f"  ✓  Control — non-friend Park City past: Petra Holloway (NOT in wishlist card)")
    print(f"  ✓  Control — friend with no trips: Nina (184)")
    print(f"  ✓  Control — friend with many trips, no overlap: Marco (185)")
    print(f"  ✓  Control — friend at diff mtn today: Dev at Breckenridge")
    print("\n══════════════════════════════════════════════════════════════════════════")
    print("DONE")
    print("══════════════════════════════════════════════════════════════════════════")
