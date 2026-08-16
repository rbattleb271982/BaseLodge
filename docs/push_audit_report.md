# BaseLodge Push Notification System — Full Audit Report
_Generated: 2026-08-16_

---

## Executive Summary

BaseLodge has a **functioning push notification pipeline** for the majority of events and users. The **primary failure** is a OneSignal SDK v5.3.8 race condition that places the developer's own iPhone subscription (external_id="2", subscription `f10dcf69`) into a locked disabled state (`notification_types=-30`) on every cold app launch, making it impossible to self-test push delivery from that device. The pipeline itself is architecturally sound. Eleven separate event types have successfully delivered pushes in production. The SDK race has no currently deployed fix; a device-validated workaround is still needed.

---

## Section 1 — Architecture

Two independent push systems run in parallel on every page load inside the native iOS/Android shell:

### System A: Capacitor PushNotifications (APNs/FCM Direct)

- **File:** `static/js/bl-native.js` lines 144–575
- **Role:** Registers the OS-issued APNs token with BaseLodge's own DB at `/api/push/register-token`
- **Flow:** `PushNotifications.addListener('registration')` → POST `/api/push/register-token` → stored in `push_device_tokens` table
- **Token store hygiene:** Only 1 active token per platform per user is allowed. On re-registration, all other active tokens for that user+platform are deactivated.
- **BaseLodge DB is NOT used for delivery.** It is a diagnostic aid and a pre-flight check gate (see Section 4).
- **This system is working correctly.** Token id=137 (`4DDC89DF`, env=sandbox, active=True) was updated 2026-08-16 02:37:53 — healthy.

### System B: OneSignal Cordova Plugin v5.3.8

