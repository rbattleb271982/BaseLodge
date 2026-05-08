# BaseLodge Outbound Messaging Architecture Audit
**Date:** May 2026  
**Purpose:** Migration-ready technical audit of all outbound messaging, notification, and in-app communication systems in BaseLodge. No code was changed during this audit.

---

## Searches Conducted

The following patterns were searched across the entire codebase (`app.py`, `models.py`, `templates/`, `docs/`, `scripts/`, `migrations/`, `services/`, `static/`, `ios/`):

```
sendgrid, SendGridAPIClient, Mail(, sg.send, SENDGRID, email, EmailLog,
reset, password, token, notification, push, PushDeviceToken, APNS, apns,
FCM, firebase, OneSignal, ONESIGNAL, invite, friend, trip invite, feedback,
contact, cron, scheduler, lifecycle, reminder, digest, weekly, journey,
emit_, ActivityType, Activity.query, send_onesignal, send_apns, send_fcm,
push_register_token, push_preferences, push_debug_beacon
```

**Match counts (relevant to messaging):**
- `sendgrid` / `SendGridAPIClient` / `sg.send` / `Mail(` — 18 hits in app.py, 4 in requirements.txt, 1 in docs
- `OneSignal` / `ONESIGNAL` / `send_onesignal` — 47 hits in app.py, 9 in ios/ Podfile.lock
- `APNS` / `apns` / `send_apns_push` — 80+ hits in app.py, 12 in templates/components/analytics_head.html
- `FCM` / `firebase` / `send_fcm_push` — 20 hits in app.py
- `EmailLog` — 12 hits in app.py, 8 in models.py, 6 in migrations
- `PushDeviceToken` — 30 hits in app.py, 6 in models.py, 3 in test_push_lifecycle.py
- `cron` / `scheduler` / `celery` / `rq` / `apscheduler` — **0 hits** (no background job infrastructure)
- `emit_` (activity functions) — 15 function definitions, 10+ call sites in app.py

---

## A. Executive Summary

### Current Provider Responsibilities

| Provider | Responsibility |
|----------|---------------|
| **SendGrid** | Password reset email; admin feedback email |
| **OneSignal** | Friend pass-change Journey trigger (custom event); admin test push (REST API) |
| **APNs (direct)** | iOS push delivery — admin test routes only currently |
| **FCM (direct)** | Android push delivery — admin test routes only currently |
| **In-app / DB only** | All social notifications (trip invites, friend joins, carpool, overlap, connection accepted) |

### What Is Production-Critical
- **Password reset email via SendGrid** — the only recovery path for email-auth users. No fallback exists. If `SENDGRID_API_KEY` is missing or invalid, reset silently fails (error is logged, user sees a generic message).
- **Token registration pipeline** (`POST /api/push/register-token`) — required before any push can be delivered. Handles iOS and Android.
- **Push preference toggle** (`POST /api/push/preferences`) — gates all OneSignal delivery.

### What Is Test / Admin Only
- `/admin/test-push` — sends to latest active token for any user
- `/admin/test-push-all` — sends to all active tokens for the admin user
- `/admin/test-push-broadcast` — sends to **every active token in the database across all users** (dangerous in production)
- `/admin/test-onesignal-push` — sends a OneSignal push to the calling admin
- `/admin/push-diagnostics` — read-only JSON diagnostic (hardcoded `target_user_id = 2`)
- `/admin/list-tokens` — read-only token list

### What Is Duplicate or Risky
- **Three separate push delivery providers exist simultaneously**: APNs direct, FCM direct, and OneSignal. OneSignal is also an APNs/FCM wrapper. If OneSignal is eventually used for all pushes, the direct APNs/FCM code becomes redundant but will not self-disable.
- **`/admin/test-push-broadcast`** has no per-user opt-out check and no rate-limiting. It can spam every device in the database. It does check platform (iOS vs Android) but not `push_notifications_enabled`. High risk if triggered in production by mistake.
- **`EmailLog` is never written to** during actual email sends (password reset, feedback). The table and its infrastructure exist but track nothing in production. This is a silent gap.
- **Email preference flags** (`email_opt_in`, `email_transactional`, `email_social`, `email_digest`) exist on the User model but are **never checked** before sending emails.

### What Is Safe to Migrate Later
- `send_onesignal_custom_event` for `friend_pass_changed` — already using OneSignal Journeys, no changes needed.
- In-app Activity records (notifications page) — purely internal, no provider dependency.

### What Should Be Handled Carefully
- Password reset email — should stay on SendGrid for now; moving to OneSignal requires email channel setup + domain authentication and testing.
- APNs/FCM direct push infrastructure — mature, env-aware, with retry logic. Should not be removed until OneSignal push is confirmed to fully replace it.

---

## B. Full Inventory Table

