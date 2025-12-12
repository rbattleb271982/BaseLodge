# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application designed to help users track ski days, manage resort passes, and connect with friends. It features a modern, mobile-first design, robust authentication, and comprehensive trip planning and sharing. Key capabilities include user profile management, an invitation-based friends system, and a centralized trip management hub. The project aims to provide a seamless and engaging experience for snow sports enthusiasts, with future plans for a native mobile application.

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
The application prioritizes a mobile-first responsive design, utilizing a unified "BaseLodge" design system with CSS variables. Key UI elements include segmented controls, a 4-tab bottom navigation with emoji icons, and a home-first navigation paradigm. The brand colors are a deep red primary (#8F011B) with clean background (#F7F7F7) and surface (#FFFFFF). Component partials are used for reusability.

### Technical Implementations
The backend is built with Flask, using SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS and Vanilla JS for interactive elements and AJAX. The application uses session-based authentication.

### Feature Specifications
- **Authentication & Onboarding:** Modern signup/login with a simplified one-step onboarding for rider_type and skill_level.
- **User Profile:** Comprehensive profiles storing rider type, pass type, skill level, home state, birth year, gender, gear, and mountains visited.
- **Trip Management:** Users can create ski trips with state-to-mountain linking, date selection, and `is_public` toggles. Trips are displayed in a 3-tab interface (My Trips, Friends' Trips, Overlaps).
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages showing public trip information. Secure token-based invites are supported via `/invite/<token>` and QR codes.
- **Pass Selection:** A dedicated screen (`/select-pass`) with search, grouped pass lists (Major, Regional, Other), and a dismissible "Choose your pass" card on the Home screen.
- **Navigation:** A consistent 4-tab bottom navigation (Home, Friends, Invite, More) provides access to core features.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized for clarity, separating application logic, models, templates, and static assets.
- **API Endpoints:** Dedicated API routes for trip management (create, edit, delete) and friend management (invite, list, accept, remove).
- **Models:** Core models include `User`, `SkiTrip`, `Resort`, `Friend`, `Invitation`, and `InviteToken`, with appropriate relationships.

## Recent Changes (Dec 12, 2025)

### Auth Screen UX Improvements - COMPLETE
Updated signup/login screen with improved clarity:
1. **Segmented control tabs** - Pill-style buttons with red active state
2. **Show/hide password toggle** - Both signup and login forms
3. **Password helper text** - "At least 8 characters" below signup password field
4. **Updated disclaimer** - "You're joining an early test version of Base Lodge."
5. **Autocomplete attributes** - Added for better browser autofill support

### Home Screen Redesign (v0 Layout) - COMPLETE
Updated Home Screen to match new v0 design:
1. **CSS design tokens** - Warm neutral theme (#FAF7F2 background, #E9E4DE borders)
2. **Profile header card** - Welcome message, rider type, pass, skill level, trip count
3. **Onboarding card** - Pass selection prompt with "Skip for now" option
4. **Pill-style tabs** - "My Trips", "Friends' Trips", "Overlaps" with rounded pill buttons
5. **Trip cards** - Unified display format with "No Pass" fallback
6. **Simplified bottom nav** - Text-only labels

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.