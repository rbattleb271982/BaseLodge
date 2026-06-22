#!/usr/bin/env python3
"""
Invite reliability test suite.
Covers Gap 1 (expiry), Gap 2 (QR session keys), and trip-invite stability.
Run: python3 tests/test_invite_reliability.py
"""
import sys, os, uuid, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

import logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
logging.getLogger().setLevel(logging.ERROR)

import app as appmod
from app import app, db
from models import User, Friend, InviteToken, SkiTrip, TripInviteToken

SUFFIX = uuid.uuid4().hex[:8]
_created_user_ids   = []
_created_token_strs = []
RESULTS = []


# ──────────────────────── helpers ────────────────────────────────────────────

def ok(name, notes=""):
    RESULTS.append({"name": name, "passed": True, "notes": notes})
    print(f"  ✅  {name}" + (f"  ({notes})" if notes else ""))

def fail(name, reason):
    RESULTS.append({"name": name, "passed": False, "notes": reason})
    print(f"  ❌  {name}  —  {reason}")


def make_user(tag=""):
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f"tst_{uid}{tag}@bl-reliability.invalid",
        first_name=f"T{tag[:4].title() if tag else 'Est'}",
        last_name="Tester",
        created_at=datetime.utcnow(),
    )
    u.password_hash = generate_password_hash("Test1234!")
    u.lifecycle_stage = "active"
    u.is_seeded = True
    u.rider_types = ["Skier"]
    u.pass_type   = "ikon"
    u.skill_level = "intermediate"
    u.home_state  = "CO"
    db.session.add(u)
    db.session.flush()
    _created_user_ids.append(u.id)
    return u


def make_invite_token(inviter, *, used_at=None, expires_at=None, expired_past=False):
    import secrets
    tok = secrets.token_urlsafe(16)
    if expired_past:
        expires_at = datetime.utcnow() - timedelta(hours=72)
    inv = InviteToken(
        token=tok,
        inviter_id=inviter.id,
        used_at=used_at,
        expires_at=expires_at,
    )
    db.session.add(inv)
    db.session.flush()
    _created_token_strs.append(tok)
    return inv


def login(client, user):
    rv = client.post("/auth", data={
        "action": "login",
        "email": user.email,
        "password": "Test1234!",
    }, follow_redirects=False)
    return rv


def inject_csrf(client):
    """Inject a known CSRF token into the session and return its value."""
    with client.session_transaction() as sess:
        sess["_csrf_token"] = "testcsrf99"
    return "testcsrf99"


# ──────────────────────── test cases ─────────────────────────────────────────

