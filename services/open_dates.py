"""
Open Dates Service
Provides deterministic query logic for computing open date overlaps between users and friends.

Data source priority:
1. UserAvailability table (rows with is_available=True)
2. Legacy user.open_dates JSON column (fallback when no table rows exist)

This is the foundation for:
- Open tab display
- Pass compatibility badges
- Notifications (future)
- "Who's open this weekend?" (future)
"""

from datetime import date as date_cls
from models import db, User, Friend, UserAvailability


def get_available_dates_for_user(user):
    """
    Returns a set of future "YYYY-MM-DD" strings representing the user's available dates.

    Priority:
    1. Query UserAvailability table for rows with is_available=True.
       If any rows exist, use those exclusively.
    2. If no UserAvailability rows exist, fall back to the legacy user.open_dates JSON list.

    Always filters to today and future dates only.
    Always returns YYYY-MM-DD strings.
    """
    today_str = date_cls.today().isoformat()

    rows = (
        UserAvailability.query
        .filter_by(user_id=user.id, is_available=True)
        .all()
    )

    if rows:
        return {
            row.date.isoformat()
            for row in rows
            if row.date.isoformat() >= today_str
        }

    # Fallback: legacy open_dates JSON
    legacy = user.open_dates or []
    return {
        d for d in legacy
        if isinstance(d, str) and len(d) == 10 and d >= today_str
    }


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
    - Open <-> Open only (no trips)
    - No scoring or filtering by pass
    - Skip friends with no/empty available dates
    - Uses UserAvailability table first; falls back to legacy open_dates JSON per user
    """

    # Step 1: Get current user's available dates
    my_dates = get_available_dates_for_user(current_user)
    if not my_dates:
        return []

    # Step 2: Fetch friends (single query)
    friends = (
        db.session.query(User)
        .join(Friend, Friend.friend_id == User.id)
        .filter(Friend.user_id == current_user.id)
        .all()
    )

    # Step 3: Compute overlaps in Python (intentional — explicit and debuggable)
    matches = []

    for friend in friends:
        friend_dates = get_available_dates_for_user(friend)

        if not friend_dates:
            continue

        overlapping = my_dates & friend_dates

        for match_date in overlapping:
            matches.append({
                "date": match_date,
                "friend_id": friend.id,
                "friend_name": friend.first_name,
                "friend_pass": friend.pass_type,
                "same_pass": friend.pass_type == current_user.pass_type
            })

    # Step 4: Sort results — date ascending, then friend name ascending
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
