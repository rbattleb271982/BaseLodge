# Base Lodge

## Overview
Base Lodge is a Flask-based ski/snowboard trip planning application designed for mountain enthusiasts. Its primary purpose is to help users track their ski days, manage resort passes, and connect with friends. The project features a modern, mobile-first design, robust authentication, and a comprehensive system for planning and sharing ski trips. Key capabilities include user profile management, an invitation-based friends system, and a centralized trip management hub. The ambition is to provide a seamless and engaging experience for planning and documenting snow sports adventures, with future plans for a native mobile application.

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
The application prioritizes a mobile-first responsive design, utilizing a unified "BaseLodge" design system with CSS variables for color, spacing, typography, and components. Key UI elements include segmented controls for selections (e.g., pass/rider type), a 4-tab bottom navigation with emoji icons, and a home-first navigation paradigm. The brand colors are focused around a deep red primary (#8F011B), with a clean background (#F7F7F7) and surface (#FFFFFF). Component partials are used for reusability across templates.

### Technical Implementations
The backend is built with Flask, using SQLAlchemy for ORM and Werkzeug for password hashing. Jinja2 handles templating, complemented by custom CSS for styling and Vanilla JS for interactive elements and AJAX calls. The application uses session-based authentication.

### Feature Specifications
- **Authentication & Onboarding:** Modern signup/login, followed by a three-step onboarding flow capturing rider type, pass type, home state, birth year, and skill level.
- **User Profile:** Comprehensive user profiles storing rider type, pass type, skill level, home state, birth year, gender, gear, and mountains visited.
- **Trip Management:** Users can create ski trips with state-to-mountain linking, date selection, and `is_public` toggles for visibility control. Trips are displayed in a 3-tab interface on the home screen (My Trips, Friends' Trips, All Trips).
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages showing public trip information.
- **Navigation:** A 4-tab bottom navigation (Home, Friends, Invite, Settings) provides consistent access to core features.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized for clarity, separating application logic (`app.py`), database models (`models.py`), templates, and static assets.
- **API Endpoints:** Dedicated API routes for trip management (create, edit, delete) and friend management (invite, list, accept, remove).
- **Models:** Core models include `User`, `SkiTrip`, `Friend`, and `Invitation`, with appropriate relationships and constraints.

## Recent Changes (Dec 11, 2025)

### Trip Management System - COMPLETE ✅
- **Added Flask-Login** for Flask-native user session management
- **Updated User model** to inherit from `UserMixin` for Flask-Login compatibility
- **Updated MOUNTAINS_BY_STATE** mapping to use 2-letter state codes (CO, UT, CA, etc.) for consistency
- **Implemented `/my-trips` route** with Upcoming/Past trip sections using `current_user`
- **Implemented `/add_trip` route (GET/POST)** with form-based trip creation
- **Implemented `/trips/<id>/edit` route (GET/POST)** for form-based trip editing with validation
- **Implemented `/trips/<id>/delete` route (POST)** for trip deletion with 403 protection
- **Updated `/api/mountains/<state>` route** to accept 2-letter state codes
- **Created `templates/add_trip.html`** with dynamic mountain dropdown and validation
- **Created `templates/my_trips.html`** with Upcoming/Past trip cards, edit/delete actions
- **Reusable form template** for both add and edit operations via `trip` and `form_action` variables
- All routes use `@login_required` decorator and `current_user` from Flask-Login

### Trip Features
- **Validation:** State, mountain, dates all required; end_date >= start_date
- **Visibility:** `is_public` toggle defaults to ON; controls friend visibility
- **Security:** 403 abort for unauthorized edit/delete attempts
- **Dates:** Support same-day and multi-day trips with proper formatting

### State Support
Currently supports 15 states with curated mountain lists:
- CO (Colorado) - 12 mountains
- UT (Utah) - 8 mountains  
- CA (California) - 7 mountains
- AK, ID, ME, MI, MT, NH, NM, NY, OR, VT, WA, WY (2-5 mountains each)

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management with login manager and UserMixin.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.