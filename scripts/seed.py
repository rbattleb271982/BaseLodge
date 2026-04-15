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
        wish_list_resorts=[whistler.id, telluride.id, abasin.id],
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

    # Availability: Jackson Hole window + Telluride window + free around Stowe
    set_open_dates(alex, list(range(44, 51)) + list(range(13, 18)) + list(range(62, 68)))

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
    set_open_dates(tyler, list(range(breck_start - 1, breck_end + 2)) + list(range(35, 39)))

    print("    ✓ Primary account + Cohort A (6 users) created")

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
        password='seed_pass_1!',
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
    # Open dates: cover the Telluride/Vail/Copper window, the Jackson window, and Stowe window
    set_open_dates(test5, list(range(35, 40)) + list(range(44, 52)) + list(range(60, 66)))

    print("    ✓ Cohort B (3 connection state users) created")
    print("    ✓ Taylor Reed <test5@gmail.com> created (personal demo, full social graph)")

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

    # test5 incoming: Priya → test5 (pending, separate record from Priya → Alex)
    make_invitation(priya, test5, status='pending')

    # test5 outgoing: test5 → Rachel (pending; Rachel has no confirmed connection)
    make_invitation(test5, rachel, status='pending')

    print("    ✓ 15 bidirectional friendships, 4 pending invitations")

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
        (alex,   "Primary test account — Skier+Boarder, Advanced, Epic+Ikon"),
        (jordan, "Power User — Expert Skier, Epic, 6 upcoming + 1 past trip"),
        (maya,   "Boarder — Snowboarder, Advanced, Ikon, Tahoe-based"),
        (sam,    "Mixed Rider — Skier+Boarder, Intermediate, past trips only"),
        (chris,  "Social/Empty — No pass, no trips, incomplete profile"),
        (emma,   "Beginner Planner — Indy, near-miss Breck trip"),
        (tyler,  "The Regular — Advanced Skier, Ikon, CO-based"),
        (priya,  "Incoming request → Alex + test5 (pending)"),
        (jake,   "Outgoing request from Alex (pending)"),
        (rachel, "No connection to Alex; pending request from test5"),
        (test5,  "Personal demo — Skier, Advanced, Epic+Ikon, 5 upcoming trips, friends with all core users"),
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
    print(f"    ✓ test5 social graph: friends with all 7 core users, 1 incoming (Priya), 1 outgoing (Rachel)")
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
