"""
Ideas Ranking Service
Scores and sorts overlap windows by quality for the Ideas page and Home Best Match.

Scoring model (0–100 scale):
  Pass Alignment    25 pts
  Window Quality    20 pts
  Friend Count      15 pts
  Timing Proximity  15 pts
  Wishlist          10 pts
  Feasibility       10 pts
  Variation          5 pts

Architecture:
  - Scores are computed after _build_overlap_windows() produces the window list.
  - Windows are mutated in-place (score key added), then sorted descending.
  - is_first_row is reset after sorting.
  - Hard filter: windows with start_date < today receive score = -1 and are excluded.
"""

import random
from datetime import date as date_cls, timedelta

BAD_PASSES = {None, "", "I don't have a pass", "Other"}


def score_overlap_windows(windows, user, shared_wishlist_friend_ids=None):
    """
    Score and sort overlap windows by quality.

    Args:
        windows: list of dicts from _build_overlap_windows(); must include
                 friends_in_window, friend_count, start_date, end_date keys.
        user:    current Flask-Login user (pass_type used for context).
        shared_wishlist_friend_ids: set of friend user IDs who share at least
                 one wishlist resort with the current user. Pass None to skip
                 wishlist scoring.

    Returns:
        A new list sorted by score descending. Each window dict gains a "score"
        key. Past windows (score = -1) are excluded entirely.
    """
    today = date_cls.today()
    shared_wishlist_friend_ids = shared_wishlist_friend_ids or set()

    valid = []

    for w in windows:
        try:
            start = date_cls.fromisoformat(w["start_date"])
            end = date_cls.fromisoformat(w["end_date"])
        except (ValueError, KeyError):
            w["score"] = -1
            continue

        if start < today:
            w["score"] = -1
            continue

        n_days = (end - start).days + 1
        days_until_start = (start - today).days
        friends_in_window = w.get("friends_in_window", [])
        friend_count = len(friends_in_window) or 1

        # ── PASS ALIGNMENT (25 pts) ───────────────────────────────────────────
        friends_with_same_pass = sum(
            1 for f in friends_in_window if f.get("same_pass")
        )
        same_pass_ratio = friends_with_same_pass / friend_count
        pass_score = same_pass_ratio * 25

        # ── WINDOW QUALITY (20 pts) ───────────────────────────────────────────
        if n_days == 1:
            length_score = 5
        elif n_days == 2:
            length_score = 12
        elif n_days == 3:
            length_score = 18
        else:
            length_score = 20

        includes_weekend = any(
            (start + timedelta(days=i)).weekday() in (5, 6)
            for i in range(n_days)
        )
        weekend_bonus = 8 if includes_weekend else 0
        window_score = min(length_score + weekend_bonus, 20)

        # ── FRIEND COUNT (15 pts, diminishing returns) ────────────────────────
        friend_score = min(friend_count / 3, 1.0) * 15

        # ── TIMING PROXIMITY (15 pts) ─────────────────────────────────────────
        if days_until_start < 3:
            proximity = 0.6
        elif days_until_start <= 30:
            proximity = 1.0
        elif days_until_start <= 90:
            proximity = 0.7
        else:
            proximity = 0.4
        proximity_score = proximity * 15

        # ── WISHLIST (10 pts) ─────────────────────────────────────────────────
        window_friend_ids = {f["friend_id"] for f in friends_in_window}
        has_shared_wishlist = bool(window_friend_ids & shared_wishlist_friend_ids)
        wishlist_score = 10 if has_shared_wishlist else 0

        # ── FEASIBILITY (10 pts) ──────────────────────────────────────────────
        feasibility_score = 10 if n_days >= 2 else 3

        # ── VARIATION (5 pts) ─────────────────────────────────────────────────
        variation_score = random.uniform(0, 5)

        w["score"] = (
            pass_score
            + window_score
            + friend_score
            + proximity_score
            + wishlist_score
            + feasibility_score
            + variation_score
        )
        valid.append(w)

    valid.sort(key=lambda w: (
        -w["score"],
        w["start_date"],
        -w.get("friend_count", 1),
        -(
            (date_cls.fromisoformat(w["end_date"]) - date_cls.fromisoformat(w["start_date"])).days
        ),
    ))

    for idx, w in enumerate(valid):
        w["is_first_row"] = (idx == 0)

    return valid
