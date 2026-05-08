# BaseLodge Outbound Messaging — Architectural Inventory
**Date:** May 2026  
**Type:** Read-only architectural inventory and migration-readiness assessment.  
**No code changes were made.**

---

## 0. How This Was Produced

All findings are derived from direct code inspection. Searches covered every `.py`, `.html`, `.js`, and `.md` file in the repository. Key patterns searched: all provider SDK calls, all `emit_*` and `send_*` functions, all `import` and initialization statements, all preference model fields, all DB model class definitions, all admin routes, and all scheduling/async libraries.

---

## 1. Current Outbound Messaging Entry Points

### 1A. Routes (Direct user-action triggers)

| Route | Function | What It Sends | Provider |
|-------|----------|--------------|---------|
| `POST /forgot-password` | `forgot_password()` | Password reset email | SendGrid |
| `POST /feedback` | `feedback()` | Admin feedback email | SendGrid |
| `POST /trips/<id>/invite` | `send_trip_invites()` | **Nothing outbound** — Activity row only | — |
| `POST /api/friends/invite` | `invite_friend()` | **Nothing outbound** — Invitation row only | — |
| `POST /api/friends/invite/<id>/accept` | `accept_invitation()` | **Nothing outbound** — Activity row only | — |
| `POST /trips/<id>/request-join` | `request_to_join_trip()` | **Nothing outbound** — Activity row only | — |
| `POST /trips/<id>/respond-join/<id>` | `respond_to_join_request()` | **Nothing outbound** — Activity row only | — |
| `POST /trips/<id>/respond` | `respond_to_trip_invite()` | **Nothing outbound** — Activity rows only | — |
| `POST /api/push/register-token` | `push_register_token()` | Infrastructure — stores token | DB write |
| `POST /api/push/preferences` | `push_preferences()` | Infrastructure — writes User flag | DB write |
| `POST /api/push/beacon` | `push_debug_beacon()` | Logging only | None |

### 1B. Routes (OneSignal Custom Event — Journey trigger)

| Route | Function | Event Name | Condition |
|-------|----------|-----------|-----------|
| `POST /edit-profile` | `edit_profile()` | `friend_pass_changed` | Only if pass actually changed AND user has friends |
| `POST /select-pass` | `select_pass()` | `friend_pass_changed` | Only if pass actually changed AND user has friends |

### 1C. Admin / Test Routes

| Route | Function | Provider | Risk Level |
|-------|----------|---------|-----------|
| `GET /admin/push-diagnostics` | `admin_push_diagnostics()` | None (read-only) | None |
| `GET/POST /admin/test-push` | `admin_test_push()` | APNs or FCM (auto-routed) | Low |
| `GET /admin/test-push-all` | `admin_test_push_all()` | APNs + FCM (per-platform) | Low |
| `GET /admin/test-push-broadcast` | `admin_test_push_broadcast()` | APNs + FCM (all users) | **HIGH** |
| `GET /admin/list-tokens` | `admin_list_tokens()` | None (read-only) | None |
| `GET/POST /admin/test-onesignal-push` | `admin_test_onesignal_push()` | OneSignal REST | Low |

### 1D. Services (Non-route helpers called inline by routes)

| Function | Location | Purpose | Provider |
|----------|----------|---------|---------|
| `emit_event()` | app.py:691 | Write high-signal lifecycle event to `Event` table | DB only |
| `create_activity()` | app.py:712 | Write an in-app activity row | DB only |
| `get_friend_ids()` | app.py:706 | Resolve friend ID list for fan-out | DB read |
| `send_onesignal_push()` | app.py:4413 | Send immediate push via OneSignal REST | OneSignal |
| `send_onesignal_custom_event()` | app.py:4514 | Fire Journey trigger via OneSignal Events API | OneSignal |
| `send_apns_push()` | app.py:4040 | Send iOS push via APNs HTTP/2 directly | APNs |
| `send_fcm_push()` | app.py:3962 | Send Android push via Firebase Admin SDK | FCM |

### 1E. SDK-Triggered (Client-Side)

| Trigger | File | What Happens | Result |
|---------|------|-------------|--------|
| Native app opens → `DOMContentLoaded` | `templates/components/analytics_head.html:57–365` | Capacitor `PushNotifications.register()` → OS token delivered → POST to `/api/push/register-token` | Token stored in DB |
| Same load | `analytics_head.html:367–end` | OneSignal SDK initialized → `login(userId)` → `optIn()` for subscription | OneSignal subscription registered |
| User taps notification | Native Capacitor shell | Foreground: `pushNotificationReceived` listener logs it | Console only — no server call |

