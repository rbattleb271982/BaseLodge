# BaseLodge Phase 1E — Mobile Navigation + Real Device Performance Audit

**Date:** May 17, 2026
**Scope:** Audit only — no code changes. Covers navigation UX, WebView rendering, JS/CSS payload, perceived speed, device instrumentation, and ranked recommendations.
**Baseline:** /home 0.887s wall-clock, /trips 0.414s, /friends 0.554s (post Phase 1D).

---

## A. Executive Summary

BaseLodge is a server-rendered MPA wrapped in a Capacitor iOS shell that points directly at the live production server (`https://app.baselodgeapp.com`). Every tab tap — Home, Trips, Friends, Mountains — triggers a full HTTP round-trip to Supabase-backed Flask before any pixels change. On a production device, each tab switch costs server processing time (414–887ms) plus at least one WKWebView network RTT (~60–200ms depending on connection). The total perceived transition time between screens is therefore typically 500ms–1100ms before the new page even begins painting.

Three structural mitigations are already in place: a 2px bordeaux progress bar (`bl-page-loader`) that animates immediately on tap, a touchstart opacity fade on the bottom nav to signal responsiveness, and `<link rel="prefetch">` hints on Home, Trips, and Friends that instruct the browser to speculatively fetch adjacent tab HTML in the background. These collectively reduce the *felt* latency without reducing actual server time. The prefetch coverage has a notable gap: no page prefetches `/mountains`, so the Mountains tab is the coldest tab every time.

The most impactful single fix available — without changing server logic — is to point the Capacitor launch URL directly at `/home` instead of `/`, eliminating the guaranteed 302 redirect on every cold app launch. The second most impactful is adding `/mountains` to the prefetch hints on the three tabs that don't already link there. Beyond those two low-regression wins, the remaining gains require either server-side route caching (mountains resort JSON is ~75–100KB of static-ish data rebuilt per request), CSS/JS splitting, or skeleton screens for the heavier routes (/home, /friends).

---

## B. Navigation Bottleneck Map

| Route | Trigger | Server Time | Est. WKWebView RTT | Prefetch Coverage | Notes |
|---|---|---|---|---|---|
| `/` → 302 → `/home` | Cold app launch (Capacitor) | 2× RTT + 0.887s | ~60–200ms × 2 | None | Double round-trip every launch |
| `/home` | Home tab tap | 0.887s | ~60–200ms | From Trips, Friends (partial) | Heaviest route; 12 Supabase queries |
| `/my-trips` | Trips tab tap | 0.414s | ~60–200ms | From Home, Friends | Best performing tab |
| `/friends` | Friends tab tap | 0.554s | ~60–200ms | From Home, Profile | 3+ batch Supabase queries |
| `/mountains` | Mountains tab tap | ~0.2–0.4s est. | ~60–200ms | **None from any tab** | Cold every time; large JSON payload |
| `/trips/<id>` | Trip card tap | Unknown | ~60–200ms | None | Not measured yet |
| `/friends/<id>` | Friend card tap | Unknown | ~60–200ms | None | Not measured yet |
| `/mountain/<slug>` | Mountain detail tap | Unknown | ~60–200ms | None | Not measured yet |
| `/planning` | (Legacy) | 0ms + redirect | ~60–200ms | — | Immediate 302 → /home; adds RTT |

**Redirect chains observed:**
- Cold launch: `GET /` → `302 /home` → full home render (2 round-trips, ~120–400ms overhead before first byte of HTML)
- Auth-state guard: `resolve_navigation()` runs on every request; for active users navigating to `/` or `/auth`, adds a redirect. All other routes are allowed through directly (no overhead for authenticated tab navigation).
- Legacy planning: `GET /planning` → `302 /home` — any saved bookmark or link to `/planning` costs an extra round-trip.

**Back-forward cache (bfcache):**
- `pageshow` event is wired in `bl-page-loader` to dismiss the progress bar on bfcache restore.
- WKWebView supports bfcache for pages that don't use `unload` event listeners or `Cache-Control: no-store`. No `Cache-Control` headers are set explicitly in `app.py`, so Flask's default behavior applies (no caching of dynamic responses). This means WKWebView will not serve any tab from bfcache — every back-navigation is a fresh server request.
- **Implication:** Back-button taps on `/trip/<id>` or `/friends/<id>` re-fetch the parent tab from the server.

