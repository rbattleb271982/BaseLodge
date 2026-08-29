# BaseLodge

## Overview
BaseLodge is a Flask-based ski/snowboard trip planning application. It enables users to track ski days, manage resort passes, and connect with friends. The application aims to be the primary platform for snow sports enthusiasts to plan, track, and socialize their winter mountain experiences by providing a modern, mobile-first experience focused on user profiles, an invitation-based friends system, and a centralized trip management hub.

## User Preferences
- Mobile-first design approach
- Editorial/blush-maroon design system (v2 active)
- Reusable component partials for DRY templating
- Max width 900px for main pages on web
- Inline modals for trip management (no page navigation)
- Home-first navigation structure (centralized trip management)
- Bottom navigation — text-only with dot indicator (no emojis)
- Georgia serif for display titles, system-ui for body

## System Architecture

### UI/UX Decisions
The application uses a mobile-first responsive design with an editorial "BaseLodge" design system (v2). It features a blush hero block for primary content, hairline section rows instead of cards, text-only bottom navigation with a dot indicator, and Georgia serif headlines. The color scheme primarily uses bordeaux (`#5C1219`) and cream (`#F5F1E8`) backgrounds. All logged-in templates extend `templates/base_app.html` for shared shell (DOCTYPE, head, viewport with `viewport-fit=cover`, CSS link, favicons, analytics, bottom nav). Page-specific styles go in `{% block head %}` and scripts in `{% block scripts %}`. Non-logged-in templates (auth, onboarding, legal, admin, error pages) remain standalone. There is no dark mode in v2.

### Safe-Area / iOS Shell
`templates/base_app.html` owns the `<div class="app-shell">` wrapper which applies `padding-top: env(safe-area-inset-top, 0px)` via CSS so content never hides behind the iOS status bar. The `.page-container` class in `static/styles.css` has `padding-bottom: calc(76px + env(safe-area-inset-bottom, 0px))` to clear the fixed bottom tab bar plus iOS home indicator. Custom wrappers `.mv-wrap` (mountains_visited) and `.et-page` (edit_trip) use the same `env(safe-area-inset-bottom)` pattern. Sticky action bars that own their own `env(safe-area-inset-bottom)` offset (trip_detail, edit_profile, trip_invite_detail) are not given an additional inset on their scroll container.

### Technical Implementations
The backend is built with Flask, SQLAlchemy for ORM, and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS and Vanilla JS for interactivity and AJAX. Flask-Login manages session-based authentication. An event system captures user actions for notifications. User lifecycle stages (`new`, `onboarding`, `active`) and canonical states (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) control UI and feature availability. Supabase is the single system of record for all resort data. The `UserAvailability` table and `services/open_dates.py` service manage user availability for features like `/trip-ideas`. Jinja2 filters in `app.py` ensure consistent formatting of mountain passes, state abbreviations, and full state names.

### Data Ownership & Source of Truth
To prevent regressions, profile data (equipment setup, rider preferences, pass info, mountain history) is owned by the `User` profile, while trip-specific data (dates, resort, carpool roles, lesson intent) is owned by `SkiTrip`. Trip views may reference profile data but must not duplicate or allow per-trip overrides. Country labels are derived from `utils/countries.py`. The `Resort` table is the single source of truth for all resort data, with selections referencing `Resort` IDs.

### Feature Specifications
-   **Authentication & Onboarding:** Two-step onboarding (Identity, Location) with a welcome modal.
-   **User Profile:** Comprehensive profiles via a "Settings" page.
-   **Trip Management:** Create trips with location, dates, and privacy settings. Focuses on personal trips, open availability, and trip ideas. Date validation ensures future dates and prevents duplicate active trips at the same resort.
-   **Date Range Calendar:** Inline calendar for selecting trip dates.
-   **Unified Trip Date Display:** Consistent date formatting for all trips.
-   **Trip Invites:** Owners invite friends, managing participant status. Invited users can view details before accepting.
-   **Friends System:** Invitation-based, bidirectional system with dedicated profiles and token-based invites. Features tabs for friends, friends' trips, and overlaps.
-   **Trip Ideas:** Suggestions based on overlapping open availability with friends and wishlist matches.
-   **Mountains Discovery:** `/mountains` tab is a live search + filter page. All active resorts loaded as JSON into the page; country → state/province → name search filters client-side. Default country/state pre-selected from `user.home_state` (onboarding field). Each row links to `/mountain/<slug>`. No new API endpoints.
-   **Home Coordination Layer:** Home restructured as a 4-section coordination hub — Welcome card → Smart action pills (Ideas/Requests/Add dates) → Happening (ambient friend activity) → Opportunities (ranked coordination feed, up to 5 rows, dismissible). Pills activate `blPillActivate()` to focus/dim sections. New CSS namespace `.bl-*`. Old module system (`home_modules`) preserved in backend for rollback safety but no longer rendered.
-   **Planning Feature:** Displays availability overlap windows between users and friends, with detail views of available friends for specific windows.
-   **Friend Profile Calendar:** Toggleable calendar view on friend profiles showing highlighted trip dates with modal details.
-   **Pass Selection:** Quick-select for major passes, with an "Other passes" option.
-   **Navigation:** Consistent 4-tab bottom navigation (Trips, Friends, Invite, Profile).
-   **Location Selector:** Unified typeahead component for state/province selection.
-   **Multi-Pass & International Resort Support:** `Resort` model includes `pass_brands`, `country`, and expanded `state` fields.
-   **Multi-Setup Equipment:** `EquipmentSetup` supports multiple setups per user. `is_primary=True` marks the active setup shown on profiles. Users can add, edit, delete, and "Make primary" any setup. First saved setup auto-becomes primary. Deleting primary auto-promotes next oldest. `User.equipment_status` remains the high-level "have_own_equipment" / "needs_rentals" signal; switching to "I rent" does not delete setups. New columns `is_primary`, `label`, `created_at` added via safe `ALTER TABLE IF NOT EXISTS` startup migration with `slot=primary` → `is_primary=TRUE` backfill.
-   **Group Coordination Signals:** `SkiTripParticipant` includes `transportation_status` and `equipment_status`.
-   **Carpool Coordination:** Participants set carpool roles, generating activity notifications.
-   **Lesson Tracking:** Participants indicate lesson intent for trips.
-   **Wish List Destinations:** Users can save up to 3 aspirational resorts, displayed on profiles with overlap features.
-   **Mountains Visited:** Users track visited resorts, viewable by friends.
-   **Friend Read-Only Views:** Specific pages for viewing friends' mountains and wish lists (friends-only access).
-   **Profile Stats Bar:** Displays counts for Trips, Mountains visited, and Wish list.
-   **Personalization Features:** Terrain preferences, smart resort defaults, next trip countdown, availability match nudges, and relevance-based friend ordering.

