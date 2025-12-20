# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application designed to help users track ski days, manage resort passes, and connect with friends. It offers a modern, mobile-first experience with a focus on user profiles, an invitation-based friends system, and a centralized trip management hub, aiming to be a seamless platform for snow sports enthusiasts. The business vision is to create a primary platform for snow sports enthusiasts to plan, track, and socialize their winter mountain experiences.

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
The application uses a mobile-first responsive design with a unified "BaseLodge" design system and CSS variables. Key UI elements include segmented controls, a 4-tab bottom navigation with SVG icons, and a home-first navigation paradigm. Brand colors are a deep red (#8F011B) with clean backgrounds (#F7F7F7) and surfaces (#FFFFFF). Component partials ensure reusability. Profile forms are optimized for mobile with a max-width of 500px and scaled-up interactive elements. Settings screens utilize a card-based layout with redesigned wish list and equipment sections. Flash messages are context-specific.

### Technical Implementations
The backend is built with Flask, using SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS and Vanilla JS for interactive elements and AJAX. Flask-Login provides robust session-based authentication. An event system captures high-signal user actions for email/push notifications, excluding seeded users. Email logging and suppression prevent duplicate sends. User lifecycle stages (`new`, `onboarding`, `active`) are derived from user actions and milestones. Canonical user states (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) dictate UI copy and feature availability.

### Feature Specifications
- **Authentication & Onboarding:** Modern signup/login with simplified one-step onboarding using Flask-Login.
- **User Profile:** Comprehensive profiles (rider type, pass type, skill level, home state, birth year, gender, equipment, mountains visited) consolidated into a "Settings" page.
- **Trip Management:** Users create trips with state-to-mountain linking, dates, `is_public` toggles, `ride_intent` status. Trips are displayed in a 3-tab interface (My Trips, Friends' Trips, Overlaps). Supports `day_trip`, `one_night`, `two_nights`, `three_plus_nights` durations, with auto-calculation and prominent display. Duplicate active trips at the same resort are prevented. Users can filter trips by duration and equipment status.
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages. Supports token-based invites via URL and QR codes.
- **Pass Selection:** Quick-select for Epic/Ikon, "Other passes" dropdown, and "I don't have a pass" option.
- **Navigation:** Consistent 4-tab bottom navigation (Home, Friends, Invite, Settings) using iOS-style stroked SVG icons.
- **Open Dates:** Users mark available ski dates on a calendar for friend matching.
- **Multi-Pass Support:** `Resort` model includes `pass_brands`.
- **International Resort Support:** `Resort` model includes `country` (ISO-2 codes) and expanded `state` field for international regions.
- **Shared Interest Discovery:** Home screen displays "Shared Interest" card for overlapping wishlist resorts.
- **Social Trip Models (`GroupTrip`):** Supports multi-user trips with host invitations, guest management, `TripGuest` and `EquipmentSetup` integration. Hosts can update accommodation and transportation statuses.
- **Equipment Management:** Users add/edit Primary and Secondary equipment setups (Discipline, Brand, Length, Width, Binding Type, Boot Brand, Boot Flex) via settings. Users can set a global `equipment_status` (`have_own_equipment`, `needs_rentals`) with per-trip overrides.
- **Wish List Destinations:** Users save up to 3 aspirational resorts, displayed on profiles with "Wish List Overlap" for friends.
- **Friend Profile Features:** Full-page profiles at `/friends/<id>` show header card, equipment, upcoming trips, pass compatibility, trip/availability overlaps, and wish lists.
- **Personalization Features:** Terrain preferences, smart resort defaults in trip creation, countdown to next trip, availability match nudges, relevance-based friend ordering, rider-aware copy, and seasonal awareness for empty states.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized separation of application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated routes for authentication, trip management, friend management, and profile/equipment updates.
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `InviteToken`, `GroupTrip`, `TripGuest`, and `EquipmentSetup`, with defined relationships.
- **Database Initialization:** Idempotent database initialization via `flask init-db` CLI command or `/admin/init-db` HTTP endpoint.
- **Test Data Seeding:** `/admin/seed-test-users` provides demo data including a primary user, 20 friends with complete profiles, trips, equipment, and bidirectional friendships.

### Lifecycle Signals (Dec 2025)

**Canonical User States (computed properties on User model):**
- `is_core_profile_complete`: True when rider_type AND pass_type AND skill_level all present
- `has_started_planning`: True when `first_planning_timestamp` is set OR user has created a SkiTrip OR accepted as TripGuest
- `is_active_user`: True when `is_core_profile_complete` AND `has_started_planning`

**Lifecycle Signal Fields:**
- `login_count`: Integer, incremented on every successful login (second-login detection: `login_count == 2`)
- `first_planning_timestamp`: Set when user first creates a trip or accepts TripGuest (idempotent via `mark_planning_started()`)
- `planning_completed_timestamp`: Set when user completes OR dismisses planning callout flow

**Signal Integration Rules:**
- Suppress planning nudges if `has_started_planning` is true OR `planning_completed_timestamp` is set
- Suppress onboarding nudges if `is_core_profile_complete` is true
- UI copy adapts based on 4 narrative states (see below)

### Narrative Continuity (Dec 2025)

**4 Narrative States (derived dynamically, not stored):**

| State | Conditions | Intent | Example Copy |
|-------|------------|--------|--------------|
| 1. Early Onboarding | `!is_core_profile_complete && login_count <= 1` | Welcoming, light guidance | "Welcome, [Name]", "Finish setting up your profile" |
| 2. Profile Complete, Not Planning | `is_core_profile_complete && !has_started_planning && login_count >= 2` | Confident, invitational | "You're all set", "Now put it to use" |
| 3. Planning Started | `has_started_planning && !is_active_user` | Affirming, directional | "[Name], you're planning", "Here's what's next" |
| 4. Active User | `is_active_user` | Calm, non-instructional | "[Name]", "+ Add a trip", "Edit Profile" |

**Screens with narrative copy:**
- Home: Headline adapts, empty states use state-appropriate messaging
- Edit Profile: Title adapts ("Finish setting up" vs "Edit Profile"), subhead for State 1
- Friends: Empty state copy adapts per state
- More/Settings: No narrative copy (utility-focused)

### Next Best Action (NBA) System (Dec 2025)

**Core Rule:** At most ONE primary CTA (`.bl-btn-primary`) per screen. Some states intentionally have NO primary CTA.

**NBA by State and Screen:**

| Screen | State 1 (Early Onboarding) | State 2 (Profile Complete) | State 3 (Planning Started) | State 4 (Active) |
|--------|---------------------------|---------------------------|---------------------------|------------------|
| **Home - My Trips** | Copy only; "Select Pass" card is primary if shown | "Create a trip" is primary | Secondary button only | Secondary button only |
| **Home - Open Avail** | Secondary button | Secondary button | Secondary button | Secondary button |
| **Friends** | Secondary button (copy-only NBA) | Secondary button | Secondary button | Secondary button |
| **Edit Profile** | Copy only ("Finish setting up") | Copy only | Copy only | Copy only |
| **More/Settings** | No NBA (utility) | No NBA | No NBA | No NBA |

**Implementation Rules:**
- NBA expressed via: primary vs secondary button styling, CTA copy, headline alignment
- No new UI components added
- No features hidden or removed
- No navigation reordering

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.
- **Alembic:** Database migration tool (via Flask-Migrate).
- **SendGrid:** (Planned for email integration).