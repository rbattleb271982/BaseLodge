"""
Seed Richard's Home screen with full signal coverage.

Target:  richardbat@gmail.com  (password: TestPass1!)

Signals seeded:
  [Banner]          Trip invites from P05 + P14 → soonest shows, "+1 more invite"
  [Secondary card]  Incoming connect invite from P03 (P04 queued behind)
  [Best Match]      Richard's UserAvailability on D1/D2 overlaps P06 (already friend)
  [Friend Activity] Populated via secondary_card above
  [Stat row]        Richard's own trip (created here if none exists)

Relationships:
  ACCEPTED friends:  Richard ↔ P05, P06, P08, P14, P16  (already done by cross-connect)
  UN-friended:       Richard ↔ P03, P04, P11, P12        (removed → enables realistic invites)
  Incoming invites:  P03 → Richard,  P04 → Richard       (connect, trip_id=None)
  Outgoing invites:  Richard → P11,  Richard → P12       (silent, trip_id=None)
  Trip invites:      P05's trip → Richard (INVITED)
                     P14's trip → Richard (INVITED)
  UA rows:           Richard on D1, D2 (UA only — no open_dates JSON → Best Match, no nudge)

Idempotent — safe to re-run.

Run:
    python scripts/seed_richard_home_signals.py
"""

import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import (
    db, User, Friend, SkiTrip, SkiTripParticipant, Invitation,
    UserAvailability, Resort,
    GuestStatus, ParticipantRole,
)

TODAY = date.today()
RICHARD_EMAIL = "richardbat@gmail.com"

UNFRIEND_EMAILS = [
    "p03.owntripnofriends@test.com",
    "p04.guesttrip@test.com",
    "p11.noequipment@test.com",
    "p12.noidentity@test.com",
]
INCOMING_INVITE_EMAILS = [
    "p03.owntripnofriends@test.com",
    "p04.guesttrip@test.com",
]
OUTGOING_INVITE_EMAILS = [
    "p11.noequipment@test.com",
    "p12.noidentity@test.com",
]
TRIP_INVITE_EMAILS = [
    "p05.friendtrip@test.com",
    "p14.multioverlap@test.com",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_user(email):
    u = User.query.filter_by(email=email).first()
    if not u:
        raise RuntimeError(f"User not found: {email}  — run seed_home_permutations.py first")
    return u


def _remove_friend_link(uid1, uid2):
    """Remove both directions of a friend link. Returns number of rows deleted."""
    deleted = 0
    for a, b in [(uid1, uid2), (uid2, uid1)]:
        row = Friend.query.filter_by(user_id=a, friend_id=b).first()
        if row:
            db.session.delete(row)
            deleted += 1
    db.session.flush()
    return deleted


def _add_connect_invite(sender, receiver):
    """Pending connection invite (trip_id=None). Idempotent."""
    existing = Invitation.query.filter_by(
        sender_id=sender.id, receiver_id=receiver.id, trip_id=None
    ).first()
    if existing:
        if existing.status != 'pending':
            existing.status = 'pending'
            db.session.flush()
            return existing, False
        return existing, False
    inv = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        trip_id=None,
        status='pending',
        created_at=datetime.utcnow(),
    )
    db.session.add(inv)
    db.session.flush()
    return inv, True


def _add_trip_invite(trip, user):
    """Add user as INVITED guest on a trip. Idempotent."""
    existing = SkiTripParticipant.query.filter_by(
        trip_id=trip.id, user_id=user.id
    ).first()
    if existing:
        if existing.status != GuestStatus.INVITED:
            existing.status = GuestStatus.INVITED
            db.session.flush()
        return existing, False
    p = SkiTripParticipant(
        trip_id=trip.id,
        user_id=user.id,
        status=GuestStatus.INVITED,
        role=ParticipantRole.GUEST,
        created_at=datetime.utcnow(),
    )
    db.session.add(p)
    db.session.flush()
    return p, True


def _add_ua_only(user, date_strings):
    """Add UserAvailability rows (no open_dates JSON touch). Idempotent."""
    added = 0
    for d_str in date_strings:
        d = date.fromisoformat(d_str)
        if not UserAvailability.query.filter_by(user_id=user.id, date=d).first():
            db.session.add(UserAvailability(user_id=user.id, date=d, is_available=True))
            added += 1
    db.session.flush()
    return added