| # | Flow / Message | Channel | Current Provider | Trigger | File Path | Function / Route | Env Vars | DB Models | Status | User-facing Copy | Migration Notes |
|---|---------------|---------|-----------------|---------|-----------|-----------------|----------|-----------|--------|-----------------|----------------|
| 1 | Password reset email | Email | SendGrid | User action (POST /forgot-password) | app.py:1910 | `forgot_password()` | SENDGRID_API_KEY | User (read) | **Active** | Subject: "Reset your BaseLodge password" | Should stay transactional; do not move to OneSignal immediately |
| 2 | Admin feedback email | Email | SendGrid | User action (POST /feedback) | app.py:6845 | `feedback()` | SENDGRID_API_KEY, ADMIN_FEEDBACK_EMAIL | User (read) | **Active** | Subject: "New BaseLodge Feedback" | Should stay transactional; admin ops channel |
| 3 | Friend pass-changed Journey trigger | Push (deferred) | OneSignal Custom Events API | User action (pass save) | app.py:2447 | `edit_profile()` | ONESIGNAL_APP_ID, ONESIGNAL_REST_API_KEY | User, Friend (read) | **Active** | No copy here; Journey controls push copy | Easy to extend with more events |
| 4 | Friend pass-changed Journey trigger (select pass) | Push (deferred) | OneSignal Custom Events API | User action (pass save) | app.py:9308 | `select_pass()` | ONESIGNAL_APP_ID, ONESIGNAL_REST_API_KEY | User, Friend (read) | **Active** | No copy here; Journey controls push copy | Duplicate of #3 via different route; consolidate later |
| 5 | Admin test push (latest token) | Push | APNs or FCM (auto-routed) | Admin action | app.py:4593 | `admin_test_push()` @ /admin/test-push | APNS_KEY_P8, APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_USE_SANDBOX, FIREBASE_SERVICE_ACCOUNT_JSON | PushDeviceToken | **Test-only** | "BaseLodge / Test push from BaseLodge" | Remove or protect post-migration |
| 6 | Admin test push (all user tokens) | Push | APNs or FCM (per-platform) | Admin action | app.py:4781 | `admin_test_push_all()` @ /admin/test-push-all | same as #5 | PushDeviceToken | **Test-only** | "BaseLodge / Test push from BaseLodge" | Remove or protect post-migration |
| 7 | Admin test push (broadcast all users) | Push | APNs or FCM (per-platform) | Admin action | app.py:4946 | `admin_test_push_broadcast()` @ /admin/test-push-broadcast | same as #5 | PushDeviceToken | **Test-only, HIGH RISK** | "BaseLodge / Test push from BaseLodge" | Should be disabled or heavily guarded before scaling |
| 8 | Admin test push via OneSignal | Push | OneSignal REST API | Admin action | app.py:12720 | `admin_test_onesignal_push()` @ /admin/test-onesignal-push | ONESIGNAL_APP_ID, ONESIGNAL_REST_API_KEY | User (read) | **Test-only** | "BaseLodge / Test push from BaseLodge (OneSignal)" | Useful for validating OneSignal setup |
| 9 | Trip invite notification (in-app) | In-app | DB only | User action (owner sends invite) | app.py:8627 | `send_trip_invites()` @ POST /trips/<id>/invite | none | Activity, SkiTripParticipant | **Active, in-app only** | None | Good candidate for future OneSignal Journey |
| 10 | Trip invite accepted notification (in-app) | In-app | DB only | User action (invitee accepts) | app.py:8815 | `respond_to_trip_invite()` | none | Activity | **Active, in-app only** | None | Good candidate for future OneSignal Journey |
| 11 | Trip invite declined notification (in-app) | In-app | DB only | User action (invitee declines) | app.py:8824 | `respond_to_trip_invite()` | none | Activity | **Active, in-app only** | None | Low priority |
| 12 | Friend joined trip notification (in-app) | In-app | DB only | User action (accept invite) | app.py:8816 | `emit_friend_joined_trip_activities()` | none | Activity | **Active, in-app only** | None | Good candidate for OneSignal |
| 13 | Connection accepted notification (in-app) | In-app | DB only | User action (accept friend invite) | app.py:3694 | `accept_invitation()` | none | Activity, Friend | **Active, in-app only** | None | Good candidate for OneSignal |
| 14 | Carpool offered notification (in-app) | In-app | DB only | User action (set carpool role) | app.py:3586 | `update_participant_signals()` | none | Activity | **Active, in-app only** | None | Lower priority |
| 15 | Trip overlap notification (in-app) | In-app | DB only | Background/startup event | app.py:1108 | `emit_availability_overlap_activities_for_user()` | none | Activity, UserAvailability | **Active, in-app only** | None | Could become a Journey trigger |
| 16 | Join request received notification (in-app) | In-app | DB only | User action (request to join public trip) | app.py:8685 | `request_to_join_trip()` | none | Activity, Invitation | **Active, in-app only** | None | Good OneSignal candidate |
| 17 | Join request accepted/declined notification (in-app) | In-app | DB only | User action (owner responds) | app.py:8731,8740 | `respond_to_join_request()` | none | Activity, Invitation | **Active, in-app only** | None | Good OneSignal candidate |
| 18 | Friend invite (in-app, no outbound email) | In-app | DB only | User action (API invite) | app.py:3598 | `invite_friend()` @ POST /api/friends/invite | none | Invitation | **Active, DB only** | None | No email sent; consider adding OneSignal push |
| 19 | Invite token (link share, no email) | None (URL) | n/a | User action | app.py:5875 | `invite()` @ /invite | none | InviteToken | **Active** | "Copy link" / QR | No outbound send; user shares link manually via SMS/copy |
| 20 | Push token registration | Infrastructure | APNs / FCM (token only) | App startup (native app) | app.py:3767 | `push_register_token()` @ POST /api/push/register-token | APNS_USE_SANDBOX | PushDeviceToken | **Active** | None | Required for all push delivery |
| 21 | Push preference toggle | Infrastructure | DB write | User action (Settings) | app.py:3894 | `push_preferences()` @ POST /api/push/preferences | none | User | **Active** | None | Checked by send_onesignal_push; not by broadcast route |
| 22 | Push debug beacon | Logging only | none | App navigation (native app JS) | app.py:3869 | `push_debug_beacon()` @ POST /api/push/beacon | none | none | **Active, debug only** | None | Useful; retain for diagnostics |
| 23 | Push diagnostics (read-only) | Admin | none | Admin action | app.py:4281 | `admin_push_diagnostics()` @ GET /admin/push-diagnostics | all APNS_ vars | PushDeviceToken | **Active, diagnostic** | None | Hardcoded to user_id=2; generalize before wider use |
| 24 | Token list (read-only) | Admin | none | Admin action | app.py:5112 | `admin_list_tokens()` @ GET /admin/list-tokens | none | PushDeviceToken | **Active, diagnostic** | None | Safe; retain |
| 25 | Trip created activity (in-app) | In-app | DB only | User action | app.py:728 | `emit_trip_created_activities()` | none | Activity | **Active, in-app only** | None | Future Journey: "Your friend created a trip" |
| 26 | Trip updated activity (in-app) | In-app | DB only | User action | app.py:743 | `emit_trip_updated_activities()` | none | Activity | **Active, in-app only** | None | Low priority |
| 27 | Trip location changed activity (in-app) | In-app | DB only | User action | app.py:760 | `emit_trip_location_changed_activities()` | none | Activity | **Active, in-app only** | None | Low priority |
| 28 | Trip pass changed activity (in-app) | In-app | DB only | User action | app.py:781 | `emit_trip_pass_changed_activities()` | none | Activity | **Active, in-app only** | None | Already has OneSignal event in parallel |

