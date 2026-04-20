"""
Ideas Engine
Shared logic for constructing overlap windows and wishlist overlaps.

Used by:
- /trip-ideas  (full ideas page)
- /home        (Next Best Match module)

This module is the single source of truth for ideas window construction.
Do not duplicate this logic in routes.
"""

import re
from collections import Counter
from datetime import date, timedelta
from flask import url_for
from utils.formatting import format_name
from models import Resort, SkiTrip

_BAD_PASSES = {None, "", "I don't have a pass", "Other"}


def _norm_pass(pt):
    """Normalize a pass type string: 'Ikon Pass' → 'Ikon', empty/junk → ''."""
    if not pt:
        return ""
    for part in pt.split(","):
        part = part.strip()
        if not part or part.lower() in ("none", "i don't have a pass", "other", "no pass"):
            continue
        return re.sub(r"\s+[Pp]ass$", "", part).strip()
    return ""


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


# ──────────────────────────────────────────────────────────────────────────────
# V1 UNIFIED FEED HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _format_date_range(start_str, end_str):
    """Format a date range compactly: 'Jan 20', 'Jan 20–22', or 'Jan 30–Feb 2'."""
    s = date.fromisoformat(start_str)
    e = date.fromisoformat(end_str)
    if s == e:
        return s.strftime("%b %-d")
    elif s.month == e.month:
        return f"{s.strftime('%b %-d')}–{e.strftime('%-d')}"
    else:
        return f"{s.strftime('%b %-d')}–{e.strftime('%b %-d')}"


