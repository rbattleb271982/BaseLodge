"""
Open Dates Service
Provides deterministic query logic for computing open date overlaps between users and friends.

This is the foundation for:
- Open tab display
- Pass compatibility badges
- Notifications (future)
- "Who's open this weekend?" (future)
"""

from models import db, User, Friend


def get_open_date_matches(current_user):
    """
    Returns a list of open-date overlaps between current_user and their friends.
    
    Output structure (one entry per overlapping date per friend):
    [
      {
        "date": "2025-12-14",
        "friend_id": 42,
        "friend_name": "Alex",
        "friend_pass": "Epic",
        "same_pass": True
      },
      ...
    ]
    
    Matching rules:
    - Date-by-date comparison
    - Open ↔ Open only (no trips)
    - No scoring or filtering by pass
    - Skip friends with no/empty/invalid open_dates
    """
    
    # Step 1: Normalize current user dates
    my_dates = set(current_user.open_dates or [])
    if not my_dates:
        return []
    
    # Step 2: Fetch friends (single query)
    # Friendship is bidirectional in our model, so we query where user_id = current_user.id
    friends = (
        db.session.query(User)
        .join(Friend, Friend.friend_id == User.id)
        .filter(Friend.user_id == current_user.id)
        .all()
    )
    
    # Step 3: Compute overlaps in Python (intentional - explicit and debuggable)
    matches = []
    
    for friend in friends:
        friend_dates = set(friend.open_dates or [])
        
        # Skip friends with no open dates
        if not friend_dates:
            continue
        
        # Find overlapping dates
        overlapping = my_dates & friend_dates
        
        for date in overlapping:
            # Validate date format (skip invalid)
            if not isinstance(date, str) or len(date) != 10:
                continue
            
            matches.append({
                "date": date,
                "friend_id": friend.id,
                "friend_name": friend.first_name,
                "friend_pass": friend.pass_type,
                "same_pass": friend.pass_type == current_user.pass_type
            })
    
    # Step 4: Sort results - date ascending, then friend name ascending
    matches.sort(key=lambda x: (x["date"], x["friend_name"] or ""))
    
    return matches


# ============================================================================
# SANITY CHECK / DEBUG HELPER
# ============================================================================
# Example expectation:
# If I have open_dates ["2025-12-14", "2025-12-18"]
# And Alex has ["2025-12-14"]
# Then exactly ONE match should return for Dec 14
#
# Usage in Flask shell:
#   from services.open_dates import get_open_date_matches
#   from models import User
#   user = User.query.filter_by(email="test@example.com").first()
#   matches = get_open_date_matches(user)
#   print(matches)
# ============================================================================
