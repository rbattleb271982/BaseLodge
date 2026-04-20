#!/usr/bin/env python3
"""
scripts/seed.py — BaseLodge deterministic reset-and-reseed script

Wipes all seeded/demo data (is_seeded=True) and recreates a rich pseudo-live
demo environment covering all key product states.

Usage:
    python scripts/seed.py

Safety: only deletes records tied to seeded users. Real user data is untouched.
Primary demo account: richardbattlebaxter@gmail.com (enriched in-place if it
exists; created from scratch otherwise).
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

    seeded_users = User.query.filter_by(is_seeded=True).all()

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

    # Anchor weekend ~3 weeks out
    breck_start = 21
    breck_end   = 24

    # ─────────────────────────────────────────────────────────────────────────
    # PRIMARY ACCOUNT — Richard Battle-Baxter
    # Enrich in-place if real account exists, else create seeded copy.
    # ─────────────────────────────────────────────────────────────────────────
    print("🌱  Creating users...")

    richard = User.query.filter_by(email='richardbattlebaxter@gmail.com').first()
    if richard:
        richard.is_seeded        = True
        richard.lifecycle_stage  = 'active'
        richard.profile_completed_at   = NOW
        richard.onboarding_completed_at = NOW
        richard.created_at       = NOW - timedelta(days=180)
        richard.last_active_at   = NOW
        richard.rider_types      = ['Skier', 'Snowboarder']
        richard.skill_level      = 'Advanced'
        richard.pass_type        = 'Epic,Ikon'
        richard.terrain_preferences = ['Steeps', 'Trees']
        richard.home_state       = 'CO'
        richard.backcountry_capable = True
        richard.avi_certified    = True
        richard.home_resort_id   = breck.id
        richard.visited_resort_ids = [vail.id, breck.id, park_city.id, mammoth.id, jackson.id]
        richard.wish_list_resorts  = [whistler.id, telluride.id, jackson.id]
        richard.equipment_status = 'have_own_equipment'
        richard.open_dates       = []
        db.session.flush()
    else:
        richard = make_user(
            first_name='Richard', last_name='Battle-Baxter',
            email='richardbattlebaxter@gmail.com',
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

    # Clear old equipment for richard so we don't duplicate
    EquipmentSetup.query.filter_by(user_id=richard.id).delete()
    db.session.flush()

    make_equipment(richard, EquipmentSlot.PRIMARY, EquipmentDiscipline.SKIER,
                   brand='Atomic', model='Bent Chetler 100',
                   boot_brand='Salomon', boot_model="S/Pro Alpha 120", boot_flex=120)
    make_equipment(richard, EquipmentSlot.SECONDARY, EquipmentDiscipline.SNOWBOARDER,
                   brand='Burton', model='Custom 157',
                   boot_brand='Burton', boot_model='Photon Boa', is_active=False)
    set_open_dates(richard, list(range(13, 18)) + list(range(44, 51)) + list(range(61, 68)) + list(range(281, 285)))

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

    # A4 — Chris Adler (Social / Empty-state contrast)
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

    # A5 — Emma Russo (Beginner Planner: boots only, near-miss Breck)
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

    print("    ✓ Richard + Cohort A (6 users)")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT B — CONNECTION STATE USERS
    # ─────────────────────────────────────────────────────────────────────────

    # B1 — Priya Mehta (incoming friend request to Richard)
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

    # B2 — Jake Simmons (outgoing request from Richard)
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

    # B3 — Rachel Stone (no connection to Richard)
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

    print("    ✓ Cohort B (3 connection-state users)")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT C — IDEAS ENGINE OVERLAP CLUSTERS
    # ─────────────────────────────────────────────────────────────────────────
    # Cluster A (Jun 16–19 / Telluride / Ikon): Richard + Nina + Marco
    # Cluster B (Jan 22–25 2027 / Jackson / Ikon): Richard + Tyler + Casey

    # C1 — Nina Patel (Cluster A anchor)
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
    set_open_dates(nina, list(range(61, 65)) + list(range(30, 35)))

    # C2 — Marco Rivera (Cluster A anchor)
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
    set_open_dates(marco, list(range(61, 65)) + list(range(25, 30)))

    # C3 — Casey Kim (Cluster B anchor)
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
    set_open_dates(casey, list(range(281, 285)) + list(range(50, 55)))

    print("    ✓ Cohort C (3 ideas-cluster users)")

    # ─────────────────────────────────────────────────────────────────────────
    # COHORT D — JOIN A TRIP SCORING DIVERSITY + FRIENDS > UPCOMING VOLUME
    # ─────────────────────────────────────────────────────────────────────────
    # Preet → Telluride T+62–66   wishlist(3)+overlap(2)+pass(1) = 6
    # Lena  → Whistler  T+14–18   wishlist(3)+overlap(2)+no_pass = 5
    # Dev   → Vail      T+15–19   overlap(2)+pass(1)             = 3
    # Zara  → Mammoth   T+77–81   Ikon pass only                 = 1
    # Owen  → Park City T+100–4   Epic pass only                 = 1
    # Sofia → Mammoth   T+77–81   No pass, no overlap            = 0

    # D1 — Preet Singh (score=6)
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

    # D2 — Lena Kowalski (score=5)
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

    # D3 — Dev Sharma (score=3)
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

    # D4 — Sofia Reyes (score=0)
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

    # D5 — Zara Ahmed (score=1, Ikon pass only; also in Mammoth multi-friend)
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

    # D6 — Owen Park (score=1, Epic pass only; multiple next-season trips)
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

    print("    ✓ Cohort D (6 scoring/volume users)")

    # ─────────────────────────────────────────────────────────────────────────
    # FRIENDSHIPS
    # ─────────────────────────────────────────────────────────────────────────
    print("🤝  Creating friendships...")

    # Richard ↔ Cohort A
    make_friends(richard, jordan)
    make_friends(richard, maya)
    make_friends(richard, sam)
    make_friends(richard, chris)
    make_friends(richard, emma)
    make_friends(richard, tyler)

    # Richard ↔ Cohort C (ideas clusters)
    make_friends(richard, nina)
    make_friends(richard, marco)
    make_friends(richard, casey)

    # Richard ↔ Cohort D (scoring diversity)
    make_friends(richard, preet)
    make_friends(richard, lena)
    make_friends(richard, dev)
    make_friends(richard, sofia)
    make_friends(richard, zara)
    make_friends(richard, owen)

    # Cross-connections among other seeded users
    make_friends(jordan, maya)
    make_friends(jordan, tyler)

    db.session.flush()

    # Pending invitations (B1 incoming, B2 outgoing)
    make_invitation(priya, richard, status='pending')
    make_invitation(richard, jake, status='pending')

    db.session.flush()
    print(f"    ✓ 15 friendships for Richard + 2 pending invitations")

    # ─────────────────────────────────────────────────────────────────────────
    # TRIPS
    # ─────────────────────────────────────────────────────────────────────────
    print("🏔   Creating trips...")
    trip_count = 0

    # ── Richard owns: Breckenridge (group weekend) ────────────────────────────
    trip_breck = make_trip(richard, breck, breck_start, breck_end,
                           trip_status='going',
                           pass_type='Epic',
                           accommodation_status='hotel',
                           is_group_trip=True,
                           is_public=True)
    trip_count += 1

    # ── Richard upcoming: Jackson Hole (overlap with Jordan) ─────────────────
    trip_jackson_richard = make_trip(richard, jackson, 45, 49,
                                     trip_status='planning',
                                     pass_type='Ikon',
                                     is_public=True)
    trip_count += 1

    # ── Richard upcoming: Telluride ───────────────────────────────────────────
    trip_telluride_richard = make_trip(richard, telluride, 63, 67,
                                       trip_status='planning',
                                       pass_type='Mountain Collective',
                                       is_public=True)
    trip_count += 1

    # ── Richard past: Park City ───────────────────────────────────────────────
    trip_park_city_past = make_trip(richard, park_city, -35, -32,
                                    trip_status='going',
                                    pass_type='Epic',
                                    is_public=True)
    trip_count += 1

    # ── Jordan (power user: 6 upcoming + 1 past) ─────────────────────────────
    trip_stowe = make_trip(jordan, stowe, 14, 17,
                           trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_vail_jordan = make_trip(jordan, vail, 35, 38,
                                 trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

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

    # ── Maya: Palisades Tahoe ─────────────────────────────────────────────────
    trip_palisades_maya = make_trip(maya, palisades, 42, 46,
                                    trip_status='going', pass_type='Ikon', is_public=True)
    trip_count += 1

    # ── Sam: past only ────────────────────────────────────────────────────────
    trip_vail_sam_past = make_trip(sam, vail, -90, -86,
                                   trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_whistler_sam_past = make_trip(sam, whistler, -60, -55,
                                       trip_status='going', pass_type='Epic', is_public=True)
    trip_count += 1

    # ── Emma: near-miss Breck ─────────────────────────────────────────────────
    trip_breck_emma = make_trip(emma, breck, breck_end + 2, breck_end + 5,
                                trip_status='planning', pass_type='Indy', is_public=True)
    trip_count += 1

    # ── Tyler: Copper Mountain ────────────────────────────────────────────────
    trip_copper_tyler = make_trip(tyler, copper, 35, 38,
                                  trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # ── Cohort D: scoring trips (current season) ──────────────────────────────
    # Preet: Telluride T+62–66 → score=6 for Richard
    trip_telluride_preet = make_trip(preet, telluride, 62, 66,
                                     trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # Lena: Whistler T+14–18 → score=5 for Richard
    trip_whistler_lena = make_trip(lena, whistler, 14, 18,
                                   trip_status='planning', pass_type='Mountain Collective', is_public=True)
    trip_count += 1

    # Dev: Vail T+15–19 → score=3 for Richard
    trip_vail_dev = make_trip(dev, vail, 15, 19,
                              trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    # Sofia: Mammoth T+77–81 → score=0 for Richard
    trip_mammoth_sofia = make_trip(sofia, mammoth, 77, 81,
                                   trip_status='planning', pass_type='No Pass', is_public=True)
    trip_count += 1

    # Zara: Mammoth T+77–81 → score=1 for Richard (Ikon pass only)
    trip_mammoth_zara = make_trip(zara, mammoth, 77, 81,
                                  trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    # Owen: Park City T+100–104 → score=1 for Richard (Epic pass only)
    trip_park_city_owen = make_trip(owen, park_city, 100, 104,
                                    trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    # ── Cohort D: next-season volume trips (Dec 2026 – Mar 2027) ─────────────
    trip_vail_dev_winter = make_trip(dev, vail, 243, 247,
                                     trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_park_city_owen_winter = make_trip(owen, park_city, 246, 250,
                                           trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_breck_sofia_winter = make_trip(sofia, breck, 250, 254,
                                        trip_status='planning', pass_type='No Pass', is_public=True)
    trip_count += 1

    trip_whistler_lena_winter = make_trip(lena, whistler, 260, 265,
                                          trip_status='planning', pass_type='Mountain Collective', is_public=True)
    trip_count += 1

    trip_jackson_zara_winter = make_trip(zara, jackson, 283, 288,
                                         trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_killington_owen_winter = make_trip(owen, killington, 302, 306,
                                            trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_telluride_preet_winter = make_trip(preet, telluride, 305, 309,
                                            trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    trip_vail_dev_spring = make_trip(dev, vail, 328, 332,
                                     trip_status='planning', pass_type='Epic', is_public=True)
    trip_count += 1

    trip_mammoth_zara_spring = make_trip(zara, mammoth, 332, 336,
                                         trip_status='planning', pass_type='Ikon', is_public=True)
    trip_count += 1

    print(f"    ✓ {trip_count} trips created")

    # ─────────────────────────────────────────────────────────────────────────
    # GROUP TRIP PARTICIPANTS
    # ─────────────────────────────────────────────────────────────────────────
    print("👥  Setting up group trip participants...")

    add_participant(trip_breck, jordan, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.FLYING)
    add_participant(trip_breck, tyler, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.DRIVING)
    add_participant(trip_breck, maya, status=GuestStatus.INVITED)
    add_participant(trip_breck, chris, status=GuestStatus.DECLINED)

    add_participant(trip_stowe, richard, status=GuestStatus.ACCEPTED,
                    transportation_status=ParticipantTransportation.FLYING)
    trip_stowe.is_group_trip = True

    print("    ✓ Breck: Jordan + Tyler accepted, Maya pending, Chris declined")
    print("    ✓ Richard accepted on Jordan's Stowe trip")

    # ─────────────────────────────────────────────────────────────────────────
    # ACTIVITIES
    # ─────────────────────────────────────────────────────────────────────────
    print("📋  Creating activity records...")
    n_activities = 0

    add_activity(jordan, richard, ActivityType.TRIP_CREATED, 'trip', trip_stowe.id)
    add_activity(jordan, richard, ActivityType.TRIP_CREATED, 'trip', trip_vail_jordan.id)
    n_activities += 2

    add_activity(jordan, richard, ActivityType.TRIP_INVITE_RECEIVED, 'trip', trip_stowe.id)
    add_activity(richard, jordan, ActivityType.TRIP_INVITE_ACCEPTED, 'trip', trip_stowe.id)
    n_activities += 2

    add_activity(maya, richard, ActivityType.TRIP_CREATED, 'trip', trip_palisades_maya.id)
    add_activity(maya, jordan, ActivityType.TRIP_CREATED, 'trip', trip_palisades_maya.id)
    n_activities += 2

    add_activity(tyler, richard, ActivityType.TRIP_CREATED, 'trip', trip_copper_tyler.id)
    n_activities += 1

    add_activity(jordan, richard, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_jordan.id)
    add_activity(richard, jordan, ActivityType.TRIP_OVERLAP, 'trip', trip_jackson_richard.id)
    n_activities += 2

    add_activity(jordan, richard, ActivityType.CONNECTION_ACCEPTED, 'user', jordan.id)
    add_activity(richard, jordan, ActivityType.CONNECTION_ACCEPTED, 'user', richard.id)
    add_activity(tyler, richard, ActivityType.CONNECTION_ACCEPTED, 'user', tyler.id)
    n_activities += 3

    add_activity(jordan, maya, ActivityType.FRIEND_JOINED_TRIP, 'trip', trip_breck.id)
    add_activity(tyler, maya, ActivityType.FRIEND_JOINED_TRIP, 'trip', trip_breck.id)
    n_activities += 2

    add_activity(preet, richard, ActivityType.TRIP_CREATED, 'trip', trip_telluride_preet.id)
    add_activity(lena,  richard, ActivityType.TRIP_CREATED, 'trip', trip_whistler_lena.id)
    add_activity(dev,   richard, ActivityType.TRIP_CREATED, 'trip', trip_vail_dev.id)
    add_activity(sofia, richard, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_sofia.id)
    add_activity(zara,  richard, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_zara.id)
    add_activity(owen,  richard, ActivityType.TRIP_CREATED, 'trip', trip_park_city_owen.id)
    n_activities += 6

    add_activity(jordan, richard, ActivityType.TRIP_CREATED, 'trip', trip_mammoth_jordan.id)
    n_activities += 1

    add_activity(preet, richard, ActivityType.CONNECTION_ACCEPTED, 'user', preet.id)
    add_activity(lena,  richard, ActivityType.CONNECTION_ACCEPTED, 'user', lena.id)
    add_activity(dev,   richard, ActivityType.CONNECTION_ACCEPTED, 'user', dev.id)
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
        t.id for t in SkiTrip.query.filter(SkiTrip.user_id.in_(all_seeded_ids)).all()
    ]
    friend_rows = Friend.query.filter(Friend.user_id.in_(all_seeded_ids)).count()
    invite_rows = Invitation.query.filter(
        (Invitation.sender_id.in_(all_seeded_ids)) |
        (Invitation.receiver_id.in_(all_seeded_ids))
    ).count()
    participant_rows = SkiTripParticipant.query.filter(
        SkiTripParticipant.trip_id.in_(all_trip_ids)
    ).count()
    richard_friend_count = Friend.query.filter_by(user_id=richard.id).count()

    divider = "═" * 62
    print(f"\n{divider}")
    print("  🎿  BaseLodge Seed Complete")
    print(divider)
    print(f"  Seeded users:        {len(all_seeded)}")
    print(f"  Richard friends:     {richard_friend_count}")
    print(f"  All friend rows:     {friend_rows} ({friend_rows // 2} pairs)")
    print(f"  Pending invitations: {invite_rows}")
    print(f"  Trips created:       {len(all_trip_ids)}")
    print(f"  Participants:        {participant_rows} rows")
    print(f"  Activities:          {n_activities}")
    print()
    print("  Primary demo account:")
    print("    Email:    richardbattlebaxter@gmail.com")
    print()
    print("  Richard's friends:")
    r_friends = Friend.query.filter_by(user_id=richard.id).all()
    for rf in r_friends:
        fu = User.query.get(rf.friend_id)
        print(f"    • {fu.first_name} {fu.last_name}  <{fu.email}>")
    print(divider)


if __name__ == '__main__':
    with app.app_context():
        try:
            teardown()
            seed()
        except Exception as e:
            db.session.rollback()
            print(f"\n❌  Seed failed: {e}")
            raise
