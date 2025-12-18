# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application designed to help users track ski days, manage resort passes, and connect with friends. It offers a modern, mobile-first experience with a focus on user profiles, an invitation-based friends system, and a centralized trip management hub, aiming to be a seamless platform for snow sports enthusiasts.

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
The application utilizes a mobile-first responsive design with a unified "BaseLodge" design system and CSS variables. Key UI elements include segmented controls, a 4-tab bottom navigation with SVG icons (replacing emojis), and a home-first navigation paradigm. Brand colors are a deep red (#8F011B) with clean backgrounds (#F7F7F7) and surfaces (#FFFFFF). Component partials ensure reusability. Profile forms are optimized for mobile with a max-width of 500px and scaled-up interactive elements.

### Technical Implementations
The backend is built with Flask, using SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS and Vanilla JS for interactive elements and AJAX. Flask-Login provides robust session-based authentication.

### Feature Specifications
- **Authentication & Onboarding:** Modern signup/login with simplified one-step onboarding, leveraging Flask-Login.
- **User Profile:** Comprehensive profiles (rider type, pass type, skill level, home state, birth year, gender, equipment, mountains visited) consolidated into a "Settings" page.
- **Trip Management:** Users can create ski trips with state-to-mountain linking, date selection, `is_public` toggles, and `ride_intent` status. Trips are displayed in a 3-tab interface (My Trips, Friends' Trips, Overlaps).
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages. Secure token-based invites via `/invite/<token>` and QR codes are supported.
- **Pass Selection:** Supports quick-select for Epic/Ikon, and a dropdown for "Other passes." Required during onboarding. "I don't have a pass" option manages mutual exclusion with other pass selections.
- **Navigation:** A consistent 4-tab bottom navigation (Home, Friends, Invite, Settings) using iOS-style stroked SVG icons.
- **Open Dates:** Users can mark available ski dates using a calendar for matching with friends' availability.
- **Multi-Pass Support:** `Resort` model includes `pass_brands` for multiple affiliations.
- **Social Trip Models (`GroupTrip`):** Supports multi-user trips with host invitations, guest acceptance/leaving, and host-managed guest removal. Integrates `TripGuest` and `EquipmentSetup` models.
- **Equipment Management:** Users can add/edit Primary and Secondary equipment setups (Discipline, Brand, Length, Width, Binding Type, Boot Brand, Boot Flex) via a dedicated settings page. Primary equipment supports optional `purchase_year` field displayed as "Bought: YYYY" on own profile only.
- **Accommodation & Transportation Status:** Hosts can update accommodation and transportation statuses for group trips.
- **Invite Token System:** Single-use invite tokens (`InviteToken` model) enforce one-time usage for friend invitations.
- **Wish List Destinations:** Users can save up to 3 aspirational resorts via Settings. Displayed on own profile and friend profiles. Friend profiles show "Wish List Overlap" when both users share destination resorts.
- **Friend Profile Features:** Full-page friend profiles at `/friends/<id>` with header card, equipment display, upcoming trips, pass compatibility badges ("Can ski your upcoming trips"), trip overlaps, availability overlaps, and wish list sections.
- **Personalization Features (Dec 2025):**
  - *Terrain Preferences:* Users can select up to 2 terrain types (Groomers, Trees, Park, Backcountry), displayed on friend profiles with secondary text
  - *Smart Resort Defaults:* Trip creation pre-selects user's home state and sorts resorts by pass compatibility
  - *Countdown to Next Trip:* Home page shows "Your next trip starts in X days" banner for upcoming trips
  - *Availability Match Nudge:* Dismissible notification on Home showing friend availability overlaps (with DismissedNudge tracking)
  - *Friend Ordering by Relevance:* Friends list sorted by trip overlap, pass compatibility, and shared availability (score hidden)
  - *Rider-Aware Copy:* Jinja helpers (get_gear_term, get_ride_term) for context-aware terminology
  - *Seasonal Awareness:* Empty states adjust based on season (preseason, midseason, spring, offseason)
- **UI/UX Polish Pass (Dec 2025):**
  - *Settings screen:* Card-based layout with 24px group spacing, reduced header weight (12px, 600 weight)
  - *Wish List Destinations:* Redesigned to match Mountains Visited pattern (pills with × buttons, state filter, typeahead search)
  - *Equipment page:* Card layout with 12px gaps, removed section dividers
  - *Invite screen:* Hierarchy reordered (text invite primary → QR code at 200px → copy link as underlined text)
  - *Flash messages:* "Trip added" scoped to create route only, edit trips save silently

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized separation of application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated routes for authentication, trip management (create, edit, delete), friend management (invite, list, accept, remove), and profile/equipment updates.
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `InviteToken`, `GroupTrip`, `TripGuest`, and `EquipmentSetup`, with defined relationships.
- **Database Initialization:** Database initialization logic is decoupled from module-level imports, using `flask init-db` CLI command or `/admin/init-db` HTTP endpoint for idempotent setup.
- **Test Data Seeding:** Visit `/admin/seed-test-users` to create demo data including:
  - Primary user: richard@richard.com / 12345678
  - 20 friends with complete profiles, trips, equipment
  - Bidirectional friendships and date overlaps for testing feeds

## Email & Notification Infrastructure (Dec 2025)

### User Lifecycle & Identity
- **created_at:** Timestamp of user registration (backfilled from earliest trip/friend activity)
- **last_active_at:** Updated only on login; measures presence
- **lifecycle_stage:** Simplified model with three stages: `new`, `onboarding`, `active` (derived by logic, not user-controlled)
- **is_seeded:** Flag to exclude test users from lifecycle logic, events, and email

### Email Preferences (Channel-Agnostic)
- **email_opt_in:** Master consent (default TRUE)
- **email_transactional:** For account events (default TRUE)
- **email_social:** For connection/trip invites (default FALSE)
- **email_digest:** For weekly/digest emails (default FALSE)
- **timezone:** User's timezone for send scheduling (nullable)

### Event System (Foundation)
**Event table:** Captures high-signal user actions for email/push notifications
- account_created
- onboarding_completed
- profile_completed
- trip_created
- trip_joined
- connection_created
- open_dates_set

Seeded users are excluded from event emission.

### Email Logging & Suppression
**EmailLog table:** Tracks all email sends for deduplication & suppression
- Prevents duplicate sends for same event
- Tracks send count & last_sent_at per email_type
- Links to source event for audit trail
- Environment tagged (dev/prod) for safe local testing

## Step 6 Event Emission Wiring (Dec 18, 2025)

**5 of 7 approved events now emit on user actions:**
- ✅ account_created - When user signs up (auth route)
- ✅ onboarding_completed - When user completes setup_profile
- ✅ profile_completed - When user edits full profile (edit_profile)
- ✅ trip_created - When user creates a ski trip (create_trip)
- ✅ connection_created - When user accepts friend invite (_connect_pending_inviter)
- ⏳ trip_joined - Route identified: `/group-trip/<trip_id>/accept` (accept_group_trip_invite)
- ⏳ open_dates_set - Route identified: `/add-open-dates` POST (add_open_dates)

**Event Emission Implementation:**
- Helper function `emit_event(event_name, user, payload)` added to app.py
- Respects is_seeded flag: test users excluded from event emission
- Stores event_name, user_id, payload, created_at, environment in Event table
- Ready for Step 7 backfill & Step 8 SendGrid integration

## Step 7 Lifecycle Backfill (Dec 18, 2025)

**Simplified lifecycle model implemented:**
- **new**: User created, no onboarding milestones
- **onboarding**: onboarding_completed_at set, but no profile/trip/connection yet
- **active**: profile_completed_at OR first_trip_created_at OR first_connection_at set

**Backfill Results (non-seeded users):**
- 75 users backfilled, all remain 'new' (expected: seeded users have no milestones)
- Real users going forward will populate milestones as they take actions
- Lifecycle stage auto-updates on event emission via milestone timestamps

**Lifecycle Derivation Logic:**
- Derived from milestone timestamps (not user-controlled)
- Excludes seeded users (is_seeded=FALSE filter)
- Profile completion OR trip creation OR first connection → 'active'
- Onboarding completion without profile/trip/connection → 'onboarding'

## Remaining Event Routes (Not Yet Wired - Ready for Step 8+)

**trip_joined:**
- Route: POST `/group-trip/<trip_id>/accept`
- Handler: `accept_group_trip_invite(trip_id)` at line 3267
- Trigger: When guest accepts GroupTrip invitation (TripGuest.status = GuestStatus.ACCEPTED)
- Payload: trip_id, accepted_by_user_id

**open_dates_set:**
- Route: POST `/add-open-dates`
- Handler: `add_open_dates()` at line 1960
- Trigger: When user updates open_dates calendar (User.open_dates updated)
- Payload: date_count, dates (array of YYYY-MM-DD strings)

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.
- **Alembic:** Database migration tool (via Flask-Migrate).