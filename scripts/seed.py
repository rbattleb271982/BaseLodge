#!/usr/bin/env python3
"""
scripts/seed.py — BaseLodge deterministic reset-and-reseed script

Wipes all seeded/demo data (is_seeded=True) and recreates a rich pseudo-live
demo environment covering all key product states.

Usage:
    python scripts/seed.py

Safety: only deletes records tied to seeded users. Real user data is untouched.
"""

import sys
import os
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import (
    User, SkiTrip, SkiTripParticipant, Friend, Invitation, InviteType,
    InviteToken, EquipmentSetup, EquipmentSlot, EquipmentDiscipline,
    UserAvailability, Activity, ActivityType, DismissedNudge,
    ParticipantRole, GuestStatus, ParticipantTransportation,
    ParticipantEquipment, LessonChoice, Resort,
)
from werkzeug.security import generate_password_hash


# ─────────────────────────────────────────────────────────────────────────────
# RESORT SLUGS REQUIRED
# ─────────────────────────────────────────────────────────────────────────────

REQUIRED_RESORT_SLUGS = [
    'vail-us',
    'breckenridge-us',
    'park-city-us',
    'mammoth-mountain-us',
    'jackson-hole-us',
    'telluride-us',
    'stowe-us',
    'copper-mountain-us',
    'palisades-tahoe-us',
    'killington-pico-us',
    'arapahoe-basin-us',
    'whistler-blackcomb-ca',
]


def resolve_resorts():
    resorts = {}
    missing = []
    for slug in REQUIRED_RESORT_SLUGS:
        r = Resort.query.filter_by(slug=slug).first()
        if r:
            resorts[slug] = r
        else:
            missing.append(slug)
    if missing:
        print("\n❌  MISSING RESORTS — seed aborted. Add these resorts first:\n")
        for slug in missing:
            print(f"   • {slug}")
        sys.exit(1)
    return resorts


# ─────────────────────────────────────────────────────────────────────────────
# TEARDOWN
# ─────────────────────────────────────────────────────────────────────────────

def teardown():
    print("🗑   Tearing down prior seed data...")

    # test5@gmail.com may exist as a real (non-seeded) account; include it in teardown
    seeded_users = User.query.filter_by(is_seeded=True).all()
    test5_user = User.query.filter_by(email='test5@gmail.com').first()
    if test5_user and test5_user not in seeded_users:
        seeded_users = list(seeded_users) + [test5_user]

    if not seeded_users:
        print("    No seeded users found — nothing to remove.")
        return

    seeded_ids = [u.id for u in seeded_users]

    seeded_trip_ids = [
        t.id for t in SkiTrip.query.filter(SkiTrip.user_id.in_(seeded_ids)).all()
    ]

    Activity.query.filter(
        (Activity.actor_user_id.in_(seeded_ids)) |
        (Activity.recipient_user_id.in_(seeded_ids))
    ).delete(synchronize_session=False)

    if seeded_trip_ids:
        SkiTripParticipant.query.filter(
            SkiTripParticipant.trip_id.in_(seeded_trip_ids)
        ).delete(synchronize_session=False)

    SkiTripParticipant.query.filter(
        SkiTripParticipant.user_id.in_(seeded_ids)
    ).delete(synchronize_session=False)

    Invitation.query.filter(
        (Invitation.sender_id.in_(seeded_ids)) |
        (Invitation.receiver_id.in_(seeded_ids))
    ).delete(synchronize_session=False)

    InviteToken.query.filter(
        InviteToken.inviter_id.in_(seeded_ids)
    ).delete(synchronize_session=False)

    DismissedNudge.query.filter(
        DismissedNudge.user_id.in_(seeded_ids)
    ).delete(synchronize_session=False)

    EquipmentSetup.query.filter(
        EquipmentSetup.user_id.in_(seeded_ids)
    ).delete(synchronize_session=False)

    UserAvailability.query.filter(
        UserAvailability.user_id.in_(seeded_ids)
    ).delete(synchronize_session=False)

    if seeded_trip_ids:
        SkiTrip.query.filter(SkiTrip.id.in_(seeded_trip_ids)).delete(
            synchronize_session=False
        )

    Friend.query.filter(
        (Friend.user_id.in_(seeded_ids)) |
        (Friend.friend_id.in_(seeded_ids))
    ).delete(synchronize_session=False)

    User.query.filter(User.id.in_(seeded_ids)).delete(synchronize_session=False)

    db.session.commit()
    print(f"    Removed {len(seeded_users)} seeded user(s) and all related records.")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

TODAY = date.today()
NOW   = datetime.utcnow()


def d(delta_days):
    return TODAY + timedelta(days=delta_days)


def make_user(**kwargs):
    defaults = dict(
        is_seeded=True,
        lifecycle_stage='active',
        profile_completed_at=NOW,
        onboarding_completed_at=NOW,
        created_at=NOW - timedelta(days=90),
        last_active_at=NOW,
        email_opt_in=True,
        email_transactional=True,
        email_social=False,
        email_digest=False,
        equipment_status='have_own_equipment',
        backcountry_capable=False,
        avi_certified=False,
        visited_resort_ids=[],
        wish_list_resorts=[],
        terrain_preferences=[],
        rider_types=[],
        open_dates=[],
    )
    defaults.update(kwargs)
    raw_password = defaults.pop('password', 'seed_pass_1!')
    defaults['password_hash'] = generate_password_hash(raw_password)
    u = User(**defaults)
    db.session.add(u)
    return u


def make_trip(owner, resort, start_delta, end_delta, **kwargs):
    defaults = dict(
        user_id=owner.id,
        resort_id=resort.id,
        mountain=resort.name,
        state=resort.state_code or '',
        start_date=d(start_delta),
        end_date=d(end_delta),
        is_public=True,
        is_group_trip=False,
        trip_status='planning',
        pass_type='No Pass',
        accommodation_status='none_yet',
    )
    defaults.update(kwargs)
    trip = SkiTrip(**defaults)
    db.session.add(trip)
    db.session.flush()

    owner_part = SkiTripParticipant(
        trip_id=trip.id,
        user_id=owner.id,
        role=ParticipantRole.OWNER,
        status=GuestStatus.ACCEPTED,
        transportation_status=ParticipantTransportation.TBD,
        equipment_status=ParticipantEquipment.OWN,
        taking_lesson=LessonChoice.NO,
    )
    db.session.add(owner_part)
    return trip


def add_participant(trip, user, status=GuestStatus.ACCEPTED, **kwargs):
    defaults = dict(
        trip_id=trip.id,
        user_id=user.id,
        role=ParticipantRole.GUEST,
        status=status,
        transportation_status=ParticipantTransportation.TBD,
        equipment_status=ParticipantEquipment.OWN,
        taking_lesson=LessonChoice.NO,
    )
    defaults.update(kwargs)
    p = SkiTripParticipant(**defaults)
    db.session.add(p)
    if status == GuestStatus.ACCEPTED:
        trip.is_group_trip = True
    return p