### Account Management
-   **Logout:** Secure logout, redirects to auth.
-   **Forgot Password:** Generates time-limited token for email accounts only.
-   **Reset Password:** 30-minute token validity, single-use enforced by `password_changed_at` timestamp.
-   **Change Password:** Email-auth users only; Google-auth users are redirected. Updates `password_changed_at`.
-   **Delete Account:** Requires email confirmation, deletes all associated data in a safe, FK-ordered manner.

### Hardening Measures
-   **Dedicated Application Role:** `baselodge_app` role with restricted database permissions.
-   **Credential Separation:** Application connects as `baselodge_app`.
-   **Permission Mapping:** `baselodge_app` has `CONNECT`, `USAGE` on `public` schema, and `ALL` privileges on tables and sequences.
-   **Resort Architecture:** `Resort` table as single source of truth for all resort data, with `country_name_override` and canonical country/state mappings from `utils/countries.py`.
-   **Lifecycle Signals:** Canonical User States and tracking fields (`login_count`, `first_planning_timestamp`) for dynamic UI and nudge suppression.
-   **Narrative Continuity:** Four narrative states dynamically adjust UI copy.
-   **Next Best Action (NBA) System:** Prioritizes a single primary CTA per screen.

### Release Identity
-   **Canonical source identity:** A deployed build uses the exact 40-character Git commit SHA as its release identity; no separate release ID is required.
-   **Runtime verification:** In Production, `build/release.sha` is the only identity source. The read-only `/health` response includes only `release_sha` and `release_identity_status` for this contract. Missing, unreadable, empty, or malformed metadata is reported as `UNVERIFIED` while normal runtime health remains independent. Development may fall back to a clean local Git checkout when generated metadata is absent.
-   **Publish build handoff:** Replit does not document an automatic immutable Git-SHA deployment variable, so the Autoscale build configuration clears `build/release.sha`, then writes the source checkout's Git `HEAD` only when the checkout is clean. If either check fails, the running process remains honest and reports `UNVERIFIED` rather than claiming a valid release.
-   **Release gating:** A release preflight must treat `UNVERIFIED` as a blocking release condition; this identity feature does not implement that gate.
-   **Release preflight:** Run `python -m release_preflight` before a release candidate is approved. It is read-only, reports one PASS/FAIL result, validates the resolved environment and database identity, checks the current Alembic head and live schema, and never migrates, repairs, or changes data. BL-139 will later define when this command is required in the rollout process.
-   **CI integrity gates:** GitHub Actions runs the full Python test suite and a separate source-integrity job on pull requests and pushes to `main`. The jobs resolve the same `requirements.txt` manifest used by Replit runtime and publishing into a temporary pinned Python 3.11 environment for each run, add pytest only as a test tool, and verify that `requirements.txt`, `pyproject.toml`, and `uv.lock` remain synchronized. Tests use isolated configuration and disposable local PostgreSQL tooling where needed. Source checks also cover Python compilation, repository hygiene, candidate source identity, and dynamic Alembic source-head validation. CI never connects to BaseLodge Development or Production and never runs the live database path of `python -m release_preflight`.
-   **PR candidate identity:** On pull requests, the source-integrity job verifies GitHub's checked-out synthetic merge candidate. This is the tested merge result, not the contributor's raw PR-head SHA.
-   **Release handoff:** The intended sequence is Replit development → reviewed GitHub commit → passing CI → operator-run `python -m release_preflight` against the explicitly selected environment → BL-139 release process → Replit Publish. A passing CI run validates source and tests only; it is not evidence that a real environment schema was inspected.
-   **GitHub enforcement:** Creating the workflow makes `Tests` and `Source integrity` visible as checks but does not require them for merging. An administrator must separately configure GitHub branch protection or a ruleset to require those checks on `main`; this project does not change repository settings automatically.

## External Dependencies

-   **Flask:** Python web framework.
-   **Flask-Login:** User session management.
-   **SQLAlchemy:** SQL toolkit and ORM.
-   **Werkzeug:** WSGI utility library for password hashing.
-   **Jinja2:** Templating engine.
-   **SQLite:** Default development database.
-   **PostgreSQL:** Production-ready database.
-   **Alembic:** Database migration tool (via Flask-Migrate).
-   **Supabase:** Single system of record for all resort data.