# Base Lodge

## Overview
Base Lodge is a ski/snowboard trip planning application built with Flask. It helps mountain enthusiasts track their ski days and manage their resort passes.

## Current State
- Authentication system with sign up and login
- User profile with rider type and pass type
- Two-step onboarding flow after registration
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
- **JavaScript**: Vanilla JS for form interactions

### File Structure
```
├── app.py              # Main Flask application with routes
├── models.py           # SQLAlchemy User model
├── templates/
│   ├── auth.html       # Sign up / Login page
│   ├── setup_profile.html  # Two-question onboarding
│   └── profile.html    # User profile display
├── static/
│   └── styles.css      # Mobile-first CSS with brand colors
└── replit.md           # This file
```

### Routes
- `/` - Redirects to /auth
- `/auth` - Sign up and login page
- `/setup-profile` - Two-step onboarding (rider type, pass type)
- `/profile` - User profile page
- `/logout` - Clears session and redirects to auth

### Brand Colors
- Primary: #8F011B (deep red)
- Primary Dark: #660014
- Primary Light: #B30A2A
- Background: #F7F7F7
- Surface: #FFFFFF

## Recent Changes
- December 2024: Initial project setup with auth, onboarding, and profile pages

## User Preferences
- Mobile-first design approach
- Clean, modern UI with card-style layouts
- Max width 420px for auth/profile cards
