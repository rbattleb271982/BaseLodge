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

### Setup Profile & Before Request Handler - COMPLETE
1. **Created /setup-profile route** - Collects Rider Type and Pass Type with segmented controls
2. **Added @login_required** - Protects setup_profile and cleaned up old session logic
3. **Added before_request handler** - Redirects incomplete users (missing rider_type or pass_type) to /setup-profile
4. **Updated auth flow** - Login/signup now check rider_type and pass_type instead of profile_setup_complete field
5. **Cleaned up all profile_setup_complete references** - Removed deprecated field usage throughout app

### Trip Row Design Standardization - COMPLETE
Unified trip card design across all trip displays:
1. **Canonical trip row design** - Single horizontal row: bold dates, location inline, subtle card container
2. **Applied to Home Screen tabs** - My Trips, Friends' Trips, Overlaps all use consistent .bl-trip-card
3. **Updated My Trips page** - Refactored from vertical stacking to inline horizontal design
4. **Consistent CSS** - Updated .bl-trip-card and related styles for unified appearance
5. **Updated trip_row.html component** - Made it more reusable and aligned with canonical design

### Bottom Navigation Bar Fix - COMPLETE
Restored mobile-first bottom navigation design:
1. **Fixed class names** - Changed from .bl-bottom-nav-new to .bl-bottom-nav, .bl-bottom-nav-btn to .bl-nav-item
2. **Added emoji icons** - Home (🏠), Friends (👥), Invite (🎟️), More (⚙️)
3. **Active state detection** - Using request.endpoint to highlight current page
4. **Styling restored** - Fixed positioning, proper spacing, color transitions
5. **Touch-friendly** - 56px height, 4-column flex layout, proper tap targets

### Onboarding Pass Type Selection - COMPLETE
High-level pass family selector for fast onboarding:
1. **5 pass options only** - Epic, Ikon, Indy, Other, None (no search bar)
2. **"None" is first-class** - Valid option for users without a pass
3. **Segmented control UI** - Pill buttons with wrap layout for mobile
4. **Continue button gated** - Disabled until both rider_type AND pass_type selected
5. **Calm, reassuring copy** - "Tell us a bit about yourself to get started" + "You can change these later in your profile"
6. **Saves as pass family** - Stored in user.pass_type field without schema changes
7. **Future-proof** - Ready for detailed pass selector (25+ variants) in Profile editing later

### Home Screen Progressive Profile Completion - COMPLETE
Supporting progressive profile enhancement via subtle links:
1. **Skill level link** - When missing, displays "Skill level TBD →" as a tappable link to Profile
2. **Conditional display** - Shows static text when skill_level exists, link when null/empty
3. **Subtle styling** - Dotted underline, text-muted color with hover transition to primary color
4. **Non-blocking** - Does not restrict any app actions based on missing skill level
5. **Navigation** - Links to /profile for users to complete their profile progressively
6. **Home mountain display** - Shows home_mountain in summary if set (e.g., "Skier · Indy · Aspen")

### Add Trip Flow Improvements - COMPLETE
Enhanced "Add a trip" with date validation, resort filtering, and home mountain setting:
1. **Date validation** - End date cannot be before start date (frontend + backend)
   - Frontend: End date min attribute synced with start date
   - Backend: Rejects invalid date ranges with error message
2. **State-based resort filtering** - State dropdown required before resort selection
   - Resorts dynamically filtered by selected state via JavaScript
   - Preserves existing resort data and relationships
3. **Home mountain option** - Optional checkbox to set home mountain
   - Only shows if user doesn't have one OR different from current
   - Non-blocking feature that enhances profile progressively
4. **Home screen display** - Subtly shows home mountain in welcome summary when set

### Invite Share Copy Personalization - COMPLETE
Updated Web Share API with inviter-led language:
1. **Share title** - "You've been invited by {FirstName}"
2. **Share text** - "{FirstName} invited you to Base Lodge to see when you can hit the slopes together — join now!"
3. **Share URL** - Unique invite token (unchanged)
4. **Mechanism** - navigator.share() with personalized payload

### Invite Landing Page Personalization - COMPLETE
Aligned invite landing page with personalized share copy:
1. **Headline** - "You've been invited by {FirstName}" (derived from invite token inviter)
2. **Subtext** - "See when you can hit the slopes together and share ski trips."
3. **Primary CTA** - "Create your account" (styled in primary red)
4. **Secondary CTA** - "Already have an account? Log in" (styled as outline button)
5. **Design** - Maintains Base Lodge design language, mobile-first layout
6. **Functionality** - Preserves invite token and connection logic