def make_friends(a, b):
    f1 = Friend(user_id=a.id, friend_id=b.id, created_at=NOW, is_seeded=True)
    f2 = Friend(user_id=b.id, friend_id=a.id, created_at=NOW, is_seeded=True)
    db.session.add_all([f1, f2])


def make_invitation(sender, receiver, status='pending', trip=None):
    inv = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        invite_type=InviteType.OUTBOUND,
        status=status,
        trip_id=trip.id if trip else None,
        created_at=NOW,
    )
    db.session.add(inv)
    return inv


def make_equipment(user, slot, discipline, brand=None, model=None,
                   boot_brand=None, boot_model=None, boot_flex=None,
                   is_active=True):
    eq = EquipmentSetup(
        user_id=user.id,
        slot=slot,
        discipline=discipline,
        brand=brand,
        model=model,
        boot_brand=boot_brand,
        boot_model=boot_model,
        boot_flex=boot_flex,
        is_active=is_active,
    )
    db.session.add(eq)
    return eq


def set_open_dates(user, date_deltas):
    """Populate both legacy open_dates JSON and the UserAvailability table."""
    dates = [d(delta).isoformat() for delta in date_deltas]
    user.open_dates = dates
    for delta in date_deltas:
        ua = UserAvailability(
            user_id=user.id,
            date=d(delta),
            is_available=True,
        )
        db.session.add(ua)


def add_activity(actor, recipient, atype, object_type, object_id):
    if actor.id == recipient.id:
        return
    act = Activity(
        actor_user_id=actor.id,
        recipient_user_id=recipient.id,
        type=atype.value,
        object_type=object_type,
        object_id=object_id,
        created_at=NOW,
    )
    db.session.add(act)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SEED
# ─────────────────────────────────────────────────────────────────────────────

