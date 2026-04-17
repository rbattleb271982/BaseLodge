# BaseLodge

## Overview
BaseLodge is a Flask-based ski/snowboard trip planning application. It helps users track ski days, manage resort passes, and connect with friends. The application provides a modern, mobile-first experience focused on user profiles, an invitation-based friends system, and a centralized trip management hub. The vision is to be the primary platform for snow sports enthusiasts to plan, track, and socialize their winter mountain experiences.

## User Preferences
- Mobile-first design approach
- Editorial/blush-maroon design system (v2 active)
- Reusable component partials for DRY templating
- Max width 900px for main pages on web
- Inline modals for trip management (no page navigation)
- Home-first navigation structure (centralized trip management)
- Bottom navigation — text-only with dot indicator (no emojis)
- Georgia serif for display titles, system-ui for body

## Design System (v2 — Active)
**Tokens:**
- Primary: `#5C1219` (bordeaux)
- Background: `#F5F1E8` (cream)
- Surface: `#FFFFFF`
- Surface-blush: `#F0DDD8`
- Border-soft: `#E5DFD0`
- Border: `#D9D2BF`
- Text: `#1A1A1A` | Muted: `#6B665A` | Tertiary: `#8A857A`
- No shadows. Radii: sm:4px / md:8px / lg:12px

**Font families:**
- Serif (editorial): `Georgia, 'Times New Roman', serif` → `var(--bl-font-serif)`
- Sans (UI): `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif` → `var(--bl-font-sans)`
- Cormorant Garamond: auth branding only (not used in app UI)

**Unified typography roles (`static/styles.css` → `.type-*` classes):**
| Class | Role | Size | Font |
|---|---|---|---|
| `.type-display` | Page-anchor name (empty home) | 38px | serif |
| `.type-heading` | Page/section titles | 26px | serif |
| `.type-body` | Editorial paragraphs | 17px | sans |
| `.type-list` | List item text | 16px | sans |
| `.type-caption` | Identity lines, metadata | 14px | sans |
| `.type-label` | Uppercase stat labels, eyebrows | 11px | sans |
| `.type-tagline` | Italic serif pull-quote | 15px | serif italic |
| `.type-stat` | Large serif numerals | 32px | serif |

**Legacy classes** (still in use where not yet migrated): `.bl-heading-xl/l/m`, `.bl-body`, `.bl-label`, `.bl-caption`, `.bl-heading-serif-xl/l/m`

**Hero block standard:** `background: #F0DDD8; border: 0.5px solid #5C1219; border-radius: 8px; padding: 20px`
**Activity tags:** bordeaux dot `::before` + uppercase label, single color `#5C1219`
**Selection state (pills):** blush bg + soft neutral border + bold hint text

## System Architecture

### UI/UX Decisions
The application employs a mobile-first responsive design with an editorial "BaseLodge" design system (v2). Key UI elements include the blush hero block for primary content, hairline section rows replacing cards, a text-only bottom navigation with dot indicator, and serif (Georgia) headlines for emotional resonance. The color scheme features bordeaux `#5C1219` as primary with cream `#F5F1E8` backgrounds. No dark mode in v2. All main templates link to `static/styles.css` for shared tokens; page-specific overrides live in inline `<style>` blocks.

### Technical Implementations
The backend is built with Flask, utilizing SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 is used for templating, complemented by custom CSS and Vanilla JS for interactivity and AJAX. Flask-Login handles session-based authentication. An event system captures user actions for notifications. User lifecycle stages (`new`, `onboarding`, `active`) and canonical states (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) dictate UI and feature availability. Supabase is the single system of record for all resort data.

**Availability system (Phase 2):** User availability is stored in the `UserAvailability` table (model in `models.py`). The `services/open_dates.py` service reads from `UserAvailability` first; if no rows exist for a user, it falls back to the legacy `user.open_dates` JSON column. The `/trip-ideas` route uses this service exclusively — no direct `user.open_dates` reads. The `get_open_date_matches(user)` function output structure (list of dicts with `date`, `friend_id`, `friend_name`, `friend_pass`, `same_pass`) is unchanged for all callers.

### Template Filters for Consistent Display
Centralized Jinja2 filters in `app.py` ensure consistent formatting across all templates:
-   **`mountain_passes`**: Formats resort pass brands (e.g., "Epic · Ikon") without "Pass" suffix. Returns empty string if no pass.
-   **`state_abbrev`**: Returns state abbreviation (e.g., "CO"). Accepts resort object or string.
-   **`state_fullname`**: Returns full state name (e.g., "Colorado") with fallback to `resort.state` if `state_name` is empty.

**UI Terminology Standards:**
-   Use "Mountain" instead of "Resort" in user-facing labels
-   Use "Pass" instead of "Pass Type" for field labels
-   Trip cards/tiles: Mountain name (line 1), State abbr · Date · Pass (line 2)
-   Detail pages: Full state name with country when applicable
-   Pass brands come from mountain data (`resort.pass_brands`), not user data
-   Omit empty fields entirely rather than showing "No Pass" or placeholder text