### 1F. Background Jobs / Workers / Cron

**None exist.** Zero evidence of Celery, RQ, APScheduler, `threading.Thread`, `asyncio`, or any background job pattern in application code. The search for `celery`, `rq`, `apscheduler`, `BackgroundScheduler`, `asyncio`, `concurrent.futures`, and `threading` returned only library internals (werkzeug reloader, greenlet tests). All messaging is fully synchronous and request-scoped.

---

## 2. Per-Flow Architectural Properties

| Flow | Trigger | Channel | Provider | Abstraction? | Pref Checked? | Logged? | Retry? | Idempotent? | Async? |
|------|---------|---------|---------|-------------|--------------|--------|-------|-----------|-------|
| Password reset email | User POST | Email | SendGrid | Direct SDK call | No | No | No | No | No |
| Admin feedback email | User POST | Email | SendGrid | Direct SDK call | No | No | No | No | No |
| Pass-change Journey trigger (`edit_profile`) | User POST | Push (deferred) | OneSignal Events API | Helper fn | No | Warning log only | No | No | No |
| Pass-change Journey trigger (`select_pass`) | User POST | Push (deferred) | OneSignal Events API | Helper fn | No | Warning log only | No | No | No |
| Admin test push (latest token) | Admin GET/POST | Push | APNs/FCM auto-route | Helper fn | No | Warning log | APNs: yes (1 retry on wrong env) | No | No |
| Admin test push (all user tokens) | Admin GET | Push | APNs+FCM per-platform | Helper fn | No | Warning log | APNs: yes | No | No |
| Admin broadcast push | Admin GET | Push | APNs+FCM all users | Helper fn | **No — gap** | Warning log | APNs: yes | No | No |
| Admin OneSignal test push | Admin GET/POST | Push | OneSignal REST | Helper fn | Filtered | Warning log | No | No | No |
| Trip invite (Activity only) | User POST | In-app | DB | `emit_*` helper | N/A | None | N/A | Partial (duplicate check) | No |
| Connection accepted (Activity only) | User POST | In-app | DB | `emit_*` helper | N/A | None | N/A | No | No |
| Join request (Activity only) | User POST | In-app | DB | `emit_*` helper | N/A | None | N/A | No | No |
| Trip overlap (Activity only) | User POST | In-app | DB | `emit_*` helper | N/A | None | N/A | No | No |
| Availability overlap (Activity only) | User POST | In-app | DB | `emit_*` helper | N/A | None | N/A | Replace-all pattern | No |

---

## 3. Provider-Specific Dependencies

### 3A. SendGrid
```
Package:    sendgrid (imported at module top: from sendgrid import SendGridAPIClient)
            sendgrid.helpers.mail import Mail (module top)
            sendgrid.helpers.mail import Mail, Email, To, Content (lazy inside feedback())
Call sites: sg.send(message)              — forgot_password()
            sg.client.mail.send.post()    — feedback() [inconsistent form]
Env vars:   SENDGRID_API_KEY
Sender:     noreply@baselodgeapp.com (hardcoded in both send sites)
```
Two different calling styles in the same codebase. Both work; one should be the canonical form.

### 3B. OneSignal
```
Server-side:
  send_onesignal_push()          → POST https://onesignal.com/api/v1/notifications
  send_onesignal_custom_event()  → POST https://api.onesignal.com/apps/{app_id}/events (one per recipient)
  Both use: httpx.post(..., timeout=10.0) — synchronous

Client-side SDK:
  iOS:     OneSignal Capacitor Plugin v5.5.1 (XCFramework, via Podfile.lock)
  Android: onesignal-cordova-plugin (via Capacitor bridge)
  Init:    OS.initialize({ appId }) → OS.User.login(userId) → optIn()
  Bridge:  Cap.Plugins.OneSignal → Cap.registerPlugin('OneSignal') → window.plugins.OneSignal
           (three fallback paths, in priority order)

Identity:  BaseLodge user.id (integer) = OneSignal external_id
Env vars:  ONESIGNAL_APP_ID (public, injected into templates via Jinja global)
           ONESIGNAL_REST_API_KEY (secret, server-side only)
```