---

## C. File-by-File Findings

### `app.py` (12,758 lines — primary location of all messaging logic)

All messaging code lives in `app.py`. There is no email service module, no notification service, no push service file. Everything is inlined.

**SendGrid block (lines 1910–1966):** `forgot_password()` route.  
- Constructs an HTML + plain-text email inline.  
- Calls `SendGridAPIClient(key).send(message)`.  
- Failure is caught and logged; the user always sees the same response message regardless of success.  
- `EmailLog` is **not** written here.  
- Rate-limited at 5 per hour.

**SendGrid block (lines 6845–6902):** `feedback()` route.  
- Sends to `ADMIN_FEEDBACK_EMAIL` env var.  
- Uses the alternative `sg.client.mail.send.post()` API form (vs `sg.send()`). Both work; slightly inconsistent.  
- Also not logged to `EmailLog`.

**OneSignal push helper (lines 4413–4511):** `send_onesignal_push()`.  
- Full push via OneSignal REST API.  
- Checks `push_notifications_enabled` on the User model before sending — opt-out is respected.  
- Currently called only by `admin_test_onesignal_push()`. **Not wired to any user-facing event.**

**OneSignal event helper (lines 4514–4590):** `send_onesignal_custom_event()`.  
- Fires a custom event (one POST per recipient) to trigger a OneSignal Journey.  
- No per-user opt-out check here; opt-out is the Journey's responsibility.  
- Called at: `edit_profile()` (line 2447) and `select_pass()` (line 9308), both on pass change.

**APNs infrastructure (lines 4015–4279):**  
- `_apns_jwt()` — builds a signed JWT for Apple's HTTP/2 APNs API using ES256.  
- `send_apns_push()` — sends to one token. Environment-aware (sandbox/production). Retry logic on `BadEnvironmentKeyInToken` or `BadDeviceToken`. Self-corrects `PushDeviceToken.apns_environment` on successful retry. Marks token inactive if both environments fail.  
- Payload format: `{"aps": {"alert": {"title": ..., "body": ...}, "sound": "default", "badge": 1}}`.

**FCM infrastructure (lines 3928–4013):**  
- `_get_firebase_admin()` — lazy singleton initialization of Firebase Admin SDK.  
- `send_fcm_push()` — sends to one Android token via `firebase_admin.messaging`.

**Token registration (lines 3767–3866):** `push_register_token()`.  
- Idempotent upsert: refreshes existing row or inserts new one.  
- Resolves `apns_environment` from: client hint → server APNS_USE_SANDBOX → "unknown".  
- Will not overwrite a confirmed sandbox/production value with a weaker "unknown" or conflicting hint.

**Activity emit functions (lines 728–1154):**  
- 10+ `emit_*` functions. Each creates one or more `Activity` rows with `actor_user_id`, `recipient_user_id`, `type`, `object_type`, `object_id`, optional `extra_data`.  
- No email or push is sent in any of them.  
- These feed the `/notifications` page and the Home happenings/opportunities feed.

