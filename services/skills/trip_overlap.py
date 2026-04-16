"""
Trip Overlap Skill
Surfaces friends' trips as IdeaCards when the current user has open
dates that overlap with those trips, or when the trip is at a resort on the
user's wishlist.

Returns up to 3 IdeaCard dicts produced by make_idea_card().
"""

from datetime import date, timedelta

from flask import url_for

from models import GuestStatus, SkiTrip, SkiTripParticipant
from services.ideas_engine import make_idea_card
from services.open_dates import get_available_dates_for_user


def trip_overlap_skill(user, all_friends):
    """Return up to 3 IdeaCards for friends' upcoming trips that are relevant
    to the current user.

    Scoring (additive, max ~105):
      +40  At least one date in the user's availability overlaps the trip
      +30  Trip's pass_type matches (contains) the user's pass_type
      +20  Trip's resort is on the user's wishlist
      +10  Trip starts within the next 30 days
      +10  Trip starts within the next 14 days (stackable)
      +5   Trip is in 'planning' state (more socially open, ranked higher)

    Copy varies by trip_status:
      planning → softer, open: "Alex is considering Jackson Hole"
      going    → firmer: "Join Alex in Jackson Hole"

    Exclusions:
      - Trips the user owns (trip.user_id == user.id)
      - Trips the user has already accepted (SkiTripParticipant row with
        status == GuestStatus.ACCEPTED)
      - Non-public trips (is_public != True)
      - Past trips (end_date < today)

    Grouping:
      Multiple friends on the same trip produce one card.
    """
    today = date.today()
    thirty_days = today + timedelta(days=30)

    if not all_friends:
        return []

    friend_ids = [f.id for f in all_friends]
    friend_by_id = {f.id: f for f in all_friends}

    user_dates = get_available_dates_for_user(user)
    user_wishlist = set(user.wish_list_resorts or [])
    user_pass = (user.pass_type or "").lower()

    user_accepted_trip_ids = {
        p.trip_id
        for p in SkiTripParticipant.query.filter_by(
            user_id=user.id, status=GuestStatus.ACCEPTED
        ).all()
    }

    from sqlalchemy import or_

    friend_trips = (
        SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.end_date >= today,
            SkiTrip.is_public == True,
            or_(
                SkiTrip.trip_status.in_(["planning", "going"]),
                SkiTrip.trip_status.is_(None),
            ),
        ).all()
    )

    also_participant_rows = (
        SkiTripParticipant.query.filter(
            SkiTripParticipant.trip_id.in_([t.id for t in friend_trips]),
            SkiTripParticipant.user_id.in_(friend_ids),
            SkiTripParticipant.status == GuestStatus.ACCEPTED,
        ).all()
        if friend_trips
        else []
    )

    trip_extra_friends = {}
    for row in also_participant_rows:
        trip_extra_friends.setdefault(row.trip_id, set()).add(row.user_id)

    trip_map = {}
    for trip in friend_trips:
        if trip.user_id == user.id:
            continue
        if trip.id in user_accepted_trip_ids:
            continue

        if trip.id not in trip_map:
            trip_map[trip.id] = {"trip": trip, "friend_ids": set()}

        trip_map[trip.id]["friend_ids"].add(trip.user_id)

        for extra_fid in trip_extra_friends.get(trip.id, set()):
            if extra_fid != user.id:
                trip_map[trip.id]["friend_ids"].add(extra_fid)

    cards = []
    for trip_id, entry in trip_map.items():
        trip = entry["trip"]
        involved_friend_ids = list(entry["friend_ids"])

        trip_dates = set()
        cur = trip.start_date
        while cur <= trip.end_date:
            trip_dates.add(cur.isoformat())
            cur += timedelta(days=1)

        resort_id = trip.resort_id
        has_date_overlap = bool(user_dates & trip_dates)
        has_wishlist_match = bool(resort_id and resort_id in user_wishlist)

        if not (has_date_overlap or has_wishlist_match):
            continue

        fourteen_days = today + timedelta(days=14)

        score = 50  # base
        if has_date_overlap:
            score += 40
        trip_pass = (trip.pass_type or "").lower()
        pass_aligns = bool(
            user_pass and trip_pass
            and (user_pass in trip_pass or trip_pass in user_pass)
        )
        if pass_aligns:
            score += 30
        if has_wishlist_match:
            score += 20
        if today <= trip.start_date <= thirty_days:
            score += 10
        if today <= trip.start_date <= fourteen_days:
            score += 10  # stackable with 30-day bonus

        trip_status = trip.trip_status or "planning"

        # Planning-state ideas are more socially open — rank them slightly higher
        if trip_status == "planning":
            score += 5

        resort_name = trip.mountain or "a resort"

        anchor_fid = involved_friend_ids[0]
        anchor_friend = friend_by_id.get(anchor_fid)
        anchor_name = anchor_friend.first_name if anchor_friend else "Your friend"

        n = len(involved_friend_ids)

        # Copy varies by trip status
        if trip_status == "going":
            if n == 1:
                title = f"Join {anchor_name} in {resort_name}"
            elif n == 2:
                names = sorted(
                    friend_by_id[fid].first_name
                    for fid in involved_friend_ids
                    if fid in friend_by_id
                )
                title = f"{' and '.join(names)} are going to {resort_name}"
            else:
                title = f"{n} friends are going to {resort_name}"
        else:
            # planning — softer, more open language
            if n == 1:
                title = f"{anchor_name} is considering {resort_name}"
            elif n == 2:
                names = sorted(
                    friend_by_id[fid].first_name
                    for fid in involved_friend_ids
                    if fid in friend_by_id
                )
                title = f"{' and '.join(names)} are thinking about {resort_name}"
            else:
                title = f"{n} friends are thinking about {resort_name}"

        subtitle = None
        if pass_aligns and trip_pass:
            display_pass = trip.pass_type or user_pass
            if n == 1:
                subtitle = f"You both have {display_pass}"
            else:
                subtitle = f"Covered on your {display_pass} pass"
        elif user_pass and trip_pass:
            subtitle = "Passes vary"

        eyebrow = None
        if trip.start_date and trip.end_date:
            fmt = "%b %-d"
            eyebrow = f"{trip.start_date.strftime(fmt)} – {trip.end_date.strftime(fmt)}"

        card = make_idea_card(
            idea_type="trip_overlap",
            title=title,
            cta_url=url_for("idea_detail_trip", trip_id=trip.id),
            cta_label="See more →",
            friend_ids=involved_friend_ids,
            score=float(score),
            subtitle=subtitle,
            eyebrow=eyebrow,
            start_date=trip.start_date.isoformat() if trip.start_date else None,
            end_date=trip.end_date.isoformat() if trip.end_date else None,
            resort_id=resort_id,
            resort_name=resort_name,
            anchor_friend_id=anchor_fid,
            anchor_friend_name=anchor_name,
            meta={"trip_id": trip.id, "trip_status": trip_status},
        )
        cards.append(card)

    cards.sort(key=lambda c: c["score"], reverse=True)
    return cards  # no pre-limit; apply_diversity_selection in build_ranked_idea_feed handles cap