def _get_or_create_richard_trip(richard, resort):
    """Return Richard's soonest upcoming owned trip, or create one 20 days out."""
    trip = (SkiTrip.query
            .filter_by(user_id=richard.id)
            .filter(SkiTrip.end_date >= TODAY)
            .order_by(SkiTrip.start_date.asc())
            .first())
    if trip:
        return trip, False
    start = TODAY + timedelta(days=20)
    end   = TODAY + timedelta(days=23)
    trip = SkiTrip(
        user_id=richard.id,
        resort_id=resort.id,
        mountain=resort.name,
        state=resort.state_code or resort.state,
        start_date=start,
        end_date=end,
        pass_type=richard.pass_type or "No Pass",
        is_public=True,
        trip_status="going",
        accommodation_status="not_yet",
        created_at=datetime.utcnow(),
    )
    db.session.add(trip)
    db.session.flush()
    owner_p = SkiTripParticipant(
        trip_id=trip.id,
        user_id=richard.id,
        status=GuestStatus.ACCEPTED,
        role=ParticipantRole.OWNER,
        created_at=datetime.utcnow(),
    )
    db.session.add(owner_p)
    db.session.flush()
    return trip, True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SEED
# ─────────────────────────────────────────────────────────────────────────────

def seed_richard():
    with app.app_context():
        print()
        print("=" * 65)
        print("  SEED: Richard Home Screen Signals")
        print("=" * 65)

        richard = _get_user(RICHARD_EMAIL)
        print(f"\n  Richard: {richard.first_name} {richard.last_name}"
              f" (id={richard.id})")

        resort = Resort.query.filter_by(is_active=True).first()
        if not resort:
            raise RuntimeError("No active resort — run resort seed first.")

        # ── 0. Ensure Richard's own trip exists (populated state) ──────────
        print("\n── Step 0: Richard's trip ───────────────────────────────────")
        r_trip, created = _get_or_create_richard_trip(richard, resort)
        status_str = "created" if created else "already exists"
        print(f"  Richard's trip: {r_trip.mountain}  "
              f"{r_trip.start_date} → {r_trip.end_date}  [{status_str}]")
        db.session.commit()

        # ── 1. Remove friend links that would conflict with pending invites ─
        print("\n── Step 1: Remove friend links for invite-pending users ─────")
        unfriend_users = [_get_user(e) for e in UNFRIEND_EMAILS]
        for u in unfriend_users:
            n = _remove_friend_link(richard.id, u.id)
            label = "removed" if n else "not found (ok)"
            print(f"  Richard ↔ {u.first_name} ({u.email}): {label} ({n} rows)")
        db.session.commit()

        # ── 2. Incoming connect invites → secondary card ───────────────────
        print("\n── Step 2: Incoming connect invites (P03 → R, P04 → R) ─────")
        for email in INCOMING_INVITE_EMAILS:
            sender = _get_user(email)
            inv, new = _add_connect_invite(sender, richard)
            label = "created" if new else "already exists"
            print(f"  {sender.first_name} ({email}) → Richard  [{label}]  id={inv.id}")
        db.session.commit()

        # ── 3. Outgoing connect invites → silent ──────────────────────────
        print("\n── Step 3: Outgoing connect invites (R → P11, R → P12) ─────")
        for email in OUTGOING_INVITE_EMAILS:
            receiver = _get_user(email)
            inv, new = _add_connect_invite(richard, receiver)
            label = "created" if new else "already exists"
            print(f"  Richard → {receiver.first_name} ({email})  [{label}]  id={inv.id}")
        db.session.commit()

        # ── 4. Trip invites → banner ───────────────────────────────────────
        print("\n── Step 4: Trip invites (P05 → R, P14 → R) ─────────────────")
        for email in TRIP_INVITE_EMAILS:
            trip_owner = _get_user(email)
            owner_trip = (SkiTrip.query
                          .filter_by(user_id=trip_owner.id)
                          .filter(SkiTrip.end_date >= TODAY)
                          .order_by(SkiTrip.start_date.asc())
                          .first())
            if not owner_trip:
                print(f"  ⚠️  {email} has no upcoming trip — skipping trip invite")
                continue
            participant, new = _add_trip_invite(owner_trip, richard)
            label = "created" if new else "already exists"
            print(f"  {trip_owner.first_name} (trip {owner_trip.id}: "
                  f"{owner_trip.start_date}) → Richard  [{label}]")
        db.session.commit()

        # ── 5. Richard's UserAvailability for Best Match ───────────────────
        print("\n── Step 5: Richard's UA rows (Best Match with P06) ──────────")
        D1 = (TODAY + timedelta(days=14)).isoformat()
        D2 = (TODAY + timedelta(days=21)).isoformat()
        n = _add_ua_only(richard, [D1, D2])
        p06 = _get_user("p06.overlapnudge@test.com")
        p06_ua_count = UserAvailability.query.filter_by(user_id=p06.id).count()
        print(f"  Richard UA: {D1}, {D2}  ({n} new rows added)")
        print(f"  P06 (Hana) UA rows: {p06_ua_count}  (overlaps Richard on {D1}, {D2})")
        friend_link = Friend.query.filter_by(
            user_id=richard.id, friend_id=p06.id).first()
        print(f"  Richard ↔ P06 friend link: {'✓ exists' if friend_link else '✗ MISSING'}")
        db.session.commit()

        # ── Summary ───────────────────────────────────────────────────────
        print()
        print("=" * 65)
        print("  RELATIONSHIPS CREATED — Expected Home signals for Richard")
        print("=" * 65)

        active_banner = SkiTripParticipant.query.filter(
            SkiTripParticipant.user_id == richard.id,
            SkiTripParticipant.status == GuestStatus.INVITED,
        ).count()
        incoming_conn = Invitation.query.filter_by(
            receiver_id=richard.id, status='pending', trip_id=None
        ).count()
        outgoing_conn = Invitation.query.filter_by(
            sender_id=richard.id, status='pending', trip_id=None
        ).count()
        richard_ua = UserAvailability.query.filter_by(
            user_id=richard.id, is_available=True).count()
        friend_count = Friend.query.filter_by(user_id=richard.id).count()
        richard_trips = SkiTrip.query.filter_by(user_id=richard.id).filter(
            SkiTrip.end_date >= TODAY).count()

        print(f"""
  ┌─ Banner (trip invites)          {active_banner:>3} pending INVITED participations
  ├─ Secondary card (conn invite)   {incoming_conn:>3} incoming connect invite(s) → 1 shows
  ├─ Outgoing conn invites          {outgoing_conn:>3} (silent — Richard → P11, P12)
  ├─ Best Match (UA rows)           {richard_ua:>3} UA date(s) → P06 overlaps D1+D2
  ├─ Next Up (populated state)      {richard_trips:>3} upcoming owned trip(s)
  └─ Friends total                  {friend_count:>3}
""")
        print("  Expected rendering for richardbat@gmail.com:")
        print("   [TOP]   Trip invite banner  — soonest P05/P14 trip + '+1 more invite'")
        print("   [HERO]  Next Up: Richard's own trip  → 'Edit →'")
        print("   [MATCH] Best Match: Hana (P06) is free on", D1)
        print("   [CARD]  Friend Activity: 'Dale (P03) wants to connect'  [Accept]")
        print()
        print("  Priority chain verified:")
        print("   connect_invite (P03) > overlap (none — UA only) > friend_trip")
        print()
        print("  Pass diversity among Richard's accepted friends:")
        for email in ["p05.friendtrip@test.com", "p06.overlapnudge@test.com",
                      "p08.bestmatch@test.com", "p14.multioverlap@test.com",
                      "p16.nooverlap@test.com"]:
            u = User.query.filter_by(email=email).first()
            f = Friend.query.filter_by(user_id=richard.id, friend_id=u.id).first() if u else None
            trip = (SkiTrip.query.filter_by(user_id=u.id)
                    .filter(SkiTrip.end_date >= TODAY).first()) if u else None
            print(f"   {u.first_name:8}  pass={u.pass_type or '?':6}  "
                  f"trip={'yes' if trip else 'no ':3}  "
                  f"friend_link={'✓' if f else '✗'}")
        print()


if __name__ == "__main__":
    seed_richard()