**Admin push routes:**
- `/admin/test-push` (line 4593) — routes to APNs or FCM based on latest active token's platform.
- `/admin/test-push-all` (line 4781) — loops all active tokens for current admin user.
- `/admin/test-push-broadcast` (line 4946) — loops ALL active tokens in DB. **No opt-out check. No rate limit beyond `@admin_required`.**
- `/admin/test-onesignal-push` (line 12720) — sends via OneSignal to calling admin's external_id.
- `/admin/push-diagnostics` (line 4281) — read-only JSON dump. Target user hardcoded to ID=2.
- `/admin/list-tokens` (line 5112) — read-only, parameterizable by `?user_id=`.

---

### `models.py` — Data models for messaging

**`User` model — messaging-relevant fields:**
| Field | Default | Purpose |
|-------|---------|---------|
| `email_opt_in` | True | Master opt-in flag (never checked) |
| `email_transactional` | True | Transactional email flag (never checked) |
| `email_social` | False | Social email flag (never checked) |
| `email_digest` | False | Digest email flag (never checked) |
| `push_notifications_enabled` | True | Checked by `send_onesignal_push()`; NOT checked by admin broadcast |
| `password_changed_at` | None | Used to invalidate reset tokens already used |
| `welcome_modal_seen_at` | None | Controls welcome modal; not used for messaging |

**`EmailLog` model (lines 1162–1177):**
```
email_log: id, user_id (FK), email_type (str), source_event_id (FK event),
           sent_at, send_count, environment
```
- Never written to during any active email send.
- Only touched during account deletion (rows are deleted).
- Would be the right place to record all sends for deduplication and suppression.

**`Activity` / `ActivityType` (lines 1180–1226):**
- `ActivityType` values: TRIP_CREATED, TRIP_UPDATED, FRIEND_JOINED_TRIP, TRIP_INVITE_RECEIVED, TRIP_INVITE_ACCEPTED, TRIP_INVITE_DECLINED, CONNECTION_ACCEPTED, TRIP_OVERLAP, FRIEND_TRIP_OVERLAPS_AVAILABILITY, CARPOOL_OFFERED, JOIN_REQUEST_RECEIVED, JOIN_REQUEST_ACCEPTED, JOIN_REQUEST_DECLINED, TRIP_LOCATION_CHANGED, TRIP_PASS_CHANGED
- Each activity has: `actor_user_id`, `recipient_user_id`, `type`, `object_type`, `object_id`, `extra_data` (JSON)
- Rendered on `/notifications` page.
- **No outbound delivery from any of these.**

**`PushDeviceToken` model (lines 1229–1252):**
```
push_device_token: id, user_id (FK), token (str 512), platform (ios|android),
                   active (bool), apns_environment (sandbox|production|unknown|n/a),
                   created_at, updated_at
UniqueConstraint: (user_id, token)
```

**`InviteToken` model:**
```
invite_token: id, token (str), inviter_id (FK user), created_at, expires_at, used_at
```
- Used for shareable friend-invite links only. No email is ever sent automatically with this token.

**`Invitation` model:**
```
invitation: id, sender_id, receiver_id, trip_id, invite_type (enum), status ('pending'|'accepted'|...)
```
- Used for friend invites (in-app) and trip join requests. No outbound messaging.

---

### `templates/forgot_password.html`
- Standard auth shell (no `base_app.html`).
- Includes `analytics_head.html` for PostHog/push beacon script.
- Single form field: email.
- No CSRF token on this form (low risk — rate-limited by IP/user).

### `templates/reset_password.html`
- Standard auth shell.
- Token passed as path param (`/reset-password/<token>`).
- No JavaScript.

### `templates/feedback.html`
- Extends `base_app.html`.
- Simple textarea → POST.
- No CSRF on this form either.

### `templates/notifications.html`
- Renders `Activity` rows from `/notifications` route.
- Shows pending `Invitation` connection requests with inline accept button.
- Accept calls `POST /api/friends/invite/<id>/accept` via JS fetch.
- Push-only; nothing else is sent.

### `templates/components/analytics_head.html`
- Contains the Capacitor push registration JS.
- On app startup (native), POSTs to `/api/push/register-token` with token and platform.
- Uses `Capacitor.DEBUG` as hint for `apns_environment`.
- POSTs beacons to `/api/push/beacon` at each registration step.
- Also initializes PostHog and OneSignal SDK client-side (for subscription management).

### `docs/email-crm-product-spec.md`
- Documents the intended CRM architecture.
- Confirms SendGrid for transactional, ADMIN_FEEDBACK_EMAIL for feedback.
- Lists planned email types (social, lifecycle, digest) that are not yet implemented.
- States the spec intent: "Email behavior should be quiet, explicit, and privacy-safe."

### `test_push_lifecycle.py`
- Unit tests for `PushDeviceToken` lifecycle.
- Tests: no_active_tokens returns 200 without calling APNs; list-tokens is safe; register-token reactivates; no duplicates.
- Patches `send_apns_push` to confirm it is NOT called for certain admin routes.

### `scripts/seed.py`, `scripts/seed_richard_home_signals.py`
- Seed scripts populate `Activity` rows for demo data.
- No email or push is triggered.

---

## D. Provider Map

