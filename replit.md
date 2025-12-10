# Base Lodge

## Overview
Base Lodge is a ski/snowboard trip planning application built with Flask. It helps mountain enthusiasts track their ski days and manage their resort passes.

## Current State
- Authentication system with sign up, login, and **birthday capture**
- User profile with rider type and pass type
- Two-step onboarding flow after registration
- Ski trip creation, editing, and deletion
- State and mountain selection with filtering
- Mobile-first responsive design
- **Friends system** (invitation-based, bidirectional friendships)
- **Friend management APIs** (invite, list, remove, accept)

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
│   ├── auth.html       # Sign up / Login page (with birthday field)
│   ├── setup_profile.html  # Two-question onboarding
│   ├── profile.html    # User profile and trip management
│   └── my_trips.html   # Dedicated trips view
├── static/
│   └── styles.css      # Mobile-first CSS with brand colors
└── replit.md           # This file
```

### Routes
- `/` - Redirects to /auth
- `/auth` - Sign up and login page
- `/setup-profile` - Two-step onboarding (rider type, pass type)
- `/profile` - User profile page with trip management
- `/logout` - Clears session and redirects to auth

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
- Birthday field is captured but not yet displayed in profile (mobile only)
- Friends feature is API-only - no UI in web app yet (mobile priority)
- "Visible to friends only" toggle is placeholder - visibility not enforced yet
- No email notifications for friend invitations (phase 2)

## User Preferences
- Mobile-first design approach (now supporting both web & mobile)
- Clean, modern UI with card-style layouts
- Max width 420px for auth/profile cards on web
- Inline modals for trip management (no page navigation)
- Incremental feature rollout prioritizing mobile