---

## C. WebView Bottleneck Map

### JS Assets

| Asset | Size | Loading | Cached by WKWebView | Risk |
|---|---|---|---|---|
| `static/js/bl-native.js` | 44.7KB (949 lines) | `defer` | Yes (static file) | Parse/execute cost per cold WKWebView session; cached across tab navigations within the same session |
| `static/analytics.js` | 2.3KB (40 lines) | `defer` | Yes (static file) | Negligible |
| `analytics_head.html` inline block | ~1.2KB | Synchronous inline | No (inline, varies per user) | Blocks HTML parsing for CSRF wrapper setup; intentional (fetch must be patched before body scripts) |
| `base_app.html` inline scripts | ~4KB total | Synchronous | No (inline) | BL-NAV debug, blToast, bl-page-loader, nav tap feedback — all inline, fire on every page |

**bl-native.js detail:** The file is 44.7KB but loaded `defer`, meaning HTML parsing is not blocked. However, on a cold WKWebView session start (app launch), the JS engine must parse and execute 44.7KB before `DOMContentLoaded` callbacks fire. On repeat navigations within the same session, WKWebView's HTTP cache serves this file from disk (no re-download), but it is re-parsed per full-page navigation since MPA navigations destroy and recreate the JavaScript context. On modern iPhone hardware (A15+) this is ~5–15ms; on older devices (A12/A13) it may be 20–40ms.

### CSS Assets

| Asset | Size | Loading | Notes |
|---|---|---|---|
| `static/styles.css` | 51.3KB (2,322 lines) | Synchronous `<link>` | Render-blocking by spec; browser must fully download + parse before painting. Cached by WKWebView after first load. |

`styles.css` is a single-file design system covering all pages. The render-blocking `<link>` tag means the browser will not paint *anything* until `styles.css` is downloaded and parsed. On the first request in a session, this adds the download time of 51.3KB to first paint. On repeat navigations within a session, WKWebView serves from cache — the parse cost remains but download is eliminated. No CSS splitting or critical-path inlining is in place.

### HTML Payload / DOM

| Template | Lines | Notable Includes | Est. HTML bytes |
|---|---|---|---|
| `home.html` | 1,236 | 8 partials (`base_app.html` + 7 section partials) | ~40–55KB |
| `my_trips.html` | 679 | `base_app.html` | ~20–30KB |
| `friends.html` | 331 | `base_app.html` | ~12–18KB |
| `mountains_tab.html` | 446 | `base_app.html` + inline JS | ~15–20KB + resort JSON |
| `base_app.html` (shell) | 217 | `bottom_nav.html`, `analytics_head.html` | ~8KB base overhead |

**Mountains tab JSON payload:** `/mountains` serializes every active non-region resort as a `var RESORTS = {{resorts_data | tojson}}` block inline in the HTML. Each resort object includes: `id`, `name`, `display_name`, `slug`, `country_code`, `country_name`, `state_code`, `state_name`, `pass_labels`, `pass_keys`, `friend_count`. At an estimated ~300 active resorts × ~250 bytes/resort, this is approximately **75–100KB of JSON** embedded in the page HTML on every `/mountains` request. This JSON is static-ish (changes only when resort data changes in Supabase, which is infrequent) but is rebuilt from scratch on every page load.

### Safe-Area / Fixed Elements (iOS)

| Element | CSS pattern | Risk |
|---|---|---|
| Bottom nav (`.bl-bottom-nav`) | `position: fixed; bottom: env(safe-area-inset-bottom)` | Triggers composited layer; repaint on scroll if not isolated |
| `bl-page-loader` | `position: fixed; top: env(safe-area-inset-top)` | Composited layer; minimal cost |
| App shell `.app-shell` | `padding-top: env(safe-area-inset-top)` | Static; no reflow after initial layout |
| Top bar `.bl-top-bar` | Inline in shell | Not fixed; scrolls with content on some pages |
| Sticky action bars (trip_detail, edit_profile) | `position: sticky` with `env(safe-area-inset-bottom)` | Safe; sticky avoids fixed-layer thrashing |

