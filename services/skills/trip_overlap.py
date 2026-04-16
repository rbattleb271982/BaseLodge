"""
Trip Overlap Skill
Surfaces friends' booked trips as IdeaCards when the current user has open
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

    Scoring (additive, max 100):
      +40  At least one date in the user's availability overlaps the trip
      +30  Trip's pass_type matches (contains) the user's pass_type
      +20  Trip's resort is on the user's wishlist
      +10  Trip starts within the next 30 days

    Exclusions:
      - Trips the user owns (trip.user_id == user.id)
      - Trips the user has already accepted (SkiTripParticipant row with
        status == GuestStatus.ACCEPTED)
      - Non-public trips (is_public != True)
      - Past trips (end_date < today)

    Grouping:
      Multiple friends on the same trip produce one card. The title is updated
      to reflect the number of friends when > 1.
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

    friend_trips = (
        SkiTrip.query.filter(
            SkiTrip.user_id.in_(friend_ids),
            SkiTrip.end_date >= today,
            SkiTrip.is_public == True,
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

        score = 0

        if user_dates & trip_dates:
            score += 40

        trip_pass = (trip.pass_type or "").lower()
        if user_pass and trip_pass and (user_pass in trip_pass or trip_pass in user_pass):
            score += 30

        resort_id = trip.resort_id
        if resort_id and resort_id in user_wishlist:
            score += 20

        if trip.start_date <= thirty_days:
            score += 10

        resort_name = trip.mountain or "a resort"

        n = len(involved_friend_ids)
        if n == 1:
            anchor_fid = involved_friend_ids[0]
            anchor_friend = friend_by_id.get(anchor_fid)
            anchor_name = anchor_friend.first_name if anchor_friend else "Your friend"
            title = f"{anchor_name} is going to {resort_name}"
        elif n == 2:
            names = sorted(
                friend_by_id[fid].first_name
                for fid in involved_friend_ids
                if fid in friend_by_id
            )
            title = f"{' and '.join(names)} are going to {resort_name}"
        else:
            title = f"{n} friends are going to {resort_name}"
            anchor_fid = involved_friend_ids[0]
            anchor_name = friend_by_id.get(anchor_fid, user).first_name

        anchor_fid = involved_friend_ids[0]
        anchor_friend = friend_by_id.get(anchor_fid)
        anchor_name = anchor_friend.first_name if anchor_friend else None

        eyebrow = None
        if trip.start_date and trip.end_date:
            fmt = "%b %-d"
            eyebrow = f"{trip.start_date.strftime(fmt)} – {trip.end_date.strftime(fmt)}"

        card = make_idea_card(
            idea_type="trip_overlap",
            title=title,
            cta_url=url_for("friend_trip_details", trip_id=trip.id),
            cta_label="View trip →",
            friend_ids=involved_friend_ids,
            score=float(score),
            eyebrow=eyebrow,
            start_date=trip.start_date.isoformat() if trip.start_date else None,
            end_date=trip.end_date.isoformat() if trip.end_date else None,
            resort_id=resort_id,
            resort_name=resort_name,
            anchor_friend_id=anchor_fid,
            anchor_friend_name=anchor_name,
            meta={"trip_id": trip.id},
        )
        cards.append(card)

    cards.sort(key=lambda c: c["score"], reverse=True)
    return cards[:3]