### 3C. APNs (Direct)
```
Auth:      JWT (ES256) via PyJWT — _apns_jwt() helper (app.py ~4015)
Transport: httpx.Client(http2=True) — one persistent connection per send call
           (not a connection pool — new context manager per call)
Host:      api.sandbox.push.apple.com (APNS_USE_SANDBOX=true)
           api.push.apple.com           (APNS_USE_SANDBOX=false)
Retry:     One automatic retry on BadEnvironmentKeyInToken or BadDeviceToken
           against the opposite host. Self-corrects token's apns_environment.
Token mgmt: Deactivates PushDeviceToken on Unregistered or 410 Gone.
            Corrects apns_environment on successful retry.
Env vars:  APNS_KEY_P8, APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_USE_SANDBOX
Call sites: admin_test_push(), admin_test_push_all(), admin_test_push_broadcast()
            — NONE from production user-action flows
```

### 3D. FCM (Direct)
```
SDK:       firebase_admin (lazy singleton: _firebase_admin_app, _get_firebase_admin())
           firebase_admin.messaging.Message + send()
Init:      Reads FIREBASE_SERVICE_ACCOUNT_JSON on first call; cached thereafter
Retry:     None
Env vars:  FIREBASE_SERVICE_ACCOUNT_JSON (full JSON string)
Call sites: admin_test_push(), admin_test_push_all(), admin_test_push_broadcast()
            — NONE from production user-action flows
```

### 3E. Capacitor Push (Client-Side)
```
Plugin:    @capacitor/push-notifications (Capacitor native plugin)
Flow:      requestPermissions() → register() → 'registration' event → POST /api/push/register-token
Platform:  Detects iOS vs Android from Cap.getPlatform()
iOS hint:  Uses Cap.DEBUG (bool) to infer apns_environment: false→production, true→sandbox
Android:   Creates 'baselodge_default' notification channel (importance=5, heads-up)
Listener:  pushNotificationReceived (foreground only) — logs notification, no action taken
Dedup:     window.__pushSetupDone flag (cleared on every full page load)
           Deliberately avoids sessionStorage (persists across WKWebView relaunches)
```

### 3F. PostHog (Analytics — Not a Messaging Provider)
```
Service:   services/analytics.py (custom wrapper around posthog library)
Calls:     ph_analytics.track(), identify(), alias(), get_anon_id()
Purpose:   Product analytics only — not an outbound notification channel
Injection: POSTHOG_KEY and POSTHOG_HOST injected as Jinja globals
           __POSTHOG_KEY__, __POSTHOG_HOST__ available in all templates via analytics_head.html
```

---

## 4. Messaging-Related Models / Tables

### `event` table — `Event` model (models.py:1147)
```
Fields:     id, event_name (str 100), user_id (FK), payload (JSON), created_at, environment
Purpose:    High-signal lifecycle event log ("profile_completed", "trip_created")
Written by: emit_event() — only 2 call sites currently
            edit_profile() → 'profile_completed'
            create_trip()  → 'trip_created'
Read by:    EmailLog.source_event_id FK (FK exists, but EmailLog is never written to)
Guard:      Skips seeded users (user.is_seeded)
```

### `email_log` table — `EmailLog` model (models.py:1162)
```
Fields:     id, user_id (FK), email_type (str 100), source_event_id (FK event),
            sent_at, send_count, environment
Purpose:    Designed for email send tracking, deduplication, suppression
Written by: NOWHERE — table exists, model exists, never written during sends
Read by:    Deleted during account deletion only
Gap:        Both password reset and feedback sends skip logging entirely
```

### `activity` table — `Activity` model (models.py:1199)
```
Fields:     id, actor_user_id (FK), recipient_user_id (FK), type (str),
            object_type (str), object_id (int), created_at, extra_data (JSON)
Purpose:    In-app notification feed visible on /notifications
Types:      15 ActivityType enum values (see below)
Written by: 15 emit_*() helper functions, create_activity() primitive
Read by:    /notifications route, inject_notif_count context processor (every page),
            Home feed (happenings/opportunities sections)
Outbound:   NONE — purely display layer
```