def seed():
    R = resolve_resorts()
    vail       = R['vail-us']
    breck      = R['breckenridge-us']
    park_city  = R['park-city-us']
    mammoth    = R['mammoth-mountain-us']
    jackson    = R['jackson-hole-us']
    telluride  = R['telluride-us']
    stowe      = R['stowe-us']
    copper     = R['copper-mountain-us']
    palisades  = R['palisades-tahoe-us']
    killington = R['killington-pico-us']
    abasin     = R['arapahoe-basin-us']
    whistler   = R['whistler-blackcomb-ca']

    print("✅  All required resorts found.\n")

    # ── High-density weekend anchor dates ────────────────────────────────────
    # Land on a long weekend ~3 weeks out
    breck_start = 21
    breck_end   = 24

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY TEST ACCOUNT — Alex Chen
    # ─────────────────────────────────────────────────────────────────────────
    print("🌱  Creating users...")

    alex = make_user(
        first_name='Alex', last_name='Chen',
        email='demo@baselodge.app',
        password='demo1234',
        rider_types=['Skier', 'Snowboarder'],
        skill_level='Advanced',
        pass_type='Epic,Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CO',
        backcountry_capable=True,
        avi_certified=True,
        home_resort_id=breck.id,
        visited_resort_ids=[vail.id, breck.id, park_city.id, mammoth.id, jackson.id],
        wish_list_resorts=[whistler.id, telluride.id, jackson.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=180),
    )
    db.session.flush()

    make_equipment(alex, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Atomic', model='Bent Chetler 100',
                   boot_brand='Salomon', boot_model="S/Pro Alpha 120", boot_flex=120)
    make_equipment(alex, EquipmentSlot.SECONDARY, EquipmentDiscipline.SNOWBOARDER,
                   brand='Burton', model='Custom 157',
                   boot_brand='Burton', boot_model='Photon Boa', is_active=False)

    # Availability: near-term window + Jackson Hole window + Telluride/Jun16 window + Jan 2027 Cluster B
    set_open_dates(alex, list(range(13, 18)) + list(range(44, 51)) + list(range(61, 68)) + list(range(281, 285)))

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT A — CORE SOCIAL GRAPH
    # ─────────────────────────────────────────────────────────────────────────

    # A1 — Jordan Walsh (Power User: Expert Skier, 6 upcoming + 1 past)
    jordan = make_user(
        first_name='Jordan', last_name='Walsh',
        email='jordan@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Expert',
        pass_type='Epic',
        terrain_preferences=['Steeps', 'Park'],
        home_state='VT',
        home_resort_id=stowe.id,
        visited_resort_ids=[stowe.id, killington.id, vail.id, breck.id, whistler.id, mammoth.id],
        wish_list_resorts=[jackson.id, telluride.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=365),
    )
    db.session.flush()
    make_equipment(jordan, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='K2', model='Mindbender 108Ti',
                   boot_brand='Tecnica', boot_model='Mach1 LV 120', boot_flex=120)
    set_open_dates(jordan, list(range(44, 51)) + list(range(13, 18)) + list(range(55, 59)))

    # A2 — Maya Torres (Boarder: Snowboarder, Ikon, Tahoe-based)
    maya = make_user(
        first_name='Maya', last_name='Torres',
        email='maya@seed.baselodge.app',
        rider_types=['Snowboarder'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CA',
        home_resort_id=palisades.id,
        visited_resort_ids=[palisades.id, mammoth.id],
        wish_list_resorts=[whistler.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=75),
    )
    db.session.flush()
    make_equipment(maya, EquipmentSlot.PRIMARY, EquipmentDiscipline.SNOWBOARDER,
                   brand='Burton', model='Custom 154',
                   boot_brand='32', boot_model='TM-Two', boot_flex=55)
    set_open_dates(maya, list(range(breck_start, breck_end + 1)) + list(range(42, 47)))

    # A3 — Sam Park (Mixed Rider: past trips only)
    sam = make_user(
        first_name='Sam', last_name='Park',
        email='sam@seed.baselodge.app',
        rider_types=['Skier', 'Snowboarder'],
        skill_level='Intermediate',
        pass_type='Epic,Ikon',
        terrain_preferences=['Trees', 'Groomers'],
        home_state='WA',
        home_resort_id=vail.id,
        visited_resort_ids=[vail.id, whistler.id, park_city.id],
        wish_list_resorts=[jackson.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=200),
    )
    db.session.flush()
    make_equipment(sam, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Rossignol', model='Experience 86Ti',
                   boot_brand='Nordica', boot_model='Dobermann Pro 130', boot_flex=130)

    # A4 — Chris Adler (Social / Empty-state contrast: no trips, no equipment,
    #                   terrain_preferences intentionally empty for QA)
    chris = make_user(
        first_name='Chris', last_name='Adler',
        email='chris@seed.baselodge.app',
        rider_types=['Social'],
        skill_level=None,
        pass_type='No Pass',
        terrain_preferences=[],
        home_state='NY',
        visited_resort_ids=[],
        wish_list_resorts=[],
        equipment_status='needs_rentals',
        profile_completed_at=None,
        created_at=NOW - timedelta(days=14),
    )
    db.session.flush()

    # A5 — Emma Russo (Beginner Planner: boots only, near-miss Breck scenario)
    emma = make_user(
        first_name='Emma', last_name='Russo',
        email='emma@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Beginner',
        pass_type='Indy',
        terrain_preferences=['Groomers'],
        home_state='CO',
        home_resort_id=breck.id,
        visited_resort_ids=[breck.id],
        wish_list_resorts=[vail.id, copper.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=45),
    )
    db.session.flush()
    make_equipment(emma, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand=None, model=None,
                   boot_brand='Dalbello', boot_model='DS Asolo 120', boot_flex=100)
    set_open_dates(emma, list(range(breck_end + 2, breck_end + 7)))

    # A6 — Tyler Grant (The Regular: Advanced Skier, Ikon, CO-based)
    tyler = make_user(
        first_name='Tyler', last_name='Grant',
        email='tyler@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Groomers', 'Trees'],
        home_state='CO',
        home_resort_id=copper.id,
        visited_resort_ids=[copper.id, breck.id, abasin.id],
        wish_list_resorts=[jackson.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=110),
    )
    db.session.flush()
    make_equipment(tyler, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Salomon', model='QST 99',
                   boot_brand='Lange', boot_model='XT3 Tour Pro 130', boot_flex=130)
    set_open_dates(tyler, list(range(breck_start - 1, breck_end + 2)) + list(range(35, 39)) + list(range(281, 285)))

    print("    ✓ Primary account + Cohort A (6 users) created")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT C — IDEAS ENGINE OVERLAP CLUSTERS
    # ─────────────────────────────────────────────────────────────────────────
    # Purpose-built users to generate strong Ideas tab signals:
    #
    #   Cluster A (Jun 16–19 / Telluride / Ikon): Alex + Nina + Marco
    #   Cluster B (Jan 22–25, 2027 / Jackson Hole / Ikon): Alex + Tyler + Casey
    #   Soft pull (Whistler wishlist, no shared dates): Alex + Maya + Nina + Casey

    # C1 — Nina Patel (Cluster A anchor: Jun 16–19, Telluride, Ikon)
    nina = make_user(
        first_name='Nina', last_name='Patel',
        email='nina@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Trees', 'Groomers'],
        home_state='CO',
        home_resort_id=telluride.id,
        visited_resort_ids=[telluride.id, mammoth.id],
        wish_list_resorts=[telluride.id, whistler.id, mammoth.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=55),
    )
    db.session.flush()
    make_equipment(nina, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Head', model='Kore 99',
                   boot_brand='Atomic', boot_model='Hawx Ultra 110', boot_flex=110)
    # Cluster A window: Jun 16–19 (T+61 to T+64) + some near-term days
    set_open_dates(nina, list(range(61, 65)) + list(range(30, 35)))

    # C2 — Marco Rivera (Cluster A anchor: Jun 16–19, Telluride, Ikon)
    marco = make_user(
        first_name='Marco', last_name='Rivera',
        email='marco@seed.baselodge.app',
        rider_types=['Skier', 'Snowboarder'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='NM',
        home_resort_id=telluride.id,
        visited_resort_ids=[telluride.id, vail.id, abasin.id],
        wish_list_resorts=[telluride.id, mammoth.id, abasin.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=40),
    )
    db.session.flush()
    make_equipment(marco, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Nordica', model='Enforcer 100',
                   boot_brand='Fischer', boot_model='Ranger One 110', boot_flex=110)
    # Cluster A window: Jun 16–19 (T+61 to T+64) + some near-term days
    set_open_dates(marco, list(range(61, 65)) + list(range(25, 30)))

    # C3 — Casey Kim (Cluster B anchor: Jan 22–25, 2027, Jackson Hole, Ikon)
    casey = make_user(
        first_name='Casey', last_name='Kim',
        email='casey@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Intermediate',
        pass_type='Ikon',
        terrain_preferences=['Groomers', 'Trees'],
        home_state='WA',
        home_resort_id=jackson.id,
        visited_resort_ids=[jackson.id, park_city.id],
        wish_list_resorts=[jackson.id, whistler.id, mammoth.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=25),
    )
    db.session.flush()
    make_equipment(casey, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Blizzard', model='Rustler 10',
                   boot_brand='Dalbello', boot_model='Panterra 100', boot_flex=100)
    # Cluster B window: Jan 22–25, 2027 (T+281 to T+284) + some near-term days
    set_open_dates(casey, list(range(281, 285)) + list(range(50, 55)))

    print("    ✓ Cohort C (3 cluster users) created: Nina Patel, Marco Rivera, Casey Kim")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT B — CONNECTION STATE USERS
    # ─────────────────────────────────────────────────────────────────────────

    # B1 — Priya Mehta (Incoming friend request → Alex, pending)
    priya = make_user(
        first_name='Priya', last_name='Mehta',
        email='priya@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Intermediate',
        pass_type='Epic',
        terrain_preferences=['Groomers', 'Steeps'],
        home_state='MA',
        home_resort_id=stowe.id,
        visited_resort_ids=[stowe.id],
        wish_list_resorts=[breck.id],
        equipment_status='needs_rentals',
        created_at=NOW - timedelta(days=30),
    )
    db.session.flush()

    # B2 — Jake Simmons (Outgoing friend request from Alex, pending)
    jake = make_user(
        first_name='Jake', last_name='Simmons',
        email='jake@seed.baselodge.app',
        rider_types=['Snowboarder'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Trees', 'Park'],
        home_state='UT',
        visited_resort_ids=[abasin.id],
        wish_list_resorts=[mammoth.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=20),
    )
    db.session.flush()
    make_equipment(jake, EquipmentSlot.PRIMARY, EquipmentDiscipline.SNOWBOARDER,
                   brand='Lib Tech', model='T.Rice Pro 155',
                   boot_brand='32', boot_model='Lashed', boot_flex=54)

    # B3 — Rachel Stone (No connection to Alex)
    rachel = make_user(
        first_name='Rachel', last_name='Stone',
        email='rachel@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Mountain Collective',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CO',
        visited_resort_ids=[telluride.id, abasin.id],
        wish_list_resorts=[vail.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=60),
    )
    db.session.flush()
    make_equipment(rachel, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Faction', model='Agent 2.0',
                   boot_brand='La Sportiva', boot_model='Vega')

    # T — Taylor Reed (test5@gmail.com: personal demo / full social graph user)
    test5 = make_user(
        first_name='Taylor', last_name='Reed',
        email='test5@gmail.com',
        password='12345678',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Epic,Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CO',
        home_resort_id=vail.id,
        visited_resort_ids=[vail.id, breck.id, jackson.id, stowe.id],
        wish_list_resorts=[mammoth.id, whistler.id, telluride.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=120),
    )
    db.session.flush()
    make_equipment(test5, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Völkl', model='Mantra M6 102',
                   boot_brand='Tecnica', boot_model='Mach1 LV 120', boot_flex=120)
    # Open dates: Vail/Copper window and Jackson overlap window.
    # Intentionally excludes Jun 16–22 (T+61–67): test5 has a Stowe trip that week,
    # and keeping that window clear ensures the Cluster A (Nina+Marco Jun 16–19) card
    # surfaces cleanly on the demo@baselodge.app Ideas tab.
    set_open_dates(test5, list(range(35, 40)) + list(range(44, 52)))

    print("    ✓ Cohort B (3 connection state users) created")
    print("    ✓ Taylor Reed <test5@gmail.com> created (personal demo, full social graph)")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT D — JOIN A TRIP SCORING DIVERSITY + FRIENDS > UPCOMING VOLUME
    # ─────────────────────────────────────────────────────────────────────────
    # Each user is deliberately designed to produce a specific curated score
    # for Alex (demo@baselodge.app) in the "Join a Trip" tab.
    #
    #  Preet → Telluride T+62–66   wishlist(3)+overlap(2)+pass(1) = 6
    #  Lena  → Whistler  T+14–18   wishlist(3)+overlap(2)+no_pass = 5
    #  Dev   → Vail      T+15–19   no_wishlist + overlap(2)+pass(1) = 3
    #  Sofia → Mammoth   T+77–81   no_wishlist + no_overlap + no_pass = 0
    #  Zara  → Mammoth   T+77–81   no_wishlist + no_overlap + Ikon(1) = 1
    #  Owen  → Park City T+100–4   no_wishlist + no_overlap + Epic(1) = 1
    #
    # Sofia + Zara + Jordan all at Mammoth T+77–81 → multi-friend scenario.
    # Dev, Sofia, Zara, Owen, Lena, Preet also carry next-season trips
    # (Dec 2026 – Mar 2027) to fill out Friends > Upcoming across more months.

    # D1 — Preet Singh (score=6 trip: Telluride, Ikon, overlaps Alex's Jun window)
    preet = make_user(
        first_name='Preet', last_name='Singh',
        email='preet@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CO',
        home_resort_id=telluride.id,
        visited_resort_ids=[telluride.id, abasin.id],
        wish_list_resorts=[telluride.id, mammoth.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=30),
    )
    db.session.flush()
    make_equipment(preet, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Dynastar', model='Speed 4x4 96',
                   boot_brand='Dalbello', boot_model='Panterra 130', boot_flex=130)
    set_open_dates(preet, list(range(60, 68)))

    # D2 — Lena Kowalski (score=5 trip: Whistler, Mountain Collective, overlaps Alex's early window)
    lena = make_user(
        first_name='Lena', last_name='Kowalski',
        email='lena@seed.baselodge.app',
        rider_types=['Snowboarder'],
        skill_level='Advanced',
        pass_type='Mountain Collective',
        terrain_preferences=['Steeps', 'Trees', 'Park'],
        home_state='WA',
        home_resort_id=whistler.id,
        visited_resort_ids=[whistler.id, palisades.id],
        wish_list_resorts=[whistler.id, jackson.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=60),
    )
    db.session.flush()
    make_equipment(lena, EquipmentSlot.PRIMARY, EquipmentDiscipline.SNOWBOARDER,
                   brand='Never Summer', model='Harpoon 154',
                   boot_brand='ThirtyTwo', boot_model='Lashed BC', boot_flex=57)
    set_open_dates(lena, list(range(13, 20)) + list(range(258, 267)))

    # D3 — Dev Sharma (score=3 trip: Vail, Epic, overlaps Alex's early window but not wishlist)
    dev = make_user(
        first_name='Dev', last_name='Sharma',
        email='dev@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Intermediate',
        pass_type='Epic',
        terrain_preferences=['Groomers', 'Trees'],
        home_state='CO',
        home_resort_id=vail.id,
        visited_resort_ids=[vail.id, breck.id, copper.id],
        wish_list_resorts=[vail.id, stowe.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=80),
    )
    db.session.flush()
    make_equipment(dev, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Atomic', model='Redster X9S',
                   boot_brand='Atomic', boot_model='Hawx Prime 110', boot_flex=110)
    set_open_dates(dev, list(range(14, 20)) + list(range(240, 248)))

    # D4 — Sofia Reyes (score=0: no pass, no overlap, non-wishlist; Mammoth multi-friend)
    sofia = make_user(
        first_name='Sofia', last_name='Reyes',
        email='sofia@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Beginner',
        pass_type='No Pass',
        terrain_preferences=['Groomers'],
        home_state='CA',
        home_resort_id=mammoth.id,
        visited_resort_ids=[mammoth.id],
        wish_list_resorts=[palisades.id],
        equipment_status='needs_rentals',
        created_at=NOW - timedelta(days=10),
    )
    db.session.flush()

    # D5 — Zara Ahmed (score=1: Ikon pass match only; also at Mammoth multi-friend)
    zara = make_user(
        first_name='Zara', last_name='Ahmed',
        email='zara@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Ikon',
        terrain_preferences=['Steeps', 'Trees'],
        home_state='CA',
        home_resort_id=mammoth.id,
        visited_resort_ids=[mammoth.id, palisades.id, jackson.id],
        wish_list_resorts=[mammoth.id, jackson.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=50),
    )
    db.session.flush()
    make_equipment(zara, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Volkl', model='Kenja 88',
                   boot_brand='Salomon', boot_model='X Pro 100', boot_flex=100)
    set_open_dates(zara, list(range(75, 83)) + list(range(282, 290)))

    # D6 — Owen Park (score=1: Epic pass match, non-wishlist, non-overlap;
    #                 carries multiple next-season trips for Friends > Upcoming volume)
    owen = make_user(
        first_name='Owen', last_name='Park',
        email='owen@seed.baselodge.app',
        rider_types=['Skier'],
        skill_level='Advanced',
        pass_type='Epic',
        terrain_preferences=['Trees', 'Steeps'],
        home_state='UT',
        home_resort_id=park_city.id,
        visited_resort_ids=[park_city.id, vail.id, breck.id, stowe.id],
        wish_list_resorts=[jackson.id, mammoth.id],
        equipment_status='have_own_equipment',
        created_at=NOW - timedelta(days=95),
    )
    db.session.flush()
    make_equipment(owen, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='K2', model='Reckoner 102',
                   boot_brand='Technica', boot_model='Mach Sport HV 80', boot_flex=80)
    set_open_dates(owen, list(range(100, 106)) + list(range(244, 252)) + list(range(302, 310)))

    print("    ✓ Cohort D (6 users) created: Preet, Lena, Dev, Sofia, Zara, Owen")

    # ─────────────────────────────────────────────────────────────────────────
    # FRIENDSHIPS
    # ─────────────────────────────────────────────────────────────────────────
    print("🤝  Creating friendships...")

    make_friends(alex, jordan)
    make_friends(alex, maya)
    make_friends(alex, sam)
    make_friends(alex, chris)
    make_friends(alex, emma)
    make_friends(alex, tyler)
    make_friends(jordan, maya)
    make_friends(jordan, tyler)

    # Cohort C — Cluster users connected to Alex
    make_friends(alex, nina)
    make_friends(alex, marco)
    make_friends(alex, casey)

    # Cohort D — Scoring diversity + volume users
    make_friends(alex, preet)
    make_friends(alex, lena)
    make_friends(alex, dev)
    make_friends(alex, sofia)
    make_friends(alex, zara)
    make_friends(alex, owen)

    # test5 also connected to Cohort D
    make_friends(test5, preet)
    make_friends(test5, lena)
    make_friends(test5, dev)
    make_friends(test5, sofia)
    make_friends(test5, zara)
    make_friends(test5, owen)

    # B1: Priya → Alex (incoming to Alex, pending)
    make_invitation(priya, alex, status='pending')

    # B2: Alex → Jake (outgoing from Alex, pending)
    make_invitation(alex, jake, status='pending')

    # test5 — confirmed friends with all core seed users
    make_friends(test5, alex)
    make_friends(test5, jordan)
    make_friends(test5, maya)
    make_friends(test5, sam)
    make_friends(test5, chris)
    make_friends(test5, emma)
    make_friends(test5, tyler)

    # test5 also connected to Cohort C cluster users
    make_friends(test5, nina)
    make_friends(test5, marco)
    make_friends(test5, casey)

    # test5 incoming: Priya → test5 (pending, separate record from Priya → Alex)
    make_invitation(priya, test5, status='pending')

    # test5 outgoing: test5 → Rachel (pending; Rachel has no confirmed connection)
    make_invitation(test5, rachel, status='pending')

    print("    ✓ 33 bidirectional friendships, 4 pending invitations")

    # ─────────────────────────────────────────────────────────────────────────
    # TRIPS
    # ─────────────────────────────────────────────────────────────────────────
    print("🏔   Creating trips...")
    trip_count = 0

    # ── SCENARIO 1: HIGH-DENSITY WEEKEND — Breckenridge ──────────────────────
    # Alex owns; Jordan + Tyler accepted; Maya pending; Chris declined
    trip_breck = make_trip(alex, breck, breck_start, breck_end,
                           trip_status='going',
                           pass_type='Epic',
                           accommodation_status='hotel',
                           is_group_trip=True,
                           is_public=True)
    trip_count += 1

    # ── Alex upcoming: Jackson Hole (true overlap with Jordan) ────────────────
    trip_jackson_alex = make_trip(alex, jackson, 45, 49,
                                  trip_status='planning',
                                  pass_type='Ikon',
                                  is_public=True)
    trip_count += 1

    # ── Alex upcoming: Telluride ──────────────────────────────────────────────
    trip_telluride_alex = make_trip(alex, telluride, 63, 67,
                                    trip_status='planning',
                                    pass_type='Mountain Collective',
                                    is_public=True)
    trip_count += 1

    # ── Alex past: Park City ──────────────────────────────────────────────────
    trip_park_city_past = make_trip(alex, park_city, -35, -32,
                                    trip_status='going',
                                    pass_type='Epic',
                                    is_public=True)
    trip_count += 1

    # ── Jordan's trips (power user: 6 upcoming + 1 past) ─────────────────────
    trip_stowe = make_trip(jordan, stowe, 14, 17,
                           trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_vail_jordan = make_trip(jordan, vail, 35, 38,
                                 trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    # True overlap: Jordan and Alex both at Jackson Hole T+45→T+49
    trip_jackson_jordan = make_trip(jordan, jackson, 45, 49,
                                    trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_killington_jordan = make_trip(jordan, killington, 55, 58,
                                       trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_mammoth_jordan = make_trip(jordan, mammoth, 77, 81,
                                    trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_copper_jordan = make_trip(jordan, copper, 91, 95,
                                   trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_whistler_jordan_past = make_trip(jordan, whistler, -50, -45,
                                          trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    # ── Maya's upcoming: Palisades Tahoe ─────────────────────────────────────
    trip_palisades_maya = make_trip(maya, palisades, 42, 46,
                                    trip_status='going', pass_type='Ikon', is_public=True)
    trip_count += 1

    # ── Sam's past trips (no upcoming) ───────────────────────────────────────
    trip_vail_sam_past = make_trip(sam, vail, -90, -86,
                                   trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_whistler_sam_past = make_trip(sam, whistler, -60, -55,
                                       trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    # ── SCENARIO 2: NEAR-MISS — Emma arrives at Breck 2 days after group leaves
    trip_breck_emma = make_trip(emma, breck, breck_end + 2, breck_end + 5,
                                trip_status='planning', pass_type='Indy', is_public=True)
    trip_count += 1

    # ── Tyler's upcoming: Copper Mountain ────────────────────────────────────
    trip_copper_tyler = make_trip(tyler, copper, 35, 38,
                                  trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # ── test5 (Taylor Reed) trips ─────────────────────────────────────────────
    # Scenario A — Near overlap: arrives at Breck T+22, 1 day into the main group window
    trip_breck_test5 = make_trip(test5, breck, 22, 25,
                                 trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    # Scenario B — Exact overlap: Jackson Hole T+45→T+49, same as Alex AND Jordan
    trip_jackson_test5 = make_trip(test5, jackson, 45, 49,
                                   trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # Scenario C — Different resort, same dates: Telluride T+35→T+38
    #              while Jordan is at Vail and Tyler is at Copper — same window
    trip_telluride_test5 = make_trip(test5, telluride, 35, 38,
                                     trip_status='planning', pass_type='Mountain Collective', is_public=True)
    trip_count += 1

    # Upcoming density trip — Stowe
    trip_stowe_test5 = make_trip(test5, stowe, 61, 64,
                                 trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    # Far-future trip — Mammoth (Ideas tab cross-resort inspiration)
    trip_mammoth_test5 = make_trip(test5, mammoth, 85, 89,
                                   trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # ── COHORT D: current-season scoring trips ────────────────────────────────
    #
    # These are the trips that produce intentional curated scores for Alex on
    # the "Join a Trip" tab. Trip at each score tier is seeded exactly once
    # (except the Mammoth cluster which needs three to show multi-friend).

    # Preet: Telluride T+62–66 → score=6 for Alex (wishlist+overlap+pass)
    trip_telluride_preet = make_trip(preet, telluride, 62, 66,
                                     trip_status='planning', pass_type='Ikon',
                                     is_public=True)
    trip_count += 1

    # Lena: Whistler T+14–18 → score=5 for Alex (wishlist+overlap, no pass match)
    trip_whistler_lena = make_trip(lena, whistler, 14, 18,
                                   trip_status='planning', pass_type='Mountain Collective',
                                   is_public=True)
    trip_count += 1

    # Dev: Vail T+15–19 → score=3 for Alex (overlap+pass, not on wishlist)
    trip_vail_dev = make_trip(dev, vail, 15, 19,
                              trip_status='planning', pass_type='Epic',
                              is_public=True)
    trip_count += 1

    # Sofia: Mammoth T+77–81 → score=0 for Alex (no signals — fallback row)
    trip_mammoth_sofia = make_trip(sofia, mammoth, 77, 81,
                                   trip_status='planning', pass_type='No Pass',
                                   is_public=True)
    trip_count += 1

    # Zara: Mammoth T+77–81 → score=1 for Alex (Ikon pass only)
    # Combined with Jordan (T+77–81) + Sofia: 3 friends at Mammoth same weekend
    trip_mammoth_zara = make_trip(zara, mammoth, 77, 81,
                                  trip_status='planning', pass_type='Ikon',
                                  is_public=True)
    trip_count += 1

    # Owen: Park City T+100–104 → score=1 for Alex (Epic pass, nothing else)
    trip_park_city_owen = make_trip(owen, park_city, 100, 104,
                                    trip_status='planning', pass_type='Epic',
                                    is_public=True)
    trip_count += 1

    # ── COHORT D: next-season volume trips (Dec 2026 – Mar 2027) ─────────────
    # Purpose: fill out Friends > Upcoming so it shows Dec / Jan / Feb / Mar
    # month sections, not just the summer cluster.

    # Dec 2026 cluster (~T+240 = Dec 16)
    trip_vail_dev_winter = make_trip(dev, vail, 243, 247,
                                     trip_status='planning', pass_type='Epic',
                                     is_public=True)
    trip_count += 1

    trip_park_city_owen_winter = make_trip(owen, park_city, 246, 250,
                                           trip_status='planning', pass_type='Epic',
                                           is_public=True)
    trip_count += 1

    trip_breck_sofia_winter = make_trip(sofia, breck, 250, 254,
                                        trip_status='planning', pass_type='No Pass',
                                        is_public=True)
    trip_count += 1

    # Jan 2027 cluster (~T+260 = Jan 5, T+281 = Jan 26)
    trip_whistler_lena_winter = make_trip(lena, whistler, 260, 265,
                                          trip_status='planning', pass_type='Mountain Collective',
                                          is_public=True)
    trip_count += 1

    trip_jackson_zara_winter = make_trip(zara, jackson, 283, 288,
                                         trip_status='planning', pass_type='Ikon',
                                         is_public=True)
    trip_count += 1

    # Feb 2027 cluster (~T+302 = Feb 16)
    trip_killington_owen_winter = make_trip(owen, killington, 302, 306,
                                            trip_status='planning', pass_type='Epic',
                                            is_public=True)
    trip_count += 1

    trip_telluride_preet_winter = make_trip(preet, telluride, 305, 309,
                                            trip_status='planning', pass_type='Ikon',
                                            is_public=True)
    trip_count += 1

    # Mar 2027 (~T+328 = Mar 14)
    trip_vail_dev_spring = make_trip(dev, vail, 328, 332,
                                     trip_status='planning', pass_type='Epic',
                                     is_public=True)
    trip_count += 1

    trip_mammoth_zara_spring = make_trip(zara, mammoth, 332, 336,
                                         trip_status='planning', pass_type='Ikon',
                                         is_public=True)
    trip_count += 1

    print(f"    ✓ {trip_count} trips created")

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP TRIP PARTICIPANTS — Breckenridge weekend
    # ─────────────────────────────────────────────────────────────────────────
    print("👥  Setting up group trip participants...")

    add_participant(trip_breck, jordan, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.FLYING)
    add_participant(trip_breck, tyler, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.DRIVING)
    add_participant(trip_breck, maya, status=GuestStatus.INVITED)
    add_participant(trip_breck, chris, status=GuestStatus.DECLINED)

    # Alex is accepted guest on Jordan's Stowe trip
    add_participant(trip_stowe, alex, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.FLYING)
    trip_stowe.is_group_trip = True

    print("    ✓ Breck: Jordan + Tyler accepted, Maya pending, Chris declined")
    print("    ✓ Alex accepted on Jordan's Stowe trip")

    # ─────────────────────────────────────────────────────────────────────────
    # ACTIVITIES
    # ─────────────────────────────────────────────────────────────────────────
    print("📋  Creating activity records...")
    n_activities = 0

    # Jordan created trips → Alex sees them
    add_activity(jordan, alex, ActivityType.TRIP_CREATED, 'trip', trip_stowe.id)
    add_activity(jordan, alex, ActivityType.TRIP_CREATED, 'trip', trip_vail_jordan.id)
    n_activities += 2

    # Alex invited to Stowe, then accepted
    add_activity(jordan, alex, ActivityType.TRIP_INVITE_RECEIVED, 'trip', trip_stowe.id)
    add_activity(alex, jordan, ActivityType.TRIP_INVITE_ACCEPTED, 'trip', trip_stowe.id)
    n_activities += 2

    # Maya created palisades trip → Alex + Jordan see it
    add_activity(maya, alex, ActivityType.TRIP_CREATED, 'trip', trip_palisades_maya.id)
    add_activity(maya, jordan, ActivityType.TRIP_CREATED, 'trip', trip_palisades_maya.id)
    n_activities += 2

    # Tyler created copper trip → Alex sees it
    add_activity(tyler, alex, ActivityType.TRIP_CREATED, 'trip', trip_copper_tyler.id)
    n_activities += 1

    # True overlap: Alex + Jordan both going to Jackson Hole
    add_activity(jordan, alex, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_jordan.id)
    add_activity(alex, jordan, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_alex.id)
    n_activities += 2

    # New connections
    add_activity(jordan, alex, ActivityType.CONNECTION_ACCEPTED, 'user', jordan.id)
    add_activity(alex, jordan, ActivityType.CONNECTION_ACCEPTED, 'user', alex.id)
    add_activity(tyler, alex, ActivityType.CONNECTION_ACCEPTED, 'user', tyler.id)
    n_activities += 3

    # Jordan joined Alex's Breck trip → Maya + Tyler see it
    add_activity(jordan, maya, ActivityType.FRIEND_JOINED_TRIP, 'trip', trip_breck.id)
    add_activity(tyler, maya, ActivityType.FRIEND_JOINED_TRIP, 'trip', trip_breck.id)
    n_activities += 2

    # test5 exact overlaps: Jackson Hole — test5 + Alex + Jordan all there T+45→T+49
    add_activity(jordan, test5, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_jordan.id)
    add_activity(test5, jordan, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_test5.id)
    add_activity(alex, test5, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_alex.id)
    add_activity(test5, alex, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_test5.id)
    n_activities += 4

    # test5 new connections
    add_activity(alex, test5, ActivityType.CONNECTION_ACCEPTED, 'user', alex.id)
    add_activity(test5, alex, ActivityType.CONNECTION_ACCEPTED, 'user', test5.id)
    add_activity(jordan, test5, ActivityType.CONNECTION_ACCEPTED, 'user', jordan.id)
    n_activities += 3

    # Friends' trips visible to test5
    add_activity(jordan, test5, ActivityType.TRIP_CREATED, 'trip', trip_stowe.id)
    add_activity(jordan, test5, ActivityType.TRIP_CREATED, 'trip', trip_vail_jordan.id)
    add_activity(maya, test5, ActivityType.TRIP_CREATED, 'trip', trip_palisades_maya.id)
    add_activity(tyler, test5, ActivityType.TRIP_CREATED, 'trip', trip_copper_tyler.id)
    n_activities += 4

    # Cohort D trips visible to Alex
    add_activity(preet, alex, ActivityType.TRIP_CREATED, 'trip', trip_telluride_preet.id)
    add_activity(lena,  alex, ActivityType.TRIP_CREATED, 'trip', trip_whistler_lena.id)
    add_activity(dev,   alex, ActivityType.TRIP_CREATED, 'trip', trip_vail_dev.id)
    add_activity(sofia, alex, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_sofia.id)
    add_activity(zara,  alex, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_zara.id)
    add_activity(owen,  alex, ActivityType.TRIP_CREATED, 'trip', trip_park_city_owen.id)
    n_activities += 6

    # Mammoth multi-friend signal → Alex sees all three going
    add_activity(jordan, alex, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_jordan.id)
    n_activities += 1

    # New Cohort D connections
    add_activity(preet, alex, ActivityType.CONNECTION_ACCEPTED, 'user', preet.id)
    add_activity(lena,  alex, ActivityType.CONNECTION_ACCEPTED, 'user', lena.id)
    add_activity(dev,   alex, ActivityType.CONNECTION_ACCEPTED, 'user', dev.id)
    n_activities += 3

    print(f"    ✓ {n_activities} activity records created")

    # ─────────────────────────────────────────────────────────────────────────
    # COMMIT
    # ─────────────────────────────────────────────────────────────────────────
    db.session.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────
    all_seeded = User.query.filter_by(is_seeded=True).all()
    all_seeded_ids = [u.id for u in all_seeded]
    all_trip_ids = [
        t.id for t in SkiTrip.query.filter(
            SkiTrip.user_id.in_(all_seeded_ids)
        ).all()
    ]
    friend_rows = Friend.query.filter(Friend.user_id.in_(all_seeded_ids)).count()
    invite_rows = Invitation.query.filter(
        (Invitation.sender_id.in_(all_seeded_ids)) |
        (Invitation.receiver_id.in_(all_seeded_ids))
    ).count()
    participant_rows = SkiTripParticipant.query.filter(
        SkiTripParticipant.trip_id.in_(all_trip_ids)
    ).count()
    resort_names = sorted(set(
        t.mountain for t in SkiTrip.query.filter(SkiTrip.id.in_(all_trip_ids)).all()
    ))

    divider = "═" * 62
    print(f"\n{divider}")
    print("  🎿  BaseLodge Seed Complete")
    print(divider)
    print(f"  Users created:       {len(all_seeded)}")
    print(f"  Friendships:         {friend_rows // 2} pairs  ({friend_rows} rows)")
    print(f"  Pending invitations: {invite_rows}")
    print(f"  Trips created:       {len(all_trip_ids)}")
    print(f"  Participants:        {participant_rows} rows")
    print(f"  Activities:          {n_activities}")
    print()
    print("  Resorts used:")
    for name in resort_names:
        print(f"    • {name}")
    print()
    print("  Primary demo account:")
    print("    Email:    demo@baselodge.app")
    print("    Password: demo1234")
    print()
    print("  Seeded archetypes:")
    archetypes = [
        (alex,   "PRIMARY — Skier+Boarder, Advanced, Epic+Ikon, wishlist: Whistler/Telluride/Jackson"),
        (jordan, "Power User — Expert Skier, Epic, 6 upcoming + 1 past trip"),
        (maya,   "Boarder — Snowboarder, Advanced, Ikon, Tahoe-based"),
        (sam,    "Mixed Rider — Skier+Boarder, Intermediate, past trips only (empty upcoming)"),
        (chris,  "Social/Empty — No pass, no trips, incomplete profile"),
        (emma,   "Beginner Planner — Indy, near-miss Breck trip"),
        (tyler,  "The Regular — Advanced Skier, Ikon, CO-based; Cluster B anchor"),
        (priya,  "Incoming request → Alex + test5 (pending)"),
        (jake,   "Outgoing request from Alex (pending)"),
        (rachel, "No connection to Alex; pending request from test5"),
        (test5,  "Personal demo — Skier, Advanced, Epic+Ikon, 5 upcoming trips, full social graph"),
        (nina,   "Cluster A anchor — Ikon, Telluride wishlist, free Jun 16–19"),
        (marco,  "Cluster A anchor — Ikon, Telluride wishlist, free Jun 16–19"),
        (casey,  "Cluster B anchor — Ikon, Jackson wishlist, free Jan 22–25 2027"),
        (preet,  "Score-6 trip: Telluride T+62–66, Ikon (wishlist+overlap+pass for Alex)"),
        (lena,   "Score-5 trip: Whistler T+14–18, Mountain Collective (wishlist+overlap, no pass)"),
        (dev,    "Score-3 trip: Vail T+15–19, Epic (overlap+pass, not on Alex's wishlist)"),
        (sofia,  "Score-0 trip: Mammoth T+77–81, No Pass (no signals — fallback row)"),
        (zara,   "Score-1 trip: Mammoth T+77–81, Ikon (pass only) + next-season Jackson"),
        (owen,   "Score-1 trip: Park City T+100–4, Epic (pass only) + Dec/Feb next season"),
    ]
    for user, label in archetypes:
        print(f"    {user.first_name} {user.last_name}  <{user.email}>")
        print(f"      {label}")
    print()
    print("  Scenarios:")
    print(f"    ✓ High-density weekend: Breck T+{breck_start}→T+{breck_end}")
    print(f"      Jordan + Tyler accepted, Maya pending, Chris declined")
    print(f"    ✓ True overlap: Alex + Jordan both at Jackson Hole T+45→T+49")
    print(f"    ✓ Near-miss: Emma arrives at Breck T+{breck_end+2} (2 days late)")
    print(f"    ✓ Guest view: Alex accepted on Jordan's Stowe trip T+14→T+17")
    print(f"    ✓ Power user: Jordan — 6 upcoming + 1 past, full profile + gear")
    print(f"    ✓ Empty state: Chris — no trips, no equipment, no terrain prefs")
    print(f"    ✓ Past trips: Sam (Vail + Whistler), Alex (Park City), Jordan (Whistler)")
    print(f"    ✓ Ideas overlap: Alex + Jordan share open dates T+44→T+50")
    print(f"    ✓ Pending connection: Priya → Alex (incoming), Alex → Jake (outgoing)")
    print(f"    ✓ No connection: Rachel Stone has no relationship with Alex")
    print(f"    ✓ test5 exact overlap: Taylor + Alex + Jordan all at Jackson Hole T+45→T+49")
    print(f"    ✓ test5 near overlap: Taylor at Breck T+22→T+25 (1 day into main group T+21)")
    print(f"    ✓ test5 different resort: Taylor at Telluride T+35→T+38 (Jordan=Vail, Tyler=Copper)")
    print(f"    ✓ test5 social graph: friends with all 16 core users, 1 incoming (Priya), 1 outgoing (Rachel)")
    print()
    print("  Join a Trip curated scoring (demo@baselodge.app):")
    print(f"    ✓ Score 6: Jackson Hole (Jordan, T+45, Ikon)  — wishlist+overlap+pass")
    print(f"    ✓ Score 6: Telluride (Preet, T+62, Ikon)     — wishlist+overlap+pass")
    print(f"    ✓ Score 5: Whistler (Lena, T+14, MC)         — wishlist+overlap, no pass")
    print(f"    ✓ Score 3: Stowe (Jordan, T+14, Epic)        — overlap+pass, not wishlist")
    print(f"    ✓ Score 3: Palisades (Maya, T+42, Ikon)      — overlap+pass, not wishlist")
    print(f"    ✓ Score 3: Vail (Dev, T+15, Epic)            — overlap+pass, not wishlist")
    print(f"    ✓ Score 1: Various (Vail J, Copper T, Killington J, Mammoth J, Zara, Owen)")
    print(f"    ✓ Score 0: Mammoth (Sofia, T+77, No Pass)    — fallback row")
    print(f"    ✓ Multi-friend Mammoth: Jordan + Sofia + Zara all T+77–81")
    print()
    print("  Friends > Upcoming monthly spread (demo@baselodge.app):")
    print(f"    ✓ May 2026   — Stowe (Jordan), Whistler (Lena), Vail (Dev), Breck (Emma)")
    print(f"    ✓ Jun 2026   — Vail (Jordan), Copper (Tyler), Palisades (Maya),")
    print(f"                   Jackson (Jordan), Killington (Jordan), Telluride (Preet)")
    print(f"    ✓ Jul 2026   — Mammoth x3 (Jordan+Sofia+Zara), Copper (Jordan)")
    print(f"    ✓ Dec 2026   — Vail (Dev), Park City (Owen), Breck (Sofia)")
    print(f"    ✓ Jan 2027   — Whistler (Lena), Jackson (Zara)")
    print(f"    ✓ Feb 2027   — Killington (Owen), Telluride (Preet)")
    print(f"    ✓ Mar 2027   — Vail (Dev), Mammoth (Zara)")
    print()
    print("  Ideas Engine clusters (demo@baselodge.app):")
    print(f"    ✓ Cluster A — Jun 16–19 / Telluride / Ikon:  Alex + Nina + Marco")
    print(f"      → Expect: availability_overlap card 'You, Nina, and Marco are free Jun 16–19'")
    print(f"      → Expect: wishlist_overlap card 'Telluride is on your lists' (Alex + Jordan + Nina + Marco)")
    print(f"    ✓ Cluster B — Jan 22–25, 2027 / Jackson Hole / Ikon:  Alex + Tyler + Casey")
    print(f"      → Expect: availability_overlap card 'You, Tyler, and Casey are free Jan 22–25'")
    print(f"      → Expect: wishlist_overlap card 'Jackson Hole is on your lists' (Alex + Tyler + Casey + Sam)")
    print(f"    ✓ Soft pull — Whistler wishlist:  Alex + Maya + Nina + Casey + Lena (no shared avail)")
    print(f"      → Expect: lower-priority wishlist_overlap card for Whistler")
    print()
    print("  QA checklist — log in as demo@baselodge.app / demo1234:")
    print()
    print("  /trip-ideas:")
    print("    □ Friend-trip cards: Jordan (Jackson/Vail/Stowe), Maya (Palisades), Tyler (Copper)")
    print("    □ Availability overlap card Jun 16–19 featuring Nina and/or Marco")
    print("    □ Availability overlap card Jan 22–25, 2027 featuring Tyler and/or Casey")
    print("    □ Wishlist card for Telluride (Alex + Jordan + Nina + Marco)")
    print("    □ Wishlist card for Jackson Hole (Alex + Tyler + Casey + Sam)")
    print()
    print("  /my-trips → Join a Trip tab:")
    print("    □ Score-6 trips at top: Jackson (Jordan) and Telluride (Preet)")
    print("    □ Score-5 Whistler (Lena) appears before score-3 group")
    print("    □ Score-3 group: Stowe (Jordan), Palisades (Maya), Vail (Dev)")
    print("    □ Score-1 and score-0 entries appear last (or are capped out)")
    print("    □ Multi-friend Mammoth weekend shows Jordan + Sofia + Zara")
    print()
    print("  /friends → Upcoming tab:")
    print("    □ Month headers: May, June, July, Dec 2026, Jan 2027, Feb 2027, Mar 2027")
    print("    □ Mammoth in July shows 3 friends (Jordan, Sofia, Zara)")
    print("    □ Next-season Dec/Jan/Feb/Mar entries are visible below summer cluster")
    print()
    print("  /friends → Friends tab:")
    print("    □ 16 friends visible (not counting pending Priya/Jake/Rachel)")
    print("    □ Mix of skill levels, passes, rider types visible in list")
    print()
    print("  Friend profiles:")
    print("    □ Jordan: 6 upcoming trips, full gear, full profile")
    print("    □ Sam: past trips only, no upcoming")
    print("    □ Chris: no trips, no equipment, incomplete profile")
    print("    □ Preet: Telluride specialist, Ikon, score-6 alignment with Alex")
    print(divider + "\n")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        try:
            teardown()
            seed()
        except Exception as e:
            db.session.rollback()
            print(f"\n❌  Seed failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
