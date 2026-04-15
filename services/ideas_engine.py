"""
Ideas Engine
Shared logic for constructing overlap windows and wishlist overlaps.

Used by:
- /trip-ideas  (full ideas page)
- /home        (Next Best Match module)

This module is the single source of truth for ideas window construction.
Do not duplicate this logic in routes.
"""

from collections import Counter
from datetime import date
from utils.formatting import format_name
from models import Resort

_BAD_PASSES = {None, "", "I don't have a pass", "Other"}


def build_overlap_windows(matches, user_pass_type, friend_trip_statuses=None):
    """
    Transforms a flat list of open-date matches into display-ready overlap windows.

    Input: output of get_open_date_matches() — list of dicts with keys:
        date, friend_id, friend_name, friend_pass, same_pass

    friend_trip_statuses: optional dict of {friend_id: trip_status} for
        status-aware supporting lines. When a friend has a 'going' trip,
        supporting text notes it.

    Output: list of window dicts ready for the template, sorted date asc.
    Each dict contains: start_date, end_date, display_date_range,
    descriptor_title, supporting_line, anchor_friend_id, anchor_friend_name,
    friend_count, friends_in_window, is_first_row.
    """
    if not matches:
        return []

    # Step 1: group matches by date, dedupe friends per date by friend_id
    date_to_friends = {}
    for m in matches:
        d = m["date"]
        if d not in date_to_friends:
            date_to_friends[d] = {}
        fid = m["friend_id"]
        if fid not in date_to_friends[d]:
            date_to_friends[d][fid] = {
                "friend_id": m["friend_id"],
                "friend_name": m["friend_name"],
                "friend_pass": m["friend_pass"],
                "same_pass": m["same_pass"],
            }

    sorted_dates = sorted(date_to_friends.keys())

    # Step 2: group consecutive dates into contiguous windows
    raw_windows = []
    window_dates = [sorted_dates[0]]
    for i in range(1, len(sorted_dates)):
        prev = date.fromisoformat(sorted_dates[i - 1])
        curr = date.fromisoformat(sorted_dates[i])
        if (curr - prev).days == 1:
            window_dates.append(sorted_dates[i])
        else:
            raw_windows.append(window_dates)
            window_dates = [sorted_dates[i]]
    raw_windows.append(window_dates)

    # Step 3: build view model for each window
    num_words = {
        1: "One", 2: "Two", 3: "Three", 4: "Four",
        5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
        9: "Nine", 10: "Ten",
    }

    result = []
    for idx, wdates in enumerate(raw_windows):
        start_str = wdates[0]
        end_str = wdates[-1]
        start_obj = date.fromisoformat(start_str)
        end_obj = date.fromisoformat(end_str)

        # Collect unique friends across all dates in window, alphabetically sorted
        seen_ids = {}
        for d_str in wdates:
            for fid, f in date_to_friends[d_str].items():
                if fid not in seen_ids:
                    seen_ids[fid] = dict(f, friend_name=format_name(f["friend_name"]))
        friends = sorted(seen_ids.values(), key=lambda f: (f["friend_name"] or ""))

        # Anchor friend — alphabetically first (used for /add-trip?friend_id=)
        anchor_friend_id = friends[0]["friend_id"] if friends else None

        # Window length phrase
        n_days = (end_obj - start_obj).days + 1
        if n_days == 1:
            length_phrase = "A day"
        elif n_days == 2:
            length_phrase = "A weekend"
        elif n_days == 3:
            length_phrase = "A long weekend"
        else:
            length_phrase = f"{num_words.get(n_days, str(n_days))} days"

        # Descriptor title
        if not friends:
            descriptor = "A good time to go"
        elif len(friends) == 1:
            descriptor = f"{length_phrase} with {friends[0]['friend_name']}"
        else:
            descriptor = f"{length_phrase}, {len(friends)} friends free"

        # Supporting line (pass alignment + trip status)
        _fts = friend_trip_statuses or {}
        if not friends:
            supporting = ""
        elif len(friends) == 1:
            f = friends[0]
            fid = f.get("friend_id")
            is_going = _fts.get(fid) == "going"
            if f["same_pass"] and f["friend_pass"] not in _BAD_PASSES:
                supporting = f"{f['friend_name']} also has {f['friend_pass']}"
                if is_going:
                    supporting += " · Going"
            else:
                supporting = "Already going." if is_going else "Make it a trip."
        else:
            going_names = [
                f["friend_name"] for f in friends
                if _fts.get(f.get("friend_id")) == "going"
            ]
            passes = [f["friend_pass"] for f in friends if f["friend_pass"] not in _BAD_PASSES]
            if going_names:
                supporting = f"{going_names[0]} already going"
            elif passes:
                counts = Counter(passes)
                top_pass, top_count = counts.most_common(1)[0]
                if top_count >= 2:
                    supporting = f"{top_count} share {top_pass}"
                else:
                    supporting = f"{len(friends)} friends free"
            else:
                supporting = f"{len(friends)} friends free"

        # Display date range string
        if start_obj == end_obj:
            display_range = start_obj.strftime("%a %b %-d").upper()
        else:
            display_range = (
                f"{start_obj.strftime('%a %b %-d').upper()} "
                f"→ {end_obj.strftime('%a %b %-d').upper()}"
            )

        result.append({
            "start_date": start_str,
            "end_date": end_str,
            "display_date_range": display_range,
            "descriptor_title": descriptor,
            "supporting_line": supporting,
            "anchor_friend_id": anchor_friend_id,
            "anchor_friend_name": friends[0]["friend_name"] if friends else None,
            "friend_count": len(friends),
            "friends_in_window": friends,
            "is_first_row": idx == 0,
        })

    return result