def build_availability_overlap_cards(user, windows, all_friends, user_wishlist):
    """
    Convert build_overlap_windows() output into availability_overlap IdeaCards.

    Each window becomes one card. Past windows are excluded.
    Pass and wishlist signals enhance the subtitle but never create a card alone.

    # FUTURE: /add_trip only supports single friend_id; multi-friend prefill TBD.
    """
    today = date.today()
    friend_by_id = {f.id: f for f in all_friends}
    user_pass = (user.pass_type or "").strip()

    cards = []
    for w in windows:
        try:
            start = date.fromisoformat(w["start_date"])
        except (ValueError, KeyError):
            continue
        if start < today:
            continue

        days_until = (start - today).days
        friends_in_window = w.get("friends_in_window", [])
        n = len(friends_in_window)
        if n == 0:
            continue

        date_range = _format_date_range(w["start_date"], w["end_date"])

        if n == 1:
            fname = friends_in_window[0].get("friend_name") or "your friend"
            title = f"You and {fname} are free {date_range}"
        elif n == 2:
            names = [f.get("friend_name", "") for f in friends_in_window[:2]]
            title = f"You, {names[0]}, and {names[1]} are free {date_range}"
        else:
            title = f"You and {n} friends are free {date_range}"

        window_friend_ids = {f["friend_id"] for f in friends_in_window}

        shared_resort_name = None
        shared_resort_id = None
        if user_wishlist:
            for fid in window_friend_ids:
                friend_obj = friend_by_id.get(fid)
                if friend_obj:
                    shared = user_wishlist & set(friend_obj.wish_list_resorts or [])
                    if shared:
                        rid = next(iter(shared))
                        resort = Resort.query.get(rid)
                        if resort:
                            shared_resort_name = resort.name
                            shared_resort_id = rid
                            break

        # Abbreviated date range for feed line 2 (e.g. "Jun 16–19")
        date_short = _format_date_range(w["start_date"], w["end_date"])

        # Total people including the user
        people_count = n + 1

        # Build pass_phrase for feed subtitle
        user_pass_clean = user_pass if user_pass not in _BAD_PASSES else None
        user_pass_name = _norm_pass(user_pass) if user_pass_clean else ""
        friend_pass_names = set()
        for _f in friends_in_window:
            _fp = _f.get("friend_pass", "")
            if _fp and _fp not in _BAD_PASSES:
                _np = _norm_pass(_fp)
                if _np:
                    friend_pass_names.add(_np)

        if user_pass_name and friend_pass_names:
            _all = friend_pass_names | {user_pass_name}
            if len(_all) == 1:
                _p = next(iter(_all))
                pass_phrase = f"You both have {_p}" if people_count == 2 else f"All have {_p}"
            else:
                pass_phrase = "Different passes"
        else:
            pass_phrase = ""

        # Used for scoring only
        pass_aligns = pass_phrase and not pass_phrase.startswith("Different")

        subtitle = None  # feed subtitle replaced by template-level combined line

        anchor_friend_id = w.get("anchor_friend_id")

        # Build cta_url → idea detail route
        friend_ids_param = ",".join(str(fid) for fid in sorted(window_friend_ids))
        params = f"?friend_ids={friend_ids_param}&start_date={w['start_date']}&end_date={w['end_date']}"
        if shared_resort_id:
            params += f"&resort_id={shared_resort_id}"
        cta_url = url_for("idea_detail_availability") + params

        # Window length phrase for featured card headline
        start_obj_inner = date.fromisoformat(w["start_date"])
        end_obj_inner = date.fromisoformat(w["end_date"])
        n_days = (end_obj_inner - start_obj_inner).days + 1
        _num_words_lc = {1:"one",2:"two",3:"three",4:"four",5:"five",
                         6:"six",7:"seven",8:"eight",9:"nine",10:"ten"}
        if n_days == 1:
            length_phrase = "A one-day window"
        elif n_days == 2:
            length_phrase = "A weekend"
        elif n_days == 3:
            length_phrase = "A long weekend"
        else:
            length_phrase = f"A {_num_words_lc.get(n_days, str(n_days))}-day window"

        # Long date range for display ("June 16 – 19" or "June 16 – July 4")
        if start_obj_inner.month == end_obj_inner.month:
            display_date_long = f"{start_obj_inner.strftime('%B %-d')} – {end_obj_inner.strftime('%-d')}"
        else:
            display_date_long = f"{start_obj_inner.strftime('%B %-d')} – {end_obj_inner.strftime('%B %-d')}"

        # Tier base 1000: guarantees availability ranks above all trip cards (max ~380)
        score = 1000
        score += min(n * 5, 20)   # up to 20 for overlapping friend count
        if shared_resort_name:
            score += 15
        if pass_aligns:
            score += 10
        if days_until <= 14:
            score += 5
        elif days_until <= 30:
            score += 3

        cards.append(make_idea_card(
            idea_type="availability_overlap",
            title=title,
            cta_url=cta_url,
            cta_label="Plan trip →",
            friend_ids=list(window_friend_ids),
            score=float(score),
            subtitle=subtitle,
            start_date=w["start_date"],
            end_date=w["end_date"],
            resort_name=shared_resort_name,
            anchor_friend_id=anchor_friend_id,
            anchor_friend_name=friends_in_window[0].get("friend_name") if friends_in_window else None,
            meta={
                "window_length_phrase": length_phrase,
                "display_date_long": display_date_long,
                "date_short": date_short,
                "people_count": people_count,
                "pass_phrase": pass_phrase,
                "friends_data": [
                    {
                        "id": f["friend_id"],
                        "name": f.get("friend_name", ""),
                    }
                    for f in friends_in_window
                ],
            },
        ))

    return cards


