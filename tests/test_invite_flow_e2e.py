#!/usr/bin/env python3
"""
End-to-end invite flow test suite.
Tests all acceptance paths using real DB, real sessions, real HTTP via Flask test client.
Run: python3 tests/test_invite_flow_e2e.py
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
from models import User, Friend, InviteToken

SUFFIX = uuid.uuid4().hex[:8]
_created_user_ids  = []
_created_token_strs = []
RESULTS = []


# ──────────────────────── Test-result helpers ─────────────────────────────────

def ok(name, notes=""):
    RESULTS.append({"name": name, "passed": True, "notes": notes})
    print(f"  ✓  {name}" + (f"  [{notes}]" if notes else ""))

def fail(name, notes=""):
    RESULTS.append({"name": name, "passed": False, "notes": notes})
    print(f"  ✗  {name}" + (f"  [{notes}]" if notes else ""))

def check(cond, name_pass, name_fail=None, notes=""):
    if cond:
        ok(name_pass, notes)
    else:
        fail(name_fail or name_pass, notes)


# ──────────────────────── DB / auth helpers ───────────────────────────────────

def make_user(tag, password="Test1234!", complete=True):
    """Create a test user directly in the DB (within an active app_context)."""
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


def make_token(inviter):
    """Create a fresh 48-hour invite token."""
    tok = InviteToken(
        token=uuid.uuid4().hex,
        inviter_id=inviter.id,
        expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    db.session.add(tok)
    db.session.flush()
    _created_token_strs.append(tok.token)
    return tok


def add_friend_rows(uid_a, uid_b):
    db.session.add(Friend(user_id=uid_a, friend_id=uid_b, created_at=datetime.utcnow()))
    db.session.add(Friend(user_id=uid_b, friend_id=uid_a, created_at=datetime.utcnow()))


def are_friends(uid_a, uid_b):
    db.session.expire_all()
    f1 = Friend.query.filter_by(user_id=uid_a, friend_id=uid_b).first()
    f2 = Friend.query.filter_by(user_id=uid_b, friend_id=uid_a).first()
    return bool(f1 and f2)


def friend_row_count(uid_a, uid_b):
    db.session.expire_all()
    c1 = Friend.query.filter_by(user_id=uid_a, friend_id=uid_b).count()
    c2 = Friend.query.filter_by(user_id=uid_b, friend_id=uid_a).count()
    return c1, c2


def token_used(tok_str):
    db.session.expire_all()
    t = InviteToken.query.filter_by(token=tok_str).first()
    return t and t.is_used()


# ──────────────────────── Session helpers ─────────────────────────────────────

def sess_get(client, key):
    with client.session_transaction() as s:
        return s.get(key)

def sess_snapshot(client):
    with client.session_transaction() as s:
        return dict(s)

def sess_csrf(client):
    """Return CSRF token from session, injecting one if absent.

    Injecting directly is equivalent to a page render calling generate_csrf_token()
    — both write the same key to the Flask session. This avoids depending on a
    specific page being rendered (which may not happen in all test flows).
    """
    with client.session_transaction() as s:
        if "_csrf_token" not in s:
            s["_csrf_token"] = uuid.uuid4().hex
        return s["_csrf_token"]

def login(client, tag, password="Test1234!"):
    """POST /auth to log in. Returns response."""
    email = f"test_{SUFFIX}_{tag}@bl-test.invalid"
    return client.post("/auth", data={
        "form_type": "login",
        "email": email,
        "password": password,
    }, follow_redirects=False)

def signup(client, tag, password="Test1234!"):
    """POST /auth to create a new account. Returns response."""
    return client.post("/auth", data={
        "form_type": "signup",
        "email":      f"test_{SUFFIX}_{tag}@bl-test.invalid",
        "password":   password,
        "first_name": f"T{tag[:4].title()}",
        "last_name":  "Tester",
    }, follow_redirects=False)

def complete_onboarding(client):
    """POST /onboarding with complete profile data. Returns response."""
    return client.post("/onboarding", data={
        "rider_types": "Skier",
        "skill_level": "intermediate",
        "pass_type":   "ikon",
        "home_state":  "CO",
    }, follow_redirects=False)

def invite_confirm(client, token_str):
    """POST /invite/<token>/confirm with valid CSRF. Returns response."""
    csrf = sess_csrf(client)
    return client.post(f"/invite/{token_str}/confirm",
        data={"csrf_token": csrf}, follow_redirects=False)

def body_ok(r):
    """Return decoded body of response."""
    return r.data.decode("utf-8", errors="replace")

def is_accepted_screen(body):
    return "invite_accepted" in body or "connected" in body.lower()

def is_expired_screen(body):
    return "expired" in body.lower() or "invite_expired" in body

def is_invalid_screen(body):
    return ("no longer valid" in body.lower() or "not found" in body.lower()
            or "invite_invalid" in body or is_expired_screen(body))


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — Logged-in recipient accepts directly
# ═════════════════════════════════════════════════════════════════════════════

def scenario_1():
    print("\n─── S1: Logged-in recipient accepts invite ───────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s1i")
            rec = make_user("s1r")
            tok = make_token(inv)
            inv_id, rec_id = inv.id, rec.id
            tok_str = tok.token
            db.session.commit()

        login(c, "s1r")

        # GET landing
        r_get = c.get(f"/invite/{tok_str}")
        check(r_get.status_code == 200, "S1.1  GET /invite/<token> → 200", notes=str(r_get.status_code))

        # POST confirm
        r_post = invite_confirm(c, tok_str)
        b = body_ok(r_post)
        check(r_post.status_code == 200, "S1.2  POST confirm → 200", notes=str(r_post.status_code))
        check(is_accepted_screen(b),     "S1.3  renders invite_accepted.html", notes=b[:80])

        with app.app_context():
            check(are_friends(inv_id, rec_id), "S1.4  mutual Friend rows created")
            check(token_used(tok_str),         "S1.5  token.used_at set")

        check(not sess_get(c, "invite_token"), "S1.6  invite_token cleared from session")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — Logged-out → POST confirm → login → back to invite → accept
# ═════════════════════════════════════════════════════════════════════════════

def scenario_2():
    print("\n─── S2: Logged-out → login → accept ──────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s2i")
            rec = make_user("s2r")
            tok = make_token(inv)
            inv_id, rec_id = inv.id, rec.id
            tok_str = tok.token
            db.session.commit()

        # GET landing unauthenticated
        r_get = c.get(f"/invite/{tok_str}")
        check(r_get.status_code == 200, "S2.1  GET landing (unauth) → 200")

        # POST confirm unauthenticated → must 302 to /auth
        r_unauth = invite_confirm(c, tok_str)
        loc_unauth = r_unauth.headers.get("Location", "")
        check(r_unauth.status_code == 302 and "/auth" in loc_unauth,
              "S2.2  unauth confirm → 302 /auth", notes=f"{r_unauth.status_code} {loc_unauth}")

        # Session variables after unauthenticated confirm
        s = sess_snapshot(c)
        inv_tok_val = s.get("invite_token", "")
        pll_val     = s.get("post_login_redirect", "")
        por_val     = s.get("post_onboarding_redirect", "")

        check(bool(inv_tok_val),          "S2.3  session[invite_token] set",              notes=inv_tok_val[:12])
        check(tok_str in pll_val,         "S2.4  post_login_redirect → /invite/<token>",  notes=pll_val)
        check(tok_str in por_val,         "S2.5  post_onboarding_redirect → /invite/<token>", notes=por_val)

        # Token NOT consumed at this point
        with app.app_context():
            check(not token_used(tok_str), "S2.6  token NOT consumed before login")

        # Login → should redirect to /invite/<token>
        r_login = login(c, "s2r")
        loc_login = r_login.headers.get("Location", "")
        check(r_login.status_code == 302 and tok_str in loc_login,
              "S2.7  login → 302 /invite/<token>", notes=f"{r_login.status_code} {loc_login}")

        # post_login_redirect consumed
        check(not sess_get(c, "post_login_redirect"),
              "S2.8  post_login_redirect consumed after login")

        # GET /invite/<token> (now logged in, landing shows confirm form)
        r_get2 = c.get(loc_login if loc_login.startswith("/") else f"/invite/{tok_str}")
        check(r_get2.status_code == 200, "S2.9  GET /invite/<token> logged-in → 200",
              notes=str(r_get2.status_code))

        # POST confirm (authenticated)
        r_accept = invite_confirm(c, tok_str)
        b = body_ok(r_accept)
        check(r_accept.status_code == 200, "S2.10 authenticated confirm → 200",
              notes=str(r_accept.status_code))
        check(is_accepted_screen(b),       "S2.11 renders invite_accepted.html", notes=b[:80])

        with app.app_context():
            check(are_friends(inv_id, rec_id), "S2.12 mutual Friend rows created")
            check(token_used(tok_str),         "S2.13 token marked used")

        check(not sess_get(c, "invite_token"), "S2.14 invite_token cleared from session")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — New signup → onboarding → redirect back to invite → accept
# ═════════════════════════════════════════════════════════════════════════════

def scenario_3():
    print("\n─── S3: Signup → onboarding → accept ─────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s3i")
            tok = make_token(inv)
            inv_id  = inv.id
            tok_str = tok.token
            db.session.commit()

        # GET landing unauthenticated
        c.get(f"/invite/{tok_str}")

        # POST confirm unauthenticated → stores redirects in session
        invite_confirm(c, tok_str)

        por_before = sess_get(c, "post_onboarding_redirect") or ""
        check(tok_str in por_before,
              "S3.1  post_onboarding_redirect pre-set before signup", notes=por_before)

        # Signup
        r_signup = signup(c, "s3n")
        loc_signup = r_signup.headers.get("Location", "")
        check(r_signup.status_code == 302 and "/onboarding" in loc_signup,
              "S3.2  signup → 302 /onboarding", notes=f"{r_signup.status_code} {loc_signup}")

        # New user in DB
        with app.app_context():
            nu = User.query.filter_by(email=f"test_{SUFFIX}_s3n@bl-test.invalid").first()
            new_uid = nu.id if nu else None
            if nu:
                _created_user_ids.append(nu.id)
        check(bool(new_uid), "S3.3  new User row in DB", notes=str(new_uid))

        # post_onboarding_redirect preserved through signup (not overwritten)
        por_after_signup = sess_get(c, "post_onboarding_redirect") or ""
        check(tok_str in por_after_signup,
              "S3.4  post_onboarding_redirect preserved after signup", notes=por_after_signup)

        # Friendship NOT created at signup (deferred)
        with app.app_context():
            if new_uid:
                premature = are_friends(inv_id, new_uid)
            else:
                premature = True
        check(not premature, "S3.5  friendship NOT created prematurely at signup")

        # Complete onboarding
        r_onboard = complete_onboarding(c)
        loc_onboard = r_onboard.headers.get("Location", "")
        check(r_onboard.status_code == 302 and tok_str in loc_onboard,
              "S3.6  onboarding → redirect to /invite/<token>",
              notes=f"{r_onboard.status_code} {loc_onboard}")

        # post_onboarding_redirect consumed
        check(not sess_get(c, "post_onboarding_redirect"),
              "S3.7  post_onboarding_redirect consumed after onboarding")

        # GET /invite/<token> post-onboarding
        r_get2 = c.get(loc_onboard if loc_onboard.startswith("/") else f"/invite/{tok_str}")
        check(r_get2.status_code == 200,
              "S3.8  GET /invite/<token> post-onboarding → 200", notes=str(r_get2.status_code))

        # POST confirm (authenticated, profile complete)
        r_accept = invite_confirm(c, tok_str)
        b = body_ok(r_accept)
        check(r_accept.status_code == 200, "S3.9  final confirm → 200",
              notes=str(r_accept.status_code))
        check(is_accepted_screen(b),       "S3.10 renders invite_accepted.html", notes=b[:80])

        with app.app_context():
            if new_uid:
                check(are_friends(inv_id, new_uid), "S3.11 mutual Friend rows created")
                check(token_used(tok_str),          "S3.12 token marked used")
            else:
                fail("S3.11 mutual Friend rows created", "new_uid unknown")
                fail("S3.12 token marked used")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 4 — Already-connected cases
# ═════════════════════════════════════════════════════════════════════════════

def scenario_4():
    print("\n─── S4: Already-connected behavior ───────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv  = make_user("s4i")
            rec  = make_user("s4r")
            tok  = make_token(inv)
            tok2 = make_token(inv)
            inv_id, rec_id = inv.id, rec.id
            tok_str  = tok.token
            tok_str2 = tok2.token
            # Case A: token used + already friends
            tok.used_at = datetime.utcnow()
            add_friend_rows(inv_id, rec_id)
            db.session.commit()

        login(c, "s4r")

        # Case A: used token + already friends → invite_accepted.html
        r_a = c.get(f"/invite/{tok_str}")
        b_a = body_ok(r_a)
        check(r_a.status_code == 200 and is_accepted_screen(b_a),
              "S4.1  used-token+already-friends GET → invite_accepted.html",
              notes=f"{r_a.status_code}")

        # Case B: unused token + already friends → invite_accepted.html (token gets marked used)
        r_b = c.get(f"/invite/{tok_str2}")
        b_b = body_ok(r_b)
        check(r_b.status_code == 200 and is_accepted_screen(b_b),
              "S4.2  unused-token+already-friends GET → invite_accepted.html",
              notes=f"{r_b.status_code}")
        with app.app_context():
            check(token_used(tok_str2), "S4.3  unused token marked used on re-visit")

        # Case C: POST confirm when already friends → also invite_accepted.html
        # Re-query inviter by ID — inv object is expired after the first app_context closed.
        with app.app_context():
            fresh_inv = db.session.get(User, inv_id)
            tok3 = make_token(fresh_inv)
            tok3_str = tok3.token
            db.session.commit()
        r_c = invite_confirm(c, tok3_str)
        b_c = body_ok(r_c)
        check(r_c.status_code == 200 and is_accepted_screen(b_c),
              "S4.4  POST confirm already-friends → invite_accepted.html",
              notes=f"{r_c.status_code}")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 5 — Self-invite guard
# ═════════════════════════════════════════════════════════════════════════════

def scenario_5():
    print("\n─── S5: Self-invite guard ─────────────────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s5i")
            tok = make_token(inv)
            tok_str = tok.token
            db.session.commit()

        login(c, "s5i")

        # GET own invite link
        r_get = c.get(f"/invite/{tok_str}", follow_redirects=False)
        loc_get = r_get.headers.get("Location", "")
        check(r_get.status_code == 302 and "/friends" in loc_get,
              "S5.1  GET own invite → 302 /friends", notes=f"{r_get.status_code} {loc_get}")

        # POST confirm own invite
        r_post = invite_confirm(c, tok_str)
        loc_post = r_post.headers.get("Location", "")
        check(r_post.status_code == 302 and "/friends" in loc_post,
              "S5.2  POST confirm own invite → 302 /friends", notes=f"{r_post.status_code} {loc_post}")

        # Token must NOT be consumed by self-invite
        with app.app_context():
            check(not token_used(tok_str), "S5.3  token NOT consumed by self-invite attempt")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 6 — Expired token
# ═════════════════════════════════════════════════════════════════════════════

def scenario_6():
    print("\n─── S6: Expired token ─────────────────────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s6i")
            tok = InviteToken(
                token=uuid.uuid4().hex,
                inviter_id=inv.id,
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.session.add(tok)
            db.session.commit()
            _created_token_strs.append(tok.token)
            tok_str = tok.token

        r = c.get(f"/invite/{tok_str}")
        b = body_ok(r)
        check(r.status_code == 200 and is_expired_screen(b),
              "S6.1  expired token GET → invite_expired.html", notes=str(r.status_code))

        # POST confirm on expired token
        r_post = invite_confirm(c, tok_str)
        b_post = body_ok(r_post)
        check(r_post.status_code == 200 and is_expired_screen(b_post),
              "S6.2  POST confirm expired token → invite_expired.html",
              notes=str(r_post.status_code))


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 7 — Invalid (non-existent) token
# ═════════════════════════════════════════════════════════════════════════════

def scenario_7():
    print("\n─── S7: Non-existent token ────────────────────────────────────────")
    with app.test_client() as c:
        r = c.get("/invite/totallyfaketoken99999xyz")
        b = body_ok(r)
        check(r.status_code == 200 and is_invalid_screen(b),
              "S7.1  fake token GET → invite_invalid.html", notes=str(r.status_code))


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 8 — Used token, stranger (never connected)
# ═════════════════════════════════════════════════════════════════════════════

def scenario_8():
    print("\n─── S8: Used token, not connected ─────────────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s8i")
            rec = make_user("s8r")
            tok = InviteToken(
                token=uuid.uuid4().hex,
                inviter_id=inv.id,
                expires_at=datetime.utcnow() + timedelta(hours=48),
                used_at=datetime.utcnow(),
            )
            db.session.add(tok)
            db.session.commit()
            _created_token_strs.append(tok.token)
            tok_str = tok.token

        # Unauthenticated
        r_anon = c.get(f"/invite/{tok_str}")
        b_anon = body_ok(r_anon)
        check(r_anon.status_code == 200 and is_expired_screen(b_anon),
              "S8.1  used-token anon GET → invite_expired.html", notes=str(r_anon.status_code))

        # Authenticated but not friends
        login(c, "s8r")
        r_auth = c.get(f"/invite/{tok_str}")
        b_auth = body_ok(r_auth)
        check(r_auth.status_code == 200 and is_expired_screen(b_auth),
              "S8.2  used-token authed+no-friendship GET → invite_expired.html",
              notes=str(r_auth.status_code))


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 9 — Duplicate friendship prevention (double-submit)
# ═════════════════════════════════════════════════════════════════════════════

def scenario_9():
    print("\n─── S9: Duplicate friendship prevention ───────────────────────────")
    with app.test_client() as c:
        with app.app_context():
            inv = make_user("s9i")
            rec = make_user("s9r")
            tok = make_token(inv)
            inv_id, rec_id = inv.id, rec.id
            tok_str = tok.token
            db.session.commit()

        login(c, "s9r")

        # First accept
        r1 = invite_confirm(c, tok_str)
        check(r1.status_code == 200 and is_accepted_screen(body_ok(r1)),
              "S9.1  first confirm → invite_accepted.html")

        # Second submit (token now used) → safe response
        r2 = invite_confirm(c, tok_str)
        b2 = body_ok(r2)
        safe = r2.status_code == 200 and (is_expired_screen(b2) or is_accepted_screen(b2))
        check(safe, "S9.2  double-submit → safe 200 response", notes=b2[:80])

        # Exactly one Friend row each direction
        with app.app_context():
            c1, c2 = friend_row_count(inv_id, rec_id)
        check(c1 == 1 and c2 == 1,
              "S9.3  exactly one Friend row per direction", notes=f"fwd={c1} rev={c2}")


# ═════════════════════════════════════════════════════════════════════════════
# SCENARIO 10 — Google OAuth redirect ordering (unit-level, no real OAuth)
# ═════════════════════════════════════════════════════════════════════════════

def scenario_10():
    """Verify Google callback code ordering via source inspection (OAuth round-trip not testable)."""
    print("\n─── S10: Google callback ordering (source audit) ──────────────────")
    import inspect
    src = inspect.getsource(appmod.auth_google_callback)

    # Find block positions for redirect control logic only
    # post_login_redirect pop is at the redirect-control block, after analytics
    # We look for the redirect block specifically
    lines = src.split("\n")
    pll_line = next((i for i, l in enumerate(lines) if "session.pop(\"post_login_redirect\"" in l), -1)
    inv_line = next((i for i, l in enumerate(lines)
                     if '"invite_token" in session' in l and "connect_pending_inviter" in "\n".join(lines[i:i+5])), -1)

    check(pll_line != -1, "S10.1 post_login_redirect pop present in Google callback")
    check(inv_line != -1, "S10.2 invite_token fallback present in Google callback")
    check(pll_line < inv_line,
          "S10.3 post_login_redirect checked BEFORE invite_token fallback",
          notes=f"pll_line={pll_line} inv_line={inv_line}")
    check("session[\"post_onboarding_redirect\"] = _post_login" in src,
          "S10.4 new Google user: destination preserved through onboarding")
    check("[invite_context_restored]" in src,
          "S10.5 [invite_context_restored] lifecycle log present")
    check("[invite_friendship_created]" in src,
          "S10.6 [invite_friendship_created] lifecycle log present")


# ═════════════════════════════════════════════════════════════════════════════
# Cleanup
# ═════════════════════════════════════════════════════════════════════════════

def cleanup():
    with app.app_context():
        try:
            for tok_str in _created_token_strs:
                InviteToken.query.filter_by(token=tok_str).delete()
            for uid in _created_user_ids:
                Friend.query.filter(
                    (Friend.user_id == uid) | (Friend.friend_id == uid)
                ).delete()
                # Clear FK references to this user before deleting
                User.query.filter_by(invited_by_user_id=uid).update(
                    {"invited_by_user_id": None}
                )
                InviteToken.query.filter_by(inviter_id=uid).delete()
            db.session.flush()
            for uid in _created_user_ids:
                User.query.filter_by(id=uid).delete()
            db.session.commit()
            print(f"\n[cleanup] Removed {len(_created_user_ids)} users, "
                  f"{len(_created_token_strs)} tokens")
        except Exception as e:
            db.session.rollback()
            print(f"[cleanup error] {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 68)
    print("BASELODGE — INVITE FLOW END-TO-END TEST SUITE")
    print(f"Run suffix: {SUFFIX}")
    print("=" * 68)

    scenarios = [
        scenario_1,
        scenario_2,
        scenario_3,
        scenario_4,
        scenario_5,
        scenario_6,
        scenario_7,
        scenario_8,
        scenario_9,
        scenario_10,
    ]

    for fn in scenarios:
        try:
            fn()
        except Exception:
            print(f"  [EXCEPTION in {fn.__name__}]")
            traceback.print_exc()

    cleanup()

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = [r for r in RESULTS if not r["passed"]]
    total  = len(RESULTS)

    print("\n" + "=" * 68)
    print(f"RESULTS  {passed}/{total} passed    {len(failed)} failed")
    print("=" * 68)

    if failed:
        print("\nFAILED TESTS:")
        for r in failed:
            print(f"  ✗  {r['name']}" + (f"  — {r['notes']}" if r["notes"] else ""))

    print()
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
