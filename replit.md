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

## External Dependencies
- **Flask:** Python web framework.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.