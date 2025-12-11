# Base Lodge

## Overview
Base Lodge is a ski/snowboard trip planning application built with Flask. It helps mountain enthusiasts track their ski days and manage their resort passes.

## Current State
- **Authentication:** Modern signup/login using BaseLodge design system
- **Onboarding:** Two-step flow (Step 1: Skill Level + Rider Type; Step 2: Pass Type)
- User profile with rider type, pass type, skill level, gender
- Ski trip creation, editing, and deletion
- Mobile-first responsive design with BaseLodge design tokens
- **Friends system** (invitation-based, bidirectional friendships)
- **Home-first navigation:** /home is central trip management hub with 3-tab interface
- **Design System:** Unified BaseLodge tokens (colors, spacing, typography, components)

## Project Architecture

### Backend
- **Framework**: Flask (Python)
- **Database**: SQLite (development) / PostgreSQL (production ready)
- **ORM**: SQLAlchemy
- **Password Hashing**: Werkzeug

### Frontend
- **Templates**: Jinja2
- **Styling**: Custom CSS with CSS variables
- **JavaScript**: Vanilla JS for form interactions and AJAX

### File Structure
```
├── app.py              # Main Flask application with routes & APIs
├── models.py           # SQLAlchemy models (User, SkiTrip, Friend, Invitation)
├── templates/
│   ├── auth.html       # Sign up / Login page (BaseLodge styled)
│   ├── setup_profile.html  # Two-step onboarding (skill level, rider type, pass type)
│   ├── home.html       # Landing page with welcome header + trip tabs (My Trips / Friends' Trips / All Trips)
│   ├── profile.html    # User profile settings (editable fields)
│   ├── friends.html    # Friends list with inline rows
│   ├── friend_profile.html  # Friend's public profile with trips
│   ├── invite.html     # NEW - Invite a friend page (copy link + QR code)
│   ├── my_trips.html   # Deprecated (redirects to /home)
│   ├── components/
│   │   ├── profile_summary.html  # Profile card component
│   │   ├── stats_card.html  # Stats display component
│   │   ├── segmented_trips_tabs.html  # Tab control component
│   │   ├── trip_row.html  # Trip row component
│   │   ├── friend_row.html  # Friend row (inline with name, pass, rider, skill)
│   │   └── bottom_nav.html  # 4-tab bottom navigation (Home, Friends, Invite, Settings)
│   └── edit_profile.html  # Edit profile form
├── static/
│   └── styles.css      # BaseLodge unified design system with color tokens, spacing, typography, components
└── replit.md           # This file
```

### Routes
- `/` - Redirects to /auth
- `/auth` - Sign up / Login page (unified form with tabs, BaseLodge styled)
- `/setup-profile` - Two-step onboarding:
  - Step 1: Skill Level (Beginner/Intermediate/Advanced/Expert) + Rider Type (Skier/Snowboarder/Both)
  - Step 2: Pass Type (Epic/Ikon/Other/None) using segmented controls
- `/create-trip` - Trip creation page (full page, not modal)
- `/home` - Landing page with welcome header + 3-tab interface: My Trips / Friends' Trips / All Trips
- `/profile` - User settings page (editable profile fields)
- `/invite` - Invite a friend page (copy invite link, QR code placeholder)
- `/friends` - Friends list with inline rows
- `/profile/<user_id>` - Friend's public profile with trips
- `/my-trips` - Deprecated route (redirects to /home)
- `/logout` - Clears session and redirects to auth

**Bottom Navigation (4 tabs):**
- Home 🏠 → `/home`
- Friends 👥 → `/friends`
- Invite ✉️ → `/invite`
- Settings ⚙️ → `/profile`

### API Routes

**Trip Management:**
- `/api/mountains/<state>` - GET mountains for a state
- `/api/trip/create` - POST create new trip
- `/api/trip/<id>/edit` - POST edit trip
- `/api/trip/<id>/delete` - POST delete trip

**Friends (MVP):**
- `/api/friends/invite` - POST send friend invitation (requires `friend_email`)
- `/api/friends` - GET list of connected friends
- `/api/friends/<user_id>` - GET friend profile details
- `/api/friends/invite/<invitation_id>/accept` - POST accept friend invitation
- `/api/friends/<user_id>` - DELETE remove friend (bidirectional)

### Models