### Data Ownership & Source of Truth
To prevent UI and architectural regressions, the following ownership rules must be maintained:
- **Profile Owns:** Equipment setup, rider preferences, pass info, and mountain history.
- **Trips Own:** Specific dates, resort selection, carpool roles, and lesson intent.
- **UI Constraints:** Trip-level views may reference profile data (e.g., displaying equipment status) but must not duplicate, store, or allow per-trip overrides of profile-owned data.
- **Geography:** Country labels must always be derived from the canonical `utils/countries.py` mapping, never inferred from raw `Resort` table data.

### Feature Specifications
-   **Authentication & Onboarding:** A two-step onboarding process (Identity Setup, Location Setup) follows signup. Welcome modal appears after both steps are complete.
-   **User Profile:** Comprehensive profiles managed via a "Settings" page, including rider types, skill level, pass types, home state, equipment, and visited mountains.
-   **Trip Management:** Users can create trips with location, dates (via inline calendar), public toggles, and ride intent. The Trips page focuses on personal trip management with a simple list of My Trips (2-line format: destination bold, date muted) plus an Open Availability section and Trip Ideas link. Date validation enforces future dates for new trips and prevents duplicate active trips at the same resort.
-   **Date Range Calendar:** An inline calendar allows selecting start and end dates, calculating trip duration automatically. Past dates are disabled for new trips.
-   **Unified Trip Date Display:** All trip dates are consistently formatted using `format_trip_dates(trip)` based on their duration and relation to the current date (e.g., "Today", "Dec 25–Dec 28").
-   **Trip Invites:** Trip owners can invite friends, managing participant status (INVITED/ACCEPTED/DECLINED). Invited users can view trip details before accepting. Accept flow redirects to Trip Detail with "You're going" confirmation; decline flow redirects to My Trips. Trip Detail shows participant overlap copy (e.g., "You and Alex overlap for 2 days").
-   **Friends System:** An invitation-based, bidirectional friendship system with dedicated profiles and token-based invites. The Friends page has 3 tabs: Friends (list with filters), Friends' Trips (upcoming trips from friends), and Overlaps (date/location overlaps with "View" action leading to detail screen with friend list and "Start a trip" CTA).
-   **Trip Ideas:** A standalone page (`/trip-ideas`) showing suggestions based on overlapping open availability with friends. Data flows include date-based open overlaps and wishlist matches. Defensive programming ensures no null entries in the ideas list and template-level guards prevent crashes.
-   **Planning Feature:** A dedicated Planning tab (`/planning`) displays availability overlap windows between the user and their friends. Each card shows a date range and which friends are free. Tapping a card navigates to a People List View (`/planning/window/<start>/<end>`) showing friends available during that window with their identity line. User must have availability set to see overlaps.
-   **Friend Profile Calendar:** Friend profiles feature a List/Calendar toggle for the Upcoming Trips section. The calendar view displays a custom vanilla JS calendar with vertical scrolling months and trip date highlighting. Tapping highlighted dates opens a modal with trip details and navigation to the trip detail page.
-   **Pass Selection:** Quick-select options for major passes, with a dropdown for "Other passes" or "I don't have a pass."
-   **Navigation:** Consistent 4-tab bottom navigation (Trips, Friends, Invite, Profile). Planning is accessed via the segmented toggle inside My Trips.
-   **Location Selector:** A unified typeahead component for state/province selection, grouped by country and alphabetically sorted.
-   **Multi-Pass & International Resort Support:** The `Resort` model includes `pass_brands`, `country`, and expanded `state` fields.
-   **Group Coordination Signals:** `SkiTripParticipant` includes `transportation_status` and `equipment_status` for per-participant coordination, summarized in a Group Signals card on the Trip Detail page.
-   **Carpool Coordination:** Participants can set their carpool role (driver with available seats, or rider needing a ride) via inline picker on the Trip Detail page. Carpool offers emit activity notifications to friends with overlapping trips at the same location.
-   **Lesson Tracking:** Participants can indicate if they're taking lessons (yes/maybe/no) for a trip, helping coordinate group activities.
-   **Wish List Destinations:** Users can save up to 3 aspirational resorts, displayed on profiles with overlap features. Instant-save via `/api/wishlist/add` and `/api/wishlist/remove` (max 3 enforced silently).
-   **Mountains Visited:** Users can track resorts they've skied, grouped by region. Instant-save via `/api/mountains-visited/add` and `/api/mountains-visited/remove`. Read-only friend views at `/mountains-visited/<user_id>`.
-   **Friend Read-Only Views:** `/mountains-visited/<user_id>` and `/wishlist/<user_id>` show a friend's mountains/wishlist (friends-only access, 403 if not friends). Includes "On your wish list" / "You've been here" cross-reference badges.
-   **Profile Stats Bar (profile.html):** Shows Trips / Mountains visited / Wish list — all tappable links. Uses `all_trips_count` (total trips owned by user) not just upcoming. Stats render even at zero.
-   **Friend Profile Stats (stat_row.html):** Rewritten to show Trips / Mountains / Wish list for all contexts. Mountains and Wishlist tiles are tappable when `stat_mountains_url`/`stat_wishlist_url` are provided. Zero-safe with `or 0` guards.
-   **Personalization Features:** Terrain preferences, smart resort defaults, next trip countdown, availability match nudges, and relevance-based friend ordering.

