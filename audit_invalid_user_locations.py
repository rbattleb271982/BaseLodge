#!/usr/bin/env python3
"""
Audit script to find users with invalid location data that could break dropdowns.
Run this script to identify production users with country/state values that
don't match any resorts in the database.

Usage:
    python audit_invalid_user_locations.py
"""

from app import app, db
from models import User, Resort

def audit_invalid_locations():
    with app.app_context():
        valid_countries = set(r.country_code for r in Resort.query.all() if r.country_code)
        valid_states = set(r.state_code for r in Resort.query.all() if r.state_code)
        valid_resort_ids = set(r.id for r in Resort.query.all())
        
        print(f"Valid countries: {sorted(valid_countries)}")
        print(f"Valid states count: {len(valid_states)}")
        print(f"Valid resort IDs count: {len(valid_resort_ids)}")
        print()
        
        users = User.query.all()
        bad_users = []
        
        for u in users:
            issues = []
            
            if hasattr(u, 'country') and u.country and u.country not in valid_countries:
                issues.append(f"invalid country: {u.country}")
            
            if hasattr(u, 'state') and u.state and u.state not in valid_states:
                issues.append(f"invalid state: {u.state}")
            
            if hasattr(u, 'home_resort_id') and u.home_resort_id and u.home_resort_id not in valid_resort_ids:
                issues.append(f"invalid home_resort_id: {u.home_resort_id}")
            
            if issues:
                bad_users.append((u, issues))
        
        print(f"Found {len(bad_users)} users with invalid location data\n")
        
        for u, issues in bad_users:
            email = getattr(u, 'email', 'N/A')
            print(f"User {u.id}: {email}")
            for issue in issues:
                print(f"  - {issue}")
            print()
        
        if bad_users:
            print("\n" + "="*60)
            print("TO FIX: Run the following in Flask shell (flask shell):")
            print("="*60)
            print("""
from app import db
from models import User

# Get user IDs from above output
user_ids = [...]  # <-- Fill in the user IDs

for uid in user_ids:
    u = User.query.get(uid)
    if u:
        # Reset invalid fields
        if hasattr(u, 'country'):
            u.country = None
        if hasattr(u, 'state'):
            u.state = None
        if hasattr(u, 'home_resort_id'):
            u.home_resort_id = None
        print(f"Reset user {uid}")

db.session.commit()
print("Done!")
""")
        else:
            print("All users have valid location data!")

if __name__ == "__main__":
    audit_invalid_locations()