### SendGrid
**Responsibilities:**
1. Password reset email (`forgot_password()`) — active, production-critical.
2. Admin feedback email (`feedback()`) — active, admin ops only.

**Not responsible for:**
- Any social or lifecycle emails (none exist yet).
- Invite emails (no invite emails are sent).
- Digest or reminder emails (none exist).

**Configuration:**
- `SENDGRID_API_KEY` — required for both sends.
- `ADMIN_FEEDBACK_EMAIL` — required only for feedback.
- Sender address: `noreply@baselodgeapp.com` (hardcoded in both send calls).

---

### OneSignal
**Responsibilities:**
1. Custom event delivery for `friend_pass_changed` Journey (2 call sites).
2. Admin test push via REST API (`admin_test_onesignal_push()`).
3. Client-side SDK subscription management (opt-in/opt-out via `blSetPushEnabled()` in `analytics_head.html`).
4. ONESIGNAL_APP_ID is injected as a Jinja global and used in client-side JS.

**Not responsible for (yet):**
- Trip invite push notifications.
- Friend connection push notifications.
- Any social lifecycle push.

**Configuration:**
- `ONESIGNAL_APP_ID` — public, injected into templates.
- `ONESIGNAL_REST_API_KEY` — secret, server-side only.
- External user identity: BaseLodge `user.id` is the OneSignal `external_id`.

---

### APNs (direct — Apple Push Notification Service)
**Responsibilities:**
1. iOS push delivery for all 3 admin test routes.
2. No production user-facing push is currently sent via APNs.

**Architecture:**
- JWT-based auth (`_apns_jwt()`).
- HTTP/2 via `httpx.Client(http2=True)`.
- Per-token send (not broadcast).
- Environment-aware: sandbox vs production, with retry on mismatch.
- Self-healing: corrects `apns_environment` on retry success; deactivates token if both environments fail.

**Configuration:**
- `APNS_KEY_P8` — ES256 private key contents.
- `APNS_KEY_ID` — 10-char key ID from Apple Developer.
- `APNS_TEAM_ID` — 10-char team ID from Apple Developer.
- `APNS_BUNDLE_ID` — default `com.baselodge.app`.
- `APNS_USE_SANDBOX` — `"false"` = production (TestFlight/App Store); `"true"` = sandbox (Xcode).

---

### FCM (direct — Firebase Cloud Messaging)
**Responsibilities:**
1. Android push delivery for all 3 admin test routes.
2. No production user-facing push is currently sent via FCM.

**Architecture:**
- Singleton Firebase Admin app (`_firebase_admin_app`).
- `firebase_admin.messaging` module.
- Per-token send.

**Configuration:**
- `FIREBASE_SERVICE_ACCOUNT_JSON` — full JSON string of service account credentials.

---

### In-App / Database Only
**Responsibilities:**
- All social activity notifications (13 activity types listed above).
- All friend invite flows (Invitation model).
- All trip invite flows (SkiTripParticipant + Activity).
- InviteToken-based friend link (URL only, no outbound message).

**Key point:** Nothing in the Activity system emits any outbound message. Users only see these on the `/notifications` page. There is no push, no email, no badge count sent in response to any social event.

---

## E. Password Reset Deep Dive

### Full Request Flow

```
User → GET /forgot-password → renders forgot_password.html
User → POST /forgot-password (email field)
  → normalize email to lowercase
  → User.query.filter(func.lower(User.email) == email).first()
  
  if user found AND user.auth_provider == 'email':
    → user.get_reset_token()   # URLSafeTimedSerializer(SECRET_KEY).dumps(user.id, salt='password-reset')
    → build reset_url = f"{BASE_URL}/reset-password/{token}"
    → construct Mail(from, to, subject, plain_text, html)
    → SendGridAPIClient(SENDGRID_API_KEY).send(message)
    → log success or error
  
  if user found AND user.auth_provider == 'google':
    → set _google_account = True
    → flash "This account uses a different sign-in method"
  
  Always:
    → flash "If an account exists with that email, you'll receive a password reset link."
    → render forgot_password.html (no redirect — prevents timing attacks)
```

### Token Creation / Validation Flow

**Creation (`User.get_reset_token()` — models.py:210):**
```python
s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
return s.dumps(user.id, salt='password-reset')
```
- Token encodes `user.id` and a timestamp.
- Signed with `SECRET_KEY` + salt `'password-reset'`.
- No database storage — token is self-describing.

**Validation (`User.verify_reset_token(token, max_age=1800)` — models.py:218):**
```python
user_id, issued_at = s.loads(token, salt='password-reset', max_age=max_age, return_timestamp=True)
user = db.session.get(User, user_id)

# Single-use enforcement:
if user.password_changed_at and user.password_changed_at > issued_at_naive:
    return None
```
- 30-minute expiry (1800 seconds).
- Single-use: if `password_changed_at` is set and is newer than the token's `issued_at`, the token is rejected. This is correct and important.
- Expired or tampered tokens raise `SignatureExpired`/`BadSignature` → return `None`.

**Reset completion (`reset_password()` — app.py:1971):**
```python
user.set_password(password)
user.password_changed_at = datetime.utcnow()
db.session.commit()
login_user(user)
flash("Your password has been reset.", "success")
return redirect("/")
```

