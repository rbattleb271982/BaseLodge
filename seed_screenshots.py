"""
seed_screenshots.py — App Store / marketing screenshot seed data.

ADMIN-ONLY. Never expose via a public route.
Call only through /admin/seed-screenshot-data (login_required + admin_required).

Idempotent: safe to call multiple times — existing rows are skipped, never
duplicated. Returns a dict summarising what was created vs skipped.

Primary screenshot account
──────────────────────────
  Email:    baselodge.screenshots@gmail.com
  Password: Ikon
  Name:     John Carter
  Type:     Skier | Ikon pass | Advanced | Colorado

Connected friends (all passwords: Seed1234!)
────────────────────────────────────────────
  Mia Chen      — mia.chen.screenshots@gmail.com       — Ikon / Snowboarder / CA
  Jordan Ellis  — jordan.ellis.screenshots@gmail.com   — Epic / Skier       / CO
  Avery Brooks  — avery.brooks.screenshots@gmail.com   — Ikon / Skier       / UT
  Sam Rivera    — sam.rivera.screenshots@gmail.com     — Epic / Snowboarder / VT
  Taylor Morgan — taylor.morgan.screenshots@gmail.com  — Indy / Skier       / WY

Pending request stubs (all passwords: Seed1234!)
────────────────────────────────────────────────
  Alex Winters — alex.winters.screenshots@gmail.com — inbound  to John
  Casey Park   — casey.park.screenshots@gmail.com   — outbound from John

Trips created (winter 2026-27)
───────────────────────────────
  John   → Whistler Dec 26–Jan 2  (going)    ← overlaps Mia     → Ideas
  John   → Vail     Jan 14–17     (going)    ← overlaps Jordan  → Ideas
  John   → Park City Feb 6–9      (going)    ← overlaps Avery   → Ideas
  John   → Jackson Hole Feb 27–Mar 2 (planning) ← overlaps Sam  → Ideas
  John   → Niseko   Apr 2–8       (planning)    ← international
  Mia    → Whistler Dec 28–Jan 3  (going)    | Mammoth Mar 5–8 (planning)
  Jordan → Vail     Jan 13–17     (going)    | Aspen Mar 13–16 (going) ← John is group participant
  Avery  → Park City Feb 5–9      (going)    | Jackson Jan 20–23 (planning)
  Sam    → Stowe    Dec 26–30     (going)    | Jackson Feb 27–Mar 2 (going)
  Taylor → Jackson  Jan 2–5       (going)    | Telluride Mar 12–15 (planning)
"""

from datetime import date, datetime
from werkzeug.security import generate_password_hash

PRIMARY_EMAIL    = "baselodge.screenshots@gmail.com"
PRIMARY_PASSWORD = "Ikon"

# ── Friend specs ──────────────────────────────────────────────────────────────
FRIEND_SPECS = [
    {
        "first": "Mia",    "last": "Chen",
        "email": "mia.chen.screenshots@gmail.com",
        "pass":  "Ikon",   "types": ["Snowboarder"],
        "state": "CA",     "skill": "Advanced",
    },
    {
        "first": "Jordan", "last": "Ellis",
        "email": "jordan.ellis.screenshots@gmail.com",
        "pass":  "Epic",   "types": ["Skier"],
        "state": "CO",     "skill": "Advanced",
    },
    {
        "first": "Avery",  "last": "Brooks",
        "email": "avery.brooks.screenshots@gmail.com",
        "pass":  "Ikon",   "types": ["Skier"],
        "state": "UT",     "skill": "Intermediate",
    },
    {
        "first": "Sam",    "last": "Rivera",
        "email": "sam.rivera.screenshots@gmail.com",
        "pass":  "Epic",   "types": ["Snowboarder"],
        "state": "VT",     "skill": "Expert",
    },
    {
        "first": "Taylor", "last": "Morgan",
        "email": "taylor.morgan.screenshots@gmail.com",
        "pass":  "Indy",   "types": ["Skier"],
        "state": "WY",     "skill": "Intermediate",
    },
]

PENDING_INBOUND  = {
    "first": "Alex",  "last": "Winters",
    "email": "alex.winters.screenshots@gmail.com",
}
PENDING_OUTBOUND = {
    "first": "Casey", "last": "Park",
    "email": "casey.park.screenshots@gmail.com",
}

# Resort slugs — resolved to IDs at runtime so we never hardcode DB PKs.
RESORT_SLUGS = {
    "whistler":  "whistler-blackcomb-ca",
    "vail":      "vail-us",
    "park_city": "park-city-us",
    "jackson":   "jackson-hole-us",
    "niseko":    "niseko-jp",
    "aspen":     "aspen-mountain-us",
    "stowe":     "stowe-us",
    "telluride": "telluride-us",
    "mammoth":   "mammoth-mountain-us",
}


