"""
Open Dates Service
Provides deterministic query logic for computing open date overlaps between users and friends.

Data source precedence:
1. A UserAvailability row is authoritative for its exact calendar date.
2. Valid legacy user.open_dates values remain a compatibility fallback only
   for dates without a normalized row.

This is the foundation for:
- Open tab display
- Pass compatibility badges
- Notifications (future)
- "Who's open this weekend?" (future)
"""

import re
from datetime import date as date_cls

import sqlalchemy as sa

from models import db, User, Friend, UserAvailability
from services.visibility import reciprocal_friend_predicate
from services.pass_utils import passes_match


_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OpenDateValidationError(ValueError):
    """Raised when an owner submits an invalid availability date."""


def _parse_iso_date(value):
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        return None
    try:
        parsed = date_cls.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _parse_legacy_current_dates(values, today):
    """Return valid, deduplicated current/future dates from legacy JSON."""
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {
        parsed
        for value in values
        if (parsed := _parse_iso_date(value)) is not None and parsed >= today
    }


def _resolve_current_dates(rows, legacy_values, today):
    """Overlay normalized decisions on valid legacy dates, date by date."""
    resolved = _parse_legacy_current_dates(legacy_values, today)
    for row in rows:
        if row.date < today:
            continue
        if row.is_available:
            resolved.add(row.date)
        else:
            resolved.discard(row.date)
    return {value.isoformat() for value in resolved}


def _parse_submitted_current_dates(values, today):
    """Validate an owner's complete submitted current/future date set."""
    parsed_dates = set()
    for value in values:
        parsed = _parse_iso_date(value)
        if parsed is None:
            raise OpenDateValidationError("Choose valid availability dates.")
        if parsed < today:
            raise OpenDateValidationError("Availability dates cannot be in the past.")
        parsed_dates.add(parsed)
    return parsed_dates


def get_available_dates_for_user(user):
    """
    Returns a set of future "YYYY-MM-DD" strings representing the user's available dates.

    Normalized rows override legacy JSON for the same date. This per-date
    precedence preserves valid legacy dates for legitimately partial historical
    normalized sets while ensuring an inactive normalized row tombstones its
    matching legacy date.

    Always filters to today and future dates only.
    Always returns YYYY-MM-DD strings.
    """
    today = date_cls.today()
    rows = UserAvailability.query.filter_by(user_id=user.id).all()
    return _resolve_current_dates(rows, user.open_dates, today)


def replace_current_availability(user, selected_values, today=None):
    """
    Replace an owner's complete current/future normalized availability set.

    The legacy JSON column is updated in the same unit of work as a temporary
    rollback-compatibility mirror. The caller owns the transaction and commit.
    """
    today = today or date_cls.today()
    selected_dates = _parse_submitted_current_dates(selected_values, today)

    # Serialize complete-set replacements for this owner. Without this narrow
    # lock, concurrent submissions can each read the same old rows, commit a
    # normalized union, and leave the JSON mirror reflecting only one request.
    locked_user = (
        db.session.query(User)
        .filter(User.id == user.id)
        .populate_existing()
        .with_for_update()
        .one()
    )

    existing_rows = UserAvailability.query.filter(
        UserAvailability.user_id == locked_user.id,
        UserAvailability.date >= today,
    ).all()
    existing_by_date = {row.date: row for row in existing_rows}

    for row_date, row in existing_by_date.items():
        if row_date not in selected_dates:
            db.session.delete(row)

    for selected_date in selected_dates:
        row = existing_by_date.get(selected_date)
        if row is None:
            db.session.add(UserAvailability(
                user_id=locked_user.id,
                date=selected_date,
                is_available=True,
            ))
        else:
            row.is_available = True

    mirrored_values = sorted(value.isoformat() for value in selected_dates)
    locked_user.open_dates = mirrored_values
    return set(mirrored_values)


def get_available_dates_for_users(users):
    """Batch-resolve availability using the same per-date contract."""
    users = list(users)
    if not users:
        return {}
    today = date_cls.today()
    user_ids = [user.id for user in users]
    rows = UserAvailability.query.filter(
        UserAvailability.user_id.in_(user_ids)
    ).all()
    rows_by_user = {}
    for row in rows:
        rows_by_user.setdefault(row.user_id, []).append(row)
    return {
        user.id: _resolve_current_dates(
            rows_by_user.get(user.id, []),
            user.open_dates,
            today,
        )
        for user in users
    }


def build_resolved_availability_select(
    *,
    relevant_user_ids,
    legacy_candidates,
    today,
):
    """Build the canonical per-date overlay as a SQL selectable.

    Callers supply dialect-safe, strictly parsed legacy candidate rows with
    ``user_id`` and ``available_date`` columns so the overlay can remain
    embedded in a larger bounded query.
    """
    availability = UserAvailability.__table__
    user = User.__table__

    normalized = sa.select(
        availability.c.user_id.label("user_id"),
        availability.c.date.label("available_date"),
    ).where(
        availability.c.user_id.in_(relevant_user_ids),
        availability.c.is_available.is_(True),
        availability.c.date >= today,
    )

    legacy_decision = availability.alias("legacy_availability_decision")
    legacy_source = legacy_candidates.outerjoin(
        legacy_decision,
        sa.and_(
            legacy_decision.c.user_id == legacy_candidates.c.user_id,
            legacy_decision.c.date == legacy_candidates.c.available_date,
        ),
    )
    legacy = (
        sa.select(
            legacy_candidates.c.user_id,
            legacy_candidates.c.available_date,
        )
        .select_from(legacy_source)
        .where(
            legacy_decision.c.user_id.is_(None),
        )
    )
    return sa.union(normalized, legacy)


def get_open_date_matches(current_user, cached_my_dates=None, cached_friends=None):
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
    - Friend dates use the same per-date normalized/legacy contract

    Args:
        cached_my_dates: Optional pre-fetched set of date strings for current_user.
                         Pass this when the caller already has the data to avoid a
                         redundant UserAvailability query (saves ~60ms on Supabase).
        cached_friends:  Optional pre-fetched list of User objects for current_user's
                         friends. Pass this when the caller already has all_friends in
                         memory to skip the User JOIN Friend round-trip (saves ~60ms).
    """

    # Step 1: Get current user's available dates (use caller's cache when provided)
    my_dates = cached_my_dates if cached_my_dates is not None else get_available_dates_for_user(current_user)
    if not my_dates:
        return []

    # Step 2: Get friends — use caller's pre-fetched list when provided (avoids a
    # redundant User JOIN Friend query when caller already has all_friends in memory).
    if cached_friends is not None:
        friends = cached_friends
    else:
        friends = (
            db.session.query(User)
            .join(Friend, Friend.friend_id == User.id)
            .filter(
                Friend.user_id == current_user.id,
                reciprocal_friend_predicate(current_user.id, User.id),
            )
            .all()
        )

    availability_by_friend = get_available_dates_for_users(friends)

    # Step 3: Compute overlaps in Python (intentional — explicit and debuggable)
    matches = []

    for friend in friends:
        friend_dates = availability_by_friend.get(friend.id, set())

        if not friend_dates:
            continue

        overlapping = my_dates & friend_dates

        for match_date in overlapping:
            matches.append({
                "date": match_date,
                "friend_id": friend.id,
                "friend_name": f"{friend.first_name or ''} {friend.last_name or ''}".strip(),
                "friend_pass": friend.pass_type,
                "same_pass": passes_match(friend.pass_type, current_user.pass_type)
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