Fixed-position elements on iOS WKWebView can cause composite layer promotion, which adds GPU memory cost but generally improves scroll smoothness. Two fixed elements (bottom nav + page loader) are present on every page — a low and acceptable cost.

### White-Flash Windows

The primary white-flash window occurs between the moment a navigation link is tapped and the moment the new page's HTML begins painting. The sequence in WKWebView for a tab tap:

1. User taps nav item → `touchstart` fires → opacity feedback applied (immediate, ~16ms)
2. `click` fires → `bl-page-loader` shows 0%→70% progress bar
3. WKWebView sends HTTP request to production server
4. Server processes request (0.414–0.887s)
5. First byte arrives → WKWebView begins parsing HTML
6. `styles.css` cache hit (or download) → parse → first paint

The gap between steps 3 and 6 is the white-flash window. Current mitigations (touchstart feedback, progress bar) make the UI feel responsive but cannot eliminate the blank white frame between steps 2 and 6. The `<html style="background:#F5F1E8">` inline style in `base_app.html` ensures the background is cream (not white) during this window, which reduces the perceived harshness of the flash on content-heavy pages.

**Pages with the longest white-flash windows (by server time):**
1. `/home` — 0.887s
2. `/friends` — 0.554s
3. `/my-trips` — 0.414s
4. `/mountains` — ~0.3–0.5s (estimated, unmeasured)

---

## D. Ranked Findings

### Very High

**VH-1 — Double RTT on every cold app launch (Capacitor root URL)**
- **Issue:** `capacitor.config.json` sets `"url": "https://app.baselodgeapp.com"`. The server's `/` route immediately returns a 302 to `/home`. Every time a user opens the app from the iOS home screen (cold launch or killed-app relaunch), WKWebView loads `/` first, receives a redirect, then loads `/home`. This is two full network round-trips before any content arrives.
- **File:** `capacitor.config.json`, `app.py` (line 2311–2313)
- **User impact:** Adds ~60–400ms to cold launch perceived time (one extra RTT + server time for the redirect request). On every app open.
- **Implementation complexity:** Very low — one JSON field change in `capacitor.config.json`. No server changes. No template changes.
- **Regression risk:** Very low — `/home` is a fully auth-guarded route. Unauthenticated users get redirected to `/auth` by `resolve_navigation()` regardless of entry point.

**VH-2 — Mountains tab has zero prefetch coverage**
- **Issue:** Home prefetches `/my-trips` and `/friends`. Trips prefetches `/home` and `/friends`. Friends prefetches `/home` and `/profile`. No page prefetches `/mountains`. The Mountains tab is therefore always a cold load — WKWebView cannot begin the fetch until the user actually taps the tab.
- **File:** `templates/home.html`, `templates/my_trips.html`, `templates/friends.html` (each `{% block head %}` section, lines 5–6)
- **User impact:** Mountains tab feels slower than all other tabs, every time, regardless of connection quality. On a good LTE connection the difference is ~200–400ms of avoidable wait.
- **Implementation complexity:** Very low — add `<link rel="prefetch" href="{{ url_for('mountains_tab') }}">` to the head block of Home, Trips, and Friends templates.
- **Regression risk:** None — prefetch is advisory only; the browser ignores it under memory pressure or on slow connections.

### High

**H-1 — Mountains page rebuilds ~75–100KB resort JSON on every request**
- **Issue:** `/mountains` (route at `app.py:3215`) runs `Resort.query.filter_by(is_active=True, is_region=False)`, iterates every active resort, fetches all `ResortPass` rows, and serializes a full `resorts_data` list into an inline `var RESORTS` JS block. Resort data changes rarely (schema updates, not user actions). The JSON is rebuilt from scratch on every page view by every user.
- **File:** `app.py:3220–3340`, `templates/mountains_tab.html:288–292`
- **User impact:** The mountains page is slower to generate than it needs to be, and sends a large HTML payload (~100KB+) on every load. The inline JSON also cannot be independently cached by WKWebView (it is embedded in the dynamic HTML response).
- **Implementation complexity:** Medium — requires adding a server-side in-process cache (e.g., module-level dict + timestamp, or `functools.lru_cache` on the data-build step). The route already has `[ROUTE_PERF]` instrumentation; baseline timing should be captured first.
- **Regression risk:** Low — cache invalidation is simple since resort data only changes via admin/Supabase operations, not user actions.

