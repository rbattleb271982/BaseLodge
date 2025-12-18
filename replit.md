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

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.