### Profile Consolidation into More Screen - COMPLETE
Merged standalone Profile page into More as the single account & profile hub:
1. **Section 1: Profile** - Rider type, Pass type, Skill level, Home state (each with "Change" to existing edit_profile flow)
2. **Section 2: Activity & History** - Mountains visited (with "Change" to mountains_visited), Gear ("Coming soon", non-interactive)
3. **Section 3: Account** - Log out, Delete account (using delete_account_data route)
4. **Removed pages** - Deleted standalone profile.html and more_info.html files entirely
5. **Navigation fixed** - Updated home.html skill level link to point to More instead of Profile
6. **Navigation removed** - Friends and Invite remain in bottom navigation only (not in More)
7. **Styling** - Added .settings-section-title CSS class for uppercase section headers
8. **Preserved** - All existing edit flows, data models, styling, and mobile-first layout

### Flask-Login Authentication & Session Fix (Dec 12, 2025) - COMPLETE
Fixed critical authentication redirect loop in Replit iframe environment:
1. **Removed all session["user_id"] references** - Standardized to Flask-Login's current_user (12 instances removed)
2. **Added @login_required decorator** - All API routes now use Flask-Login protection instead of manual session checks
3. **Fixed logout function** - Now calls logout_user() + session.clear()
4. **Merged duplicate before_request handlers** - Single handler now handles both session permanence + profile setup checks
5. **Session cookie configuration for iframes:**
   - SameSite=None (instead of Lax) for cross-origin iframe compatibility
   - session.permanent = True for session persistence across requests
   - SESSION_REFRESH_EACH_REQUEST = True to refresh on each request
6. **Primary user guarantee** - Added startup check that auto-creates/repairs richardbattlebaxter@gmail.com account
7. **Test accounts ready** - Seed script generates 50 realistic dummy users with guaranteed trip overlaps

**Login now works:** richardbattlebaxter@gmail.com / 12345678

### Profile Consolidation & Trip Duration Hardening (Dec 12, 2025) - COMPLETE
Structural hardening to prevent regressions and add trip duration display:
1. **Defensive /profile redirect** - Added guard route that redirects /profile to /more (prevents TemplateNotFound errors)
2. **Standardized all profile saves** - All POST handlers that modify profile data now redirect to /more:
   - edit_profile (rider_type, pass_type, skill_level, home_state, etc.)
   - mountains_visited
3. **Trip duration display** - Added trip duration (days) to all trip cards:
   - Inline with existing trip text: "Feb 10–Feb 13 — Resort Name • 4 days"
   - Calculated as: (end_date - start_date).days + 1
   - Applied to trip_row.html component (used across home.html, my_trips.html, friend profiles)
4. **Documentation guard** - Added prominent comment at top of app.py:
   - "PROFILE CONSOLIDATION NOTE: Do NOT reintroduce profile routes or templates"
5. **Regression tests** - Created tests/test_profile_consolidation.py with:
   - /profile always redirects test
   - Profile save redirects to /more test
   - No profile.html template reference test
   - Trip duration calculation test

### Phase 1 "Open Dates" Feature (Dec 12, 2025) - COMPLETE
Lightweight availability signal separate from trips:
1. **Data Model** - New `OpenDate` table (id, user_id, start_date, end_date, created_at)
2. **Home Toggle** - Added "Open" tab to My Trips/Friends' Trips/Overlaps
3. **Add Open Dates** - Separate form at /add-open-dates (not part of trip creation)
4. **Overlap Matching** - Open dates ↔ Open dates only (ignored in Trips and Overlap tabs)
5. **Overlap Display** - "You and [friend] are both open for X days" with optional pass match
6. **Friend Profile** - Read-only "Open dates" section showing friend's availability
7. **Smart Display** - Passes displayed only when both users have same pass type
8. **Guardrails** - Open dates never appear in My Trips/Friends' Trips/Overlap tabs

**Phase 2 Features (NOT implemented):**
- Notifications for open date overlaps
- Sorting overlaps by duration/closeness
- Dummy data seeding for UI QA

## External Dependencies
- **Flask:** Python web framework.
- **Flask-Login:** User session management.
- **SQLAlchemy:** SQL toolkit and Object-Relational Mapper.
- **Werkzeug:** WSGI utility library for password hashing.
- **Jinja2:** Templating engine.
- **SQLite:** Default development database.
- **PostgreSQL:** Production-ready database.