### Email Body / Subject
- **From:** `noreply@baselodgeapp.com` (hardcoded)
- **To:** `user.email`
- **Subject:** `Reset your BaseLodge password`
- **Plain text:** `Hi {first_name},\n\nPlease use the following link...\n\nThis link expires in 30 minutes.\n\nIf you didn't request this, you can safely ignore this email.`
- **HTML:** Branded BaseLodge editorial style, bordeaux `#7A1E1E`, Georgia serif headline, cream background. Reset link as a button.

### Failure Handling
- SendGrid exception → caught, logged via `app.logger.error()`, **silently ignored from user perspective**.
- User always sees: "If an account exists with that email, you'll receive a password reset link."
- If `SENDGRID_API_KEY` is missing or invalid, the reset email is silently not sent and the user waits for an email that never arrives.
- No retry. No fallback. No `EmailLog` write.

### Why This Should NOT Move to OneSignal Immediately
- OneSignal's email channel requires separate domain authentication (SPF, DKIM, DMARC) for `baselodgeapp.com`, which is separate from the current SendGrid auth setup.
- Password reset is a security-critical transactional flow. Testing in production before confidence is built would be a risk.
- OneSignal email sends require the user to be a known subscriber with an email address registered in OneSignal — which BaseLodge users are not (they're only registered as push subscribers by external_id).
- SendGrid is working, rate-limited, and tested. This is the right place to leave it for now.

---

## F. Push Notification Deep Dive

### iOS Path

1. **Token Registration:**  
   Capacitor app opens → `analytics_head.html` JS polls for `window.Capacitor` (up to 2000ms) → calls `PushNotifications.register()` → Apple delivers APNs token → JS POSTs to `POST /api/push/register-token` with `{token, platform: 'ios', apns_environment}`.

2. **Environment Determination:**  
   `apns_environment` resolved in order: client hint (Capacitor.DEBUG) → server APNS_USE_SANDBOX inference → "unknown".

3. **Push Send:**  
   `send_apns_push(device_token, title, body)` called with the stored token.  
   - Derives host from `apns_environment` stored on token.  
   - Tries first environment. On `BadEnvironmentKeyInToken` or `BadDeviceToken`, retries opposite.  
   - On retry success: updates `PushDeviceToken.apns_environment` to corrected value.  
   - On permanent failure (`Unregistered`, 410): marks `active=False`.

### Android Path

1. **Token Registration:**  
   Same Capacitor JS → `PushNotifications.register()` → FCM token → `POST /api/push/register-token` with `{token, platform: 'android', apns_environment: 'n/a'}`.

2. **Push Send:**  
   `send_fcm_push(token, title, body)` → Firebase Admin SDK → `firebase_admin.messaging.Message`.

### Token Registration (both platforms)
- Endpoint: `POST /api/push/register-token` (login required).
- Idempotent: upsert by `(user_id, token)`. Refreshes `updated_at` and re-activates if inactive.
- Unique constraint: `(user_id, token)` — prevents duplicate rows.
- Will NOT overwrite a confirmed `apns_environment` with "unknown" or a conflicting hint.

### Device Model (`PushDeviceToken`)
```
id, user_id, token (max 512 chars), platform ('ios'|'android'),
active (bool), apns_environment ('sandbox'|'production'|'unknown'|'n/a'),
created_at, updated_at
```

### Test / Admin Push Routes
| Route | Who It Targets | Provider | Risk |
|-------|---------------|----------|------|
| `/admin/test-push` | Latest active token (most recently updated) | APNs or FCM auto-routed | Low |
| `/admin/test-push-all` | All active tokens for current admin user | APNs+FCM per-platform | Low |
| `/admin/test-push-broadcast` | **All active tokens in the entire DB** | APNs+FCM per-platform | **HIGH** — no user opt-out check |
| `/admin/test-onesignal-push` | Calling admin's OneSignal external_id | OneSignal REST | Low |
| `/admin/push-diagnostics` | Read-only, target_user_id=2 hardcoded | None | None |
| `/admin/list-tokens` | Read-only, ?user_id= param | None | None |

### Production Push Routes
**There are none currently.** No user-facing event triggers a push to another user's device. All push delivery is admin-triggered via test routes.

The `send_onesignal_push()` helper exists and has opt-out filtering, but it is only called by `admin_test_onesignal_push()`.

### Duplicate / Legacy Paths
- APNs direct, FCM direct, and OneSignal REST all exist simultaneously.
- OneSignal's SDK (iOS: v5.5.1 via Podfile) is installed in the native app — this means OneSignal can deliver pushes natively once subscribed, independent of the server calling the REST API.
- The direct APNs/FCM code is functional but overlaps with what OneSignal can do. They must not both fire for the same event.

### How OneSignal Overlaps with APNs/FCM
OneSignal is an abstraction layer over APNs and FCM. When you call the OneSignal REST API with `include_aliases: {external_id: ["123"]}`, OneSignal handles the per-platform routing internally. The direct APNs/FCM code is lower-level. They both deliver to the same devices but through different routes. If OneSignal is adopted for production push, the direct APNs/FCM admin test routes should be removed or clearly separated from production flows.

---

## G. Invite / Friend / Trip Messaging Deep Dive

### What Sends Actual Outbound Messages

| Action | Outbound? | Channel | Notes |
|--------|-----------|---------|-------|
| User generates invite link (`/invite`) | No | URL only | User shares link via copy/paste or SMS share sheet |
| User generates QR code (`/my-qr`) | No | Image only | PNG served, no external send |
| User creates friend invite (`POST /api/friends/invite`) | No | DB Invitation row only | No email, no push |
| Friend invite accepted (`POST /api/friends/invite/<id>/accept`) | No | DB only + Activity emit | No email, no push |
| Trip invite sent (`POST /trips/<id>/invite`) | No | DB SkiTripParticipant + Activity | No email, no push |
| Trip invite accepted | No | DB Activity only | No email, no push |
| Trip invite declined | No | DB Activity only | No email, no push |
| Join request sent | No | DB Invitation + Activity | No email, no push |
| Join request accepted/declined | No | DB Activity only | No email, no push |
| Pass changed | **Yes** | OneSignal Custom Event (Journey) | Deferred push via Journey |

**Summary: No social action (friend invite, trip invite, connection, join request) sends any outbound notification other than an in-app Activity row.**

### What Only Creates In-App / DB Records
Everything in the `emit_*` function family (13 activity types) creates `Activity` rows viewable on `/notifications`. No push, no email, no SMS.

### What Currently Has No Outbound Send
- Friend invite received (user receives no push or email)
- Trip invite received (user receives no push or email)
- Friend connection established (user receives no push or email)
- Trip overlap detected (user sees in home feed only)

### What Could Become Future OneSignal Journeys
These are the highest-value events to wire up:
1. **Trip invite received** — high intent; user should know immediately.
2. **Friend connection accepted** — social confirmation; good for retention.
3. **Join request received** — trip owner should be alerted.
4. **Trip overlap detected** — "You and [friend] are both free Jan 18–21" — planning value.
5. **Friend trip created** — ambient awareness; lower urgency.

---

## H. EmailLog / Tracking / State

### What Is Logged
The `EmailLog` model (`email_log` table) was designed to track:
- `user_id` — who received the email
- `email_type` — what kind of email (string)
- `source_event_id` — FK to `event` table (optional)
- `sent_at` — timestamp
- `send_count` — how many times this type was sent to this user
- `environment` — `'dev'` or `'prod'`

### Where It Is Logged
**Nowhere currently.** The `EmailLog` table exists in the database and has migration history, but no code path writes to it during any actual email send. The model is imported, and rows are deleted during account deletion, but sends are never recorded.

### Whether It Tracks Successful Delivery
No. It would need to be written to first. There is no webhook handler to capture SendGrid delivery events (bounces, opens, clicks) either.

### Whether It Would Still Be Useful After OneSignal Migration
Yes. `EmailLog` should be written to for every transactional email send regardless of provider. It supports:
- **Deduplication** — prevent sending reset email twice in a short window.
- **Suppression** — skip sending to users who recently received the same email type.
- **Audit** — record of what was sent to whom and when.
- **Debugging** — visibility into prod email volume without needing SendGrid dashboard access.

Currently the four user preference flags (`email_opt_in`, `email_transactional`, `email_social`, `email_digest`) are also never checked. Wiring `email_transactional` as a gate before sending reset/feedback emails, and writing to `EmailLog` on send, are both low-risk improvements.

---

## I. Migration Readiness

### Bucket 1: Can Move to OneSignal Soon
These items are low-risk to add OneSignal delivery for because they are currently delivering nothing outbound:

1. **Trip invite received push** — emit a `trip_invite_received` OneSignal custom event or direct push when `send_trip_invites()` runs. Wire to the existing `ActivityType.TRIP_INVITE_RECEIVED` emit point.
2. **Connection accepted push** — emit when `accept_invitation()` runs.
3. **Join request received push** — emit when `request_to_join_trip()` runs.
4. **Friend connection push** — small retention nudge; easy to add.

These all already have `Activity` rows being created; the pattern for calling `send_onesignal_push()` or `send_onesignal_custom_event()` is already established.

### Bucket 2: Should Stay As-Is For Now
1. **Password reset email (SendGrid)** — production-critical, tested, working. OneSignal email channel needs separate domain setup. Leave alone until OneSignal email is validated.
2. **Admin feedback email (SendGrid)** — ops-only. Leave alone.
3. **Direct APNs/FCM test routes** — useful for debugging and development. Leave in place but restrict or remove broadcast route.
4. **In-app Activity system** — works correctly; no reason to change. OneSignal push should augment it, not replace it.

### Bucket 3: Needs Cleanup / Product Decision First
1. **`/admin/test-push-broadcast`** — no opt-out check on `push_notifications_enabled`. Needs a safety gate before any scale.
2. **`EmailLog` — never written to** — needs a product decision: start writing to it on every send, or accept that it's unused infrastructure.
3. **Email preference flags** — `email_opt_in`, `email_transactional` etc. — never checked. Need a decision on whether to enforce them.
4. **`admin_push_diagnostics` hardcoded `target_user_id = 2`** — should accept a `?user_id=` param to be actually useful.
5. **Duplicate pass-change trigger** — two call sites (`edit_profile` and `select_pass`) both call `send_onesignal_custom_event` for `friend_pass_changed`. This is correct (they're separate routes) but should be consolidated into a shared helper if a third route is ever added.
6. **`feedback()` uses different SendGrid API form** (`sg.client.mail.send.post()`) vs `forgot_password()` (`sg.send()`). Both work; normalize to one form.

---

## J. Risks and Questions

### Open Risks

1. **Silent password reset failures.** If `SENDGRID_API_KEY` is invalid or rate-limited by SendGrid, users waiting for a reset email get nothing and no feedback. There is no retry, no fallback, and no alert to ops. Recommendation: write to `EmailLog` on every send attempt (success and failure) so this is observable.

2. **Broadcast push route with no opt-out check.** `/admin/test-push-broadcast` loops all active tokens and does not check `push_notifications_enabled`. If accidentally triggered in production with many users, it will push to opted-out users. The `send_onesignal_push()` helper does check this flag, but the broadcast route bypasses it.

3. **No SendGrid bounce or delivery webhook.** There is no inbound handler for SendGrid event webhooks. Bounced or undeliverable addresses are never marked in the database. Future email sends will keep trying invalid addresses.

4. **OneSignal SDK on iOS vs direct APNs** — both are installed. The SDK registers a separate subscription path. If a Journey and a direct APNs push both fire for the same event (once push is wired to user events), the user gets duplicate notifications. The providers must not overlap for the same trigger.

5. **No scheduled messaging infrastructure.** There is no cron, Celery, or APScheduler. All messaging is synchronous and user-action-triggered. Lifecycle emails (reminder, re-engagement, digest) cannot be built without adding a scheduler or using OneSignal's Journey time delays (which is already how `friend_pass_changed` works).

6. **`email_social` and `email_digest` default to False.** If email sends are added for social events and the flag is checked correctly, no user will receive them by default. This is likely intentional but should be confirmed before any social email is shipped.

### Open Questions Before Implementation

1. Should `send_onesignal_push()` be used for all future production push, fully replacing direct APNs/FCM? If yes, what is the plan for decommissioning the direct send infrastructure?
2. Should `EmailLog` be written to for password reset and feedback sends immediately? If yes, this is a small change and would provide immediate observability value.
3. Are email preference flags (`email_opt_in`, `email_transactional`) intended to gate the password reset email? (If so, they would need to be checked, but blocking a transactional recovery email based on an opt-out flag is generally the wrong behavior for password reset.)
4. Should the feedback email admin address (`ADMIN_FEEDBACK_EMAIL`) be documented somewhere for ops? Right now, if it is missing, feedback silently fails.
5. Is the OneSignal `friend_pass_changed` Journey configured and active in the OneSignal dashboard? The server fires the event but the Journey must exist on the OneSignal side to actually deliver a push.
6. Should `admin_push_diagnostics` and `admin_list_tokens` require a `?user_id=` parameter instead of defaulting to hardcoded IDs?
7. What is the target state for push? OneSignal for everything, or OneSignal for Journeys and direct APNs/FCM for immediate pushes?

---

## K. Recommended Next Steps

These are ordered by impact and safety. **No implementation was done during this audit.**

### Step 1 (Low risk, immediate observability): Write to `EmailLog` on every send
In `forgot_password()`, after a successful (and on failed) `sg.send()`, write an `EmailLog` row. This costs nothing, provides auditability, and enables future deduplication. Do the same in `feedback()`.

### Step 2 (Low risk, immediate value): Wire trip invite push via OneSignal
In `send_trip_invites()`, after `emit_trip_invite_received_activity()` is called, call `send_onesignal_push([friend_id], "Trip invite from [Name]", "[Name] invited you to [Mountain] – [dates]")`. Use the existing `send_onesignal_push()` helper, which already handles opt-out filtering. This is the highest-value social notification currently missing.

### Step 3 (Low risk): Wire friend connection accepted push
In `accept_invitation()`, after `emit_connection_accepted_activity()`, call `send_onesignal_push([invitation.sender_id], "New connection", "[Name] accepted your BaseLodge invite.")`.

### Step 4 (Low risk): Add safety gate to broadcast route
Add `push_notifications_enabled` check to `/admin/test-push-broadcast`, or clearly mark it as development-only with a runtime env guard.

### Step 5 (Medium effort, high value): Confirm OneSignal Journey is live
Verify in the OneSignal dashboard that the `friend_pass_changed` Journey is active, has the correct trigger event name, correct delay, and correct message copy. Run `admin_test_onesignal_push` to confirm the pipeline works end-to-end before adding more Journey events.

### Step 6 (Longer term): Evaluate SendGrid email → OneSignal email migration
Only pursue this after: OneSignal email channel is set up with SPF/DKIM/DMARC for `baselodgeapp.com`, user email addresses are imported into OneSignal as subscribers, and the password reset flow is tested in a staging environment. This is a careful migration — do not rush it.

### Step 7 (Longer term): Add scheduled lifecycle messaging
If digest, reminder, or re-engagement messaging is wanted, the server needs either: (a) a separate cron process/worker, or (b) full reliance on OneSignal Journeys with time-delay triggers. The current synchronous Flask-only architecture cannot support scheduled sends without adding infrastructure.