**H-2 — `/home` route at 0.887s wall-clock — 2 Supabase queries remain eliminable**
- **Issue:** Post Phase 1D, `/home` still fires ~10 sequential Supabase queries. The two next-highest cost items are: (a) `wishlist_resort_cache` (~63ms inside `build_destination_feed`) — a `Resort.query.filter(id.in_())` that could use the startup-loaded resort cache from `resort_utils`; (b) `active_equipment` (~60ms) — `user.get_active_equipment()` which fires a `SELECT` on the `EquipmentSetup` table per request.
- **File:** `services/ideas_engine.py:752–760`, `app.py` (home route, `home_eq` line)
- **User impact:** Each eliminable query saves ~60ms off the 0.887s home route. Eliminating both would bring `/home` to ~0.76s.
- **Implementation complexity:** Medium for `wishlist_resort_cache` (pass the startup resort map in); Low for `active_equipment` if the equipment setup is added to the user's session or eager-loaded on login.
- **Regression risk:** Low-medium — requires care to not return stale resort data if a resort is updated.

**H-3 — No HTTP cache headers on any route — bfcache disabled**
- **Issue:** Flask's default for dynamic routes is to send no explicit `Cache-Control` header, which typically results in `Cache-Control: no-cache` or no header at all. WKWebView will not serve dynamic responses from bfcache without `Cache-Control: no-store` being explicitly absent and `Vary` headers being correct. Without bfcache, every back-button navigation re-fetches from the server. This is particularly painful on `/trips/<id>` → back → `/my-trips`: the trips list reloads from scratch.
- **File:** `app.py` (no `after_request` cache headers for tab routes)
- **User impact:** Every back-button navigation pays full server round-trip cost. On `/home` (0.887s) this is especially noticeable.
- **Implementation complexity:** Low-Medium — adding `Cache-Control: no-store` explicitly would confirm bfcache is disabled by choice; adding `Cache-Control: private, max-age=0, must-revalidate` on authenticated routes is the minimum needed to not actively block bfcache. Full bfcache compatibility requires auditing all `unload` event listeners and ensuring no `Cache-Control: no-store` is set.
- **Regression risk:** Medium — cache header changes for authenticated user data require careful review to avoid serving stale data to wrong users.

### Medium

**M-1 — No skeleton screens on heavy routes**
- **Issue:** When `/home` (0.887s) or `/friends` (0.554s) are loading, the user sees the cream background and the progress bar, but no content structure. A skeleton screen — content-shaped placeholder shapes rendered immediately from cached shell HTML — would make the transition feel faster even if server time is unchanged.
- **File:** `templates/base_app.html`, `templates/home.html`, `templates/friends.html`
- **User impact:** Perceived speed improvement of 200–400ms on the two slowest tabs. Does not change actual server time.
- **Implementation complexity:** Medium — requires a separate cached shell template for each tab, served from WKWebView's local cache (or injected via Capacitor) before the network response arrives.
- **Regression risk:** Low — skeleton screens are additive; the real content replaces them on load.

**M-2 — `bl-native.js` (44.7KB) re-parsed on every MPA navigation**
- **Issue:** MPA full-page navigations destroy the JavaScript context. `bl-native.js` (44.7KB, 949 lines) is re-downloaded from WKWebView's HTTP cache (fast) and re-parsed by the JS engine on every tab change. The file contains push notification setup, keyboard scroll handling, form submit loader, and OneSignal initialization — most of which only needs to run once per app session.
- **File:** `static/js/bl-native.js`, `templates/components/analytics_head.html`
- **User impact:** ~10–40ms of JS parse time per navigation depending on device age. On A12 and older, this is closer to 30–50ms.
- **Implementation complexity:** High — reducing this meaningfully requires either (a) code-splitting so push/OneSignal code loads only on first page and smaller modules load on subsequent pages, or (b) moving to a SPA/AJAX navigation model for tab switching. Both are significant architectural changes.
- **Regression risk:** High — push notification registration timing is delicate (already documented in `bl-native.js` comments regarding WKWebView process reuse and sessionStorage).

