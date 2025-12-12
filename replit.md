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
- **Authentication & Onboarding:** Modern signup/login, followed by simplified one-step onboarding asking only rider_type and skill_level.
- **User Profile:** Comprehensive user profiles storing rider type, pass type, skill level, home state, birth year, gender, gear, and mountains visited.
- **Trip Management:** Users can create ski trips with state-to-mountain linking, date selection, and `is_public` toggles for visibility control. Trips are displayed in a 3-tab interface on the home screen (My Trips, Friends' Trips, Overlaps).
- **Friends System:** Invitation-based, bidirectional friendships with dedicated friend profile pages showing public trip information. Token-based secure invites via `/invite/<token>` and QR codes.
- **Pass Selection:** Dedicated pass selection screen (`/select-pass`) with search bar, grouped pass lists (Major, Regional, Other), and a "Choose your pass" card on Home screen (shown only if pass_type is empty, dismissible with "Skip for now").
- **Navigation:** A 4-tab bottom navigation (Home, Friends, Invite, More) provides consistent access to core features.

### System Design Choices
- **Database:** SQLite for development, PostgreSQL for production, managed via SQLAlchemy.
- **File Structure:** Organized for clarity, separating application logic (`app.py`), database models (`models.py`), templates, and static assets.
- **API Endpoints:** Dedicated API routes for trip management (create, edit, delete) and friend management (invite, list, accept, remove).
- **Models:** Core models include `User`, `SkiTrip`, `Friend`, `Invitation`, and `InviteToken`, with appropriate relationships and constraints.

## Recent Changes (Dec 12, 2025)

### Admin Routes Added ✅
1. **`/generate-dummy-users` (Admin-only)** - Creates 30 fully-functional dummy test users:
   - Protected with `@admin_required` decorator (only richardbattlebaxter@gmail.com)
   - Each user has random rider_type, skill_level, pass_type
   - 2–8 mountains visited from pool
   - 1–3 upcoming trips with realistic dates
   - Returns JSON with list of created emails
   - Skips already-existing dummy users (safe to run multiple times)
2. **`/connect-jonathan-to-dummies` (Admin-only)** - Connects all dummy users to both main accounts:
   - Protected with `@admin_required` decorator
   - Creates bidirectional friendships between:
     - richardbattlebaxter@gmail.com ↔ all dummies
     - jonathanmschmitz@gmail.com ↔ all dummies
   - Returns JSON with count and list of connected dummy emails
   - Safe to run multiple times (checks for existing connections)
3. **Admin Helper** - Added `@admin_required` decorator:
   - Checks `current_user.email == "richardbattlebaxter@gmail.com"`
   - Returns 403 Forbidden if not authenticated or wrong email
   - Used to protect sensitive routes

### Pass Selection Feature - COMPLETE ✅
1. **Added `/select-pass` route** - GET/POST endpoint with pass list:
   - Major Passes: Epic, Ikon, Indy, Mountain Collective
   - Regional Passes: Power Pass, Boyne Pass, A-Basin Pass, Loveland Pass
   - Other: Other, None
2. **Created `select_pass.html` template** - Fully styled with:
   - Search bar for filtering passes
   - Grouped sections for pass categories
   - Client-side JS for selection and filtering
   - Checkbox-style radio selection UI
   - Disabled Save button until pass selected
   - Back link to home
3. **Added `/skip-pass-prompt` route** - Sets `session["pass_prompt_skipped"] = True` and redirects to home
4. **Updated Home screen** - Added conditional "Choose your pass" card showing:
   - Only if `current_user.pass_type` is None or empty
   - Only if `session.get('pass_prompt_skipped')` is not True
   - Contains "Select Pass" button + "Skip for now" link
   - Styled with BaseLodge colors and shadows
5. **Pass submission flow** - Selecting a pass:
   - Sets `current_user.pass_type` to selected value
   - Commits to database
   - Resets `pass_prompt_skipped` to False so card shows again for users without pass
   - Redirects to home
6. **User Model** - `pass_type` field already exists (db.String(100), nullable)

## Previous Changes (Dec 11, 2025)

### Auth & Signup Fixes - COMPLETE ✅
- **Fixed flash message visibility** - Removed `is_authenticated` check from error messages on auth.html so duplicate email/invalid password errors display to all users
- **Simplified onboarding** - Single-screen setup asking only rider_type and skill_level
- **Signup flow working** - Users can successfully sign up and progress through onboarding

### Invite Flow & Link Sharing - COMPLETE ✅
1. **Home intro card restored** - Welcome card displays above tabs showing rider type, pass type, skill level, and "X upcoming trip(s)" count
2. **Backend improvement** - Home route now calculates `upcoming_trips` (end_date >= today) and passes to template
3. **Invite page UI enhanced** - "Copy Invite Link" and "Share" buttons with QR code section
4. **Backend /invite/<user_id> route** - Handles invite link flow with auth redirection
5. **Auth flow improvements** - Both signup and login routes respect `?next=` parameter

### Trip Management System - COMPLETE ✅
- **Added Flask-Login** for Flask-native user session management
- **Updated User model** to inherit from `UserMixin`
- **Implemented `/my-trips` route** with Upcoming/Past trip sections
- **Implemented `/add_trip` and `/trips/<id>/edit` routes** with form-based trip management
- **Implemented `/trips/<id>/delete` route** with 403 protection
- **Created trip management templates** with validation

### Trip Overlap Detection - COMPLETE ✅
- **Added `date_ranges_overlap()` helper** to detect when two date ranges overlap
- **Enhanced `/home` route** to build overlaps list comparing user's trips with friends' public trips
- **Added "Overlaps" tab** to trip view alongside My Trips and Friends' Trips

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management with login manager and UserMixin.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.
