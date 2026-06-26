#!/usr/bin/env python3
"""
Cross-account invite safety tests — verifying all changes from the P0 investigation.

Tests:
  A. Authenticated wrong-user invite landing shows blocking identity card
  B. Sign-out link leads back to invite page; different user can then accept
  C. Logout clears all transient invite/session keys
  D. Invite confirm logging does not crash for auth and unauth requests
  E. Existing happy path still works (logged-out → login → accept)
  F. Trip invite landing shows identity card for authenticated user

Run: python3 tests/test_invite_cross_account.py
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
from models import User, Friend, InviteToken, SkiTrip, TripInviteToken, GuestStatus

SUFFIX = uuid.uuid4().hex[:8]
_created_user_ids   = []
_created_token_strs = []
RESULTS = []


# ─── result helpers ──────────────────────────────────────────────────────────

def ok(name, notes=""):
    RESULTS.append({"name": name, "passed": True,  "notes": notes})
    print(f"  ✓  {name}" + (f"  [{notes}]" if notes else ""))

def fail(name, notes=""):
    RESULTS.append({"name": name, "passed": False, "notes": notes})
    print(f"  ✗  {name}" + (f"  [{notes}]" if notes else ""))

def check(cond, name_pass, name_fail=None, notes=""):
    if cond:
        ok(name_pass, notes)
    else:
        fail(name_fail or name_pass, notes)


# ─── DB / auth helpers ────────────────────────────────────────────────────────

def make_user(tag, password="Test1234!", complete=True):
    u = User(
        email=f"test_{SUFFIX}_{tag}@bl-test.invalid",
        first_name=f"T{tag[:4].title()}",
        last_name="Tester",
        created_at=datetime.utcnow(),
    )
    u.password_hash = generate_password_hash(password)
    u.lifecycle_stage = "active"
    u.is_seeded = True
    if complete:
        u.rider_types = ["Skier"]
        u.pass_type   = "ikon"
        u.skill_level = "intermediate"
        u.home_state  = "CO"
    db.session.add(u)
    db.session.flush()
    _created_user_ids.append(u.id)
    return u


def make_invite_token(inviter):
    import secrets
    tok = InviteToken(
        token=secrets.token_urlsafe(16),
        inviter_id=inviter.id,
        expires_at=None,
    )
    db.session.add(tok)
    db.session.flush()
    _created_token_strs.append(tok.token)
    return tok


def make_trip(owner):
    from datetime import date, timedelta as td
    t = SkiTrip(
        user_id=owner.id,
        mountain="Test Mountain",
        start_date=date.today() + td(days=30),
        end_date=date.today() + td(days=32),
        is_public=False,
    )
    db.session.add(t)
    db.session.flush()
    return t


def make_trip_invite_token(trip, inviter):
    import secrets
    tok = TripInviteToken(
        token=secrets.token_urlsafe(32),
        trip_id=trip.id,
        inviter_user_id=inviter.id,
    )
    db.session.add(tok)
    db.session.flush()
    return tok


def login(client, tag, password="Test1234!"):
    return client.post("/auth", data={
        "form_type": "login",
        "email": f"test_{SUFFIX}_{tag}@bl-test.invalid",
        "password": password,
    }, follow_redirects=False)


def sess_get(client, key):
    with client.session_transaction() as s:
        return s.get(key)

def sess_set(client, **kwargs):
    with client.session_transaction() as s:
        for k, v in kwargs.items():
            s[k] = v

def sess_snapshot(client):
    with client.session_transaction() as s:
        return dict(s)

def sess_csrf(client):
    with client.session_transaction() as s:
        if "_csrf_token" not in s:
            s["_csrf_token"] = uuid.uuid4().hex
        return s["_csrf_token"]

def invite_confirm(client, token_str):
    csrf = sess_csrf(client)
    return client.post(f"/invite/{token_str}/confirm",
        data={"csrf_token": csrf}, follow_redirects=False)

def are_friends(uid_a, uid_b):
    db.session.expire_all()
    f1 = Friend.query.filter_by(user_id=uid_a, friend_id=uid_b).first()
    f2 = Friend.query.filter_by(user_id=uid_b, friend_id=uid_a).first()
    return bool(f1 and f2)

def body(r):
    return r.data.decode("utf-8", errors="replace")


# ═════════════════════════════════════════════════════════════════════════════
# TEST A — Authenticated wrong-user invite landing shows blocking identity card
# ═════════════════════════════════════════════════════════════════════════════

def test_a():
    print("\n─── A: Authenticated landing shows blocking identity card ────────")
    with app.test_client() as c:
        with app.app_context():
            danielle = make_user("a_dan")
            isaac    = make_user("a_isa")
            tok = make_invite_token(danielle)
            dan_id, isa_id = danielle.id, isaac.id
            tok_str = tok.token
            db.session.commit()

        login(c, "a_isa")
        r = c.get(f"/invite/{tok_str}")
        b = body(r)

        check(r.status_code == 200,
              "A.1  GET /invite/<token> (auth) → 200")

        check("il-identity-card" in b,
              "A.2  blocking identity card element present",
              notes="il-identity-card not found in HTML")

        check("You are signed in as" in b,
              "A.3  'You are signed in as' text present")

        with app.app_context():
            _isaac = db.session.get(User, isa_id)
            _isaac_name = _isaac.first_name if _isaac else ""
        check(_isaac_name and _isaac_name in b,
              "A.4  current user's name appears in the identity card",
              notes=f"looking for '{_isaac_name}'")

        check("Continue as" in b,
              "A.5  primary button says 'Continue as ...'",
              notes="'Continue as' not in HTML")

        # The headline "Connect with [inviter]?" is acceptable; the SUBMIT BUTTON
        # must say "Continue as [Name]", not "Connect with [inviter]".
        check('type="submit"' not in b.split("Connect with")[0]
              if "Connect with" in b else True,
              "A.6  submit button does NOT say 'Connect with'",
              notes="verified: 'Connect with' only in headline, not button")
        # More direct: button must say "Continue as"
        import re as _re
        _btn_match = _re.search(r'<button[^>]*type=["\']submit["\'][^>]*>(.*?)</button>',
                                b, _re.DOTALL)
        _btn_text = _btn_match.group(1).strip() if _btn_match else ""
        check("Continue as" in _btn_text,
              "A.6b submit button text contains 'Continue as'",
              notes=f"button text: '{_btn_text[:60]}'")

        check("Sign out and use another account" in b,
              "A.7  sign-out option present")

        check("return_to" in b or "logout" in b,
              "A.8  sign-out link goes through /logout")


# ═════════════════════════════════════════════════════════════════════════════
# TEST B — Sign out → different user logs in → accepts as correct identity
# ═════════════════════════════════════════════════════════════════════════════

def test_b():
    print("\n─── B: Sign-out → switch account → correct friendship created ────")
    with app.test_client() as c:
        with app.app_context():
            danielle = make_user("b_dan")
            isaac    = make_user("b_isa")
            enid     = make_user("b_eni")
            tok = make_invite_token(danielle)
            dan_id, isa_id, eni_id = danielle.id, isaac.id, enid.id
            tok_str = tok.token
            db.session.commit()

        # Isaac logs in and opens Danielle's invite
        login(c, "b_isa")
        r = c.get(f"/invite/{tok_str}")
        check(r.status_code == 200, "B.1  Isaac sees the invite landing")

        b_html = body(r)
        check("Continue as" in b_html, "B.2  page shows 'Continue as' for Isaac")

        # Isaac "signs out" → /logout → check it redirects to invite page or auth
        r_logout = c.get(f"/logout?return_to=/invite/{tok_str}",
                         follow_redirects=False)
        loc = r_logout.headers.get("Location", "")
        check(r_logout.status_code == 302,
              "B.3  logout redirects (302)")
        check(f"/invite/{tok_str}" in loc or "/auth" in loc,
              "B.4  logout sends to invite page or auth",
              notes=f"Location: {loc}")

        # After logout, Isaac's session should be gone
        check(not sess_get(c, "_user_id"),
              "B.5  _user_id not in session after logout")

        # Transient session keys should also be cleared
        snap = sess_snapshot(c)
        for key in ("invite_token", "post_login_redirect",
                    "post_onboarding_redirect", "trip_invite_token"):
            check(key not in snap,
                  f"B.6  '{key}' cleared on logout",
                  notes=f"'{key}' still in session: {snap.get(key)}")

        # Enid now logs in on the same client (same browser session after Isaac's logout)
        login(c, "b_eni")

        # Enid opens the invite link directly (simulating re-opening the URL)
        r_get = c.get(f"/invite/{tok_str}")
        b_enid = body(r_get)
        check(r_get.status_code == 200, "B.7  Enid sees invite landing (200)")

        check("Continue as" in b_enid,
              "B.8  invite landing shows 'Continue as' for Enid")

        with app.app_context():
            _enid = db.session.get(User, eni_id)
            _enid_name = _enid.first_name if _enid else ""
            _isaac2 = db.session.get(User, isa_id)
            _isaac_name2 = _isaac2.first_name if _isaac2 else ""
        check(_enid_name and _enid_name in b_enid,
              "B.9  invite landing names Enid (not Isaac)",
              notes=f"looking for Enid='{_enid_name}', Isaac='{_isaac_name2}'")

        # Enid accepts
        r_confirm = invite_confirm(c, tok_str)
        b_confirm = body(r_confirm)
        check(r_confirm.status_code == 200, "B.10 Enid's confirm → 200")
        check("connected" in b_confirm.lower() or "invite_accepted" in b_confirm,
              "B.11 shows accepted screen")

        with app.app_context():
            check(are_friends(dan_id, eni_id),
                  "B.12 Danielle ↔ Enid friendship created")
            check(not are_friends(dan_id, isa_id),
                  "B.13 Danielle ↔ Isaac friendship NOT created")


# ═════════════════════════════════════════════════════════════════════════════
# TEST C — Logout clears all transient invite/session keys
# ═════════════════════════════════════════════════════════════════════════════

def test_c():
    print("\n─── C: Logout clears transient session keys ──────────────────────")
    with app.test_client() as c:
        with app.app_context():
            u = make_user("c_usr")
            db.session.commit()

        login(c, "c_usr")

        transient_keys = {
            "invite_token": "test-token-abc",
            "post_login_redirect": "/invite/test-token-abc",
            "post_onboarding_redirect": "/invite/test-token-abc",
            "trip_invite_token": "trip-test-token",
            "_auth_session_logged": True,
            "_last_active_stamp": 1234567890.0,
            "_bl_auth_method": "email",
        }
        sess_set(c, **transient_keys)

        snap_before = sess_snapshot(c)
        for k in transient_keys:
            check(k in snap_before,
                  f"C.pre  '{k}' present before logout",
                  notes=f"key not set correctly before test")

        c.get("/logout", follow_redirects=False)

        snap_after = sess_snapshot(c)
        for k in transient_keys:
            check(k not in snap_after,
                  f"C.{list(transient_keys.keys()).index(k)+1}  '{k}' cleared after logout",
                  notes=f"still present: {snap_after.get(k)}")

        # ph_reset should be set (non-transient value we want)
        check(snap_after.get("ph_reset") is True,
              "C.8  ph_reset set after logout")


# ═════════════════════════════════════════════════════════════════════════════
# TEST D — Invite confirm logging does not crash
# ═════════════════════════════════════════════════════════════════════════════

def test_d():
    print("\n─── D: Logging on invite routes does not crash ───────────────────")
    with app.test_client() as c:
        with app.app_context():
            inviter = make_user("d_inv")
            acceptor = make_user("d_acc")
            tok = make_invite_token(inviter)
            tok_str = tok.token
            db.session.commit()

        # Unauthenticated GET — should not crash
        try:
            r = c.get(f"/invite/{tok_str}")
            check(r.status_code == 200,
                  "D.1  GET /invite/<token> (unauth) does not crash")
        except Exception as e:
            fail("D.1  GET /invite/<token> (unauth) does not crash", notes=str(e))

        # Unauthenticated POST — should 302 to /auth, not crash
        try:
            r = invite_confirm(c, tok_str)
            check(r.status_code in (302, 200),
                  "D.2  POST /invite/<token>/confirm (unauth) does not crash",
                  notes=f"status={r.status_code}")
        except Exception as e:
            fail("D.2  POST /invite/<token>/confirm (unauth) does not crash", notes=str(e))

        # Authenticated GET
        try:
            login(c, "d_acc")
            r = c.get(f"/invite/{tok_str}")
            check(r.status_code == 200,
                  "D.3  GET /invite/<token> (auth) does not crash")
        except Exception as e:
            fail("D.3  GET /invite/<token> (auth) does not crash", notes=str(e))

        # Authenticated POST confirm — should create friendship without crashing
        try:
            r = invite_confirm(c, tok_str)
            check(r.status_code == 200,
                  "D.4  POST /invite/<token>/confirm (auth) does not crash",
                  notes=f"status={r.status_code}")
        except Exception as e:
            fail("D.4  POST /invite/<token>/confirm (auth) does not crash", notes=str(e))


# ═════════════════════════════════════════════════════════════════════════════
# TEST E — Existing happy path: logged-out user opens invite, logs in, accepts
# ═════════════════════════════════════════════════════════════════════════════

def test_e():
    print("\n─── E: Happy path — logged-out → login → accept ──────────────────")
    with app.test_client() as c:
        with app.app_context():
            inviter  = make_user("e_inv")
            acceptor = make_user("e_acc")
            tok = make_invite_token(inviter)
            inv_id, acc_id = inviter.id, acceptor.id
            tok_str = tok.token
            db.session.commit()

        # 1. GET landing as unauthenticated user
        r_get = c.get(f"/invite/{tok_str}")
        b_get = body(r_get)
        check(r_get.status_code == 200, "E.1  GET landing (unauth) → 200")
        check("Sign in to connect" in b_get,
              "E.2  unauthenticated landing shows 'Sign in to connect'")
        check("You are not signed in" in b_get,
              "E.3  unauthenticated landing shows 'You are not signed in'")

        # 2. POST confirm unauthenticated → stores context, redirects to /auth
        r_post_unauth = invite_confirm(c, tok_str)
        loc = r_post_unauth.headers.get("Location", "")
        check(r_post_unauth.status_code == 302 and "/auth" in loc,
              "E.4  unauth confirm → 302 /auth",
              notes=f"{r_post_unauth.status_code} {loc}")

        s = sess_snapshot(c)
        check(s.get("invite_token") == tok_str,
              "E.5  invite_token stored in session")
        check("post_login_redirect" in s,
              "E.6  post_login_redirect stored")

        # 3. Login as acceptor → follows post_login_redirect back to invite landing
        r_login = login(c, "e_acc")
        login_loc = r_login.headers.get("Location", "")
        check(r_login.status_code == 302,
              "E.7  login redirects")
        check(tok_str in login_loc or "/invite/" in login_loc,
              "E.8  login redirects back to invite landing",
              notes=f"Location: {login_loc}")

        # 4. GET the invite landing now (authenticated)
        r_auth_get = c.get(f"/invite/{tok_str}")
        b_auth = body(r_auth_get)
        check(r_auth_get.status_code == 200,
              "E.9  authenticated invite landing → 200")
        check("Continue as" in b_auth,
              "E.10 authenticated landing shows 'Continue as'")

        # 5. POST confirm authenticated → creates friendship
        r_confirm = invite_confirm(c, tok_str)
        b_confirm = body(r_confirm)
        check(r_confirm.status_code == 200,
              "E.11 authenticated confirm → 200")
        check("connected" in b_confirm.lower() or "invite_accepted" in b_confirm,
              "E.12 renders accepted screen")

        with app.app_context():
            check(are_friends(inv_id, acc_id),
                  "E.13 mutual Friend rows created after full flow")

        check(not sess_get(c, "invite_token"),
              "E.14 invite_token cleared from session after accept")


# ═════════════════════════════════════════════════════════════════════════════
# TEST F — Trip invite landing shows identity note for authenticated user
# ═════════════════════════════════════════════════════════════════════════════

def test_f():
    print("\n─── F: Trip invite landing shows identity note ───────────────────")
    with app.test_client() as c:
        with app.app_context():
            host    = make_user("f_hos")
            invitee = make_user("f_inv")
            trip = make_trip(host)
            tok  = make_trip_invite_token(trip, host)
            tok_str = tok.token
            trip_id = trip.id
            host_id = host.id
            inv_id  = invitee.id
            db.session.commit()

        login(c, "f_inv")
        r = c.get(f"/trip-invite/{tok_str}")
        b = body(r)

        check(r.status_code == 200,
              "F.1  GET /trip-invite/<token> (auth) → 200")

        check("ti-identity-note" in b,
              "F.2  trip identity note element present",
              notes="'ti-identity-note' not found in HTML")

        check("You are signed in as" in b,
              "F.3  'You are signed in as' text present")

        check("Accept as" in b,
              "F.4  accept button says 'Accept as ...'",
              notes="'Accept as' not found in HTML")

        check("Accept trip invite" not in b,
              "F.5  generic 'Accept trip invite' button NOT shown",
              notes="generic button still present")


# ═════════════════════════════════════════════════════════════════════════════
# cleanup
# ═════════════════════════════════════════════════════════════════════════════

def cleanup():
    with app.app_context():
        try:
            if _created_user_ids:
                from models import Friend, SkiTripParticipant
                Friend.query.filter(
                    Friend.user_id.in_(_created_user_ids) |
                    Friend.friend_id.in_(_created_user_ids)
                ).delete(synchronize_session=False)
                SkiTripParticipant.query.filter(
                    SkiTripParticipant.user_id.in_(_created_user_ids)
                ).delete(synchronize_session=False)
                # Remove TripInviteTokens and SkiTrips before deleting users
                # (FK: ski_trip.user_id → user.id)
                _trips = SkiTrip.query.filter(
                    SkiTrip.user_id.in_(_created_user_ids)
                ).all()
                _trip_ids = [t.id for t in _trips]
                if _trip_ids:
                    TripInviteToken.query.filter(
                        TripInviteToken.trip_id.in_(_trip_ids)
                    ).delete(synchronize_session=False)
                    SkiTrip.query.filter(
                        SkiTrip.id.in_(_trip_ids)
                    ).delete(synchronize_session=False)
                for ts in _created_token_strs:
                    InviteToken.query.filter_by(token=ts).delete()
                User.query.filter(User.id.in_(_created_user_ids)).delete(
                    synchronize_session=False)
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"  [cleanup error] {e}")


# ═════════════════════════════════════════════════════════════════════════════
# main
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 66)
    print("  Cross-account invite safety tests")
    print("=" * 66)

    with app.app_context():
        db.create_all()

    try:
        test_a()
        test_b()
        test_c()
        test_d()
        test_e()
        test_f()
    except Exception as e:
        print(f"\n[FATAL] Uncaught exception in test runner: {e}")
        traceback.print_exc()
    finally:
        cleanup()

    total  = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed

    print("\n" + "=" * 66)
    print(f"  Results: {passed}/{total} passed" +
          (f"  ✓" if failed == 0 else f"  ({failed} failed)"))
    if failed:
        print("\n  Failed tests:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"    ✗  {r['name']}" +
                      (f"  [{r['notes']}]" if r["notes"] else ""))
    print("=" * 66)

    sys.exit(0 if failed == 0 else 1)