#### User
- id, first_name, last_name, email, password_hash
- **birthday** (Date)
- rider_type, pass_type, profile_setup_complete
- created_at
- relationships: trips (SkiTrip), friends (Friend), invitations sent/received (Invitation)

#### SkiTrip
- id, user_id (FK), state, mountain
- start_date, end_date, pass_type, is_public, created_at

#### Friend
- id, user_id (FK), friend_id (FK)
- created_at
- Bidirectional: records both directions (user→friend AND friend→user)
- Unique constraint: one friendship per user pair

#### Invitation
- id, sender_id (FK), receiver_id (FK)
- status: 'pending' | 'accepted' | 'declined'
- created_at
- Unique constraint: one pending invitation per sender-receiver pair

### Brand Colors
- Primary: #8F011B (deep red)
- Primary Dark: #660014
- Primary Light: #B30A2A
- Background: #F7F7F7
- Surface: #FFFFFF

## Recent Changes

### Phase 6: Navigation & Invite System (Dec 11, 2025)
- **Bottom Navigation Redesign:** Updated from 3 tabs to 4-tab system
  - Removed duplicate "Trips" tab (now consolidated into Home)
  - New tabs: Home 🏠 | Friends 👥 | Invite ✉️ | Settings ⚙️
  - Settings correctly routes to `/profile`
- **New Invite Page:** Created `/invite` route with copy link + QR placeholder
  - Copy button copies placeholder invite URL to clipboard
  - QR code placeholder (no dynamic generation yet)
  - Full BaseLodge styling
  - Requires login via @login_required decorator
- **Home Page Header Redesign:** Added welcome card with gradient background
  - "Welcome back, {{ first_name }}!"
  - Pass Type · Rider Type · Skill Level metadata
  - Placeholder data: "Mountains visited: 0" and "Next Trip: Not scheduled"
- **Friend Row Inline:** Updated friend_row component
  - Single-row display: "Name — Pass Type — Rider Type — Skill Level"
  - Entire row clickable → `/friend/<friend_id>`