**ActivityType values and their emission points:**
```
TRIP_CREATED              → emit_trip_created_activities()       → called from create_trip(), create_trip_page(), group trip creation
TRIP_UPDATED              → emit_trip_updated_activities()       → called from edit_trip() on date change
TRIP_LOCATION_CHANGED     → emit_trip_location_changed_activities() → called from edit_trip() on resort change
TRIP_PASS_CHANGED         → emit_trip_pass_changed_activities()  → called from edit_trip() on pass change (in-app only; OneSignal event fires separately)
TRIP_OVERLAP              → check_and_emit_trip_overlap_activities() → called by emit_trip_created/updated/location_changed
FRIEND_TRIP_OVERLAPS_AVAILABILITY → emit_availability_overlap_activities_for_user/trip() → called on availability save + trip create/edit
FRIEND_JOINED_TRIP        → emit_friend_joined_trip_activities()  → called from respond_to_trip_invite() on accept
TRIP_INVITE_RECEIVED      → emit_trip_invite_received_activity()  → called from send_trip_invites()
TRIP_INVITE_ACCEPTED      → emit_trip_invite_accepted_activity()  → called from respond_to_trip_invite() on accept
TRIP_INVITE_DECLINED      → emit_trip_invite_declined_activity()  → called from respond_to_trip_invite() on decline
CONNECTION_ACCEPTED       → emit_connection_accepted_activity()   → called from accept_invitation(), connect_add()
CARPOOL_OFFERED           → emit_carpool_activity()               → called from update_participant_signals() on driver role set
JOIN_REQUEST_RECEIVED     → create_activity() inline             → called from request_to_join_trip()
JOIN_REQUEST_ACCEPTED     → create_activity() inline             → called from respond_to_join_request()
JOIN_REQUEST_DECLINED     → create_activity() inline             → called from respond_to_join_request()
```

### `push_device_token` table — `PushDeviceToken` model (models.py:1229)
```
Fields:     id, user_id (FK), token (str 512), platform (ios|android),
            active (bool), apns_environment (sandbox|production|unknown|n/a),
            created_at, updated_at
Constraint: UNIQUE (user_id, token)
Written by: push_register_token() on every app open (upsert)
            send_apns_push() → marks active=False on Unregistered/410, corrects apns_environment on retry
Read by:    All 3 admin test push routes, admin_push_diagnostics, admin_list_tokens
Cleanup:    Deleted during account deletion
```

### `User` — preference fields
```
email_opt_in             (bool, default=True)  — Never checked before email send
email_transactional      (bool, default=True)  — Never checked before email send
email_social             (bool, default=False) — Never checked; no social emails exist yet
email_digest             (bool, default=False) — Never checked; no digest emails exist yet
push_notifications_enabled (bool, default=True) — Checked only by send_onesignal_push()
                                                   NOT checked by APNs/FCM direct or broadcast
```

---

## 5. Event-Driven Patterns Currently in the Codebase

### What Exists

**Pattern 1: `emit_event()` → `Event` table (CRM event log)**
```
emit_event(event_name, user, payload=None)
  ↓ skips if user.is_seeded
  ↓ writes Event row (event_name, user_id, payload, environment)
  ↓ db.session.commit()
  → No downstream consumers exist today
  → Designed as a trigger source for future email/notification workflows
```
This is an event-emitter in intent but not in behavior. It has no subscribers. It writes to `Event` table which is connected to `EmailLog` via `source_event_id` FK, but `EmailLog` is never written to, so the link is unused.

**Pattern 2: `emit_*_activities()` → `Activity` table (in-app feed)**
```
emit_trip_created_activities(trip, actor_user_id)
  ↓ get_friend_ids(actor_user_id)                    [DB read]
  ↓ create_activity(actor, recipient, type, ...)     [DB write, no commit]
  ↓ check_and_emit_trip_overlap_activities(...)       [recursive fan-out]
  ↓ emit_availability_overlap_activities_for_trip()   [recursive fan-out per friend]
  → in-app Activity rows only, no outbound
```
This is a synchronous, in-request fan-out pattern. For a user with N friends, `emit_trip_created_activities()` can trigger O(N²) DB operations (N friends × M each having open_dates checked for overlaps). No consumer reads the Activity table for outbound delivery — it's display-only.

**Pattern 3: `send_onesignal_custom_event()` → OneSignal Journey (deferred push)**
```
send_onesignal_custom_event(user_ids, "friend_pass_changed", properties={...})
  ↓ for each uid: POST to OneSignal Events API   [synchronous, N HTTP calls]
  ↓ OneSignal handles Journey scheduling, targeting, delivery
  → deferred push to friends via Journey
```
This is the closest thing to an event-driven outbound pattern. The Journey is external — it lives in the OneSignal dashboard, not in code.

