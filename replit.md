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
The application uses a mobile-first responsive design with a unified "BaseLodge" design system and CSS variables. Key UI elements include segmented controls, a 4-tab bottom navigation with SVG icons, and a home-first navigation paradigm. Brand colors are a deep red (#8F011B) with clean backgrounds (#F7F7F7) and surfaces (#FFFFFF). Component partials ensure reusability. Profile forms are optimized for mobile with a max-width of 500px. Settings screens utilize a card-based layout. Flash messages are context-specific.

Card designs for Home and Friend Profiles use a shared `components/profile_card.html` component with an `is_owner` flag. The card displays Name, Identity line (via `identity_line` filter), Riding Style, Terrain Preferences, and Equipment. Stats row shows 3 columns: "Trips Created", "Visited Mountains", "Bucket List Mountains" with labels above numbers. For owners, stats are tappable links to respective edit pages; for friends, stats are read-only. Equipment displays brand/model or boot-only data with fallback logic. Profile cards are read-only identity snapshots; settings are the source of truth for editable fields. Terrain preferences allow max 2 selections from Groomers, Trees, Steeps, Park. When selecting a 3rd option, the oldest selection is automatically replaced (no blocking). Legacy "First Chair" and "Après" values are preserved but not selectable.

Friends List uses a 2-row structure for Name, Status, Rider Type, Passes, and Skill Level.

### Centralized Identity Formatter
All identity lines use a `{{ user|identity_line }}` Jinja2 filter. The format is `Rider Types · Pass1 · Pass2 · Skill Level`. Rules include:
- **Rider Types:** Multi-select display, all types joined with " & " (e.g., "Skier & Snowboarder")
- **Passes:** All passes listed individually, never "Both"
- **Skill Level:** Last if present
- Home state excluded from identity line
- Typography scales are increased for card contexts

### Technical Implementations
The backend uses Flask, SQLAlchemy for ORM, and Werkzeug for password hashing. Jinja2 handles templating with custom CSS and Vanilla JS for interactivity and AJAX. Flask-Login provides session-based authentication. An event system captures high-signal user actions for notifications. User lifecycle stages (`new`, `onboarding`, `active`) and canonical user states (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) dictate UI and feature availability.

### Feature Specifications
- **Authentication & Onboarding:** Two-step flow: (1) Minimal signup collects only first name, last name, email, password. (2) Full-screen Identity Setup immediately after signup collects rider_types (multi-select), skill_level (radio), and pass_type (multi-select chips). Simplified Welcome modal (single "Done" CTA) appears once after signup. Stop condition: `welcome_modal_seen_at` set. User model computed properties: `is_core_profile_complete`, `is_equipment_complete`, `is_profile_complete`. Equipment is optional and managed in Settings > Equipment. Follows prompt-on-intent principle: no auto-prompts for optional data.
- **User Profile:** Comprehensive profiles (multi-select rider types, pass, skill, home state, equipment, visited mountains) within a "Settings" page.
- **Trip Management:** Create trips with country-first location, dates via inline date-range calendar, public toggles, ride intent. Displayed in 3 tabs (My Trips, Friends' Trips, Overlaps). Auto-calculates duration as inclusive days. Date validation enforces future dates for new trips. Prevents duplicate active trips at the same resort. Includes resort search and filters. Group trip creation via "Propose a trip" flow with URL prefill params (friend_id, start_date, end_date, is_group). Trip Detail page at `/trips/<id>` serves as the primary trip hub with owner invite CTA and participant list.
- **Date Range Calendar:** Single inline calendar replaces separate date inputs. First tap selects start date, second tap selects end date. Tapping earlier than start resets the range. Same-day trips allowed. Duration calculated as `(end - start) + 1` days and stored automatically. Confirmation helper shows "Dec 25–27 · 3 days" below calendar. Past dates disabled for new trips but allowed when editing.
- **Trip Invites:** Trip owners can invite connected friends from Trip Detail page. Invites use SkiTripParticipant model with INVITED/ACCEPTED/DECLINED status. Invited users can view trip details before accepting. Home page shows pending invites with Accept/Decline actions.
- **Friends System:** Invitation-based, bidirectional friendships with dedicated profiles supporting token-based invites.
- **Pass Selection:** Quick-select for Epic/Ikon, "Other passes" dropdown, or "I don't have a pass."
- **Navigation:** Consistent 4-tab bottom navigation (Home, Friends, Invite, Settings).
- **Open Dates:** Users mark available ski dates for friend matching.
- **Multi-Pass & International Resort Support:** `Resort` model includes `pass_brands`, `country`, and expanded `state` for international regions.
- **Shared Interest Discovery:** Home screen card for overlapping wishlist resorts.
- **Social Trip Models (`GroupTrip`):** Supports multi-user trips with host and guest management.
- **Equipment Management:** Users add/edit Primary and Secondary equipment setups via settings. Displays as "Brand Model". Allows global and per-trip `equipment_status`.
- **Trip Accommodations:** Trip form now includes accommodation_status (none_yet, hotel, airbnb, other) and optional accommodation_link fields. Link input shown conditionally based on status.
- **Group Coordination Signals:** SkiTripParticipant includes transportation_status and equipment_status for per-participant trip coordination. Trip Detail page shows aggregated Group Signals summary card. Organizer is always a participant (auto-created on trip creation). Who's Going section uses tappable badges that open bottom sheet pickers for editing. Organizer sees inline reminder on invite intent if signals unset. Backfill endpoint: `/admin/backfill-organizers-as-participants`.
- **Wish List Destinations:** Users save up to 3 aspirational resorts, displayed on profiles with overlap features.
- **Friend Profile Features:** Full-page profiles showing header card, equipment, upcoming trips, pass compatibility, trip/availability overlaps, and wish lists.
- **Personalization Features:** Terrain preferences, smart resort defaults, countdown to next trip, availability match nudges, relevance-based friend ordering, rider-aware copy, and seasonal awareness.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized separation of application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated routes for authentication, trip, friend, profile, and equipment management.
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `InviteToken`, `GroupTrip`, `TripGuest`, `SkiTripParticipant`, and `EquipmentSetup`.
- **Database Initialization:** Idempotent via `flask init-db` or `/admin/init-db`.
- **Test Data Seeding:** `/admin/seed-test-users` provides demo data.

### Resort Architecture (Dec 2025)
The `Resort` table is the single source of truth for resort data. All resort selections now store Resort IDs:
- **Trips:** `SkiTrip.resort_id` (FK to Resort)
- **Wishlist:** `User.wishlist_resort_ids` (JSON array of Resort IDs)
- **Visited Mountains:** `User.visited_resort_ids` (JSON array of Resort IDs) with `User.mountains_visited` legacy fallback
- **Home Mountain:** `User.home_resort_id` (FK to Resort) with `User.home_mountain` legacy fallback

**Migration Pattern:** Dual-write strategy maintains backward compatibility. All write operations update both new ID fields and legacy string fields. GET operations prioritize legacy data then merge Resort IDs. Admin backfill endpoint: `/admin/backfill-resort-ids`.

**Helper Methods:**
- `User.get_visited_resorts()` - Returns Resort objects for visited mountains
- `User.visited_resorts_count` - Property returning count
- `User.get_home_resort()` - Returns Resort object for home mountain
- `find_resort_by_name(name, state_code)` - Case-insensitive resort lookup with alias support

**Future Work:** UI should transition from `MOUNTAINS_BY_STATE` constant to Resort table queries for checkboxes.

### Lifecycle Signals
Canonical User States (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) are computed properties on the User model. Lifecycle signal fields like `login_count`, `first_planning_timestamp`, and `planning_completed_timestamp` track user progress. These signals suppress nudges and adapt UI copy based on 4 narrative states.

### Narrative Continuity
Four narrative states (Early Onboarding, Profile Complete/Not Planning, Planning Started, Active User) dynamically adjust UI copy on Home, Friends, and Edit Profile screens based on user's progress.

### Next Best Action (NBA) System
At most one primary CTA (`.bl-btn-primary`) per screen. NBA is expressed via button styling, CTA copy, and headline alignment, without adding new UI components or reordering navigation.

### Production Readiness
Includes a backfill script for `first_planning_timestamp` and test users for narrative state validation. Deprecated fields are noted for backward compatibility.

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.
- **Alembic:** Database migration tool (via Flask-Migrate).