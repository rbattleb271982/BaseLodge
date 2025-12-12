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
- **Pass Selection:** A dedicated screen (`/select-pass`) with search, grouped pass lists (Major, Regional, Other), and a dismissible "Choose your pass" card on the Home screen, including a simplified onboarding pass selection.
- **Navigation:** A consistent 4-tab bottom navigation (Home, Friends, Invite, More) provides access to core features.
- **Open Dates:** A "Phase 1" feature allowing users to mark available ski dates using a calendar-based selection, stored as a JSON array on the User model. This is separate from trips and enables matching with friends' availability. Backend service: `services/open_dates.py` with `get_open_date_matches(current_user)` function. Debug endpoint: `/open-data-debug`.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized separation of application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated routes for trip management (create, edit, delete) and friend management (invite, list, accept, remove).
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, and `InviteToken`, with defined relationships.
- **Authentication:** Flask-Login is fully integrated for session management, replacing manual session handling, and configured for cross-origin iframe compatibility.

## Test Users
- **Primary test user:** richardbattlebaxter@gmail.com / 12345678
- **Jonathan Schmitz:** Jonathanmschmitz@gmail.com / 12345678
  - Connected as friends to all 78 existing users (bidirectional)
  - Created via Flask CLI command: `flask create-jonathan-and-connect`

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.