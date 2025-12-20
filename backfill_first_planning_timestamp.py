"""
Production Backfill Script: first_planning_timestamp

PURPOSE:
Sets first_planning_timestamp for existing users who have already started planning
(created SkiTrips or accepted TripGuest invites) but don't have the timestamp set.

WHEN TO RUN:
- After deploying the c747cdb80425 migration that adds first_planning_timestamp
- Run ONCE in production to backfill existing users
- Safe to re-run (idempotent)

HOW TO RUN:
Option 1: Flask CLI
    flask backfill-planning-timestamp

Option 2: Python shell
    python backfill_first_planning_timestamp.py

Option 3: Admin endpoint (if enabled)
    GET /admin/backfill-planning-timestamp

BEHAVIOR:
- Finds users where first_planning_timestamp IS NULL
- For each, checks if they have SkiTrips or accepted TripGuest records
- Sets first_planning_timestamp to the earliest of:
  - first_trip_created_at (if set)
  - Earliest SkiTrip.start_date
  - Earliest TripGuest.accepted_at (if applicable)
  - created_at (fallback)
  - NOW() (final fallback)
- Commits in batches of 100 for safety
"""

from datetime import datetime


def backfill_first_planning_timestamp(app, db, User, SkiTrip, TripGuest=None):
    """
    Backfill first_planning_timestamp for users who have started planning.
    
    Args:
        app: Flask application
        db: SQLAlchemy database instance
        User: User model class
        SkiTrip: SkiTrip model class
        TripGuest: TripGuest model class (optional, for accepted guests)
    
    Returns:
        dict with backfill results
    """
    results = {
        "users_checked": 0,
        "users_updated": 0,
        "users_skipped": 0,
        "errors": []
    }
    
    with app.app_context():
        users_needing_backfill = User.query.filter(
            User.first_planning_timestamp.is_(None)
        ).all()
        
        results["users_checked"] = len(users_needing_backfill)
        batch_count = 0
        
        for user in users_needing_backfill:
            try:
                planning_timestamp = None
                
                user_trips = SkiTrip.query.filter_by(user_id=user.id).order_by(SkiTrip.start_date.asc()).first()
                
                guest_accepted_at = None
                if TripGuest:
                    accepted_guest = TripGuest.query.filter(
                        TripGuest.guest_id == user.id,
                        TripGuest.status == 'accepted'
                    ).order_by(TripGuest.accepted_at.asc()).first()
                    if accepted_guest and accepted_guest.accepted_at:
                        guest_accepted_at = accepted_guest.accepted_at
                
                if user_trips or guest_accepted_at:
                    candidates = []
                    
                    if user.first_trip_created_at:
                        candidates.append(user.first_trip_created_at)
                    
                    if user_trips and user_trips.start_date:
                        candidates.append(datetime.combine(user_trips.start_date, datetime.min.time()))
                    
                    if guest_accepted_at:
                        candidates.append(guest_accepted_at)
                    
                    if user.created_at:
                        candidates.append(user.created_at)
                    
                    if candidates:
                        planning_timestamp = min(candidates)
                    else:
                        planning_timestamp = datetime.utcnow()
                    
                    user.first_planning_timestamp = planning_timestamp
                    results["users_updated"] += 1
                    batch_count += 1
                    
                    if batch_count >= 100:
                        db.session.commit()
                        batch_count = 0
                else:
                    results["users_skipped"] += 1
                    
            except Exception as e:
                results["errors"].append(f"User {user.id}: {str(e)}")
        
        if batch_count > 0:
            db.session.commit()
        
        return results


if __name__ == "__main__":
    from app import app, db
    from models import User, SkiTrip
    
    try:
        from models import TripGuest
    except ImportError:
        TripGuest = None
    
    print("=" * 60)
    print("BACKFILL: first_planning_timestamp")
    print("=" * 60)
    
    results = backfill_first_planning_timestamp(app, db, User, SkiTrip, TripGuest)
    
    print(f"Users checked:  {results['users_checked']}")
    print(f"Users updated:  {results['users_updated']}")
    print(f"Users skipped:  {results['users_skipped']} (no planning activity)")
    
    if results["errors"]:
        print(f"\nErrors ({len(results['errors'])}):")
        for error in results["errors"][:10]:
            print(f"  - {error}")
        if len(results["errors"]) > 10:
            print(f"  ... and {len(results['errors']) - 10} more")
    else:
        print("\nNo errors.")
    
    print("=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