### What Does NOT Exist
- No Blinker signals, Flask signals, or any signal/event bus
- No pub/sub (Redis channels, etc.)
- No observers or hooks
- No queue (Celery, RQ, SQS, etc.)
- No async jobs or deferred tasks
- No event consumers or subscribers in application code
- No webhook handlers (incoming SendGrid delivery events, OneSignal delivery callbacks)

---

## 6. Admin / Test / Broadcast Tooling

| Tool | Route | What It Does | Safety Issues |
|------|-------|-------------|--------------|
| Push diagnostics | `GET /admin/push-diagnostics` | Read-only JSON — APNs config, token list, instructions | `target_user_id` hardcoded to 2 |
| Test push (latest) | `GET/POST /admin/test-push` | Sends to most recently updated active token for `?user_id=` param | Low risk — targeted |
| Test push (all for user) | `GET /admin/test-push-all` | Sends to ALL active tokens for current admin user | Low risk — self-targeted |
| Broadcast push | `GET /admin/test-push-broadcast` | Sends to **every active token in the database** | **No opt-out check on push_notifications_enabled. No per-user consent check.** |
| OneSignal test | `GET/POST /admin/test-onesignal-push` | Sends OneSignal push to calling admin | Filtered by send_onesignal_push() opt-out logic |
| List tokens | `GET /admin/list-tokens` | Read-only — token list for `?user_id=` | Safe |

**Unsafe tooling detail — `/admin/test-push-broadcast`:**
- Loops every `PushDeviceToken` where `active=True` across all users.
- Routes each token to APNs or FCM directly.
- Does **not** check `User.push_notifications_enabled`.
- Does **not** check any email or push preference field.
- Produces a JSON result with every token's send status and a preview.
- Protected by `@admin_required` decorator only.
- No rate limit beyond admin session control.

---

## 7. Preference Enforcement: Current State and Gaps

### What Is Enforced

| Preference | Where Enforced | How |
|-----------|---------------|-----|
| `push_notifications_enabled` | `send_onesignal_push()` (app.py:4444–4458) | DB query filters opted-out user IDs before building external_id list |

### What Is NOT Enforced (Gaps)

| Preference | Gap Description | Risk |
|-----------|----------------|------|
| `push_notifications_enabled` | APNs direct push (admin test and any future production path) does not check this flag | Sends to opted-out users when using direct APNs |
| `push_notifications_enabled` | Broadcast route does not check this flag | Sends to opted-out users at scale |
| `push_notifications_enabled` | `send_onesignal_custom_event()` does not filter by this flag (relies on Journey settings) | Users who opted out server-side but are still OneSignal subscribers may receive Journey pushes |
| `email_opt_in` | Never checked before any email send | Opted-out users can receive password reset (arguably correct) and feedback confirmation |
| `email_transactional` | Never checked | Intended gate for transactional emails; currently inert |
| `email_social` | Never checked | No social emails exist yet; flag is future infrastructure |
| `email_digest` | Never checked | No digest emails exist yet; flag is future infrastructure |

### Why `email_opt_in` Probably Should Not Gate Password Reset
Password reset is a security-recovery flow, not a marketing email. Industry standard is to always send it regardless of marketing opt-out. However, `email_transactional` should be the gate, and it is not. This is a schema gap worth resolving before any lifecycle emails are built on top of the same model.

---

## 8. Async / Background Infrastructure

### Current State

**There is no async or background processing infrastructure.**

All messaging operations execute synchronously within the Flask request handler:
- `SendGridAPIClient(key).send(message)` — blocks until SendGrid responds
- `httpx.post(onesignal_url, ...)` — blocks until OneSignal responds (up to 10s timeout)
- `httpx.Client(http2=True).post(apns_url, ...)` — blocks until APNs responds (10s timeout)
- `firebase_admin.messaging.send(message)` — blocks until FCM responds
- Every `emit_*_activities()` call — DB writes committed before response returns

**Implications:**
1. A slow OneSignal response (or timeout) adds up to 10 seconds to the user's page load.
2. If a user has many friends and `send_onesignal_custom_event()` fires (1 HTTP call per friend), the request latency scales linearly with friend count.
3. There is no retry queue — if a send fails, it is lost.
4. There is no way to schedule a future send (e.g., "send this push in 30 minutes") from application code without an external scheduler.

**Current workaround for scheduling:** OneSignal Journeys handle time-based delays for the `friend_pass_changed` event. This is the only form of "scheduled" messaging, and it lives entirely in the OneSignal dashboard, not in code.