- **File:** `static/js/bl-native.js` lines 577–959
- **Role:** Registers the device as a OneSignal subscription (by external_id = user's DB id) and delivers all push notifications
- **Init sequence:**
  1. `OS.initialize(appId)` — sets up the SDK, fires `optOut()` async if permission state is `not_determined`
  2. `OS.login(userId)` — links subscription to `external_id`
  3. `OS.Notifications.requestPermission(true)` — requests OS permission (already-granted paths skip the dialog)
- **Delivery:** All production pushes go through OneSignal REST API at `https://api.onesignal.com/notifications`

### Push-tap routing

- **File:** `static/js/bl-native.js` lines 961–1194
- `_extractPushUrl(notification)` reads `notification.additionalData.url || notification.launchURL`
- `_doNavFromPush(url)` applies `window.location.href = url`
- Every `EventSpec` in `message_dispatch.py` includes a `push_data.url` that feeds `additionalData`

---

## Section 2 — OneSignal Server State (Critical)

**Lookup URL:** `GET /apps/{app_id}/users/by/external_id/2`  
**Result:** HTTP 200 — user exists with OneSignal ID `19af6c81-0bfe-4819-a258-21906a4d6361`

| Subscription ID | Type | Token prefix | enabled | notification_types | Device | session_count |
|---|---|---|---|---|---|---|
| `f10dcf69` | iOSPush | `4ddc89df` | **false** | **-30** | iPhone16,1 / iOS 26.5.2 | 319 |
| `d742f79b` | iOSPush | `d7e8144f` | false | -2 | iPhone16,1 / iOS 26.4.2 | 2 |
| `dc044eb2` | AndroidPush | `fKOElz8o` | **true** | **1** | SM-A166U1 (Samsung Galaxy A16) | 12 |
| `aa58b5db` | iOSPush | _(empty)_ | false | -10 | iPhone16,1 / iOS 26.4.2 | 61 |
| `02afd4cd` | iOSPush | `5d918361` | false | -30 | iPhone16,1 / iOS 26.4.2 | 8 |
| `8e043033` | iOSPush | _(empty)_ | false | -10 | iPhone16,1 / iOS 26.4.2 | 21 |
| `f5c7980a` | AndroidPush | _(empty)_ | false | -10 | — | 3 |

### notification_types legend
| Value | Meaning |
|---|---|
| 1 | All enabled |
| -2 | Notifications disabled at OS level (user denied) |
| -10 | Subscription has no token (registration incomplete) |
| -30 | SDK-locked optOut state — set by `OS.initialize()` background optOut() call |

### Root cause of `invalid_aliases` on test sends

Sending to `external_id="2"` returns `{"errors": {"invalid_aliases": {"external_id": ["2","2","2","2","2"]}}}`. OneSignal reports 5 invalid aliases, one per disabled iOS subscription. The Android subscription (`dc044eb2`) is nominally `enabled=true`, but delivery tests still fail — most likely because the FCM token for the Samsung Galaxy A16 has expired at Google's FCM (device not used in weeks, last registered 2026-05-09). OneSignal's internal enabled flag reflects the last SDK state, not FCM reachability. When all subscriptions fail delivery, OneSignal returns `invalid_aliases` for the entire send.

**Conclusion:** `external_id="2"` EXISTS in OneSignal. `invalid_aliases` is returned because there is no currently deliverable subscription linked to it. The iPhone sub is SDK-disabled (-30); the Android sub's FCM token is stale.

### The SDK optOut() race (root cause of -30 state)

On every cold launch, `OS.initialize(appId)` fires an async `optOut()` call internally when the OneSignal SDK's persisted permission state is `not_determined`. This sets `notification_types=-30` on the server. The native source (`OneSignalPush.m`) confirms `requestPermission()` has no `initDone` guard — it can be called before `initialize()` — but physical device testing proved that calling `requestPermission()` before `initialize()` prevents `initialize()` from completing. No durable client-side fix has been device-validated.

---

## Section 3 — BaseLodge Database State (user_id=2)

| Field | Value |
|---|---|
| `push_notifications_enabled` | **True** |
| Active iOS token (id=137) | `4DDC89DF…` env=sandbox updated=2026-08-16 02:37:53 |
| Total token rows | 31 (30 inactive, 1 active) |
| Active Android token | **None** |

**Mismatch:** BaseLodge's own records say "push is enabled and device is registered". OneSignal's server says "all subscriptions are disabled". The pre-flight check in `send_onesignal_push()` passes (active token exists) but OneSignal then returns `invalid_aliases`. This mismatch is the user-visible symptom: logs show the send was attempted, but no notification arrives.

---

## Section 4 — Send Pipeline Walkthrough

```
emit_messaging_event(event_name, actor, recipient, metadata)
    └─ _get_event_spec(event_name)                          # looks up _EVENT_REGISTRY
    └─ spec.delivery_strategy == IMMEDIATE_PUSH
        └─ _dispatch_immediate_push()
            ├─ spec.render_push(metadata)                   # builds title + body + push_data.url
            ├─ is_duplicate_event()                         # DEDUPE_WINDOW_SECONDS=3600
            ├─ send_onesignal_push(user_ids=[recipient_id])
            │   ├─ user.push_notifications_enabled == False → skip (user_opted_out)
            │   ├─ no active PushDeviceToken → skip (no_device_token)       ← PRE-FLIGHT CHECK
            │   ├─ POST api.onesignal.com/notifications
            │   │   ├─ include_aliases: {external_id: [str(id)]}
            │   │   ├─ target_channel: "push"
            │   │   └─ contents, headings, data: {url: ...}
            │   ├─ HTTP 200 + no errors → success (sent)
            │   └─ errors.invalid_aliases only → skipped (channel_unavailable)
            └─ write MessageEventLog row
```

### Key guards and their effectiveness
| Guard | Purpose | Working? |
|---|---|---|
| `push_notifications_enabled` check | User preference gate | ✅ Yes |
| Active token pre-flight | Skip if no device in DB | ✅ Yes — prevents wasted API calls |
| Deduplication window (1h) | Prevents notification spam | ✅ Yes |
| `invalid_aliases` classification | Don't count as provider failure | ✅ Yes — skipped not failed |

---

## Section 5 — Event Registry and Emission Health

### Events registered in `_EVENT_REGISTRY` (message_dispatch.py)

| EventName | Strategy | Push URL | Emitted? | MEL sent count |
|---|---|---|---|---|
| `friend.request.created` | IMMEDIATE_PUSH | `/friends?requests=1` | ✅ Yes (create_friend_request) | 8 |
| `friend.request.accepted` | IMMEDIATE_PUSH | `/friends/{actor_user_id}` | ✅ Yes (accept_invitation) | 3 |
| `trip.invite.created` | IMMEDIATE_PUSH | `/trips` | ✅ Yes (create_trip) | 11 |
| `trip.invite.accepted` | IMMEDIATE_PUSH | `/trips` | ✅ Yes | 3 |
| `trip.invite.declined` | IMMEDIATE_PUSH | `/trips` | ⚠️ Registered but 0 sent rows; 1 old silent_by_design row in MEL |
| `trip.participant.added` | IMMEDIATE_PUSH | `/trips` | ✅ Yes (two call sites) | 0 sent (all sent rows predate MEL) |
| `trip.participant.left` | IMMEDIATE_PUSH | `/trips` | ✅ Yes | 1 |
| `trip.cancelled` | IMMEDIATE_PUSH | `/trips` | ✅ Yes (2 call sites) | 0 (2 channel_unavailable) |
| `trip.dates.updated` | IMMEDIATE_PUSH | `/trips/{trip_id}` | ✅ Yes | 0 (all deduped?) |
| `trip.resort.updated` | IMMEDIATE_PUSH | `/trips/{trip_id}` | ✅ Yes | 0 |
| `trip.details.updated` | IMMEDIATE_PUSH | `/trips/{trip_id}` | ✅ Yes | 2 |
| `trip.accommodation.updated` | IMMEDIATE_PUSH | `/trips/{trip_id}` | ✅ Yes | 3 |
| `trip.planning_post.created` | IMMEDIATE_PUSH | `/trips/{entity_id}/planning` | ✅ Yes | 2 |
| `trip.join.requested` | IMMEDIATE_PUSH | `/trips` | ✅ Registered, code exists (line 13628) | 0 (never triggered in MEL) |
| `friend.pass.changed` | AUTOMATION_EVENT | _(OneSignal Journey)_ | ✅ Yes | 0 sent / **78 failed** |
| `overlap.detected` | SILENT | — | ✅ Yes (3 call sites) | logged only |
| `friend.trip.created` | SILENT | — | Likely yes | not confirmed |
| `friend.trip.updated` | SILENT | — | Likely yes | not confirmed |
| `wishlist.match.detected` | SILENT | — | ✅ Yes | 3 old SENT rows (legacy path, now silent) |
| `digest.weekly.generated` | SILENT | — | Unknown | not confirmed |

### Out-of-band direct sends (bypass registry)

| Purpose | File/Line | Recipient | Notes |
|---|---|---|---|
| Suggested Friends daily | `app.py:9631` | current_user | 12-hour cooldown; directly calls `send_onesignal_push` |
| Founder new-user alert | `app.py:3957` | richard (user_id=2) | Direct send; no MEL |
| Founder app-open alert | `app.py:4010` | richard (user_id=2) | Direct send; no MEL |
| Admin test-push | `app.py:18624` | specified user | Uses `PUSH_TEST_SENT` EventName; writes MEL |
| Admin retry runner | `app.py:19036` | original recipient | Re-runs failed MEL rows |

---

## Section 6 — MEL Delivery Health Matrix

All-time delivery statistics from `message_event_log`:

| Status | Count | Assessment |
|---|---|---|
| `sent` | 116 | ✅ Good — working pipeline |
| `skipped/duplicate_event` | 44 | ✅ Expected — dedup working |
| `skipped/channel_unavailable` | 9 | ⚠️ OneSignal disabled subscriptions |
| `skipped/no_device_token` | 9 | ⚠️ User never registered a device token |
| `skipped/user_opted_out` | 8 | ✅ Expected — respecting preferences |
| `skipped/not_implemented` | 7 | ℹ️ Old events before registry was complete |
| `skipped/silent_by_design` | 3 | ✅ Expected — SILENT events |
| `skipped/digest_only` | 2 | ℹ️ Legacy |
| `failed` | 89 | ❌ Needs investigation |

### Failed breakdown
- **78 `friend.pass.changed` failures** — All AUTOMATION_EVENT path. `send_onesignal_custom_event()` calls `https://api.onesignal.com/apps/{id}/events` for OneSignal Journeys. Zero successes ever. **The OneSignal Journey for this event is either not configured or was deleted in the OneSignal dashboard.** These are guaranteed failures until a Journey is set up.
- **4 `friend.request.accepted` failed** — IMMEDIATE_PUSH path. These predate the `invalid_aliases` classification fix; they would be `channel_unavailable` skips under current code.
- **4 `trip.invite.created` failed** — Same era.
- **3 `trip.invite.accepted` failed** — Same era.
- **1 `push.broadcast.sent` failed** — Admin broadcast; likely one-off config error.
- **8 `push.test.sent` failed** — Admin test pushes to user_id=2 (the `invalid_aliases` issue confirmed).

---

## Section 7 — Test Coverage

| Test file | Lines | What it covers |
|---|---|---|
| `test_push_lifecycle.py` | 323 | Token register/refresh, dedup, invalid_aliases classification, mixed errors, success path |
| `tests/test_bl12_suggested_friends.py` | 708 | Suggested Friends notification cooldown, opt-out logic |
| `tests/test_join_request_notification.py` | 257 | Trip join request notifications |
| `tests/test_bl268_push_routing.js` | — | JS push-tap routing (Jest) |

440 tests pass. Coverage is solid for the server-side send pipeline. There is **no test** for the SDK optOut() race because it is a native iOS-only runtime behavior that cannot be unit-tested from Python.

---

## Section 8 — Code Quality

### Strengths
- Clean separation between dispatch (message_dispatch.py), send (push_providers.py), and audit (message_events.py)
- Every event produces exactly one MEL row — full audit trail
- `send_onesignal_push()` never raises; errors are returned as structured dicts
- Token hygiene: only 1 active token per user+platform enforced at registration time
- `invalid_aliases` correctly classified as `channel_unavailable` (skip, not fail)
- Deduplication window prevents notification storms
- Pre-flight token check prevents OneSignal API calls for users with no device

### Issues
1. **`friend.pass.changed` / AUTOMATION_EVENT — 78 consecutive failures.** OneSignal Journey not configured. Should suppress after N failures or degrade gracefully with a warning in logs. Currently fills MEL with useless failed rows.
2. **Founder alert direct calls bypass MEL.** `send_founder_new_user_push()` and `send_founder_app_open_push()` call `send_onesignal_push()` directly with no MEL audit. Also targeted at user_id=2 whose iOS subscription is disabled.
3. **Suggested Friends bypasses registry.** The BL-12 direct send at line 9631 has its own cooldown logic but no MEL row. Any delivery failure is invisible.
4. **`trip.invite.declined` registered as IMMEDIATE_PUSH but never emitted.** EventSpec exists; no call site emits this event. The one MEL row is from legacy code. Either wire the emission or downgrade to SILENT.
5. **`wishlist.match.detected` has 3 legacy SENT rows** — old code delivered this as a push before the registry redesigned it as SILENT. This is a historical inconsistency, not a current bug.
6. **`trip.join.requested` has 0 MEL rows.** The call site exists (line 13628) but has never fired — likely the trip join request feature is not yet used in production.
7. **The `analytics_head.html` does NOT inject `push_notifications_enabled` into `window.__USER__`.** The JS has no way to know the server-side preference. `blSetPushEnabled` drives OneSignal's client-side opt-in/out but reads from the app UI toggle, not the server state. On first load there is no reconciliation.

---

## Section 9 — Remediation Plan

### P0 — Blocking (push to user_id=2 never delivers)

**P0-A: SDK optOut() race — device validation needed**

The OneSignal SDK v5.3.8 fires `optOut()` during `OS.initialize()` when its persisted state is `not_determined`. This sets `notification_types=-30`. No durable client-side fix has been device-validated.

_Candidates to evaluate on device:_
1. Call `OS.Notifications.setPushNotificationsEnabled(true)` immediately after `OS.login()` completes — most likely to work without interfering with `initialize()`.
2. Upgrade OneSignal plugin to v5.4+ if a release fixes the race condition.
3. POST a server-side "opt-in" signal via OneSignal's v5 User API (`PATCH /apps/{appId}/users/by/external_id/{id}`) after `OS.login()` resolves — sets subscription enabled=true from the server side.

_Current status of OneSignal subscription `f10dcf69`:_
- notification_types=-30, enabled=false
- Cannot be fixed server-side without a OneSignal v5 User API subscription PATCH
- Requires device re-registration to clear if optOut() fires again on next launch

**P0-B: Stale Android FCM token**

The Samsung Galaxy A16 subscription (`dc044eb2`) appears enabled but its FCM token is stale. OneSignal does not auto-expire FCM tokens. If the Android device re-launches the BaseLodge app, the token will refresh. No server-side action needed — this will self-heal on next Android app launch.

---

### P1 — High (reliability gap)

**P1-A: `friend.pass.changed` AUTOMATION_EVENT — 78 consecutive failures**

Configure the OneSignal Journey for `friend.pass.changed` in the OneSignal dashboard, OR change the EventSpec delivery strategy to `IMMEDIATE_PUSH` with a rendered template. Until one of these is done, every pass-change event produces a guaranteed failed MEL row.

**P1-B: Add retry cap / alert for AUTOMATION_EVENT failures**

The admin retry runner (`app.py:19036`) re-runs failed MEL rows. If it runs for AUTOMATION_EVENT failures that will never succeed (Journey not configured), it creates indefinite retry loops. Add a `max_retries` check.

---

### P2 — Medium (audit gaps)

**P2-A: Wire Suggested Friends send into MEL**

The BL-12 direct send at line 9631 produces no MEL row. If delivery fails silently, there is no way to diagnose it from the admin console.

**P2-B: Wire Founder alert sends into MEL**

`send_founder_new_user_push()` and `send_founder_app_open_push()` should either use `emit_messaging_event` or write their own MEL row.

**P2-C: Resolve `trip.invite.declined` EventSpec**

Either add an emission call site in the decline handler, or downgrade the EventSpec to SILENT/NOT_IMPLEMENTED. Currently the registry claims this event sends a push but it never fires.

---

### P3 — Low (polish)

**P3-A: Reconcile `push_notifications_enabled` on login**

On app launch, after `OS.login()` resolves, fetch `/api/push/preferences` (GET) and call `blSetPushEnabled(preference)` to ensure the OneSignal client state matches the server preference. Prevents divergence between server and SDK state.

**P3-B: Surface Android subscription status in admin**

The admin `/admin/list-tokens` only shows BaseLodge DB tokens. OneSignal may have subscriptions (like the Android one) not tracked in the DB. Consider adding a "check OneSignal subscription status" link in the admin push panel.

---

## Section 10 — File/Commit Integrity

State vs last known-good commit (`29195fd`):

| File | Matches? | Note |
|---|---|---|
| `static/js/bl-native.js` | ✅ Exact (1,288 lines) | |
| `services/push_providers.py` | ✅ Exact | |
| `templates/components/analytics_head.html` | ✅ Exact | |
| `services/message_dispatch.py` | ✅ Exact | |
| `app.py` | ⚠️ One intentional diff | `/friends?tab=suggested` → `/friends` at line ~9635 (BL-12 fix, kept) |

No experimental code remains in any file. Revert is clean.

---

## Section 11 — Health Scorecard

| Subsystem | Status | Notes |
|---|---|---|
| APNs token registration | 🟢 Working | Token id=137 active and fresh |
| OneSignal init/login | 🔴 Broken (for user 2) | SDK optOut() race disables subscription on cold launch |
| Immediate push delivery (other users) | 🟢 Working | 116 sent, growing |
| Automation event (friend.pass.changed) | 🔴 Broken | Journey not configured — 78 consecutive failures |
| Push-tap routing | 🟢 Working | `_extractPushUrl` / `_doNavFromPush` intact |
| MEL audit trail | 🟢 Working | All events produce rows |
| Deduplication | 🟢 Working | 1-hour window enforced |
| User opt-out gate | 🟢 Working | Checked before every send |
| Token hygiene (1 active/platform) | 🟢 Working | Stale tokens deactivated on re-register |
| Test coverage | 🟢 Good | 440 passing; native SDK race untestable |
| Admin push tooling | 🟡 Partial | Missing MEL for direct sends |