- **Code Improvements:**
  - Added custom @login_required decorator (Flask doesn't have built-in)
  - All 4 bottom nav tabs now require login
  - Removed redundant Trips tab

### Phase 5: Auth & Onboarding Redesign (Dec 11, 2025)
- **Complete Auth/Signup Rebuild:** Redesigned auth.html using BaseLodge design system
  - Modern centered card layout with Sign Up / Log In tabs
  - Proper form styling using --bl-color-primary, spacing tokens, typography classes
  - Mobile-first responsive design
- **Onboarding Flow Overhaul:** Rebuilt setup_profile.html with 2-step flow
  - Step 1: Skill Level (4 options) + Rider Type (3 options) - both using segmented controls
  - Step 2: Pass Type (4 options) - segmented controls instead of grid
  - Fixed redirect to `/home` after completion (not `/profile`)
- **Backend Updates:**
  - setup_profile route now handles skill_level in Step 1
  - Login redirects to `/home` (not `/profile`)
  - Onboarding completion redirects to `/home`
- **Removed:**
  - Modal-based trip creation (now uses `/create-trip` page route)
  - All JSON serialization of undefined data (state_abbr, mountains_by_state)
  - Browser default form styling
- **Fixed:**
  - state_abbr references in home.html and friend_profile.html (now uses trip.state directly)
  - openCreateModal() remnants and button behavior

### Phase 4: Global Design System (Dec 10, 2025)
- **Complete CSS Refactor:** Replaced old styles.css with unified BaseLodge design system
- **Design Tokens:** Full :root CSS variables for colors, spacing (8pt scale), radius, typography, shadows
- **Component Partials:** Created reusable templates in templates/components/:
  - `profile_summary.html` - Profile card with name, pass type, skill level, rider type, mountains visited
  - `stats_card.html` - 3-column stats display (Pass Type, Skill Level, Rider Type)
  - `segmented_trips_tabs.html` - BaseLodge segmented control for My/Friends'/All Trips
  - `trip_row.html` - Individual trip row with date, user, mountain, pass info
  - `friend_row.html` - Friend profile row with name, pass type, rider type
  - `bottom_nav.html` - Fixed bottom nav with Home/Trips/Friends/Profile using `request.endpoint` for active state
- **Templates Refactored:**
  - `home.html` - Profile summary + stats card + segmented tabs + trip feed + Add Trip button
  - `profile.html` - Clean form with segmented controls for Pass Type & Rider Type
  - `friends.html` - Friend list with chips filter by pass type
  - `friend_profile.html` - Friend's public profile with upcoming/past trips
- **Typography System:** Heading XL/L/M, Body, Label, Caption classes
- **Button System:** Primary, Secondary, Ghost button variants with full hover/disabled states
- **Color Tokens:** Primary (#8F011B), Primary Soft (#B31633), backgrounds, text, borders, success, error

### Phase 3: Home-First Navigation (Dec 10, 2025)
- **Navigation Consolidation:** `/home` is now the landing page after login
- **Routes Restructured:**
  - Login redirects to `/home` (not `/profile`)
  - `/my-trips` route deprecated → redirects to `/home`
  - `/home` shows 3 tabs: My Trips, Friends' Trips, All Trips (upcoming only)
- **Profile Simplified:** Removed trip cards from `/profile` (trips now only on `/home`)
- **Bottom Navigation:** Added persistent footer nav to all main pages (Home, Trips, Friends, Profile)
- **Navigation Updates:**
  - Both "Home" and "Trips" nav buttons point to `/home`
  - "Friends" button navigates to `/friends`
  - "Profile" button shows user's own profile
- **UI/UX Refinement:**
  - Replaced Pass Type & Rider Type dropdowns with segmented button controls
  - Profile shows summary card + editable fields + invite button + settings
  - Segmented controls match setup_profile.html pattern for consistency
- **Trip Creation:** "Add a Trip" button on `/home` triggers trip creation modal (AJAX, no page nav)
- **Cleanup:** Deprecated `/my_trips.html` template

### Phase 2: Friends System (Dec 2024)
- **Backend:** Added `birthday` field to User model (required at signup)
- **Backend:** Created Friend model with bidirectional relationships and unique constraints
- **Backend:** Created Invitation model for pending friend requests (pending/accepted/declined)
- **Auth:** Updated signup form to capture date of birth with validation
- **APIs:** Added 5 friend management endpoints (invite, list, accept, remove)
- **Database:** Migrations handle new tables automatically via `db.create_all()`

### Phase 1: Trip & UI Updates (Dec 2024)
- December 2024: Added pass_type field to SkiTrip model (trips can have different passes)
- December 2024: Added STATE_ABBR dictionary for compact state display (CO, UT, VT, etc.)
- December 2024: Updated pass options to 11 choices (Epic, Ikon variants, Loveland, No Pass, Other)
- December 2024: Added floating green Add Trip button (#669127) with plus icon
- December 2024: Replaced logout link with circular icon button in top-right corner
- December 2024: Trip cards now show: Mountain, date range with trip length (X day trip), state abbr, pass type
- December 2024: Added date validation (end date cannot be before start date)
- December 2024: Changed visibility toggle label to "Visible to friends only"
- December 2024: Created dedicated /my-trips route
- December 2024: Added SkiTrip model with CRUD operations
- December 2024: Implemented inline modal forms with AJAX
- December 2024: Added state/mountain dropdown filtering
- December 2024: Initial project setup with auth, onboarding, and profile pages

## Next Steps (Phase 3 - Mobile App)
- React Native mobile app with shared Flask backend
- Friends screen UI to view friend list and passes
- Branch.io deep linking for friend invitations
- Push notifications for friend activity
- Optional: "Next Mountain" feature on friends profile

## Known Limitations
- Trip creation modal exists but needs to be properly initialized on `/home`
- Profile completion percentage (40%) is placeholder - needs real calculation
- Mountains visited count shows 0 - needs real calculation
- "Visible to friends only" toggle - visibility logic exists but may need verification
- No email notifications for friend invitations

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

## Technical Notes
- App uses session-based auth (manual checks, no @login_required decorator)
- Templates are standalone with component includes (no base.html inheritance)
- Trip creation uses profile.js (modal + AJAX) - should work on /home with proper initialization
- Segmented buttons use hidden inputs to store values for form submission
- Bottom nav shows active state based on `request.endpoint` matching
- CSS uses 8pt spacing scale (--bl-space-2 through --bl-space-8)
- Design tokens: --bl-color-primary (#8F011B), --bl-color-bg (#FAFAFA), --bl-color-surface (#FFFFFF)
- Fixed bottom nav (position: fixed) requires body padding-bottom: 80px to prevent content overlap
