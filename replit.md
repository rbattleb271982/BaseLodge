# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application. It enables users to track ski days, manage resort passes, and connect with friends, offering a modern, mobile-first experience. The project focuses on user profile management, an invitation-based friends system, and a centralized trip management hub, aiming to be a seamless platform for snow sports enthusiasts.

## User Preferences
- Mobile-first design approach (now supporting both web & mobile)
- Unified design system using CSS variables for consistency
- Reusable component partials for DRY templating
- Max width 900px for main pages on web
- Inline modals for trip management (no page navigation)
- Incremental feature rollout prioritizing mobile
- Home-first navigation structure (centralized trip management)
- Segmented controls instead of dropdowns for pass/rider type
- Bottom navigation across all main pages with emoji icons
- System font stack (system-ui, -apple-system, BlinkMacSystemFont, etc.)

## System Architecture

### UI/UX Decisions
The application employs a mobile-first responsive design, utilizing a unified "BaseLodge" design system with CSS variables. It features segmented controls, a 4-tab bottom navigation with emoji icons, and a home-first navigation paradigm. Brand colors include a deep red primary (#8F011B) with clean background (#F7F7F7) and surface (#FFFFFF). Component partials ensure reusability.

### Technical Implementations
The backend is built with Flask, using SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS and Vanilla JS for interactive elements and AJAX. Session-based authentication is used, specifically Flask-Login for robust user session management.

### Feature Specifications
- **Authentication & Onboarding:** Modern signup/login with simplified one-step onboarding for rider_type and skill_level, including Flask-Login for session handling.
- **User Profile:** Comprehensive profiles storing rider type, pass type, skill level, home state, birth year, gender, gear, and mountains visited. The profile is consolidated into the "More" screen.
- **Trip Management:** Users can create ski trips with state-to-mountain linking, date selection, and `is_public` toggles. Trips are displayed in a 3-tab interface (My Trips, Friends' Trips, Overlaps) with trip duration displayed on cards.
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages showing public trip information. Secure token-based invites via `/invite/<token>` and QR codes are supported, with personalized invite messages.
- **Pass Selection:** Epic and Ikon as quick-select buttons storing values "Epic" and "Ikon", with an "Other passes" dropdown containing: Freedom Pass, Indy Pass, Mountain Collective, Powder Alliance, Ski California Pass, Other, None. Pass selection is required during onboarding.
- **Navigation:** A consistent 4-tab bottom navigation (Home, Friends, Invite, More) provides access to core features.
- **Open Dates:** A "Phase 1" feature allowing users to mark available ski dates using a calendar-based selection, stored as a JSON array on the User model. This is separate from trips and enables matching with friends' availability. Backend service: `services/open_dates.py` with `get_open_date_matches(current_user)` function. Debug endpoint: `/open-data-debug`.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized separation of application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated routes for trip management (create, edit, delete) and friend management (invite, list, accept, remove).
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `InviteToken`, `GroupTrip`, `TripGuest`, and `EquipmentSetup`, with defined relationships.
- **Multi-Pass Support (Dec 17, 2025):**
  - `Resort.pass_brands`: New VARCHAR(150) column stores comma-separated pass affiliations (e.g., "Ikon,MountainCollective")
  - Backward compatible: `Resort.brand` remains as primary category
  - Canonical pass lists: Epic (26), Indy (25), Mountain Collective (7 Ikon overlap)
  - Backfill via: `flask backfill-pass-brands` (idempotent, safe to re-run)
  - Current state: All 118 resorts populated (16 Epic, 71 Ikon, 4 Indy, 11 MountainCollective)
- **Social Trip Models (Step 1 - Dec 2025):**
  - `GroupTrip`: Multi-user trip with host_id, title, start/end dates, accommodation_status, transportation_status enums
  - `TripGuest`: Join table linking users to group trips with status (invited/accepted) and unique constraint
  - `EquipmentSetup`: User equipment profiles with slot (primary/secondary), discipline (skier/snowboarder), brand/dimensions
  - Helper: `check_shared_upcoming_trip(user_a_id, user_b_id)` returns True if users share an accepted upcoming trip

- **GroupTrip Social Features (Step 2 - Dec 2025):**
  - Host invitations: Only GroupTrip host can invite their existing friends to trips (from friends list only)
  - Accept invite: Changes status to "accepted" and auto-creates bidirectional Friend connection with host
  - Leave trip: Guest can silently remove themselves (deletes TripGuest row)
  - Remove guest: Host can remove any guest from trip (no feed event)
  - Shared-trip Connect button: Shows on friend profile when users share accepted upcoming GroupTrip and aren't already friends
  - Permissions: All host actions (invite, remove guest) return 403 if non-host attempts them
  - Routes: `/group-trip/<id>` (view), `/group-trip/<id>/invite` (POST), `/group-trip/<id>/accept` (POST), `/group-trip/<id>/leave` (POST), `/group-trip/<id>/remove-guest/<guest_id>` (POST), `/connect-from-trip/<user_id>` (POST)

- **Equipment, Accommodation & Transportation UI (Step 3 - Dec 2025):**
  - **Equipment**: Profile edit page allows add/edit Primary and Secondary setups (Discipline, Brand, Length, Width)
    - Route: POST `/profile/equipment` - Save or update equipment (user-only permission)
    - **View/Edit Toggle UI**: When equipment exists, shows read-only card with Edit button; clicking Edit reveals form with Save/Cancel/Delete buttons
    - Save action reloads page to show fresh state; Cancel returns to view mode without saving
    - Validates length and width as positive integers
    - Max one primary + one secondary per user
  - **Accommodation Status**: GroupTrip detail page shows editable selector for host (read-only badges for guests)
    - Route: POST `/group-trip/<id>/accommodation` - Update status (host-only, returns 403 for non-hosts)
    - Values: Booked, Not yet, Staying with friends
    - Icons: 🏨 🕒 🏠
  - **Transportation Status**: GroupTrip detail page shows editable selector for host (read-only badges for guests)
    - Route: POST `/group-trip/<id>/transportation` - Update status (host-only, returns 403 for non-hosts)
    - Values: Have transportation, Need transportation, Not sure yet
    - Icons: 🚗 🙋 ❓
  - Permissions: Profile owner edits equipment; host-only edits accommodation/transportation
- **Authentication:** Flask-Login is fully integrated for session management, replacing manual session handling, and configured for cross-origin iframe compatibility.

- **Invite Token System (Dec 17, 2025):**
  - `InviteToken` model: Schema is (id, token, inviter_id, created_at, used_at)
  - Single-use enforcement via `used_at` timestamp only
  - `is_used()` method checks if token has been used
  - Friendly error page shown when visiting already-used invite link
  - No multi-use support (max_uses removed from model)

- **UI/UX Updates (Dec 17, 2025):**
  - **Edit Profile**: Mobile-first layout with card sections, floating Save button at bottom
    - Reorganized sections: "About You" (Home State, Home Mountain, Birth Year, Gender) → "Riding Details" (Rider Type, Skill Level) → "Passes" → "Equipment"
    - Home Mountain dropdown filters dynamically based on selected Home State
    - Pass hidden input initialized on page load to preserve existing selections
    - Scaled up: labels 16px, inputs 17px with min-height 48px, chips 12px 20px padding
    - All tap targets meet iOS-friendly 48px minimum height
  - **Passes**: "I don't have a pass" replaces "None" at top of list with mutual exclusion logic (auto-clears other passes when selected, and vice versa)
  - **Mountains Visited**: Removable pill/chip UI with × buttons for selected mountains
  - **Add Trip**: Client-side validation requires resort selection before home mountain checkbox can be checked
  - Max width 500px on profile forms for better mobile experience
  - **Open Availability Calendar**:
    - Selected dates now maroon (#8F011B)
    - "No dates selected" text removed
    - Save button disabled until at least one date selected
    - Dates grouped by month on separate lines (newline separator instead of pipe)
  - **Navigation**: iOS-style stroked SVG icons replace emojis, integrated "Base Lodge" header across all main pages
  - **Friends List**: Shows only primary/first pass from comma-separated pass_type field
  - **Terminology**: "Gear" renamed to "Equipment" across all templates

- **Final Product Spec v1 Alignment (Dec 17, 2025):**
  - **More Page**: Reordered sections to Profile → Equipment & Activity → Account
  - **Change Password**: Separate screen at `/change-password` with current password validation; no auto-logout on success
  - **Friends Cards**: Two-line format with "First Last, State" on line 1 and "Rider Type – Skill Level – Pass" on line 2 using en-dash separators with fallbacks (— for missing, "No Pass" for none)
  - **Onboarding**: Tightened spacing (reduced padding, margins, font sizes) to prevent scrolling on mobile
  - **Ride Intent**: New `ride_intent` column on SkiTrip model (values: "Need a ride", "Have room in car", null)
    - Selectable during Add Trip (dropdown, default=none) and Edit Trip
    - Display-only on Home page (My Trips, Friends' Trips), My Trips page, and friend trip detail page
    - Route: POST `/edit-trip/<id>` includes ride_intent field

- **Settings Refactor (Dec 17, 2025):**
  - **Navigation**: "More" renamed to "Settings" with stroked SVG gear icon in bottom nav
  - **Settings Page**: Navigation hub only with section order: Profile → Equipment & Activity → Account
  - **Dedicated Settings Pages**:
    - `/settings/profile` → redirects to Edit Profile page
    - `/settings/equipment` → Equipment management (dedicated page)
    - `/settings/mountains-visited` → redirects to Mountains Visited page
    - `/settings/password` → redirects to Change Password page
  - **Equipment Model Extensions**:
    - `binding_type` (string, nullable): Skier bindings (Alpine, Touring, Hybrid, Telemark, Other) or Snowboarder (Standard, Step-On, Splitboard, Other)
    - `boot_brand` (string, nullable): Salomon, Tecnica, Lange, Atomic, Dalbello, Nordica, K2, Fischer, Burton, ThirtyTwo, Ride, Vans, DC, Other
    - `boot_flex` (integer, nullable): Any positive number (expected range 80-140)
  - **Equipment UI**: 
    - Read-only display shows new fields only when values exist
    - Separate Edit buttons for Primary/Secondary setups
    - Auto-clears binding_type when discipline changes
  - **Removed**: Equipment section from Edit Profile (now only at /settings/equipment)

## Test Users (Main)
- **Richard Battle-Baxter:** richardbattlebaxter@gmail.com / 12345678
  - Epic pass, Advanced skier, Colorado
  - Original primary test user
- **Jonathan Schmitz:** jonathanmschmitz@gmail.com / 12345678
  - Epic pass, Advanced skier, Utah
  - Created via: `flask create-jonathan-and-connect`
- **Sam Stookesberry:** samstookes@gmail.com / 12345678
  - Epic pass, Advanced skier, Wyoming
  - Created via: `flask add-sam-stookesberry`

## Test Users (Seeded Data)
- **50 dummy users** with realistic profiles, mixed pass types (Epic/Ikon), various skill levels
  - All bidirectionally connected to Richard, Jonathan, and Sam
  - Each has 4+ future-dated ski trips with overlaps
  - Created via: `flask seed-database`

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.

## Deployment & Database Initialization

### Critical: Module-level Database Code Removed
All database initialization code has been moved OUT of module level to enable clean deployment to production servers. The app now imports without executing database operations.

### Two Methods to Initialize Database

#### Method 1: Flask CLI Command (Recommended)
```bash
flask init-db
```
- Creates all database tables
- Ensures primary user (Richard Battle-Baxter) exists
- Logs initialization status
- Idempotent (safe to run multiple times)

#### Method 2: HTTP Endpoint (Backup)
If CLI command is not available in your deployment environment:
```
GET /admin/init-db
```
- Same functionality as CLI command
- Returns JSON response
- Works in development and production

### Development Workflow (Local)
```bash
python app.py  # Start dev server
# In another terminal:
flask init-db  # Initialize database
```

### Production Deployment Steps
1. Deploy the application to production
2. Server starts cleanly (no database operations during import)
3. Run: `flask init-db` OR access `/admin/init-db`
4. Application is ready to use

**Why this change:** Production servers (gunicorn) require apps to import cleanly without side effects. Module-level database access causes initialization failures.

See `DEPLOYMENT.md` for complete deployment guide.