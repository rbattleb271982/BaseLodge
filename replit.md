# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application. It helps users track ski days, manage resort passes, and connect with friends. The application provides a modern, mobile-first experience focused on user profiles, an invitation-based friends system, and a centralized trip management hub. The vision is to be the primary platform for snow sports enthusiasts to plan, track, and socialize their winter mountain experiences.

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
The application employs a mobile-first responsive design with a unified "BaseLodge" design system and CSS variables. Key UI elements include segmented controls, a 5-tab bottom navigation with SVG icons (Trips, Friends, Invite, Profile, Feedback), and a home-first navigation paradigm. The color scheme features a deep red accent (`#8F011B` light, `#FF6B7A` dark) with clean backgrounds. Dark mode is system-based via `@media (prefers-color-scheme: dark)`, using an Alpine-inspired palette. Card designs for Home and Friend Profiles use a shared `profile_card.html` component. Profile forms are optimized for mobile, and settings use a card-based layout.

### Technical Implementations
The backend is built with Flask, utilizing SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 is used for templating, complemented by custom CSS and Vanilla JS for interactivity and AJAX. Flask-Login handles session-based authentication. An event system captures user actions for notifications. User lifecycle stages (`new`, `onboarding`, `active`) and canonical states (`is_core_profile_complete`, `has_started_planning`, `is_active_user`) dictate UI and feature availability.

### Feature Specifications
-   **Authentication & Onboarding:** A two-step onboarding process (Identity Setup, Location Setup) follows signup. Welcome modal appears after both steps are complete.
-   **User Profile:** Comprehensive profiles managed via a "Settings" page, including rider types, skill level, pass types, home state, equipment, and visited mountains.
-   **Trip Management:** Users can create trips with location, dates (via inline calendar), public toggles, and ride intent. Trips are displayed in "My Trips", "Friends' Trips", and "Overlaps" tabs. Date validation enforces future dates for new trips and prevents duplicate active trips at the same resort.
-   **Date Range Calendar:** An inline calendar allows selecting start and end dates, calculating trip duration automatically. Past dates are disabled for new trips.
-   **Unified Trip Date Display:** All trip dates are consistently formatted using `format_trip_dates(trip)` based on their duration and relation to the current date (e.g., "Today", "Dec 25–Dec 28").
-   **Trip Invites:** Trip owners can invite friends, managing participant status (INVITED/ACCEPTED/DECLINED). Invited users can view trip details before accepting.
-   **Friends System:** An invitation-based, bidirectional friendship system with dedicated profiles and token-based invites.
-   **Activity Feed:** A "Updates" tab on the Friends screen displays real-time friend activities (e.g., trip created, friend joined trip, connection accepted). Activities are limited to 50 most recent per user.
-   **Pass Selection:** Quick-select options for major passes, with a dropdown for "Other passes" or "I don't have a pass."
-   **Navigation:** Consistent 4-tab bottom navigation (Trips, Friends, Invite, Profile).
-   **Location Selector:** A unified typeahead component for state/province selection, grouped by country and alphabetically sorted.
-   **Multi-Pass & International Resort Support:** The `Resort` model includes `pass_brands`, `country`, and expanded `state` fields.
-   **Group Coordination Signals:** `SkiTripParticipant` includes `transportation_status` and `equipment_status` for per-participant coordination, summarized in a Group Signals card on the Trip Detail page.
-   **Wish List Destinations:** Users can save up to 3 aspirational resorts, displayed on profiles with overlap features.
-   **Personalization Features:** Terrain preferences, smart resort defaults, next trip countdown, availability match nudges, and relevance-based friend ordering.

### System Design Choices
-   **Database:** SQLite for development, PostgreSQL for production, managed with SQLAlchemy.
-   **File Structure:** Standardized separation of application logic, models, templates, and static assets.
-   **API Endpoints:** Dedicated routes for core functionalities like authentication, trips, friends, and profiles.
-   **Models:** Key models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, `SkiTripParticipant`, and `EquipmentSetup`.
-   **Resort Architecture:** The `Resort` table is the single source of truth for all resort data, with all resort selections (trips, wishlist, visited mountains, home mountain) referencing `Resort` IDs. Geography columns (`country_code`, `country_name`, `state_code`, `state_name`) are canonical, and resort selection flows dynamically query the `Resort` table.
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