# ── Public entry point ────────────────────────────────────────────────────────

def seed_screenshot_data(app, db, User, Friend, SkiTrip, Invitation,
                         SkiTripParticipant, Resort, GuestStatus, InviteType):
    """
    Seed App Store screenshot demo data inside an active app context.

    All model classes are passed in to avoid circular-import issues.
    Returns a summary dict of created vs skipped rows.
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
        "resort_ids":           {},
    }

    # ── Step 1: Resolve resort IDs by slug ────────────────────────────────────
    r_ids = {}
    missing = []
    for key, slug in RESORT_SLUGS.items():
        r = Resort.query.filter_by(slug=slug, is_active=True).first()
        if r:
            r_ids[key] = r.id
        else:
            missing.append(f"{key} (slug={slug})")

    if missing:
        raise ValueError(
            f"Could not resolve resort IDs for: {missing}. "
            "Check that these resorts exist and are active."
        )

    results["resort_ids"] = {k: v for k, v in r_ids.items()}

    # ── Step 2: Primary user — John Carter ───────────────────────────────────
    john = User.query.filter_by(email=PRIMARY_EMAIL).first()
    if not john:
        john = User(
            email                  = PRIMARY_EMAIL,
            first_name             = "John",
            last_name              = "Carter",
            password_hash          = generate_password_hash(PRIMARY_PASSWORD),
            rider_types            = ["Skier"],
            pass_type              = "Ikon",
            skill_level            = "Advanced",
            home_state             = "CO",
            lifecycle_stage        = "active",
            is_seeded              = True,
            is_verified            = True,
            profile_setup_complete = True,
            visited_resort_ids     = [
                r_ids["whistler"], r_ids["vail"],
                r_ids["park_city"], r_ids["aspen"], r_ids["jackson"],
            ],
            wish_list_resorts      = [r_ids["niseko"], r_ids["stowe"]],
            equipment_status       = "have_own_equipment",
            terrain_preferences    = ["All-Mountain", "Trees"],
            created_at             = datetime(2024, 10, 15),
            onboarding_completed_at= datetime(2024, 10, 15),
            first_connection_at    = datetime(2024, 10, 16),
            first_trip_created_at  = datetime(2024, 10, 20),
            first_planning_timestamp = datetime(2024, 10, 20),
            last_active_at         = datetime.utcnow(),
            login_count            = 47,
        )
        db.session.add(john)
        db.session.flush()
        results["users_created"] += 1
    else:
        results["users_skipped"] += 1

    john_id = john.id

    # ── Step 3: Friend users ──────────────────────────────────────────────────
    friend_objs = {}  # email → User

    for spec in FRIEND_SPECS:
        u = User.query.filter_by(email=spec["email"]).first()
        if not u:
            u = User(
                email                  = spec["email"],
                first_name             = spec["first"],
                last_name              = spec["last"],
                password_hash          = generate_password_hash("Seed1234!"),
                rider_types            = spec["types"],
                pass_type              = spec["pass"],
                skill_level            = spec["skill"],
                home_state             = spec["state"],
                lifecycle_stage        = "active",
                is_seeded              = True,
                is_verified            = True,
                profile_setup_complete = True,
                equipment_status       = "have_own_equipment",
                created_at             = datetime(2024, 10, 15),
                onboarding_completed_at= datetime(2024, 10, 15),
                first_planning_timestamp = datetime(2024, 10, 20),
                last_active_at         = datetime.utcnow(),
                login_count            = 12,
            )
            db.session.add(u)
            db.session.flush()
            results["users_created"] += 1
        else:
            results["users_skipped"] += 1

        friend_objs[spec["email"]] = u

    # ── Step 4: Pending-request stub users ────────────────────────────────────
    def _get_or_create_stub(spec):
        u = User.query.filter_by(email=spec["email"]).first()
        if not u:
            u = User(
                email                  = spec["email"],
                first_name             = spec["first"],
                last_name              = spec["last"],
                password_hash          = generate_password_hash("Seed1234!"),
                rider_types            = ["Skier"],
                pass_type              = "Ikon",
                skill_level            = "Intermediate",
                lifecycle_stage        = "active",
                is_seeded              = True,
                is_verified            = True,
                profile_setup_complete = True,
                created_at             = datetime(2024, 10, 15),
            )
            db.session.add(u)
            db.session.flush()
            results["users_created"] += 1
        else:
            results["users_skipped"] += 1
        return u

    alex  = _get_or_create_stub(PENDING_INBOUND)
    casey = _get_or_create_stub(PENDING_OUTBOUND)

    # ── Step 5: Bidirectional Friend rows for confirmed friends ───────────────
    def _ensure_friend(uid_a, uid_b):
        for (u, f) in [(uid_a, uid_b), (uid_b, uid_a)]:
            if not Friend.query.filter_by(user_id=u, friend_id=f).first():
                db.session.add(Friend(user_id=u, friend_id=f, is_seeded=True))
                results["friends_created"] += 1
            else:
                results["friends_skipped"] += 1

    for spec in FRIEND_SPECS:
        _ensure_friend(john_id, friend_objs[spec["email"]].id)

    db.session.flush()

    # ── Step 6: Pending friend invitations ───────────────────────────────────
    def _ensure_invitation(sender_id, receiver_id):
        existing = Invitation.query.filter_by(
            sender_id=sender_id, receiver_id=receiver_id, trip_id=None,
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

    _ensure_invitation(alex.id,  john_id)   # inbound:  Alex  → John
    _ensure_invitation(john_id,  casey.id)  # outbound: John  → Casey

    # ── Step 7: SkiTrip rows ──────────────────────────────────────────────────
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

    mia    = friend_objs["mia.chen.screenshots@gmail.com"]
    jordan = friend_objs["jordan.ellis.screenshots@gmail.com"]
    avery  = friend_objs["avery.brooks.screenshots@gmail.com"]
    sam    = friend_objs["sam.rivera.screenshots@gmail.com"]
    taylor = friend_objs["taylor.morgan.screenshots@gmail.com"]

    # John Carter — 5 trips (winter 2026-27)
    _add_trip(john_id, "whistler",  date(2026, 12, 26), date(2027,  1,  2), "going",    "Ikon")
    _add_trip(john_id, "vail",      date(2027,  1, 14), date(2027,  1, 17), "going",    "Ikon")
    _add_trip(john_id, "park_city", date(2027,  2,  6), date(2027,  2,  9), "going",    "Ikon")
    _add_trip(john_id, "jackson",   date(2027,  2, 27), date(2027,  3,  2), "planning", "Ikon")
    _add_trip(john_id, "niseko",    date(2027,  4,  2), date(2027,  4,  8), "planning", "Ikon")

    # Mia Chen — overlaps Whistler with John (Ideas), solo Mammoth
    _add_trip(mia.id, "whistler",  date(2026, 12, 28), date(2027,  1,  3), "going",    "Ikon")
    _add_trip(mia.id, "mammoth",   date(2027,  3,  5), date(2027,  3,  8), "planning", "Ikon")

    # Jordan Ellis — overlaps Vail with John (Ideas), then Aspen
    _add_trip(jordan.id, "vail",   date(2027,  1, 13), date(2027,  1, 17), "going",    "Epic")
    jordan_aspen = _add_trip(jordan.id, "aspen", date(2027, 3, 13), date(2027,  3, 16), "going", "Epic")

    # Avery Brooks — overlaps Park City with John (Ideas), solo Jackson
    _add_trip(avery.id, "park_city", date(2027,  2,  5), date(2027,  2,  9), "going",    "Ikon")
    _add_trip(avery.id, "jackson",   date(2027,  1, 20), date(2027,  1, 23), "planning", "Ikon")

    # Sam Rivera — solo Stowe (Friends' Trips diversity), overlaps Jackson with John
    _add_trip(sam.id, "stowe",   date(2026, 12, 26), date(2026, 12, 30), "going", "Epic")
    _add_trip(sam.id, "jackson", date(2027,  2, 27), date(2027,  3,  2), "going", "Epic")

    # Taylor Morgan — solo Jackson Hole + Telluride planning
    _add_trip(taylor.id, "jackson",   date(2027,  1,  2), date(2027,  1,  5), "going",    "Indy")
    _add_trip(taylor.id, "telluride", date(2027,  3, 12), date(2027,  3, 15), "planning", "Indy")

    # ── Step 8: Group trip — John accepted on Jordan's Aspen trip ────────────
    if jordan_aspen:
        existing_p = SkiTripParticipant.query.filter_by(
            trip_id=jordan_aspen.id, user_id=john_id,
        ).first()
        if not existing_p:
            db.session.add(SkiTripParticipant(
                trip_id  = jordan_aspen.id,
                user_id  = john_id,
                status   = GuestStatus.ACCEPTED,
            ))
            results["participants_created"] += 1
        else:
            results["participants_skipped"] += 1

    # ── Step 9: Commit everything ─────────────────────────────────────────────
    db.session.commit()

    return results