### Account Management (Implemented)
- **Logout** (`/logout`): `@login_required`, calls `logout_user()` only — never `session.clear()` — then redirects to `/auth`.
- **Forgot password** (`/forgot-password`): Generates itsdangerous token only for `auth_provider == 'email'` accounts. OAuth accounts receive the same generic flash message but no email. Always shows the same "If an account exists..." message to prevent email enumeration.
- **Reset password** (`/reset-password/<token>`): 30-minute window via `verify_reset_token(max_age=1800)`. Single-use enforcement: on success, `user.password_changed_at` is set to `utcnow()`. Any future attempt to verify a token issued before that moment is rejected.
- **Change password** (`/change-password`): Google-auth users (`auth_provider != 'email'`) see a friendly "Your account uses Google sign-in" message; the form is not rendered. Email-auth users get the normal current-password → new-password flow. Sets `password_changed_at` on success.
- **Delete account** (`POST /delete-account`): `@login_required`. Requires `confirm_email` to exactly match `current_user.email` (case-insensitive). Deletes all FK-linked rows in safe order (Activity → EmailLog → Event → DismissedNudge → EquipmentSetup → InviteToken → Invitation → SkiTripParticipant → TripGuest → Friend → owned SkiTrips+participants → hosted GroupTrips+guests), then calls `logout_user()`, deletes the User row, commits, and redirects to `/auth`. Wrapped in `try/except` with full rollback on failure. No `session.clear()`.
- **Profile Account section**: Three rows — Change password / Log out / Delete account. Delete account opens an inline confirmation modal requiring the user to type their email before posting to `POST /delete-account`.
- **`password_changed_at` column**: Nullable DateTime on `User`. Migrated to production via Alembic (`272f5f30536f`).

### Hardening Measures (Phase 2B)
- **Dedicated Application Role**: Created `baselodge_app` role with restricted permissions (LOGIN enabled, no superuser/createrole privileges).
- **Credential Separation**: The application now connects using `baselodge_app` instead of the `postgres` superuser.
- **Permission Mapping**: `baselodge_app` has `CONNECT` on the database, `USAGE` on the `public` schema, and `ALL` privileges on existing tables and sequences.
-   **File Structure:** Standardized separation of application logic, models, templates, and static assets.
-   **API Endpoints:** Dedicated routes for core functionalities like authentication, trips, friends, and profiles.
-   **Models:** Key models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `SkiTripParticipant`, and `EquipmentSetup`.
-   **Resort Architecture:** The `Resort` table is the single source of truth for all resort data, with all resort selections (trips, wishlist, visited mountains, home mountain) referencing `Resort` IDs. Geography columns (`country_code`, `country_name`, `state_code`, `state_name`) are canonical, and resort selection flows dynamically query the `Resort` table. A `country_name_override` field allows admins to customize the displayed country name per-resort, accessed via the `display_country_name` property. The canonical `COUNTRIES` mapping in `utils/countries.py` provides ISO-2 code to full name translation. `STATE_ABBR_MAP` (also in `utils/countries.py`) maps all 50 US state codes and 13 Canadian province/territory codes to full display names — imported at module level in `app.py` and used in Add Trip and Edit Trip forms for the `STATE_NAMES` JS constant.
-   **Dev/Local Bootstrap:** In local dev (SQLite, no Supabase), call `/admin/init-db` once after startup to seed 118 US resorts with `country_code='US'` and `state_code` set — required for the state dropdown to derive states correctly. Production always uses Supabase resort data.
-   **Lifecycle Signals:** Canonical User States and tracking fields (`login_count`, `first_planning_timestamp`) enable dynamic UI adjustments and suppress nudges.
-   **Narrative Continuity:** Four narrative states (Early Onboarding, Profile Complete/Not Planning, Planning Started, Active User) dynamically adjust UI copy.
-   **Next Best Action (NBA) System:** Prioritizes a single primary CTA per screen using styling and copy.

## External Dependencies
-   **Flask:** Python web framework.
-   **Flask-Login:** User session management.
-   **SQLAlchemy:** SQL toolkit and ORM.
-   **Werkzeug:** WSGI utility library for password hashing.
-   **Jinja2:** Templating engine.
-   **SQLite:** Default development database.
-   **PostgreSQL:** Production-ready database.
-   **Alembic:** Database migration tool (via Flask-Migrate).