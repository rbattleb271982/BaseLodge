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

### Invite Flow & Link Sharing - COMPLETE ✅
1. **Home intro card restored** - Welcome card displays above tabs showing rider type, pass type, skill level, and "X upcoming trip(s)" count
2. **Backend improvement** - Home route now calculates `upcoming_trips` (end_date >= today) and passes to template
3. **Invite page UI enhanced**:
   - "Copy Invite Link" button copies invite URL to clipboard
   - "Share" button triggers native mobile share sheet (with title, text, URL)
   - Both buttons positioned above QR code section
   - Page header is "Invite a Friend" (simplified)
4. **Backend /invite/<user_id> route** - New route handles invite link flow:
   - Not logged in → redirects to auth with next= parameter
   - Already friends → shows "already_friends.html"
   - Self-invite → shows "connect_self.html"
   - Otherwise → creates bidirectional friendship and shows connect_success.html
5. **Auth flow improvements** - Both signup and login routes now respect ?next= parameter:
   - If profile complete AND next= exists → redirect immediately
   - If profile NOT complete AND next= exists → store in session["next_after_setup"]
   - After profile setup completes → redirect to next_after_setup if it exists

### UI/UX Refactor & Home Page Optimization - COMPLETE ✅
1. **Flash messages protection** - Wrapped flash message blocks with `{% if current_user.is_authenticated %}` in auth.html and add_trip.html to prevent "Trip added" messages from appearing on login/signup screens
2. **Home tabs simplified** - Removed "All Trips" tab, kept: My Trips | Friends' Trips | Overlaps (updated segmented_trips_tabs.html and home.html)
3. **Home header redesigned** - Removed "Next Trip" card at top; page now starts with tab control and trip lists
4. **My Trips edit action** - Added explicit "Edit" link to each trip row in My Trips tab for quick access to trip editing
5. **Friends page compacted** - Removed top "Invite a Friend" button (primary entry is bottom nav); made friend list more compact with 2-line layout (name on line 1, rider type + pass on line 2)
6. **Mountains Visited redesigned** - Complete overhaul:
   - Removed state dropdown entirely
   - Added global search bar that filters mountains in real-time
   - Display selected mountains as pills at top
   - Floating "X selected" counter
   - Save button at top (no scroll needed on mobile)
   - Client-side JS updates pills and counter as checkboxes toggle
7. **My Profile page** - Renamed from "My Info", new clean layout:
   - Profile rows showing: Rider Type, Pass Type, Skill Level, Gender, Home State, Birth Year, Trips (upcoming only), Mountains Visited, Gear
   - Pencil icons (✏️) on editable fields for visual clarity
   - Chevron (›) on Mountains Visited to indicate sub-page
   - No edits on non-editable rows
   - Trips count now shows "X upcoming" (filtered by end_date >= today)
8. **Edit Profile page** - Gear field now displays "Coming soon" (non-editable, greyed out)
9. **Backend updates** - Updated profile route to calculate upcoming_trips_count; updated mountains_visited route to flatten all mountains from MOUNTAINS_BY_STATE into a single sorted list (no state grouping in template)

### QR-Based Friend Connection - COMPLETE ✅
- **Installed segno library** for QR code generation
- **Added `/my-qr` route** - Generates scannable QR code PNG pointing to `/connect/<user_id>`
- **Added `/connect/<user_id>` route** - Displays connection confirmation with smart auth handling
- **Added `/connect/<user_id>/add` POST route** - Creates bidirectional friendships (A→B and B→A)
- **Enhanced auth flow** - Login/signup now honor `next=` parameter for post-auth redirects
- **Enhanced profile setup** - Stores `next_after_setup` in session to redirect after onboarding
- **Updated `/invite` page** - Features QR code section with clear "Invite via QR Code" heading
- **Created connection templates:**
  - `connect_confirm.html` - Confirmation page before adding friend
  - `connect_success.html` - Success message after adding friend
  - `connect_self.html` - Error: cannot add yourself
  - `already_friends.html` - Already connected message
- All templates styled with BaseLodge CSS variables for consistency
- Bidirectional friendship: When User A scans User B's QR and confirms, both are added as friends

## Previous Changes (Dec 11, 2025)

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

### Bug Fixes - COMPLETE ✅
- **Fixed Flask-Login session persistence** by adding `login_user()` calls after signup and login
- **Fixed mountains_visited TypeError** by replacing `hasattr()` checks with safe pattern: `mountains = user.mountains_visited or []`
- **Fixed mutable default bug** by changing `mountains_visited = db.Column(db.JSON, default=[])` to `default=list`
- Applied consistent null-safety pattern across `friend_profile()`, `more()`, and `more_info()` routes

### Trip Overlap Detection - COMPLETE ✅
- **Added `date_ranges_overlap()` helper** to detect when two date ranges overlap
- **Enhanced `/home` route** to build overlaps list comparing user's trips with friends' public trips
- **Added "Overlaps" tab** to trip view alongside My Trips, Friends' Trips, and All Trips
- **Overlap display** shows friend name (clickable to profile), mountain, state, and overlap date range
- Uses `bl-trip-row` styling for visual consistency with BaseLodge design system

### Trip Features
- **Validation:** State, mountain, dates all required; end_date >= start_date
- **Visibility:** `is_public` toggle defaults to ON; controls friend visibility
- **Security:** 403 abort for unauthorized edit/delete attempts
- **Dates:** Support same-day and multi-day trips with proper formatting
- **Overlap Detection:** Identifies when user and friends are at same mountain on overlapping dates

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