def build_wishlist_overlap_cards(user, wishlist_data, all_friends, user_dates):
    """
    Convert build_wishlist_overlaps() output into wishlist_overlap IdeaCards.

    Shared wishlist resort is the trigger. Pass and date overlap enhance the subtitle.

    # FUTURE: /add_trip only supports single friend_id; multi-friend prefill TBD.
    """
    from services.open_dates import get_available_dates_for_user as _get_avail

    today = date.today()
    sixty_days_out = today + timedelta(days=60)
    user_pass = (user.pass_type or "").strip()
    friend_by_id = {f.id: f for f in all_friends}

    cards = []
    for resort_data in wishlist_data:
        resort_id = resort_data["resort_id"]
        resort_name = resort_data["resort_name"]
        overlapping_people = resort_data.get("overlapping_people", [])
        if not overlapping_people:
            continue

        n = len(overlapping_people)
        anchor = overlapping_people[0]
        anchor_friend_id = anchor["id"]

        # "{Resort} keeps coming up" — always this format per spec
        title = f"{resort_name} keeps coming up"

        nearest_overlap_range = None
        nearest_overlap_within_60 = False
        if user_dates:
            all_shared = set()
            for person in overlapping_people:
                fid = person["id"]
                friend_obj = friend_by_id.get(fid)
                if not friend_obj:
                    continue
                friend_dates = _get_avail(friend_obj)
                all_shared |= (user_dates & friend_dates)
            if all_shared:
                shared_sorted = sorted(all_shared)
                r_start = shared_sorted[0]
                r_end = shared_sorted[0]
                for d in shared_sorted[1:]:
                    prev = date.fromisoformat(r_end)
                    curr = date.fromisoformat(d)
                    if (curr - prev).days == 1:
                        r_end = d
                    else:
                        break
                nearest_overlap_range = _format_date_range(r_start, r_end)
                nearest_overlap_within_60 = date.fromisoformat(r_start) <= sixty_days_out

        pass_match_count = sum(
            1 for p in overlapping_people
            if p.get("pass_type") and p.get("pass_type") not in _BAD_PASSES
            and p.get("pass_type") == user_pass
        )

        anchor_full_name = f"{anchor.get('first_name', '')} {anchor.get('last_name', '')}".strip() or "a friend"
        if n == 1:
            subtitle = f"You and {anchor_full_name} have {resort_name} on your wishlists"
        else:
            subtitle = f"You and {n} friends have {resort_name} on your wishlists"

        friend_ids_param = ",".join(str(p["id"]) for p in overlapping_people)
        cta_url = (
            url_for("idea_detail_wishlist")
            + f"?resort_id={resort_id}&friend_ids={friend_ids_param}"
        )

        score = 30
        score += min(n * 5, 25)
        if pass_match_count >= 1:
            score += 10
        if nearest_overlap_range:
            score += 10
            if nearest_overlap_within_60:
                score += 10

        cards.append(make_idea_card(
            idea_type="wishlist_overlap",
            title=title,
            cta_url=cta_url,
            cta_label="Suggest dates →",
            friend_ids=[p["id"] for p in overlapping_people],
            score=float(score),
            subtitle=subtitle,
            resort_id=resort_id,
            resort_name=resort_name,
            anchor_friend_id=anchor_friend_id,
            anchor_friend_name=anchor.get("first_name"),
            meta={"overlapping_people": overlapping_people},
        ))

    return cards


def apply_diversity_selection(candidates, max_cards=5):
    """
    Greedy diversity selection. Selects up to max_cards from candidates using
    soft multiplicative penalties for repetitive signals (same friend, resort,
    date window, or idea type).

    Stronger ideas still win — penalties are soft, not hard exclusions.
    """
    if not candidates:
        return []

    pool = sorted(candidates, key=lambda c: c["score"], reverse=True)
    selected = []

    while pool and len(selected) < max_cards:
        if not selected:
            best = pool.pop(0)
            selected.append(best)
            continue

        best_idx = 0
        best_eff = -1.0

        for i, candidate in enumerate(pool):
            eff = float(candidate["score"])
            cand_friends = set(candidate.get("friend_ids") or [])
            cand_resort = candidate.get("resort_id")
            cand_start = candidate.get("start_date")
            cand_type = candidate.get("idea_type")

            for sel in selected:
                sel_friends = set(sel.get("friend_ids") or [])
                if cand_friends & sel_friends:
                    eff *= 0.70
                if cand_resort and sel.get("resort_id") and cand_resort == sel["resort_id"]:
                    eff *= 0.75
                if cand_start and sel.get("start_date"):
                    try:
                        d1 = date.fromisoformat(cand_start)
                        d2 = date.fromisoformat(sel["start_date"])
                        if abs((d1 - d2).days) <= 3:
                            eff *= 0.80
                    except (ValueError, TypeError):
                        pass
                if cand_type and cand_type == sel.get("idea_type"):
                    eff *= 0.85

            if eff > best_eff:
                best_eff = eff
                best_idx = i

        selected.append(pool.pop(best_idx))

    for i, card in enumerate(selected):
        card["is_first"] = (i == 0)

    return selected