### Scheduler / Queue Libraries in `requirements.txt`
```
None found. No celery, rq, apscheduler, dramatiq, huey, or similar in requirements.
```

---

## 9. Architecture Diagram — Current State

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  USER ACTION (browser / native app)                                         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ HTTP request
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  FLASK ROUTE HANDLER (app.py — 12,758 lines, monolithic)                    │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Business logic (validate, write DB, compute overlaps, etc.)          │  │
│  └─────┬──────────────────────┬───────────────────────┬──────────────────┘  │
│        │                      │                       │                     │
│        ▼                      ▼                       ▼                     │
│  ┌──────────────┐   ┌──────────────────┐   ┌───────────────────────────┐   │
│  │ emit_event() │   │ emit_*_activity() │   │ send_onesignal_custom_    │   │
│  │ (CRM log)    │   │ (in-app feed)     │   │ event() / send_onesignal_ │   │
│  └──────┬───────┘   └────────┬─────────┘   │ push() / send_apns_push() │   │
│         │                    │             │ / send_fcm_push()          │   │
│         ▼                    ▼             └──────────┬────────────────┘   │
│   event table          activity table                 │                     │
│   (written to)         (written to)                   │ SYNCHRONOUS         │
│   (nothing reads it)   (rendered in /notifications)   │ HTTP call           │
│                                                       │ (blocks request)    │
└───────────────────────────────────────────────────────┼─────────────────────┘
                                                        │
                       ┌────────────────────────────────┤
                       │                                │
          ┌────────────▼──────────┐   ┌────────────────▼──────────────┐
          │   SendGrid REST API   │   │   OneSignal REST API           │
          │   (email)             │   │   /v1/notifications (push)     │
          │   sg.send() or        │   │   /apps/{id}/events (Journey)  │
          │   sg.client.mail...   │   │   Payload per-user, N posts    │
          └───────────────────────┘   └──────────────────┬────────────┘
                                                         │ OneSignal routes
                                      ┌──────────────────┼────────────────────┐
                                      ▼                  ▼                    ▼
                               APNs gateway         FCM gateway        Journey engine
                               (iOS delivery)    (Android delivery)  (scheduled sends)

┌─────────────────────────────────────────────────────────────────────────────┐
│  NATIVE APP (iOS / Android — Capacitor shell)                               │
│                                                                             │
│  DOMContentLoaded:                                                          │
│    → APNs path:     PushNotifications.register() → token → POST /api/push/  │
│                     register-token (httpx stores in push_device_token)      │
│    → OneSignal path: OS.initialize() → OS.User.login(userId) → optIn()     │
│                     (OneSignal handles its own subscription internally)      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  DATABASE                                                                   │
│                                                                             │
│  event           ← lifecycle signals (profile_completed, trip_created)      │
│  email_log       ← EMPTY (never written to; schema exists)                  │
│  activity        ← in-app feed (15 types; never triggers outbound)          │
│  push_device_token ← APNs+FCM tokens (active/inactive, env-aware)           │
│  user.*          ← email_opt_in, email_transactional, email_social,         │
│                    email_digest, push_notifications_enabled                  │
│                    (only push_notifications_enabled is ever consulted)       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Coupling Risks

### Risk 1: All messaging logic is directly in route handlers (HIGHEST)
There is no messaging service, no abstraction layer, and no indirection. Every `send_*` and `emit_*` call is a bare function call inside a route handler. Adding any new notification type requires editing the route function body. This creates:
- No single place to enable/disable a channel
- No single place to add logging, retry, or opt-out checking
- No testability without firing actual sends or mocking individual functions
- Merge conflicts when multiple features touch the same route

### Risk 2: Synchronous HTTP calls block user-facing requests (HIGH)
`send_onesignal_custom_event()` fires one POST per friend synchronously. A user with 20 friends changing their pass triggers 20 sequential HTTP calls inside the request that saves their profile. At 200ms per call, that's 4 seconds of added latency, invisible to the user but real. This will degrade as user count grows.

### Risk 3: Three separate push providers may double-deliver (HIGH)
APNs direct, FCM direct, and OneSignal REST all coexist. Once production push is wired to user-action events, if both a direct APNs call and a OneSignal call fire for the same event, the user gets two notifications. There is no deduplication layer and no single gate. The direct APNs/FCM code is ready to be called from production routes — it's only admin-gated today, not architecturally separated.

