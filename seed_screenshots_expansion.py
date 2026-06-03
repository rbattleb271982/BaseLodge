"""
seed_screenshots_expansion.py — App Store screenshot seed expansion.

Expands the screenshot account (baselodge.screenshots@gmail.com, user_id=13)
with 28 new fictional users, 20 accepted friendships, 5 pending inbound
requests, 3 pending outbound requests, group trips, availability windows,
and activity notifications.

ADMIN-ONLY. Call only through /admin/seed-screenshot-expansion.
Idempotent — safe to call multiple times. All writes are get-or-create.

New users (all passwords: Seed1234!)
─────────────────────────────────────
Accepted friends (20):
  Lucas Bennett      lucas.bennett.screenshots@gmail.com       CO Ikon    Skier        Advanced
  Emma Thornton      emma.thornton.screenshots@gmail.com       UT Ikon    Snowboarder  Intermediate
  Marcus Webb        marcus.webb.screenshots@gmail.com         CA Epic    Skier        Expert
  Sofia Reyes        sofia.reyes.screenshots@gmail.com         WA Ikon    Skier        Advanced
  Derek Halvorsen    derek.halvorsen.screenshots@gmail.com     MT Indy    Skier        Intermediate
  Chloe Patterson    chloe.patterson.screenshots@gmail.com     CO Epic    Snowboarder  Advanced
  Nathan Okafor      nathan.okafor.screenshots@gmail.com       UT Ikon    Skier        Expert
  Rachel Kim         rachel.kim.screenshots@gmail.com          CA Epic    Skier        Advanced
  Tyler Marsh        tyler.marsh.screenshots@gmail.com         WY Indy    Snowboarder  Intermediate
  Haley Donovan      haley.donovan.screenshots@gmail.com       ID Ikon    Skier        Beginner
  Connor Sullivan    connor.sullivan.screenshots@gmail.com     CO Epic    Skier        Advanced
  Priya Sharma       priya.sharma.screenshots@gmail.com        CA Ikon    Snowboarder  Intermediate
  Brendan Fitzgerald brendan.fitzgerald.screenshots@gmail.com VT Epic    Skier        Expert
  Nadia Laurent      nadia.laurent.screenshots@gmail.com       BC Ikon    Snowboarder  Advanced
  Jake Whitmore      jake.whitmore.screenshots@gmail.com       CO Indy    Skier        Intermediate
  Lindsey Chen       lindsey.chen.screenshots@gmail.com        WA Epic    Skier        Advanced
  Owen Callahan      owen.callahan.screenshots@gmail.com       UT Ikon    Skier        Expert
  Brooke Simmons     brooke.simmons.screenshots@gmail.com      OR Epic    Snowboarder  Intermediate
  Ethan Kowalski     ethan.kowalski.screenshots@gmail.com      CO Ikon    Skier        Advanced
  Ryan Hutchinson    ryan.hutchinson.screenshots@gmail.com     WY Epic    Skier        Expert

Pending inbound (5) — they request John:
  Simone Leclerc     simone.leclerc.screenshots@gmail.com      BC Ikon    Snowboarder  Advanced
  Ben Hawkins        ben.hawkins.screenshots@gmail.com         CO Epic    Skier        Expert
  Olivia Strand      olivia.strand.screenshots@gmail.com       UT Ikon    Skier        Intermediate
  Carlos Ibarra      carlos.ibarra.screenshots@gmail.com       CA Epic    Skier        Advanced
  Fiona MacAllister  fiona.macallister.screenshots@gmail.com   MT Indy    Snowboarder  Intermediate

Pending outbound (3) — John requests them:
  Drew Walton        drew.walton.screenshots@gmail.com         WA Epic    Skier        Advanced
  Skylar Finn        skylar.finn.screenshots@gmail.com         OR Ikon    Snowboarder  Intermediate
  Miles Abernathy    miles.abernathy.screenshots@gmail.com     CO Ikon    Skier        Expert
"""

from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash

PRIMARY_EMAIL = "baselodge.screenshots@gmail.com"
SEED_PASSWORD = "Seed1234!"