def _fmt_date_range_short(start, end):
    """Format a date range as 'Apr 20', 'Apr 20–24', or 'May 31–Jun 4'."""
    if not start:
        return ""
    if not end or start == end:
        return start.strftime("%b %-d")
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}\u2013{end.strftime('%-d')}"
    return f"{start.strftime('%b %-d')}\u2013{end.strftime('%b %-d')}"


def build_destination_feed(user, all_friends):
    """
    Simplified dated-destination feed for the Ideas tab.

    Queries all public upcoming friend trips that have a linked resort.
    Groups by (resort_id, start_date, end_date) and counts going vs considering.
    Returns rows sorted by start_date ascending, then more going first.

    Each row dict:
        resort      – Resort ORM object (slug, name)
        start_date  – date
        end_date    – date
        date_range  – formatted string e.g. "Apr 20–24"
        going       – int (trip_status == 'going')
        considering – int (trip_status != 'going')
    """
    today = date.today()
    friend_ids = [f.id for f in all_friends]

    if not friend_ids:
        return []

    friend_trips = (
        SkiTrip.query
        .filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.end_date >= today,
            SkiTrip.is_public == True,
            SkiTrip.resort_id.isnot(None),
        )
        .order_by(SkiTrip.start_date.asc())
        .all()
    )

    groups = {}
    for trip in friend_trips:
        key = (trip.resort_id, trip.start_date, trip.end_date)
        if key not in groups:
            groups[key] = {
                "resort": trip.resort,
                "start_date": trip.start_date,
                "end_date": trip.end_date,
                "going": 0,
                "considering": 0,
            }
        if (trip.trip_status or "planning") == "going":
            groups[key]["going"] += 1
        else:
            groups[key]["considering"] += 1

    rows = sorted(
        groups.values(),
        key=lambda r: (r["start_date"], -r["going"]),
    )
    for row in rows:
        row["date_range"] = _fmt_date_range_short(row["start_date"], row["end_date"])

    return rows


def build_ranked_idea_feed(user, all_friends):
    """
    Legacy coordinator — kept for potential future secondary surfaces.
    The main Ideas tab now uses build_destination_feed() instead.

    Collect candidate IdeaCards from all skill builders, apply
    unified diversity selection, and return the top 3–5 cards.

    # FUTURE: /add_trip only supports single friend_id; multi-friend prefill TBD.
    """
    from services.skills.trip_overlap import trip_overlap_skill
    from services.open_dates import get_available_dates_for_user, get_open_date_matches

    user_dates = get_available_dates_for_user(user)
    user_wishlist = set(user.wish_list_resorts or [])
    friend_ids = [f.id for f in all_friends]

    today = date.today()
    _friend_trips = (
        SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.end_date >= today,
        ).all()
        if friend_ids else []
    )
    friend_trip_statuses = {}
    for _ft in _friend_trips:
        fid = _ft.user_id
        if fid not in friend_trip_statuses and _ft.trip_status == "going":
            friend_trip_statuses[fid] = "going"

    matches = get_open_date_matches(user)
    windows = build_overlap_windows(
        matches, user.pass_type, friend_trip_statuses=friend_trip_statuses
    )
    avail_cards = build_availability_overlap_cards(user, windows, all_friends, user_wishlist)

    wishlist_data = build_wishlist_overlaps(user, all_friends)
    wishlist_cards = build_wishlist_overlap_cards(user, wishlist_data, all_friends, user_dates)

    trip_cards = trip_overlap_skill(user, all_friends)

    all_candidates = avail_cards + wishlist_cards + trip_cards
    return apply_diversity_selection(all_candidates, max_cards=5)