### Risk 4: Broadcast route has no opt-out check (HIGH)
`/admin/test-push-broadcast` can push to opted-out users. When production push volume grows, this becomes a compliance risk. The route is behind `@admin_required` but not behind a dev-only env guard.

### Risk 5: EmailLog is dead infrastructure (MEDIUM)
The `event → email_log` pipeline was designed for deduplication and suppression but nothing writes to it. Any future email-sending code built without first fixing this gap will produce duplicate sends and have no audit trail. The schema is right; the write calls are missing.

### Risk 6: `send_onesignal_custom_event()` scales linearly but silently (MEDIUM)
Each call iterates `user_ids` and fires one HTTP POST per user. If this function is ever called with a large friend group (50+ friends), 50 sequential HTTP requests fire inside a single Flask request. There is no batching, no queue, no backpressure.

### Risk 7: Two different SendGrid calling styles (LOW)
`forgot_password()` uses `sg.send(message)`. `feedback()` uses `sg.client.mail.send.post()`. Both work, but the inconsistency means future email sends will have no canonical pattern to copy from.

### Risk 8: APNs JWT is recreated per send, not cached (LOW)
`_apns_jwt()` generates a new JWT on every call to `send_apns_push()`. Apple's APNs requires token refresh no more than once per hour. Creating a new token per call is wasteful once push is at production volume. Caching it for ~50 minutes would be more efficient.

---

## 11. Easiest Wins

These can be done with small, safe, isolated changes to the calling site only:

1. **Write to `EmailLog` on every send.** 2 call sites. Copy the same pattern: after `sg.send()` succeeds, write an `EmailLog` row. This immediately provides audit trail, enables future deduplication, and costs nothing.

2. **Fix `send_onesignal_custom_event()` to also filter by `push_notifications_enabled`.** One change to the function body, consistent with what `send_onesignal_push()` already does.

3. **Add opt-out check to `/admin/test-push-broadcast`.** One DB query at the top of the route. Prevents opted-out users from being hit by broadcast.

4. **Add production guard to `/admin/test-push-broadcast`.** If `is_production: return jsonify({"error": "not_available_in_production"}), 403`. Prevents accidental mass-push.

5. **Wire `send_onesignal_push()` to `TRIP_INVITE_RECEIVED`** — highest value missing push. One call added to `send_trip_invites()` after the Activity row emit. Completely additive, no existing behavior changes.

6. **Make `admin_push_diagnostics` accept `?user_id=` param.** Target user is currently hardcoded to `2`. One-line change.

7. **Normalize SendGrid calling style.** Change `feedback()` to use `sg.send(mail)` like `forgot_password()` does. Cosmetic but removes inconsistency.

---

## 12. Hardest Future Migration Risks

1. **No async infrastructure exists.** Adding Celery, RQ, or any task queue requires: a new service (Redis or similar), new process management, new deployment configuration, and rewriting all send call sites to enqueue tasks instead of calling synchronously. This is a multi-day infrastructure change with deployment impact.

2. **Direct APNs/FCM vs OneSignal overlap.** If OneSignal becomes the sole push provider, the APNs/FCM direct code must be fully removed (not just admin-gated). Until that happens, there is a permanent risk of accidental double-delivery once production events start firing. The removal requires confirming OneSignal handles all platforms reliably, then finding and auditing all call sites.

3. **Migrating password reset email to OneSignal.** Requires: OneSignal email channel setup for `baselodgeapp.com` (SPF, DKIM, DMARC), importing user email addresses into OneSignal as subscribers, building an email template in the OneSignal dashboard, and testing token-based recovery through a completely different delivery path. High risk, low urgency.

4. **`send_onesignal_custom_event()` N-HTTP-call fan-out.** The current pattern (one POST per user) is the only way OneSignal's Events API works — it does not accept batches. If friend networks grow large, this either needs a task queue (enqueue one job per event) or a different approach (Journey segments, audience-based rather than explicit ID lists).

5. **`emit_*_activities()` fan-out has potential O(N²) DB cost.** `emit_trip_created_activities()` calls `emit_availability_overlap_activities_for_trip()` which calls `emit_availability_overlap_activities_for_user()` for each friend. This iterates all of a friend's open dates and all of their friends' trips. For dense social graphs, this is an unbounded computation happening synchronously in-request. Mitigating this requires either a background job or a change to the Activity generation model.

---

## 13. Recommended Insertion Point for a Centralized `emit_event()` Service