**M-3 — `styles.css` (51.3KB) is render-blocking and unsplit**
- **Issue:** A single 2,322-line stylesheet covers all pages. It is included as a synchronous `<link>` in `<head>`, making it render-blocking. Pages that only use a fraction of the CSS (e.g., `/friends` at 331 lines of HTML) still pay the full parse cost of the entire design system.
- **File:** `static/styles.css`, `templates/base_app.html:21`
- **User impact:** After the first request (when CSS is in WKWebView cache), re-parse cost is ~5–15ms per navigation. On cold session start, the download of 51.3KB adds ~50–150ms to first paint on slow connections.
- **Implementation complexity:** High — CSS splitting requires identifying per-route critical CSS and extracting it, while keeping the shared design system coherent. Risk of visual regressions is significant.
- **Regression risk:** High — the v2 design system is tightly integrated. Splitting incorrectly causes visual regressions.

**M-4 — Legacy `/planning` redirect burns an RTT for any saved links**
- **Issue:** `GET /planning` → 302 → `/home` (line 6579–6580 in `app.py`). Any user with a bookmark, push notification deep link, or shared URL to `/planning` pays an extra round-trip.
- **File:** `app.py:6579`
- **User impact:** ~60–200ms extra on users with old `/planning` links. Low frequency but avoidable.
- **Implementation complexity:** Very low — check if any push notification payloads or external links reference `/planning`; if not, the redirect is harmless infrastructure debt.
- **Regression risk:** None.

### Low

**L-1 — Mountains tab not measured — no `[ROUTE_PERF]` baseline captured**
- **Issue:** `/mountains` has `[ROUTE_PERF]` instrumentation for the `all_resorts` query and `data_build` step, but no total route timing equivalent to the `[ROUTE_PERF] route=X total=Xs` line that exists on `/home`, `/my-trips`, and `/friends`. The total wall-clock cost of `/mountains` is unknown.
- **File:** `app.py:3215–3380`
- **User impact:** Cannot prioritize Mountain tab optimization without a baseline.
- **Implementation complexity:** Very low — add `_rp_t0 = time.perf_counter()` at route entry and `print(f"[ROUTE_PERF] route=mountains total=...")` before `render_template`.
- **Regression risk:** None.

**L-2 — BL_NAV_DEBUG timing not enabled — no real device timing data exists**
- **Issue:** The `BL_NAV_DEBUG` server flag enables client-side `[BL-NAV]` click + DOMContentLoaded timing via `console.log`. Without enabling this flag, no client-side timing data has been collected. All current performance numbers are server-side only; WebView render time, DOMContentLoaded, and first paint are unmeasured.
- **File:** `templates/components/analytics_head.html:34`, `app.py` (BL_NAV_DEBUG config)
- **User impact:** No impact on users; impacts the team's ability to diagnose real device lag.
- **Implementation complexity:** Very low — set `BL_NAV_DEBUG=1` in the environment, load the app in Safari Web Inspector, and capture the console output.
- **Regression risk:** None — debug logging only.

**L-3 — No prefetch from Mountains tab back to other tabs**
- **Issue:** `mountains_tab.html` does not include prefetch hints for any other tab. If a user navigates Home → Mountains → Home, the second `/home` request is cold.
- **File:** `templates/mountains_tab.html` (head block)
- **User impact:** Minor — cross-tab navigation back from Mountains pays full server cost. Existing prefetch on other tabs partially mitigates this for the return trip.
- **Implementation complexity:** Very low — add prefetch hints to `mountains_tab.html` head block.
- **Regression risk:** None.

---

## E. Suggested Implementation Order

1. **Fix Capacitor launch URL** (`capacitor.config.json` → `"url": ".../home"`) — one line, zero regression risk, eliminates a double-RTT on every cold launch. Requires a new iOS build to take effect. **(VH-1)**

2. **Add `/mountains` to prefetch hints** on Home, Trips, and Friends — three lines across three templates, zero regression risk. Deploy immediately. **(VH-2)**

3. **Add prefetch hints to Mountains tab** back to other tabs — one template, negligible work. **(L-3)**

4. **Add total route timing to `/mountains`** — enables the baseline measurement needed for H-1 optimization. Without a number, the optimization is speculative. **(L-1)**

5. **Enable BL_NAV_DEBUG and capture real device timing** — run the app in Safari Web Inspector (or use TestFlight + tethered Mac) to capture DOMContentLoaded, first paint, and perceived transition time per tab. This data determines whether H-1, H-2, or M-1 should be next. **(L-2)**

