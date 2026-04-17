"""
Seed comprehensive Home permutation test users for BaseLodge.

Each user represents one distinct, testable Home screen state.
All users share password: TestPass1!

Run:  python scripts/seed_home_permutations.py

Idempotent — safe to re-run; skips rows that already exist.
"""

import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import (
    db, User, Friend, UserAvailability, SkiTrip, SkiTripParticipant,
    Invitation, EquipmentSetup, GuestStatus, ParticipantRole,
    EquipmentSlot, EquipmentDiscipline, Resort,
)
from werkzeug.security import generate_password_hash

PASSWORD   = "TestPass1!"
PW_HASH    = generate_password_hash(PASSWORD)
TODAY      = date.today()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _resort():
    """Return any active resort."""
    r = Resort.query.filter_by(is_active=True).first()
    if not r:
        raise RuntimeError("No active resorts found — run resort seed first.")
    return r


def _make_user(first, last, email, **overrides):
    """Get or create a seeded user. Returns (user, created_bool)."""
    u = User.query.filter_by(email=email).first()
    if u:
        return u, False
    defaults = dict(
        first_name=first,
        last_name=last,
        email=email,
        password_hash=PW_HASH,
        rider_types=["Skier"],
        pass_type="Epic",
        skill_level="Intermediate",
        home_state="CO",
        profile_setup_complete=True,
        is_seeded=True,
        is_verified=True,
        equipment_status="have_own_equipment",
        open_dates=[],
        wish_list_resorts=[],
        visited_resort_ids=[],
        terrain_preferences=["Groomers"],
        lifecycle_stage="active",
        created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    u = User(**defaults)
    db.session.add(u)
    db.session.flush()
    return u, True


def _make_trip(owner, resort, start_delta, end_delta,
               status="going", is_public=True):
    """Create an upcoming trip owned by `owner`; add owner as OWNER participant."""
    start = TODAY + timedelta(days=start_delta)
    end   = TODAY + timedelta(days=end_delta)
    trip  = SkiTrip(
        user_id=owner.id,
        resort_id=resort.id,
        mountain=resort.name,
        state=resort.state_code or resort.state,
        start_date=start,
        end_date=end,
        pass_type=owner.pass_type or "No Pass",
        is_public=is_public,
        trip_status=status,
        accommodation_status="not_yet",
        created_at=datetime.utcnow(),
    )
    db.session.add(trip)
    db.session.flush()
    p = SkiTripParticipant(
        trip_id=trip.id,
        user_id=owner.id,
        status=GuestStatus.ACCEPTED,
        role=ParticipantRole.OWNER,
        created_at=datetime.utcnow(),
    )
    db.session.add(p)
    db.session.flush()
    return trip


def _get_or_make_trip(owner, resort, start_delta, end_delta, **kwargs):
    """Return existing upcoming trip for owner, or create one."""
    t = (SkiTrip.query
         .filter_by(user_id=owner.id)
         .filter(SkiTrip.end_date >= TODAY)
         .first())
    return t or _make_trip(owner, resort, start_delta, end_delta, **kwargs)


def _add_guest(trip, user, status):
    """Add or update user as a guest participant on a trip."""
    existing = SkiTripParticipant.query.filter_by(
        trip_id=trip.id, user_id=user.id).first()
    if existing:
        existing.status = status
        db.session.flush()
        return existing
    p = SkiTripParticipant(
        trip_id=trip.id,
        user_id=user.id,
        status=status,
        role=ParticipantRole.GUEST,
        created_at=datetime.utcnow(),
    )
    db.session.add(p)
    db.session.flush()
    return p


def _make_friends(u1, u2):
    """Bidirectionally friend two users (idempotent)."""
    if not Friend.query.filter_by(user_id=u1.id, friend_id=u2.id).first():
        db.session.add(Friend(
            user_id=u1.id, friend_id=u2.id,
            is_seeded=True, created_at=datetime.utcnow()))
    if not Friend.query.filter_by(user_id=u2.id, friend_id=u1.id).first():
        db.session.add(Friend(
            user_id=u2.id, friend_id=u1.id,
            is_seeded=True, created_at=datetime.utcnow()))
    db.session.flush()


def _add_open_dates(user, date_strings):
    """
    Set open_dates JSON AND add UserAvailability rows.
    Use for availability-nudge scenarios (uses open_dates JSON for nudge
    computation and UserAvailability for Best Match computation).
    """
    user.open_dates = list(date_strings)
    for d_str in date_strings:
        d = date.fromisoformat(d_str)
        if not UserAvailability.query.filter_by(user_id=user.id, date=d).first():
            db.session.add(UserAvailability(
                user_id=user.id, date=d, is_available=True))
    db.session.flush()


def _add_ua_only(user, date_strings):
    """
    Add UserAvailability rows ONLY (do NOT touch open_dates JSON).
    Use when you want Best Match to fire (via UserAvailability table) but
    NOT the availability nudge (which reads open_dates JSON).
    Caller must ensure user.open_dates stays [] for nudge to stay silent.
    """
    for d_str in date_strings:
        d = date.fromisoformat(d_str)
        if not UserAvailability.query.filter_by(user_id=user.id, date=d).first():
            db.session.add(UserAvailability(
                user_id=user.id, date=d, is_available=True))
    db.session.flush()


def _add_equipment(user, brand="Rossignol", model="Experience 86"):
    """Create a primary EquipmentSetup if none exists."""
    if EquipmentSetup.query.filter_by(user_id=user.id, is_active=True).first():
        return
    db.session.add(EquipmentSetup(
        user_id=user.id,
        slot=EquipmentSlot.PRIMARY,
        discipline=EquipmentDiscipline.SKIER,
        brand=brand,
        model=model,
        is_active=True,
        equipment_status="own",
    ))
    db.session.flush()


def _add_connect_invite(sender, receiver):
    """Pending connection invite with no trip_id (idempotent)."""
    existing = Invitation.query.filter_by(
        sender_id=sender.id, receiver_id=receiver.id, trip_id=None).first()
    if existing:
        existing.status = "pending"
        db.session.flush()
        return existing
    inv = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        trip_id=None,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.session.add(inv)
    db.session.flush()
    return inv


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SEED
# ─────────────────────────────────────────────────────────────────────────────

def seed_home_permutations():
    with app.app_context():
        resort = _resort()
        print(f"  Using resort: {resort.name} (id={resort.id})\n")

        # Shared future dates used across open-date scenarios
        D1 = (TODAY + timedelta(days=14)).isoformat()
        D2 = (TODAY + timedelta(days=21)).isoformat()
        D3 = (TODAY + timedelta(days=28)).isoformat()
        D4 = (TODAY + timedelta(days=35)).isoformat()

        # ─────────────────────────────────────────────────────────────────
        # HELPER USERS — supporting actors used by multiple scenario users
        # ─────────────────────────────────────────────────────────────────

        # h_host1 — owns a trip that others can be invited/accepted into
        h_host1, _ = _make_user("Sam", "Host", "helper.triphost1@test.com",
                                 rider_types=["Skier"], pass_type="Epic",
                                 skill_level="Advanced")
        h_host1_trip = _get_or_make_trip(h_host1, resort, 15, 19)

        # h_host2 — owns a second trip for multi-invite scenarios
        h_host2, _ = _make_user("Tara", "Host", "helper.triphost2@test.com",
                                 rider_types=["Skier"], pass_type="Ikon",
                                 skill_level="Expert")
        h_host2_trip = _get_or_make_trip(h_host2, resort, 25, 29)

        # h_friend_trip — has a public upcoming trip; drives friend_trip secondary card
        h_friend_trip, _ = _make_user("Uma", "Slope", "helper.friendtrip@test.com",
                                       rider_types=["Snowboarder"], pass_type="Ikon",
                                       skill_level="Advanced")
        h_ft_trip = _get_or_make_trip(h_friend_trip, resort, 20, 23,
                                      status="going", is_public=True)

        # h_opendate — has open dates (JSON + UserAvailability) for nudge + Best Match
        h_opendate, _ = _make_user("Vera", "Dates", "helper.opendate1@test.com",
                                    rider_types=["Skier"], pass_type="Epic",
                                    skill_level="Intermediate")
        _add_open_dates(h_opendate, [D1, D2])

        # h_opendate2, h_opendate3 — for multi-overlap ranking test (P15)
        h_opendate2, _ = _make_user("Will", "Dates", "helper.opendate2@test.com",
                                     rider_types=["Skier"], pass_type="Ikon",
                                     skill_level="Advanced")
        _add_open_dates(h_opendate2, [D2, D3])

        h_opendate3, _ = _make_user("Xena", "Dates", "helper.opendate3@test.com",
                                     rider_types=["Skier"], pass_type="Epic",
                                     skill_level="Beginner")
        _add_open_dates(h_opendate3, [D3, D4])

        # h_inv_sender — sends a connection invite to P07
        h_inv_sender, _ = _make_user("Yuri", "Connect", "helper.invsender@test.com",
                                      rider_types=["Skier"], pass_type="Ikon",
                                      skill_level="Intermediate")

        db.session.commit()
        print("  ✓ Helpers created/verified\n")

        # ─────────────────────────────────────────────────────────────────
        # P01 — Empty state only
        # Trigger: no trips (owned or guest-accepted). No friends, no invites.
        # ─────────────────────────────────────────────────────────────────
        p01, _ = _make_user("Clay", "Empty", "p01.emptyonly@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate", open_dates=[])
        _add_equipment(p01, "Atomic", "Redster G9")
        db.session.commit()
        print("  ✓ P01 Empty state only")

        # ─────────────────────────────────────────────────────────────────
        # P02 — Empty + banner invite
        # Trigger: INVITED on h_host1_trip (pending). No owned or accepted trips.
        # ─────────────────────────────────────────────────────────────────
        p02, _ = _make_user("Blair", "Empty", "p02.emptybanner@test.com",
                             rider_types=["Snowboarder"], pass_type="Ikon",
                             skill_level="Advanced", open_dates=[])
        _add_equipment(p02, "Burton", "Custom")
        _add_guest(h_host1_trip, p02, GuestStatus.INVITED)
        db.session.commit()
        print("  ✓ P02 Empty + banner invite")

        # ─────────────────────────────────────────────────────────────────
        # P03 — Own trip, zero friends → "Bring your crew"
        # Trigger: has next_trip (own), friend_count==0, secondary_card==None
        # ─────────────────────────────────────────────────────────────────
        p03, _ = _make_user("Dale", "Own", "p03.owntripnofriends@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Advanced")
        _add_equipment(p03, "Head", "Monster 98")
        _get_or_make_trip(p03, resort, 10, 13)
        db.session.commit()
        print("  ✓ P03 Own trip + no friends (Bring Your Crew)")

        # ─────────────────────────────────────────────────────────────────
        # P04 — Accepted guest trip only, no owned trips → "View trip →"
        # Trigger: ACCEPTED on h_host1_trip; user owns no upcoming trips.
        # next_trip.user_id != p04.id → action reads "View trip →"
        # ─────────────────────────────────────────────────────────────────
        p04, _ = _make_user("Faye", "Guest", "p04.guesttrip@test.com",
                             rider_types=["Skier"], pass_type="Ikon",
                             skill_level="Intermediate")
        _add_equipment(p04, "K2", "Disruption 82")
        _add_guest(h_host1_trip, p04, GuestStatus.ACCEPTED)
        # Verify no owned upcoming trip was accidentally created
        db.session.commit()
        print("  ✓ P04 Guest trip only (View trip →)")

        # ─────────────────────────────────────────────────────────────────
        # P05 — Own trip + friend_trip secondary card
        # Trigger: friend (h_friend_trip) has a public upcoming trip.
        #          No open_dates → no nudge. No connect invite.
        # ─────────────────────────────────────────────────────────────────
        p05, _ = _make_user("Glen", "Friend", "p05.friendtrip@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Expert", open_dates=[])
        _add_equipment(p05, "Salomon", "Stance 96")
        _get_or_make_trip(p05, resort, 12, 15)
        _make_friends(p05, h_friend_trip)
        db.session.commit()
        print("  ✓ P05 Own trip + friend_trip secondary card")

        # ─────────────────────────────────────────────────────────────────
        # P06 — Own trip + overlap nudge secondary card (+ Best Match)
        # Trigger: open_dates JSON overlaps with h_opendate's open_dates JSON.
        #          availability_nudge fires → secondary_card='overlap'.
        #          UserAvailability rows also exist → Best Match co-fires.
        #          No connect invite.
        # ─────────────────────────────────────────────────────────────────
        p06, _ = _make_user("Hana", "Overlap", "p06.overlapnudge@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate")
        _add_equipment(p06, "Volkl", "Mantra M6")
        _get_or_make_trip(p06, resort, 8, 11)
        _add_open_dates(p06, [D1, D2])          # JSON + UA rows → nudge + Best Match
        _make_friends(p06, h_opendate)           # h_opendate has D1,D2 → overlap
        db.session.commit()
        print("  ✓ P06 Overlap nudge secondary card (Best Match co-fires)")

        # ─────────────────────────────────────────────────────────────────
        # P07 — Own trip + connect invite (highest-priority secondary card)
        # Trigger: pending Invitation(trip_id=None) from h_inv_sender.
        #          Also has overlap data + friend trip — connect invite overrides.
        # ─────────────────────────────────────────────────────────────────
        p07, _ = _make_user("Ivan", "Connect", "p07.connectinvite@test.com",
                             rider_types=["Skier"], pass_type="Ikon",
                             skill_level="Advanced")
        _add_equipment(p07, "Blizzard", "Brahma 88")
        _get_or_make_trip(p07, resort, 18, 21)
        _add_open_dates(p07, [D1, D2])           # overlap data present (overridden)
        _make_friends(p07, h_opendate)            # friend with open dates
        _make_friends(p07, h_friend_trip)         # friend with public trip
        _add_connect_invite(h_inv_sender, p07)    # THIS wins the priority race
        db.session.commit()
        print("  ✓ P07 Connect invite secondary card (overrides overlap + friend_trip)")

        # ─────────────────────────────────────────────────────────────────
        # P08 — Own trip + Best Match + friend_trip secondary card
        # Trick: UserAvailability rows ONLY (no open_dates JSON).
        #   → get_open_date_matches fires via UA table → has_overlaps=True ✓
        #   → availability_nudge: user.open_dates=[] → NO nudge ✓
        #   → secondary_card priority: no connect, no nudge → friend_trip ✓
        # ─────────────────────────────────────────────────────────────────
        p08, _ = _make_user("Jana", "Match", "p08.bestmatch@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate",
                             open_dates=[])          # keep [] so nudge stays silent
        _add_equipment(p08, "Dynastar", "Legend W88")
        _get_or_make_trip(p08, resort, 9, 12)
        _add_ua_only(p08, [D1, D2])               # UA rows only → Best Match
        _make_friends(p08, h_opendate)             # h_opendate has UA rows for D1,D2
        _make_friends(p08, h_friend_trip)          # friend_trip fills secondary card
        db.session.commit()
        print("  ✓ P08 Best Match + friend_trip secondary card")

        # ─────────────────────────────────────────────────────────────────
        # P09 — Own trip + banner only (no friends, no secondary card)
        # Trigger: INVITED on h_host2_trip (banner). friend_count=0.
        # ─────────────────────────────────────────────────────────────────
        p09, _ = _make_user("Lena", "Banner", "p09.tripbanner@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate")
        _add_equipment(p09, "Fischer", "RC4 Worldcup SC")
        _get_or_make_trip(p09, resort, 20, 23)
        _add_guest(h_host2_trip, p09, GuestStatus.INVITED)
        db.session.commit()
        print("  ✓ P09 Own trip + banner (no friends, no secondary card)")

        # ─────────────────────────────────────────────────────────────────
        # P10 — Own trip + banner + Best Match (no secondary card)
        # UA rows only → Best Match fires. h_opendate has no public trip
        # → no friend_trip secondary. No connect invite. No nudge (open_dates=[]).
        # ─────────────────────────────────────────────────────────────────
        p10, _ = _make_user("Max", "BannerMatch", "p10.bannermatch@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Advanced",
                             open_dates=[])          # no nudge
        _add_equipment(p10, "Elan", "Ripstick 96")
        _get_or_make_trip(p10, resort, 7, 10)
        _add_ua_only(p10, [D2, D3])               # UA only → Best Match
        _make_friends(p10, h_opendate)             # h_opendate has UA on D1,D2 → D2 overlaps
        _add_guest(h_host2_trip, p10, GuestStatus.INVITED)   # banner
        db.session.commit()
        print("  ✓ P10 Own trip + banner + Best Match (no secondary card)")

        # ─────────────────────────────────────────────────────────────────
        # P11 — Populated, no equipment → "Complete your profile"
        # Trigger: no EquipmentSetup record for this user.
        # ─────────────────────────────────────────────────────────────────
        p11, _ = _make_user("Nina", "NoGear", "p11.noequipment@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate")
        # Deliberately NO _add_equipment call
        _get_or_make_trip(p11, resort, 14, 17)
        db.session.commit()
        print("  ✓ P11 Populated, no equipment (Complete your profile)")

        # ─────────────────────────────────────────────────────────────────
        # P12 — Populated, minimal identity (Social-only, no skill_level)
        # Social-only passes is_core_profile_complete with just pass_type.
        # Identity line renders only rider type + pass — no skill.
        # ─────────────────────────────────────────────────────────────────
        p12, _ = _make_user("Owen", "NoId", "p12.noidentity@test.com",
                             rider_types=["Social"],   # Social-only, skill not required
                             pass_type="Ikon",
                             skill_level=None,         # omitted
                             open_dates=[])
        # No equipment either → "Complete your profile"
        _get_or_make_trip(p12, resort, 16, 19)
        db.session.commit()
        print("  ✓ P12 Minimal identity (Social-only, no skill, no equipment)")

        # ─────────────────────────────────────────────────────────────────
        # P13 — Multiple pending trip invites → banner shows "+N more"
        # INVITED on h_host1_trip (day 15) and h_host2_trip (day 25).
        # banner shows first (soonest) + "+1 more invite".
        # Also owns a trip so populated state shows.
        # ─────────────────────────────────────────────────────────────────
        p13, _ = _make_user("Pam", "Multi", "p13.multiinvite@test.com",
                             rider_types=["Skier"], pass_type="Ikon",
                             skill_level="Expert")
        _add_equipment(p13, "Rossignol", "Black Ops 98")
        _get_or_make_trip(p13, resort, 22, 25)
        _add_guest(h_host1_trip, p13, GuestStatus.INVITED)
        _add_guest(h_host2_trip, p13, GuestStatus.INVITED)
        db.session.commit()
        print("  ✓ P13 Multiple trip invites (banner + '+1 more')")

        # ─────────────────────────────────────────────────────────────────
        # P14 — Multiple overlap windows, ranking test for Best Match
        # Three friends, each overlapping on different date windows:
        #   h_opendate  → D1, D2
        #   h_opendate2 → D2, D3   (D2 shared with h_opendate → two-friend window)
        #   h_opendate3 → D3, D4
        # Expected: Best Match shows the highest-ranked window (likely D2 = two friends).
        # ─────────────────────────────────────────────────────────────────
        p14, _ = _make_user("Quinn", "Overlap", "p14.multioverlap@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Intermediate",
                             open_dates=[])           # no nudge
        _add_equipment(p14, "Atomic", "Vantage 90")
        _get_or_make_trip(p14, resort, 6, 9)
        _add_ua_only(p14, [D1, D2, D3, D4])          # UA only
        _make_friends(p14, h_opendate)                # overlaps D1, D2
        _make_friends(p14, h_opendate2)               # overlaps D2, D3
        _make_friends(p14, h_opendate3)               # overlaps D3, D4
        db.session.commit()
        print("  ✓ P14 Multiple overlap windows (ranking test)")

        # ─────────────────────────────────────────────────────────────────
        # P15 — Both owned + accepted guest trip; guest trip is sooner
        # Owned trip starts day 30. Guest trip (h_host1_trip) starts day 15.
        # next_trip = h_host1_trip → action "View trip →"
        # ─────────────────────────────────────────────────────────────────
        p15, _ = _make_user("Rex", "Both", "p15.bothtrips@test.com",
                             rider_types=["Skier"], pass_type="Epic",
                             skill_level="Advanced")
        _add_equipment(p15, "Salomon", "QST 98")
        # Owned trip must start AFTER h_host1_trip (day 15)
        if not (SkiTrip.query
                .filter_by(user_id=p15.id)
                .filter(SkiTrip.end_date >= TODAY)
                .first()):
            _make_trip(p15, resort, 30, 33)           # own trip — starts later
        _add_guest(h_host1_trip, p15, GuestStatus.ACCEPTED)   # guest trip starts day 15
        db.session.commit()
        print("  ✓ P15 Owned + guest trips (guest trip sooner → Next Up = View trip →)")

        # ─────────────────────────────────────────────────────────────────
        # P16 — Open dates + friends but zero overlaps → no nudge, no Best Match
        # h_opendate has D1, D2. P16 has D3, D4. No intersection.
        # friend_trip secondary card shows instead (h_friend_trip has public trip).
        # ─────────────────────────────────────────────────────────────────
        p16, _ = _make_user("Sage", "Nooverlap", "p16.nooverlap@test.com",
                             rider_types=["Skier"], pass_type="Ikon",
                             skill_level="Advanced")
        _add_equipment(p16, "Line", "Sick Day 94")
        _get_or_make_trip(p16, resort, 13, 16)
        _add_open_dates(p16, [D3, D4])               # no overlap with h_opendate (D1,D2)
        _make_friends(p16, h_opendate)                # friend exists but dates don't match
        _make_friends(p16, h_friend_trip)             # friend with public trip → secondary
        db.session.commit()
        print("  ✓ P16 Open dates + friends but no overlap → friend_trip secondary")

        # ─────────────────────────────────────────────────────────────────
        db.session.commit()

        print()
        print("=" * 70)
        print("HOME PERMUTATION SEED COMPLETE")
        print(f"Password for all users: {PASSWORD}")
        print("=" * 70)
        print()

        rows = [
            ("P01", "p01.emptyonly@test.com",        "Clay Empty",       "Empty state only"),
            ("P02", "p02.emptybanner@test.com",       "Blair Empty",      "Empty state + banner invite"),
            ("P03", "p03.owntripnofriends@test.com",  "Dale Own",         "Own trip + no friends (Bring Your Crew)"),
            ("P04", "p04.guesttrip@test.com",         "Faye Guest",       "Guest trip only → 'View trip →'"),
            ("P05", "p05.friendtrip@test.com",        "Glen Friend",      "Own trip + friend_trip secondary card"),
            ("P06", "p06.overlapnudge@test.com",      "Hana Overlap",     "Own trip + overlap nudge secondary (+ Best Match co-fires)"),
            ("P07", "p07.connectinvite@test.com",     "Ivan Connect",     "Own trip + connect invite (overrides overlap + friend_trip)"),
            ("P08", "p08.bestmatch@test.com",         "Jana Match",       "Own trip + Best Match + friend_trip secondary card"),
            ("P09", "p09.tripbanner@test.com",        "Lena Banner",      "Own trip + banner only (no friends, no secondary)"),
            ("P10", "p10.bannermatch@test.com",       "Max BannerMatch",  "Own trip + banner + Best Match (no secondary card)"),
            ("P11", "p11.noequipment@test.com",       "Nina NoGear",      "Populated, no equipment → 'Complete your profile'"),
            ("P12", "p12.noidentity@test.com",        "Owen NoId",        "Populated, minimal identity (Social, no skill, no gear)"),
            ("P13", "p13.multiinvite@test.com",       "Pam Multi",        "Own trip + multiple invites → banner '+1 more'"),
            ("P14", "p14.multioverlap@test.com",      "Quinn Overlap",    "Own trip + 3 friends, multiple overlap windows (ranking)"),
            ("P15", "p15.bothtrips@test.com",         "Rex Both",         "Owned trip (day 30) + guest trip (day 15) → guest is Next Up"),
            ("P16", "p16.nooverlap@test.com",         "Sage Nooverlap",   "Open dates + friends but zero date overlap → friend_trip secondary"),
        ]

        fmt = "  {:<4}  {:<38}  {:<18}  {}"
        print(fmt.format("ID", "Email", "Name", "Scenario"))
        print("  " + "-" * 100)
        for code, email, name, scenario in rows:
            print(fmt.format(code, email, name, scenario))

        print()
        print("  Helpers (not for login — supporting actors):")
        helpers = [
            ("helper.triphost1@test.com",  "Sam Host",    "Owns trips that P02/P04/P13/P15 join"),
            ("helper.triphost2@test.com",  "Tara Host",   "Owns trips that P09/P10/P13 get invited to"),
            ("helper.friendtrip@test.com", "Uma Slope",   "Public trip — P05/P07/P08/P16 see it as friend activity"),
            ("helper.opendate1@test.com",  "Vera Dates",  "Open dates D1,D2 — drives nudge/Best Match for P06/P07/P08/P10/P14"),
            ("helper.opendate2@test.com",  "Will Dates",  "Open dates D2,D3 — second overlap window for P14"),
            ("helper.opendate3@test.com",  "Xena Dates",  "Open dates D3,D4 — third overlap window for P14"),
            ("helper.invsender@test.com",  "Yuri Connect","Sends connection invite to P07"),
        ]
        for email, name, note in helpers:
            print(f"    {name:<18}  {email:<35}  {note}")
        print()


if __name__ == "__main__":
    seed_home_permutations()