### Current State of `emit_event()`
There is already a function named `emit_event()` (app.py:691). But it only writes to the `Event` table (CRM event log). It has no downstream consumers, no routing logic, and no channel dispatch. It is a hook that was built but never connected.

### What the Centralized Version Should Do
The existing `emit_event()` is the right insertion point. It should be expanded — not replaced — into a unified dispatch function:

```
emit_event(event_name, user, payload=None)
  ↓
  1. Write Event row (existing behavior — keep)
  2. Check event_name against a dispatch table
  3. For each registered handler:
       → in-app: create_activity(...)   (existing behavior, moved here)
       → email:  queue_email_send(user, template, ...)   (new)
       → push:   queue_push_send(user_ids, title, body)  (new)
  4. Handlers should be non-blocking (enqueue, don't send inline)
```

### Why This Is the Right Insertion Point

1. **It already exists** and is called from the right places (after DB commit, before response).
2. **It already has a seeded-user guard** (`if user.is_seeded: return`). All handlers inherit this.
3. **It already has an `event` table write** — this can become the audit log for every outbound dispatch.
4. **The name matches intent** — "emit an event" is the correct model for decoupled notification dispatch.
5. **Route handlers don't need to change** — they already call `emit_event()`. New notification behaviors are registered in the dispatch table, not in route bodies.

### What Must Stay Separate (Should Not Go Through `emit_event()`)
- **Password reset email** — not a lifecycle event; it's a transactional recovery flow with a specific user-provided email address. Keep it direct.
- **Admin feedback email** — ops channel, not a user notification.
- **Push token registration** — infrastructure, not an event.
- **Admin test push routes** — tooling, not application flow.

### What Currently Bypasses `emit_event()` (Should Route Through It)
- `send_onesignal_custom_event()` for pass changes — currently called directly from route handlers. Should become a handler registered to the `friend_pass_changed` event (or `profile_completed` + pass-changed field detection).
- All `emit_*_activities()` functions — currently called directly from route handlers. Could be registered as in-app handlers in the dispatch table, centralizing the fan-out logic.

### Step-by-Step Insertion Plan (Not an Implementation)
1. Add a dispatch registry dict to `emit_event()`: `EVENT_HANDLERS = {event_name: [handler_fn, ...]}`.
2. After the existing Event row write, iterate registered handlers for the event name.
3. Move the current direct `send_onesignal_custom_event()` call for pass changes into a registered handler.
4. When a task queue is added later, replace `handler_fn(...)` calls with `queue_task(handler_fn, ...)` — one change in `emit_event()` makes all handlers async.

---

## 14. What Can Remain Untouched Initially vs. What Must Be Addressed Early

### Untouched for Now (Stable, Low Risk)
- Password reset email via SendGrid — works correctly, not broken
- Admin feedback email via SendGrid — niche, low volume
- APNs direct push infrastructure — well-built, environment-aware; keep for admin diagnostics
- FCM direct push infrastructure — same as APNs; keep for admin diagnostics
- In-app Activity system — works correctly; rendering, badge count, notification page all good
- OneSignal SDK client-side initialization — working; do not change
- Token registration pipeline — working correctly; idempotent upsert, environment-aware
- `emit_event()` for CRM log writes — harmless, keep and expand

### Must Be Addressed Before Adding More Outbound Messaging
These gaps will cause real problems the moment more notification types are added:

1. **`EmailLog` must be written to.** Before any second email type is built, the first two sends (password reset, feedback) need to write to it. Otherwise deduplication and audit trail will be impossible to retrofit.

2. **`send_onesignal_custom_event()` must filter by `push_notifications_enabled`.** Currently it doesn't. Adding more Journey triggers without fixing this will notify opted-out users.

3. **`/admin/test-push-broadcast` must get an opt-out check and a production guard.** As push volume grows, this route becomes a liability.

4. **Synchronous HTTP calls in the profile save request must move out of band.** Before `send_onesignal_custom_event()` is called for more events with more recipients, the blocking HTTP fan-out must either be bounded or made async. The current 10-friend limit is fine; a 100-friend limit is not.

5. **Push provider overlap must be architecturally resolved.** A decision must be made: is OneSignal the production push provider, or is direct APNs/FCM? Both code paths must not fire for the same event. Write this decision down and enforce it at the code level (comments + a single dispatch path), even before the non-production path is removed.

6. **A canonical `emit_event()` dispatch table should be established** before any new notification type is wired. Without it, each new type is another direct call scattered across another route body, compounding the coupling risk indefinitely.