def build_wishlist_overlaps(user, all_friends):
    """
    Returns a list of resort dicts where the user and at least one friend
    share the same wishlist resort.

    Output format:
    [
        {
            "resort_id": int,
            "resort_name": str,
            "overlapping_people": [
                {
                    "id": int,
                    "first_name": str,
                    "last_name": str,
                    "rider_type": str,
                    "skill_level": str,
                    "pass_type": str,
                }
            ]
        },
        ...
    ]

    Returns [] when the user has no wishlist or no friends.
    """
    user_wishlist = set(user.wish_list_resorts or [])
    if not user_wishlist or not all_friends:
        return []

    results = {}
    for resort_id in user_wishlist:
        overlapping_friends = []
        for friend in all_friends:
            if resort_id in set(friend.wish_list_resorts or []):
                overlapping_friends.append({
                    "id": friend.id,
                    "first_name": friend.first_name,
                    "last_name": friend.last_name or "",
                    "rider_type": friend.rider_type,
                    "skill_level": friend.skill_level,
                    "pass_type": friend.pass_type,
                })
        if overlapping_friends:
            resort = Resort.query.get(resort_id)
            if resort:
                results[resort_id] = {
                    "resort_id": resort.id,
                    "resort_name": resort.name,
                    "overlapping_people": overlapping_friends,
                }

    return list(results.values())


def make_idea_card(
    idea_type,
    title,
    cta_url,
    cta_label,
    friend_ids,
    score=0.0,
    subtitle=None,
    eyebrow=None,
    start_date=None,
    end_date=None,
    resort_id=None,
    resort_name=None,
    anchor_friend_id=None,
    anchor_friend_name=None,
    meta=None,
    is_first=False,
):
    """
    Factory for the common IdeaCard dict structure emitted by all idea skills.

    All skills (availability_overlap, wishlist_overlap, trip_overlap, etc.)
    must return lists of dicts produced by this factory so that the ranking
    layer and templates can handle any idea type uniformly.

    Required fields
    ---------------
    idea_type        str   Identifies the skill that produced this card.
                           Values: "availability_overlap", "wishlist_overlap",
                           "trip_overlap", "pass_resort", "ai_generated".
    title            str   Primary headline shown on the card.
    cta_url          str   Full URL the card navigates to on tap.
    cta_label        str   Link/button text (e.g. "Plan →", "View trip →").
    friend_ids       list  User IDs of all friends relevant to this idea.
                           Used by the ranking layer for scoring signals.

    Optional fields
    ---------------
    score            float Ranking score 0–100. Set by the ranking layer;
                           skills may leave this at 0.0.
    subtitle         str   Supporting/secondary line below the title.
    eyebrow          str   Small label above the title (e.g. date range).
    start_date       str   ISO date string. Present for date-anchored ideas.
    end_date         str   ISO date string.
    resort_id        int   Present for resort-anchored ideas.
    resort_name      str   Display name for the resort.
    anchor_friend_id int   Primary friend for pre-filling /add-trip?friend_id=.
    anchor_friend_name str Display name for the anchor friend.
    meta             dict  Escape hatch for skill-specific extra fields that
                           do not fit the standard schema.
    is_first         bool  Set post-sort by the ranking layer to flag the
                           top card for highlight styling.
    """
    return {
        "idea_type": idea_type,
        "title": title,
        "cta_url": cta_url,
        "cta_label": cta_label,
        "friend_ids": list(friend_ids),
        "score": score,
        "subtitle": subtitle,
        "eyebrow": eyebrow,
        "start_date": start_date,
        "end_date": end_date,
        "resort_id": resort_id,
        "resort_name": resort_name,
        "anchor_friend_id": anchor_friend_id,
        "anchor_friend_name": anchor_friend_name,
        "meta": meta or {},
        "is_first": is_first,
    }
