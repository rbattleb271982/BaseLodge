# BaseLodge Admin System Audit

**Audited:** 2026-05-14  
**Scope:** All `/admin/*` and `/api/admin/*` routes in `app.py`, admin templates, auth model, and supporting services.  
**Method:** Read-only code review — no data changes, no route executions.

---

## 1. Authentication Model

Every admin route carries both `@login_required` and `@admin_required`. No exceptions found.

The `admin_required` decorator reads the `ALLOWED_ADMIN_EMAILS` environment variable (currently `richardbattlebaxter@gmail.com`). If the current user's email is not in that list, it returns:
- HTTP 403 HTML for standard routes
- HTTP 403 JSON for any route under `/api/`

This is simple and solid for a single-admin setup. There is no admin session token, audit log of admin actions, or rate limiting on admin endpoints.

---

## 2. Complete Route Inventory

53 routes total. Grouped by function.

### 2a. Diagnostics — Read-only

| Route | Method | Function | Notes |
|-------|--------|----------|-------|
| `/admin/version` | GET | App version + env | Reports db source, Flask env |
| `/admin/debug-users` | GET | First 20 users + total count | Masks DB password in URI |
| `/admin/db-status` | GET | Engine type, table row counts | Detects SQLite fallback |
| `/admin/export-live-data` | GET | Full PII export | All tables; excludes `password_hash` |
| `/admin/resorts-audit` | GET | All resorts as JSON | name, state, country, pass_brands |
| `/admin/resorts/duplicates` | GET | Duplicate resort groups | Normalized (name, state, country) |
| `/admin/debug-resort-duplicates` | GET | Duplicate resort scan | **⚠ TEMP route — comment says "safe to remove"** |
| `/admin/push-diagnostics` | GET | Push pipeline diagnostic | **⚠ Hardcodes `target_user_id = 2`** |
| `/admin/retry-failed-events` | GET | Dry-run retry inspection | No mutations; safe |
| `/admin/message-events` | GET | Last 200 MEL rows | Renders `admin_message_events.html` |
| `/open-data-debug` | GET | Open date matches for current user | **⚠ Not under `/admin/` prefix** |

### 2b. Resort Management — UI Pages

| Route | Method | Notes |
|-------|--------|-------|
| `/admin/resorts` | GET | Full curation UI (`admin_resorts.html`) |
| `/admin/resorts/export-excel` | GET | Excel export of filtered resort list |
| `/admin/resorts/import-excel` | POST | Excel import; supports CREATE and UPDATE |
| `/admin/sync-from-canonical` | GET/POST | GET=preview HTML form; POST=executes sync |

### 2c. Resort CRUD — API Endpoints

| Route | Method | Notes |
|-------|--------|-------|
| `/api/admin/resorts/add` | POST | Add new resort; dupe check by name+country |
| `/api/admin/resorts/<id>` | PUT | Update editable fields |
| `/api/admin/resorts/<id>` | DELETE | Hard delete; checks all FK references first |
| `/api/admin/resorts/delete` | POST | Alternate POST-delete (frontend compatibility) |
| `/api/admin/resorts/update-pass-brand` | POST | Update pass brands (supports array) |
| `/api/admin/resorts/update-field` | POST | Inline field edit (name, country_code, state_code) |
| `/api/admin/resorts/update-country-name` | POST | Set/clear country name override |
| `/api/admin/resorts/toggle-active` | POST | Toggle `is_active` |
| `/api/admin/resorts/bulk-delete` | POST | Bulk delete; partial success if FK refs exist |
| `/api/admin/resorts/bulk-activate` | POST | Bulk activate |
| `/api/admin/resorts/bulk-deactivate` | POST | Bulk deactivate |
| `/api/admin/resorts/merge` | POST | Atomic merge: repoints all FK refs, deactivates duplicates |
| `/api/admin/resorts/export-canonical` | POST | Writes `data/canonical_resorts.json` |

### 2d. Countries Reference

| Route | Method | Notes |
|-------|--------|-------|
| `/admin/countries` | POST | Add country to `Country` table; updates in-memory `COUNTRY_NAMES` |

### 2e. Backfills

| Route | Method | Preview/Execute Logic |
|-------|--------|-----------------------|
| `/admin/backfill-resort-ids` | GET/POST | ✅ GET=preview (no writes); POST=execute |
| `/admin/backfill-country-codes` | GET/POST | **⚠ GET also writes — no preview mode** |
| `/admin/backfill-planning-timestamp` | GET/POST | Delegates to separate module |
| `/admin/backfill-primary-rider-type` | GET/POST | Inline logic; writes on both methods |
| `/admin/backfill-organizers-as-participants` | GET/POST | Inline logic |

### 2f. Seeding (Development / Demo Data)

| Route | Method | Notes |
|-------|--------|-------|
| `/admin/seed-test-users` | GET/POST | Creates Richard + 20 friends; idempotent |
| `/admin/seed-narrative-states` | GET/POST | 4 users for narrative state testing |
| `/admin/seed-screenshot-data` | GET/POST | App Store screenshot demo data |

All three seed routes **execute on GET** — no preview gate. Idempotent, so low practical risk, but inconsistent with the GET=preview pattern elsewhere.

### 2g. Push & Messaging

| Route | Method | Notes |
|-------|--------|-------|
| `/admin/push-diagnostics` | GET | All token rows for `target_user_id=2`; read-only |
| `/admin/test-push-broadcast` | GET | **⚠ Sends to ALL active tokens for ALL users** |
| `/admin/test-onesignal-push` | GET/POST | Sends test push to `current_user` (correct) |
| `/admin/test-message-event` | GET | Creates 3 sample MEL rows; no real sends |
| `/admin/retry-failed-events` | GET/POST | GET=dry-run; POST disabled (`RETRY_EXECUTION_ENABLED=False`) |