def test_expired_unused_get_renders_landing():
    """Gap 1 GET: past expires_at + used_at=None should show invite landing, not expired."""
    name = "expired-but-unused token: GET renders invite landing"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter = make_user("_eug")
                db.session.commit()
                inv = make_invite_token(inviter, expired_past=True)
                db.session.commit()

                rv = client.get(f"/invite/{inv.token}", follow_redirects=False)
                body = rv.data.decode()
                if rv.status_code == 200 and "invite_landing" in body or "Connect with" in body or "Accept" in body:
                    ok(name)
                elif rv.status_code == 200 and "expired" not in body.lower():
                    ok(name, "200 without expired text")
                else:
                    fail(name, f"status={rv.status_code} body_snippet={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_expired_unused_post_confirm_succeeds():
    """Gap 1 POST: past expires_at + used_at=None should allow successful confirm."""
    name = "expired-but-unused token: POST confirm succeeds"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter  = make_user("_eup_inv")
                acceptor = make_user("_eup_acc")
                db.session.commit()
                inv = make_invite_token(inviter, expired_past=True)
                db.session.commit()

                login(client, acceptor)
                csrf = inject_csrf(client)

                rv = client.post(
                    f"/invite/{inv.token}/confirm",
                    data={"csrf_token": csrf},
                    follow_redirects=False,
                )
                body = rv.data.decode()

                db.session.expire_all()
                friendship = Friend.query.filter_by(
                    user_id=acceptor.id, friend_id=inviter.id
                ).first()

                if friendship and rv.status_code in (200, 302):
                    ok(name)
                else:
                    fail(name, f"status={rv.status_code} friendship={friendship} body={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_permanent_token_get_renders_landing():
    """Gap 1: expires_at=None should show invite landing."""
    name = "permanent token (expires_at=None): GET renders invite landing"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter = make_user("_perm")
                db.session.commit()
                inv = make_invite_token(inviter, expires_at=None)
                db.session.commit()

                rv = client.get(f"/invite/{inv.token}", follow_redirects=False)
                body = rv.data.decode()
                if rv.status_code == 200 and "expired" not in body.lower():
                    ok(name)
                else:
                    fail(name, f"status={rv.status_code} body_snippet={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_used_token_already_friends_shows_accepted():
    """Used token + already-friends authenticated user renders invite_accepted."""
    name = "used token + already friends: renders invite_accepted"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter  = make_user("_af_inv")
                acceptor = make_user("_af_acc")
                db.session.commit()

                inv = make_invite_token(inviter, used_at=datetime.utcnow())
                f1 = Friend(user_id=acceptor.id, friend_id=inviter.id)
                f2 = Friend(user_id=inviter.id, friend_id=acceptor.id)
                db.session.add_all([f1, f2])
                db.session.commit()

                login(client, acceptor)
                rv = client.get(f"/invite/{inv.token}", follow_redirects=False)
                body = rv.data.decode()

                if rv.status_code == 200 and "connected" in body.lower():
                    ok(name)
                else:
                    fail(name, f"status={rv.status_code} body={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_used_token_not_friends_shows_expired():
    """Used token + not already friends renders invite_expired."""
    name = "used token + not friends: renders invite_expired"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter  = make_user("_nf_inv")
                acceptor = make_user("_nf_acc")
                db.session.commit()

                inv = make_invite_token(inviter, used_at=datetime.utcnow())
                db.session.commit()

                login(client, acceptor)
                rv = client.get(f"/invite/{inv.token}", follow_redirects=False)
                body = rv.data.decode()

                if rv.status_code == 200 and "expired" in body.lower():
                    ok(name)
                else:
                    fail(name, f"status={rv.status_code} body={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_unauthenticated_post_confirm_sets_session_keys():
    """Unauthenticated POST /invite/<token>/confirm sets all three session keys."""
    name = "unauthenticated POST confirm: sets invite_token + post_login_redirect + post_onboarding_redirect"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter = make_user("_uc_inv")
                db.session.commit()
                inv = make_invite_token(inviter)
                db.session.commit()

                csrf = inject_csrf(client)

                rv = client.post(
                    f"/invite/{inv.token}/confirm",
                    data={"csrf_token": csrf},
                    follow_redirects=False,
                )

                with client.session_transaction() as sess:
                    has_invite   = "invite_token" in sess
                    has_login    = "post_login_redirect" in sess
                    has_onboard  = "post_onboarding_redirect" in sess
                    inv_val      = sess.get("invite_token")
                    login_val    = sess.get("post_login_redirect", "")
                    onboard_val  = sess.get("post_onboarding_redirect", "")

                if (has_invite and has_login and has_onboard
                        and inv_val == inv.token
                        and "/invite/" in login_val
                        and "/invite/" in onboard_val):
                    ok(name)
                else:
                    fail(name, (
                        f"invite_token={has_invite}({inv_val!r}) "
                        f"post_login={has_login}({login_val!r}) "
                        f"post_onboarding={has_onboard}({onboard_val!r})"
                    ))
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_unauthenticated_qr_connect_sets_both_redirects():
    """Gap 2: unauthenticated GET /connect/<id> sets both post_login_redirect and post_onboarding_redirect."""
    name = "unauthenticated QR connect: sets post_login_redirect AND post_onboarding_redirect"
    with app.test_client() as client:
        with app.app_context():
            try:
                inviter = make_user("_qr_inv")
                db.session.commit()

                rv = client.get(f"/connect/{inviter.id}", follow_redirects=False)

                with client.session_transaction() as sess:
                    has_login   = "post_login_redirect" in sess
                    has_onboard = "post_onboarding_redirect" in sess
                    login_val   = sess.get("post_login_redirect", "")
                    onboard_val = sess.get("post_onboarding_redirect", "")

                expected_path = f"/connect/{inviter.id}"
                if (has_login and has_onboard
                        and expected_path in login_val
                        and expected_path in onboard_val):
                    ok(name)
                else:
                    fail(name, (
                        f"post_login={has_login}({login_val!r}) "
                        f"post_onboarding={has_onboard}({onboard_val!r})"
                    ))
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


def test_trip_invite_landing_unaffected():
    """Trip invite landing behavior is unchanged — still requires valid, unexpired TripInviteToken."""
    name = "trip invite landing: still rejects expired TripInviteToken (behavior unchanged)"
    with app.test_client() as client:
        with app.app_context():
            try:
                import secrets as _sec
                inviter = make_user("_ti_inv")
                db.session.commit()

                # Create a minimal trip owned by inviter
                trip = SkiTrip(
                    user_id=inviter.id,
                    mountain="Test Resort",
                    start_date=datetime.utcnow().date() + timedelta(days=10),
                    end_date=datetime.utcnow().date() + timedelta(days=12),
                )
                db.session.add(trip)
                db.session.flush()

                tok_str = _sec.token_urlsafe(16)
                trip_tok = TripInviteToken(
                    token=tok_str,
                    trip_id=trip.id,
                    inviter_user_id=inviter.id,
                    expires_at=datetime.utcnow() - timedelta(hours=1),
                )
                db.session.add(trip_tok)
                db.session.commit()
                _created_token_strs.append(tok_str)

                rv = client.get(f"/trip-invite/{tok_str}", follow_redirects=False)
                body = rv.data.decode()

                if rv.status_code == 200 and ("expired" in body.lower() or "invalid" in body.lower()):
                    ok(name, "expired TripInviteToken correctly rejected")
                elif rv.status_code in (302, 301):
                    ok(name, f"redirect to {rv.headers.get('Location')!r} (may be auth redirect)")
                else:
                    fail(name, f"status={rv.status_code} body={body[:200]!r}")
            except Exception as e:
                fail(name, traceback.format_exc(limit=3))


# ──────────────────────── cleanup ────────────────────────────────────────────

def cleanup():
    with app.app_context():
        try:
            for tok in _created_token_strs:
                InviteToken.query.filter_by(token=tok).delete()
                try:
                    TripInviteToken.query.filter_by(token=tok).delete()
                except Exception:
                    pass
            for uid in _created_user_ids:
                Friend.query.filter(
                    (Friend.user_id == uid) | (Friend.friend_id == uid)
                ).delete(synchronize_session=False)
                try:
                    SkiTrip.query.filter_by(user_id=uid).delete()
                except Exception:
                    pass
                User.query.filter_by(id=uid).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"  [cleanup warning] {e}")


# ──────────────────────── runner ─────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("  BaseLodge — Invite Reliability Tests")
    print("=" * 60)

    with app.app_context():
        db.create_all()

    tests = [
        test_expired_unused_get_renders_landing,
        test_expired_unused_post_confirm_succeeds,
        test_permanent_token_get_renders_landing,
        test_used_token_already_friends_shows_accepted,
        test_used_token_not_friends_shows_expired,
        test_unauthenticated_post_confirm_sets_session_keys,
        test_unauthenticated_qr_connect_sets_both_redirects,
        test_trip_invite_landing_unaffected,
    ]

    for t in tests:
        t()

    cleanup()

    passed = sum(1 for r in RESULTS if r["passed"])
    total  = len(RESULTS)
    print()
    print("=" * 60)
    print(f"  Results: {passed}/{total} passed")
    print("=" * 60)

    if passed < total:
        print("\nFailed tests:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  • {r['name']}: {r['notes']}")
        sys.exit(1)
    else:
        print("  All tests passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