6. **Cache mountains resort JSON** — once step 4 gives a baseline, implement a simple in-process server-side cache for `resorts_data`. This eliminates the per-request Supabase query and JSON rebuild for the most static data in the app. **(H-1)**

7. **Skeleton screens for `/home` and `/friends`** — the two slowest tabs. Implement as Capacitor-local HTML injected by the native shell before the network response arrives, or as server-rendered inline placeholders. **(M-1)**

8. **Investigate bfcache compatibility** — audit `Cache-Control` headers and `unload` listeners, then decide whether to explicitly enable or disable bfcache for each route. **(H-3)**

9. **`wishlist_resort_cache` elimination** — pass the startup-loaded resort map from `resort_utils` into `build_destination_feed`, removing the per-request `Resort.query.filter(id.in_())` call (~63ms off /home). **(H-2)**

10. **`active_equipment` query caching** — consider loading the user's primary equipment setup at login and storing in Flask session or on the `User` object. **(H-2)**

Steps 1–5 can be executed in a single session with minimal risk. Steps 6–10 should each be validated with before/after `[ROUTE_PERF]` measurements.

---

## F. Final Implementation Prompt (Phase 1F)

> **BaseLodge Phase 1F — Navigation Speed: Quick Wins**
>
> **Context:**
> BaseLodge is a Flask/Jinja2 MPA wrapped in a Capacitor iOS shell. Server times post Phase 1D:
> /home 0.887s, /trips 0.414s, /friends 0.554s. The app is a full MPA — every tab tap is a
> server round-trip. The current bottlenecks are confirmed by the Phase 1E audit.
>
> **Implement exactly these five changes. No other changes.**
>
> **Change 1 — Capacitor launch URL** (`capacitor.config.json`)
> Change `"url": "https://app.baselodgeapp.com"` to `"url": "https://app.baselodgeapp.com/home"`.
> This eliminates the guaranteed `/` → 302 → `/home` double-RTT on every cold app launch.
> The `/home` route is `@login_required`; unauthenticated users are redirected to `/auth` by
> `resolve_navigation()`, so this is safe.
>
> **Change 2 — Mountains prefetch on Home** (`templates/home.html`, `{% block head %}`)
> Add `<link rel="prefetch" href="{{ url_for('mountains_tab') }}">` alongside the existing
> `/my-trips` and `/friends` prefetch lines (lines 5–6).
>
> **Change 3 — Mountains prefetch on Trips** (`templates/my_trips.html`, `{% block head %}`)
> Add `<link rel="prefetch" href="{{ url_for('mountains_tab') }}">` alongside the existing
> prefetch lines.
>
> **Change 4 — Mountains prefetch on Friends** (`templates/friends.html`, `{% block head %}`)
> Add `<link rel="prefetch" href="{{ url_for('mountains_tab') }}">` alongside the existing
> prefetch lines.
>
> **Change 5 — Prefetch hints on Mountains tab** (`templates/mountains_tab.html`, `{% block head %}`)
> Add prefetch hints for the other three tabs:
> ```html
> <link rel="prefetch" href="{{ url_for('home') }}">
> <link rel="prefetch" href="{{ url_for('my_trips') }}">
> <link rel="prefetch" href="{{ url_for('friends') }}">
> ```
>
> **Change 6 — Mountains route total timing** (`app.py`, route `mountains_tab` at line ~3215)
> At the very start of the route function, add:
> `_rp_t0 = time.perf_counter()`
> Before `render_template(...)`, add:
> `if app.debug: print(f"[ROUTE_PERF] route=mountains total={time.perf_counter()-_rp_t0:.4f}s")`
>
> **Do not touch:** auth routes, trip_detail, bl-native.js, models, schema, styles.css, bottom_nav.html, analytics_head.html, base_app.html, the ideas engine, or any route not listed above.
>
> **Validation:**
> After changes, restart Flask and confirm:
> - `/home`, `/my-trips`, `/friends`, `/mountains` all return HTTP 200
> - `[ROUTE_PERF] route=mountains total=Xs` appears in debug logs
> - `capacitor.config.json` server URL ends in `/home`
> - Prefetch `<link>` tags are present in view-source of each updated template