### 2h. Database Init

| Route | Method | Notes |
|-------|--------|-------|
| `/admin/init-db` | POST | Seeds resorts from xlsx if table is empty; POST-only ✅ |

---

## 3. Findings

### 3.1 ⚠ HIGH — `/admin/backfill-country-codes` writes on GET

**Lines:** 11696–11724 in `app.py`

Unlike `/admin/backfill-resort-ids` which correctly uses GET for preview and POST for execute, `backfill-country-codes` runs `db.session.commit()` on both GET and POST. A browser prefetch, link preview, or accidental navigation triggers a real data mutation in production.

**Recommendation:** Add an `is_preview = request.method == "GET"` branch; only commit on POST.

---

### 3.2 ⚠ MEDIUM — `/admin/test-push-broadcast` has no opt-out check

**Lines:** 5219–5414 in `app.py`

This route queries all `PushDeviceToken` rows with `active=True` and attempts a delivery per token — across all users simultaneously. It does not check `user.push_notifications_enabled`. As the real user base grows, triggering this route by mistake (it's a simple GET) blasts every registered device.

**Recommendation:** Require POST method; add `push_notifications_enabled` filter; consider a `?dry_run=1` query param.

---

### 3.3 ⚠ MEDIUM — `/admin/push-diagnostics` hardcodes `target_user_id = 2`

**Line:** 4644 in `app.py`

The diagnostic report is always for user ID 2. If the dev account is ever re-seeded or IDs shift, this silently inspects the wrong user with no visible error.

**Recommendation:** Change to `target_user_id = current_user.id` to always reflect the logged-in admin.

---

### 3.4 ⚠ LOW — `/admin/debug-resort-duplicates` is a leftover temp route

**Line 12943:** The route decorator comment reads: "TEMP DEBUG ROUTE — safe to remove after use". A permanent duplicate detection endpoint now exists at `/admin/resorts/duplicates`.

**Recommendation:** Remove `debug_resort_duplicates` and its route.

---

### 3.5 ⚠ LOW — `/open-data-debug` lives outside the `/admin/` prefix

**Line:** 10456 in `app.py`

The route is `@admin_required` so access is correctly gated, but the URL `/open-data-debug` breaks the naming convention and could cause confusion (e.g., someone might link it without realizing it's an admin tool).

**Recommendation:** Move to `/admin/open-data-debug`. A URL-only rename with `redirect_to` or simply re-registering the decorator is enough.

---

### 3.6 INFO — `EmailLog` model exists but is never written to

Email sends (password reset via SendGrid, feedback) do not create `MessageEventLog` or `EmailLog` entries. Email delivery is only visible in the SendGrid dashboard. The MEL system covers push events but not email events.

**Recommendation:** Either wire email sends through `create_message_event()` with `channel=Channel.EMAIL`, or explicitly document that email delivery audit is out-of-scope for MEL.

---

### 3.7 INFO — `ADMIN_FEEDBACK_EMAIL` secret is not set

The `feedback()` route uses `ADMIN_FEEDBACK_EMAIL` from the environment. If the variable is absent, the email recipient is `None` and SendGrid silently rejects. Not currently a Replit secret.

**Recommendation:** Set `ADMIN_FEEDBACK_EMAIL` as a Replit secret (value: the feedback inbox address).

---

### 3.8 INFO — No central admin dashboard or action audit trail

All admin routes are accessed by direct URL or linked from within `admin_resorts.html`. There is no:
- Admin index page listing all available routes
- Audit log recording which admin performed which action and when
- Session-level logging beyond Flask/server logs

This is acceptable for a solo-admin setup but worth noting as the team grows.

---

### 3.9 INFO — `RETRY_EXECUTION_ENABLED = False` (intentional, documented)

**Line:** 13241 in `app.py`

The retry runner POST path is correctly disabled pending the Deploy B monitoring period. The re-enable path is clearly documented in the code. No action needed.

---

## 4. Admin Templates

| Template | Extends | Style |
|----------|---------|-------|
| `admin_resorts.html` | Standalone | Dark functional (`#1a1a2e` header, system-ui) |
| `admin_message_events.html` | Standalone | Dark functional (same palette) |

Both templates correctly include `components/analytics_head.html` for PostHog. Neither extends `base_app.html`, which is intentional — admin pages are separate from the user-facing app shell.

---

## 5. Priority Summary

| # | Severity | Finding | File / Line |
|---|----------|---------|-------------|
| 1 | HIGH | `backfill-country-codes` GET writes to DB | `app.py` ~11696 |
| 2 | MEDIUM | `test-push-broadcast` has no opt-out check, GET-accessible | `app.py` ~5219 |
| 3 | MEDIUM | `push-diagnostics` hardcodes `target_user_id = 2` | `app.py` 4644 |
| 4 | LOW | `debug-resort-duplicates` is a leftover temp route | `app.py` ~12942 |
| 5 | LOW | `/open-data-debug` outside `/admin/` prefix | `app.py` 10456 |
| 6 | INFO | Email delivery has no MEL logging | `app.py` / `services/` |
| 7 | INFO | `ADMIN_FEEDBACK_EMAIL` not set as Replit secret | `.env` / Replit secrets |
| 8 | INFO | No central admin index or action audit trail | — |
| 9 | INFO | `RETRY_EXECUTION_ENABLED=False` — intentional, no action | `app.py` 13241 |