# ── Resort slug → ID map (resolved at runtime) ────────────────────────────────
RESORT_SLUGS = {
    "whistler":    "whistler-blackcomb-ca",
    "vail":        "vail-us",
    "beaver":      "beaver-creek-us",
    "breck":       "breckenridge-us",
    "keystone":    "keystone-us",
    "park_city":   "park-city-us",
    "deer_valley": "deer-valley-us",
    "snowbird":    "snowbird-us",
    "alta":        "alta-us",
    "jackson":     "jackson-hole-us",
    "mammoth":     "mammoth-mountain-us",
    "aspen":       "aspen-mountain-us",
    "stowe":       "stowe-us",
    "telluride":   "telluride-us",
    "steamboat":   "steamboat-us",
    "copper":      "copper-mountain-us",
    "palisades":   "palisades-tahoe-us",
    "stevens":     "stevens-pass-us",
    "bachelor":    "mt-bachelor-us",
    "sun_valley":  "sun-valley-us",
    "revelstoke":  "revelstoke-ca",
    "abasin":      "arapahoe-basin-us",
}

# ── New accepted-friend specs ──────────────────────────────────────────────────
ACCEPTED_FRIEND_SPECS = [
    {
        "first": "Lucas",   "last": "Bennett",
        "email": "lucas.bennett.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "CO",
        "visited": ["vail", "breck", "park_city", "beaver", "keystone"],
        "wishlist": ["whistler", "jackson", "aspen"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Emma",    "last": "Thornton",
        "email": "emma.thornton.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "UT",
        "visited": ["park_city", "deer_valley", "snowbird", "alta"],
        "wishlist": ["whistler", "revelstoke"],
        "terrain": ["All-Mountain", "Park"],
    },
    {
        "first": "Marcus",  "last": "Webb",
        "email": "marcus.webb.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Expert", "state": "CA",
        "visited": ["mammoth", "palisades", "vail", "breck", "beaver", "park_city"],
        "wishlist": ["whistler", "jackson", "revelstoke"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
    {
        "first": "Sofia",   "last": "Reyes",
        "email": "sofia.reyes.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "WA",
        "visited": ["stevens", "whistler", "sun_valley"],
        "wishlist": ["jackson", "telluride"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Derek",   "last": "Halvorsen",
        "email": "derek.halvorsen.screenshots@gmail.com",
        "pass_type": "Indy", "rider_types": ["Skier"],
        "skill": "Intermediate", "state": "MT",
        "visited": ["steamboat", "sun_valley", "abasin"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Chloe",   "last": "Patterson",
        "email": "chloe.patterson.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Snowboarder"],
        "skill": "Advanced", "state": "CO",
        "visited": ["vail", "breck", "beaver", "keystone", "copper"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain", "Park"],
    },
    {
        "first": "Nathan",  "last": "Okafor",
        "email": "nathan.okafor.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Expert", "state": "UT",
        "visited": ["snowbird", "alta", "deer_valley", "park_city", "jackson"],
        "wishlist": ["whistler", "revelstoke", "aspen"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
    {
        "first": "Rachel",  "last": "Kim",
        "email": "rachel.kim.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "CA",
        "visited": ["mammoth", "palisades", "beaver", "vail"],
        "wishlist": ["whistler", "jackson", "deer_valley"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Tyler",   "last": "Marsh",
        "email": "tyler.marsh.screenshots@gmail.com",
        "pass_type": "Indy", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "WY",
        "visited": ["jackson", "sun_valley"],
        "wishlist": ["whistler", "breck"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Haley",   "last": "Donovan",
        "email": "haley.donovan.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Beginner", "state": "ID",
        "visited": ["sun_valley"],
        "wishlist": ["park_city", "whistler"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Connor",  "last": "Sullivan",
        "email": "connor.sullivan.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "CO",
        "visited": ["vail", "breck", "beaver", "keystone", "copper", "abasin"],
        "wishlist": ["whistler", "aspen", "telluride"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Priya",   "last": "Sharma",
        "email": "priya.sharma.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "CA",
        "visited": ["mammoth", "palisades", "park_city"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain", "Park"],
    },
    {
        "first": "Brendan", "last": "Fitzgerald",
        "email": "brendan.fitzgerald.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Expert", "state": "VT",
        "visited": ["stowe", "vail", "breck", "beaver", "park_city"],
        "wishlist": ["whistler", "jackson", "revelstoke"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
    {
        "first": "Nadia",   "last": "Laurent",
        "email": "nadia.laurent.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Snowboarder"],
        "skill": "Advanced", "state": "BC",
        "visited": ["whistler", "revelstoke"],
        "wishlist": ["jackson", "snowbird", "aspen"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Jake",    "last": "Whitmore",
        "email": "jake.whitmore.screenshots@gmail.com",
        "pass_type": "Indy", "rider_types": ["Skier"],
        "skill": "Intermediate", "state": "CO",
        "visited": ["breck", "keystone", "abasin", "copper"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Lindsey", "last": "Chen",
        "email": "lindsey.chen.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "WA",
        "visited": ["stevens", "whistler", "vail", "breck"],
        "wishlist": ["jackson", "telluride", "aspen"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Owen",    "last": "Callahan",
        "email": "owen.callahan.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Expert", "state": "UT",
        "visited": ["snowbird", "alta", "deer_valley", "park_city", "whistler"],
        "wishlist": ["revelstoke", "jackson"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
    {
        "first": "Brooke",  "last": "Simmons",
        "email": "brooke.simmons.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "OR",
        "visited": ["bachelor", "mammoth", "park_city"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Ethan",   "last": "Kowalski",
        "email": "ethan.kowalski.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "CO",
        "visited": ["vail", "beaver", "breck", "copper", "keystone"],
        "wishlist": ["whistler", "aspen", "telluride"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Ryan",    "last": "Hutchinson",
        "email": "ryan.hutchinson.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Expert", "state": "WY",
        "visited": ["jackson", "telluride", "vail", "breck", "aspen"],
        "wishlist": ["whistler", "revelstoke"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
]

# ── Pending inbound — they request John ───────────────────────────────────────
PENDING_INBOUND_SPECS = [
    {
        "first": "Simone",  "last": "Leclerc",
        "email": "simone.leclerc.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Snowboarder"],
        "skill": "Advanced", "state": "BC",
        "visited": ["whistler", "revelstoke"],
        "wishlist": ["jackson"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Ben",     "last": "Hawkins",
        "email": "ben.hawkins.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Expert", "state": "CO",
        "visited": ["vail", "breck", "aspen", "beaver"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
    {
        "first": "Olivia",  "last": "Strand",
        "email": "olivia.strand.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Intermediate", "state": "UT",
        "visited": ["park_city", "deer_valley"],
        "wishlist": ["whistler"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Carlos",  "last": "Ibarra",
        "email": "carlos.ibarra.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "CA",
        "visited": ["mammoth", "palisades", "vail"],
        "wishlist": ["whistler", "jackson"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Fiona",   "last": "MacAllister",
        "email": "fiona.macallister.screenshots@gmail.com",
        "pass_type": "Indy", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "MT",
        "visited": ["sun_valley", "steamboat"],
        "wishlist": ["jackson", "whistler"],
        "terrain": ["All-Mountain"],
    },
]

# ── Pending outbound — John requests them ─────────────────────────────────────
PENDING_OUTBOUND_SPECS = [
    {
        "first": "Drew",    "last": "Walton",
        "email": "drew.walton.screenshots@gmail.com",
        "pass_type": "Epic", "rider_types": ["Skier"],
        "skill": "Advanced", "state": "WA",
        "visited": ["stevens", "whistler", "vail"],
        "wishlist": ["jackson", "telluride"],
        "terrain": ["All-Mountain", "Trees"],
    },
    {
        "first": "Skylar",  "last": "Finn",
        "email": "skylar.finn.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Snowboarder"],
        "skill": "Intermediate", "state": "OR",
        "visited": ["bachelor", "whistler"],
        "wishlist": ["park_city", "mammoth"],
        "terrain": ["All-Mountain"],
    },
    {
        "first": "Miles",   "last": "Abernathy",
        "email": "miles.abernathy.screenshots@gmail.com",
        "pass_type": "Ikon", "rider_types": ["Skier"],
        "skill": "Expert", "state": "CO",
        "visited": ["vail", "aspen", "telluride", "breck", "jackson"],
        "wishlist": ["whistler", "revelstoke"],
        "terrain": ["All-Mountain", "Backcountry"],
    },
]

# ── Availability groups ────────────────────────────────────────────────────────
# Group A: Dec 18-22 (8 users + John)
GROUP_A_EMAILS = [
    "lucas.bennett.screenshots@gmail.com",
    "emma.thornton.screenshots@gmail.com",
    "marcus.webb.screenshots@gmail.com",
    "sofia.reyes.screenshots@gmail.com",
    "derek.halvorsen.screenshots@gmail.com",
    "chloe.patterson.screenshots@gmail.com",
    "nathan.okafor.screenshots@gmail.com",
    "rachel.kim.screenshots@gmail.com",
]
GROUP_A_DATES = [date(2026, 12, 18), date(2026, 12, 19), date(2026, 12, 20),
                 date(2026, 12, 21), date(2026, 12, 22)]

# Group B: Jan 15-19 (6 users + John)
GROUP_B_EMAILS = [
    "tyler.marsh.screenshots@gmail.com",
    "haley.donovan.screenshots@gmail.com",
    "connor.sullivan.screenshots@gmail.com",
    "priya.sharma.screenshots@gmail.com",
    "brendan.fitzgerald.screenshots@gmail.com",
    "nadia.laurent.screenshots@gmail.com",
]
GROUP_B_DATES = [date(2027, 1, 15), date(2027, 1, 16), date(2027, 1, 17),
                 date(2027, 1, 18), date(2027, 1, 19)]

# Group C: Feb 12-16 (4 users)
GROUP_C_EMAILS = [
    "jake.whitmore.screenshots@gmail.com",
    "lindsey.chen.screenshots@gmail.com",
    "owen.callahan.screenshots@gmail.com",
    "brooke.simmons.screenshots@gmail.com",
]
GROUP_C_DATES = [date(2027, 2, 12), date(2027, 2, 13), date(2027, 2, 14),
                 date(2027, 2, 15), date(2027, 2, 16)]

# Random windows for remaining users
RANDOM_AVAIL = {
    "ethan.kowalski.screenshots@gmail.com":   [date(2027, 3, 5), date(2027, 3, 6), date(2027, 3, 7), date(2027, 3, 8)],
    "ryan.hutchinson.screenshots@gmail.com":  [date(2027, 2, 25), date(2027, 2, 26), date(2027, 2, 27), date(2027, 2, 28)],
    "simone.leclerc.screenshots@gmail.com":   [date(2026, 12, 20), date(2026, 12, 21), date(2026, 12, 22)],
    "ben.hawkins.screenshots@gmail.com":      [date(2027, 1, 10), date(2027, 1, 11), date(2027, 1, 12)],
    "drew.walton.screenshots@gmail.com":      [date(2027, 2, 5), date(2027, 2, 6), date(2027, 2, 7)],
}

# John Carter availability additions (so he overlaps groups)
JOHN_AVAIL_DATES = (
    GROUP_A_DATES                           # Dec 18-22 — overlaps group A
    + GROUP_B_DATES                         # Jan 15-19 — overlaps group B
    + [date(2027, 2, 12), date(2027, 2, 13), date(2027, 2, 14)]  # Feb 12-14 — partial group C overlap
    + [date(2027, 2, 25), date(2027, 2, 26), date(2027, 2, 27)]  # Feb 25-27 — overlaps Ryan
)


# ── Public entry point ────────────────────────────────────────────────────────

def seed_screenshot_expansion(app, db, User, Friend, SkiTrip, Invitation,
                               SkiTripParticipant, Resort, UserAvailability,
                               Activity, GuestStatus, InviteType):
    """
    Expand App Store screenshot data for John Carter (user_id=13).
    Returns a summary dict.
    """
    results = {
        "users_created":        0,
        "users_skipped":        0,
        "friends_created":      0,
        "friends_skipped":      0,
        "invitations_created":  0,
        "invitations_skipped":  0,
        "trips_created":        0,
        "trips_skipped":        0,
        "participants_created": 0,
        "participants_skipped": 0,
        "availability_created": 0,
        "availability_skipped": 0,
        "activity_created":     0,
        "activity_skipped":     0,
    }

    # ── Step 1: Resolve resort IDs ────────────────────────────────────────────
    r_ids = {}
    missing = []
    for key, slug in RESORT_SLUGS.items():
        r = Resort.query.filter_by(slug=slug, is_active=True).first()
        if r:
            r_ids[key] = r.id
        else:
            missing.append(f"{key}={slug}")
    if missing:
        raise ValueError(f"Missing resorts: {missing}")

    # ── Step 2: Resolve John Carter ───────────────────────────────────────────
    john = User.query.filter_by(email=PRIMARY_EMAIL).first()
    if not john:
        raise ValueError(f"Primary screenshot user {PRIMARY_EMAIL} not found. Run /admin/seed-screenshot-data first.")
    john_id = john.id

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_visited(slug_keys):
        return [r_ids[k] for k in slug_keys if k in r_ids]

    def _build_wishlist(slug_keys):
        return [r_ids[k] for k in slug_keys[:3] if k in r_ids]

    def _get_or_create_user(spec):
        u = User.query.filter_by(email=spec["email"]).first()
        if not u:
            u = User(
                email                   = spec["email"],
                first_name              = spec["first"],
                last_name               = spec["last"],
                password_hash           = generate_password_hash(SEED_PASSWORD),
                rider_types             = spec["rider_types"],
                pass_type               = spec["pass_type"],
                skill_level             = spec["skill"],
                home_state              = spec["state"],
                lifecycle_stage         = "active",
                is_seeded               = True,
                is_verified             = True,
                profile_setup_complete  = True,
                equipment_status        = "have_own_equipment",
                visited_resort_ids      = _build_visited(spec.get("visited", [])),
                wish_list_resorts       = _build_wishlist(spec.get("wishlist", [])),
                terrain_preferences     = spec.get("terrain", ["All-Mountain"]),
                created_at              = datetime(2024, 11, 1),
                onboarding_completed_at = datetime(2024, 11, 1),
                first_planning_timestamp= datetime(2024, 11, 10),
                last_active_at          = datetime.utcnow(),
                login_count             = 8,
            )
            db.session.add(u)
            db.session.flush()
            results["users_created"] += 1
        else:
            results["users_skipped"] += 1
        return u

    def _ensure_friend(uid_a, uid_b):
        for (u, f) in [(uid_a, uid_b), (uid_b, uid_a)]:
            if not Friend.query.filter_by(user_id=u, friend_id=f).first():
                db.session.add(Friend(user_id=u, friend_id=f, is_seeded=True))
                results["friends_created"] += 1
            else:
                results["friends_skipped"] += 1

    def _ensure_invitation(sender_id, receiver_id):
        existing = Invitation.query.filter_by(
            sender_id=sender_id, receiver_id=receiver_id, trip_id=None
        ).first()
        if not existing:
            db.session.add(Invitation(
                sender_id   = sender_id,
                receiver_id = receiver_id,
                trip_id     = None,
                invite_type = InviteType.OUTBOUND,
                status      = "pending",
            ))
            db.session.flush()
            results["invitations_created"] += 1
        else:
            results["invitations_skipped"] += 1

    def _add_trip(user_id, resort_key, start, end, status, pass_type="Ikon"):
        resort_id = r_ids[resort_key]
        existing = SkiTrip.query.filter_by(
            user_id=user_id, resort_id=resort_id,
            start_date=start, end_date=end,
        ).first()
        if not existing:
            t = SkiTrip(
                user_id    = user_id,
                resort_id  = resort_id,
                start_date = start,
                end_date   = end,
                trip_status= status,
                pass_type  = pass_type,
                is_public  = True,
            )
            db.session.add(t)
            db.session.flush()
            results["trips_created"] += 1
            return t
        results["trips_skipped"] += 1
        return existing

    def _add_participant(trip, user_id):
        if not SkiTripParticipant.query.filter_by(trip_id=trip.id, user_id=user_id).first():
            db.session.add(SkiTripParticipant(
                trip_id = trip.id,
                user_id = user_id,
                status  = GuestStatus.ACCEPTED,
            ))
            results["participants_created"] += 1
        else:
            results["participants_skipped"] += 1

    def _add_availability(user_id, dates):
        for d in dates:
            if not UserAvailability.query.filter_by(user_id=user_id, date=d).first():
                db.session.add(UserAvailability(
                    user_id      = user_id,
                    date         = d,
                    is_available = True,
                ))
                results["availability_created"] += 1
            else:
                results["availability_skipped"] += 1

    def _add_activity(actor_id, recipient_id, atype, obj_type, obj_id, extra=None):
        existing = Activity.query.filter_by(
            actor_user_id     = actor_id,
            recipient_user_id = recipient_id,
            type              = atype,
            object_id         = obj_id,
        ).first()
        if not existing:
            db.session.add(Activity(
                actor_user_id     = actor_id,
                recipient_user_id = recipient_id,
                type              = atype,
                object_type       = obj_type,
                object_id         = obj_id,
                extra_data        = extra,
            ))
            results["activity_created"] += 1
        else:
            results["activity_skipped"] += 1

    # ── Step 3: Create accepted-friend users ──────────────────────────────────
    accepted_objs = {}
    for spec in ACCEPTED_FRIEND_SPECS:
        u = _get_or_create_user(spec)
        accepted_objs[spec["email"]] = u

    db.session.flush()

    # ── Step 4: Create accepted-friend relationships ───────────────────────────
    for email, u in accepted_objs.items():
        _ensure_friend(john_id, u.id)

    db.session.flush()

    # ── Step 5: Create pending-inbound users and invitations ──────────────────
    inbound_objs = {}
    for spec in PENDING_INBOUND_SPECS:
        u = _get_or_create_user(spec)
        inbound_objs[spec["email"]] = u
        _ensure_invitation(u.id, john_id)   # they request John

    db.session.flush()

    # ── Step 6: Create pending-outbound users and invitations ─────────────────
    outbound_objs = {}
    for spec in PENDING_OUTBOUND_SPECS:
        u = _get_or_create_user(spec)
        outbound_objs[spec["email"]] = u
        _ensure_invitation(john_id, u.id)   # John requests them

    db.session.flush()

    # ── Step 7: Resolve shorthand refs ───────────────────────────────────────
    lucas   = accepted_objs["lucas.bennett.screenshots@gmail.com"]
    emma    = accepted_objs["emma.thornton.screenshots@gmail.com"]
    marcus  = accepted_objs["marcus.webb.screenshots@gmail.com"]
    sofia   = accepted_objs["sofia.reyes.screenshots@gmail.com"]
    derek   = accepted_objs["derek.halvorsen.screenshots@gmail.com"]
    chloe   = accepted_objs["chloe.patterson.screenshots@gmail.com"]
    nathan  = accepted_objs["nathan.okafor.screenshots@gmail.com"]
    rachel  = accepted_objs["rachel.kim.screenshots@gmail.com"]
    tyler   = accepted_objs["tyler.marsh.screenshots@gmail.com"]
    haley   = accepted_objs["haley.donovan.screenshots@gmail.com"]
    connor  = accepted_objs["connor.sullivan.screenshots@gmail.com"]
    priya   = accepted_objs["priya.sharma.screenshots@gmail.com"]
    brendan = accepted_objs["brendan.fitzgerald.screenshots@gmail.com"]
    nadia   = accepted_objs["nadia.laurent.screenshots@gmail.com"]
    jake    = accepted_objs["jake.whitmore.screenshots@gmail.com"]
    lindsey = accepted_objs["lindsey.chen.screenshots@gmail.com"]
    owen    = accepted_objs["owen.callahan.screenshots@gmail.com"]
    brooke  = accepted_objs["brooke.simmons.screenshots@gmail.com"]
    ethan   = accepted_objs["ethan.kowalski.screenshots@gmail.com"]
    ryan    = accepted_objs["ryan.hutchinson.screenshots@gmail.com"]

    # ── Step 8: Create trips ──────────────────────────────────────────────────

    # ── John's existing trips (from original seed) are preserved ──────────────
    # Add group-trip participation to John's existing Whistler & Jackson trips:
    john_whistler = SkiTrip.query.filter_by(
        user_id=john_id, resort_id=r_ids["whistler"]
    ).first()
    john_jackson = SkiTrip.query.filter_by(
        user_id=john_id, resort_id=r_ids["jackson"]
    ).first()
    john_vail = SkiTrip.query.filter_by(
        user_id=john_id, resort_id=r_ids["vail"]
    ).first()
    john_park_city = SkiTrip.query.filter_by(
        user_id=john_id, resort_id=r_ids["park_city"]
    ).first()

    if john_whistler:
        for participant in [lucas, emma, marcus, nadia, connor]:
            _add_participant(john_whistler, participant.id)

    if john_jackson:
        for participant in [sofia, chloe, ryan, tyler]:
            _add_participant(john_jackson, participant.id)

    if john_vail:
        for participant in [chloe, ethan, rachel]:
            _add_participant(john_vail, participant.id)

    if john_park_city:
        for participant in [owen, brooke, sofia]:
            _add_participant(john_park_city, participant.id)

    db.session.flush()

    # ── Friend trips (create social proof on each mountain) ───────────────────
    # Lucas — Breckenridge + Steamboat
    _add_trip(lucas.id, "breck",    date(2027, 1, 5),  date(2027, 1, 8),  "going",    "Ikon")
    _add_trip(lucas.id, "steamboat",date(2027, 3, 1),  date(2027, 3, 4),  "planning", "Ikon")

    # Emma — Deer Valley + Snowbird
    _add_trip(emma.id, "deer_valley", date(2027, 1, 8),  date(2027, 1, 12), "going",   "Ikon")
    _add_trip(emma.id, "snowbird",    date(2027, 2, 18), date(2027, 2, 21), "planning","Ikon")

    # Marcus — Mammoth + Palisades + Whistler (overlaps John's Whistler trip)
    _add_trip(marcus.id, "mammoth",   date(2026, 12, 20), date(2026, 12, 24), "going",  "Epic")
    _add_trip(marcus.id, "palisades", date(2027, 2, 1),   date(2027, 2, 4),  "going",  "Epic")
    _add_trip(marcus.id, "whistler",  date(2026, 12, 27), date(2027, 1, 2),  "going",  "Epic")

    # Sofia — Sun Valley + Park City (overlaps John Feb 6-9)
    _add_trip(sofia.id, "sun_valley", date(2027, 1, 28), date(2027, 2, 1),  "planning","Ikon")
    _add_trip(sofia.id, "park_city",  date(2027, 2, 7),  date(2027, 2, 10), "going",  "Ikon")

    # Derek — Steamboat + Arapahoe Basin
    _add_trip(derek.id, "steamboat",  date(2027, 1, 15), date(2027, 1, 18), "going",  "Indy")
    _add_trip(derek.id, "abasin",     date(2026, 12, 20),date(2026, 12, 23),"going",  "Indy")

    # Chloe — Vail (overlaps John Jan 14-17) + Copper
    _add_trip(chloe.id, "vail",   date(2027, 1, 14), date(2027, 1, 17), "going",  "Epic")
    _add_trip(chloe.id, "copper", date(2027, 2, 22), date(2027, 2, 25), "planning","Epic")

    # Nathan — Snowbird + Alta
    _add_trip(nathan.id, "snowbird", date(2027, 1, 8),  date(2027, 1, 12), "going",   "Ikon")
    _add_trip(nathan.id, "alta",     date(2027, 2, 20), date(2027, 2, 23), "going",   "Ikon")

    # Rachel — Beaver Creek + Mammoth
    _add_trip(rachel.id, "beaver",  date(2027, 1, 20), date(2027, 1, 23), "going",   "Epic")
    _add_trip(rachel.id, "mammoth", date(2027, 3, 7),  date(2027, 3, 10), "planning","Epic")

    # Tyler — Jackson (overlaps John Feb 27-Mar 2)
    _add_trip(tyler.id, "jackson", date(2027, 1, 3),  date(2027, 1, 7),  "going",   "Indy")
    _add_trip(tyler.id, "jackson", date(2027, 2, 28), date(2027, 3, 3),  "going",   "Indy")

    # Haley — Sun Valley + Park City
    _add_trip(haley.id, "sun_valley", date(2027, 1, 20), date(2027, 1, 23), "planning","Ikon")
    _add_trip(haley.id, "park_city",  date(2027, 2, 12), date(2027, 2, 15), "going",  "Ikon")

    # Connor — Breckenridge + Keystone (overlaps Group C)
    _add_trip(connor.id, "breck",    date(2026, 12, 28), date(2026, 12, 31), "going",  "Epic")
    _add_trip(connor.id, "keystone", date(2027, 2, 15),  date(2027, 2, 18), "going",  "Epic")

    # Priya — Mammoth + Whistler
    _add_trip(priya.id, "mammoth",  date(2027, 1, 17), date(2027, 1, 21), "going",    "Ikon")
    _add_trip(priya.id, "whistler", date(2027, 3, 5),  date(2027, 3, 9),  "planning", "Ikon")

    # Brendan — Stowe + Vail
    _add_trip(brendan.id, "stowe", date(2026, 12, 27), date(2026, 12, 30), "going",   "Epic")
    _add_trip(brendan.id, "vail",  date(2027, 2, 3),   date(2027, 2, 6),  "planning","Epic")

    # Nadia — Whistler (overlaps John Dec 26-Jan 2) + Revelstoke
    _add_trip(nadia.id, "whistler",  date(2026, 12, 26), date(2027, 1, 3), "going",   "Ikon")
    _add_trip(nadia.id, "revelstoke",date(2027, 3, 8),   date(2027, 3, 12),"going",   "Ikon")

    # Jake — Breckenridge + Arapahoe Basin
    _add_trip(jake.id, "breck", date(2027, 2, 12), date(2027, 2, 16), "going",    "Indy")
    _add_trip(jake.id, "abasin",date(2027, 3, 15), date(2027, 3, 18), "planning", "Indy")

    # Lindsey — Stevens Pass + Whistler
    _add_trip(lindsey.id, "stevens",  date(2027, 1, 12), date(2027, 1, 15), "going",  "Epic")
    _add_trip(lindsey.id, "whistler", date(2027, 2, 14), date(2027, 2, 18), "going",  "Epic")

    # Owen — Park City (overlaps John Feb 6-9) + Deer Valley
    _add_trip(owen.id, "park_city",  date(2027, 2, 5),  date(2027, 2, 9),  "going",   "Ikon")
    _add_trip(owen.id, "deer_valley",date(2027, 1, 22), date(2027, 1, 25), "going",   "Ikon")

    # Brooke — Mt. Bachelor + Whistler
    _add_trip(brooke.id, "bachelor", date(2027, 2, 10), date(2027, 2, 14), "going",    "Epic")
    _add_trip(brooke.id, "whistler", date(2027, 3, 4),  date(2027, 3, 7),  "planning", "Epic")

    # Ethan — Copper + Breckenridge
    _add_trip(ethan.id, "copper", date(2027, 1, 10), date(2027, 1, 13), "going",   "Ikon")
    _add_trip(ethan.id, "breck",  date(2027, 2, 25), date(2027, 2, 28), "going",   "Ikon")

    # Ryan — Jackson (overlaps John Feb 27-Mar 2) + Telluride
    _add_trip(ryan.id, "jackson",  date(2027, 2, 27), date(2027, 3, 2),  "going",   "Epic")
    _add_trip(ryan.id, "telluride",date(2027, 1, 18), date(2027, 1, 21), "going",   "Epic")

    db.session.flush()

    # ── Step 9: Add availability windows ─────────────────────────────────────

    # Group A — Dec 18-22
    group_a_user_map = {spec["email"]: accepted_objs[spec["email"]]
                        for spec in ACCEPTED_FRIEND_SPECS
                        if spec["email"] in GROUP_A_EMAILS}
    for u in group_a_user_map.values():
        _add_availability(u.id, GROUP_A_DATES)

    # Group B — Jan 15-19
    group_b_user_map = {spec["email"]: accepted_objs[spec["email"]]
                        for spec in ACCEPTED_FRIEND_SPECS
                        if spec["email"] in GROUP_B_EMAILS}
    for u in group_b_user_map.values():
        _add_availability(u.id, GROUP_B_DATES)

    # Group C — Feb 12-16
    group_c_user_map = {spec["email"]: accepted_objs[spec["email"]]
                        for spec in ACCEPTED_FRIEND_SPECS
                        if spec["email"] in GROUP_C_EMAILS}
    for u in group_c_user_map.values():
        _add_availability(u.id, GROUP_C_DATES)

    # Random availability for remaining users
    all_new_users = {**accepted_objs, **inbound_objs, **outbound_objs}
    for email, dates in RANDOM_AVAIL.items():
        u = all_new_users.get(email)
        if u:
            _add_availability(u.id, dates)

    # John's availability additions (creates overlap signals)
    _add_availability(john_id, JOHN_AVAIL_DATES)

    db.session.flush()

    # ── Step 10: Activity notifications for John ──────────────────────────────
    # These appear as the notification feed items on John's Home / notification screens.
    # We use real trip IDs as object_id to make the notifications linkable.

    john_whistler_id = john_whistler.id if john_whistler else 0
    john_vail_id     = john_vail.id if john_vail else 0
    john_jackson_id  = john_jackson.id if john_jackson else 0

    # 1. Lucas accepted connection — connection_accepted
    _add_activity(lucas.id, john_id,   "connection_accepted",          "user",         lucas.id)

    # 2. Nadia created a Whistler trip overlapping John's dates
    nadia_whistler = SkiTrip.query.filter_by(
        user_id=nadia.id, resort_id=r_ids["whistler"]
    ).order_by(SkiTrip.id.desc()).first()
    if nadia_whistler:
        _add_activity(nadia.id,  john_id, "trip_created",              "trip",         nadia_whistler.id)
        _add_activity(nadia.id,  john_id, "friend_trip_overlaps_availability", "trip", nadia_whistler.id)

    # 3. Marcus's Whistler trip overlaps John's Whistler trip availability
    marcus_whistler = SkiTrip.query.filter_by(
        user_id=marcus.id, resort_id=r_ids["whistler"]
    ).first()
    if marcus_whistler:
        _add_activity(marcus.id, john_id, "friend_trip_overlaps_availability","trip",  marcus_whistler.id)

    # 4. Connor created a Breckenridge trip (friend created trip)
    connor_breck = SkiTrip.query.filter_by(
        user_id=connor.id, resort_id=r_ids["breck"]
    ).order_by(SkiTrip.start_date).first()
    if connor_breck:
        _add_activity(connor.id, john_id, "trip_created",              "trip",         connor_breck.id)

    # 5. Ryan joining Jackson (friend joined same resort)
    ryan_jackson = SkiTrip.query.filter_by(
        user_id=ryan.id, resort_id=r_ids["jackson"]
    ).order_by(SkiTrip.start_date).first()
    if ryan_jackson:
        _add_activity(ryan.id, john_id,   "friend_joined_trip",        "trip",         john_jackson_id)

    # 6. Simone (pending inbound) — join_request_received
    simone = inbound_objs.get("simone.leclerc.screenshots@gmail.com")
    if simone and john_whistler_id:
        _add_activity(simone.id, john_id, "join_request_received",     "trip",         john_whistler_id)

    db.session.flush()

    # ── Step 11: Commit ───────────────────────────────────────────────────────
    db.session.commit()

    return results
