# Base Lodge

## Overview
Base Lodge is a ski/snowboard trip planning application built with Flask. It helps mountain enthusiasts track their ski days and manage their resort passes.

## Current State
- Authentication system with sign up and login
- User profile with rider type and pass type
- Two-step onboarding flow after registration
- Ski trip creation, editing, and deletion
- State and mountain selection with filtering
- Mobile-first responsive design

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
├── app.py              # Main Flask application with routes
├── models.py           # SQLAlchemy User and SkiTrip models
├── templates/
│   ├── auth.html       # Sign up / Login page
│   ├── setup_profile.html  # Two-question onboarding
│   └── profile.html    # User profile and trip management
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
- `/api/mountains/<state>` - GET mountains for a state
- `/api/trip/create` - POST create new trip
- `/api/trip/<id>/edit` - POST edit trip
- `/api/trip/<id>/delete` - POST delete trip

### Models

#### User
- id, first_name, last_name, email, password_hash
- rider_type, pass_type, profile_setup_complete
- trips relationship to SkiTrip

#### SkiTrip
- id, user_id (FK), state, mountain
- start_date, end_date, is_public, created_at

### Brand Colors
- Primary: #8F011B (deep red)
- Primary Dark: #660014
- Primary Light: #B30A2A
- Background: #F7F7F7
- Surface: #FFFFFF

## Recent Changes
- December 2024: Added SkiTrip model with CRUD operations
- December 2024: Implemented inline modal forms with AJAX
- December 2024: Added state/mountain dropdown filtering
- December 2024: Initial project setup with auth, onboarding, and profile pages

## User Preferences
- Mobile-first design approach
- Clean, modern UI with card-style layouts
- Max width 420px for auth/profile cards
- Inline modals for trip management (no page navigation)
