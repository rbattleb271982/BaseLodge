---
name: Activity tracking / last_active_at
description: Why WAU/MAU metrics were zero and how the fix works
---

## The problem
`last_active_at` is a real DB column (`models.py`) but was **never written in app.py** — only in seed scripts. Every login handler called `db.session.commit()` without stamping the field. Result: all production users had `NULL` or stale seed values, so WAU/MAU dashboard counts showed 0.

## The fix (three touch points)
1. **Email login** — stamp `user.last_active_at = datetime.utcnow()` before `db.session.commit()` in the email login branch.
2. **Google OAuth login** — same stamp before `login_user()` in the `/auth/google/callback` handler.
3. **Password-reset login** — stamp alongside `password_changed_at` before commit.
4. **`before_request_handlers` heartbeat** — for already-authenticated sessions (remember-me, persistent sessions), updates `last_active_at` at most **once per hour** using `session['_last_active_stamp']` (a Unix timestamp) as a throttle gate. No extra SELECT needed; at most 1 UPDATE per user per hour. Skips `/static/` paths.

**Why:**
The heartbeat is essential for users who stay logged in via remember-me cookies and never re-authenticate. Without it, only users who log in within the measurement window would appear active.

**How to apply:**
Any future login path (e.g. Apple Sign-In) must also stamp `last_active_at`. The heartbeat covers persistent sessions automatically. Always use `datetime.utcnow()` (naive UTC) to match the column type (`db.DateTime`, no timezone).
