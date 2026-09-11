"""The bounded data projection used by the Trips ``Both`` view.

This module deliberately contains no presentation or dismissal policy.  Home
Ideas supplies the shared relevance boundary; this projection only reshapes
those candidates alongside the viewer's active trips.
"""

from dataclasses import dataclass, field
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from models import Friend, GuestStatus, SkiTrip, SkiTripParticipant, User, db
from services.ideas_retrieval import get_home_idea_candidates
from services.my_trips_paging import load_my_trips_page
from services.ski_seasons import get_ski_season_window
from services.trip_attendance import effective_attendance_dates
from services.visibility import reciprocal_friend_ids


@dataclass
class BothTripRow:
    trip: SkiTrip
    relationship: str
    attendance_start_date: date | None
    attendance_end_date: date | None
    overlap_names: list[str] = field(default_factory=list)
    standalone_reason: str | None = None
    going_count: int = 0
    others_count: int = 0
    friend_names: list[str] = field(default_factory=list)

    @property
    def is_opportunity(self):
        return self.standalone_reason is not None

    @property
    def mountain_name(self):
        return self.trip.resort.name if self.trip.resort else (self.trip.mountain or "Mountain TBD")


def _status(value):
    return getattr(value, "value", value)


def _active(trip, today):
    return (
        (trip.lifecycle_state or "active") == "active"
        and trip.end_date is not None
        and trip.end_date >= today
    )


def _intersects(a_start, a_end, b_start, b_end):
    return (
        a_start is not None and a_end is not None and
        b_start is not None and b_end is not None and
        a_start <= b_end and b_start <= a_end
    )


def load_both_trips(viewer_id: int, *, today: date | None = None):
    """Return authorized own rows and relevant friend opportunities.

    The only friend identities considered here are reciprocal friends.  A
    candidate is represented at most once; when it overlaps an own row it is
    attached to that row rather than emitted as a second standalone entry.
    """
    today = today or date.today()
    _season_start, season_end = get_ski_season_window(today)
    reciprocal_ids = reciprocal_friend_ids(viewer_id)

    mine_page = load_my_trips_page(
        viewer_id,
        "upcoming",
        today=today,
        page_size=None,
        through_date=season_end,
    )
    own = []
    for row in mine_page.rows:
        if row.is_invitation or row.relationship not in {"organizing", "going", "interested"}:
            continue
        own.append(BothTripRow(
            trip=row.trip,
            relationship=row.relationship,
            attendance_start_date=row.attendance_start_date,
            attendance_end_date=row.attendance_end_date,
            going_count=row.going_count,
            others_count=row.others_count,
        ))

    if not reciprocal_ids:
        return own

    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__.alias("both_friend_participant")
    owner_rows = sa.select(SkiTrip.id).where(
        SkiTrip.user_id.in_(reciprocal_ids),
        SkiTrip.is_public.is_(True),
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
        SkiTrip.end_date >= today,
        SkiTrip.start_date <= season_end,
    )
    effective_start, effective_end = (
        sa.case(
            (sa.and_(
                participant.c.status == GuestStatus.GOING,
                participant.c.start_date.is_not(None),
                participant.c.end_date.is_not(None),
            ), participant.c.start_date),
            else_=SkiTrip.start_date,
        ),
        sa.case(
            (sa.and_(
                participant.c.status == GuestStatus.GOING,
                participant.c.start_date.is_not(None),
                participant.c.end_date.is_not(None),
            ), participant.c.end_date),
            else_=SkiTrip.end_date,
        ),
    )
    participant_rows = sa.select(SkiTrip.id).select_from(
        SkiTrip.__table__.join(
            participant, participant.c.trip_id == SkiTrip.id
        )
    ).where(
        participant.c.user_id.in_(reciprocal_ids),
        participant.c.status.in_((GuestStatus.GOING, GuestStatus.INTERESTED)),
        participant.c.user_id != SkiTrip.user_id,
        SkiTrip.is_public.is_(True),
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
        SkiTrip.end_date >= today,
        effective_end >= today,
        effective_start <= season_end,
    )
    friend_ids = sa.union(owner_rows, participant_rows)
    friends = SkiTrip.query.options(
        joinedload(SkiTrip.resort),
        joinedload(SkiTrip.participants),
    ).filter(SkiTrip.id.in_(sa.select(friend_ids.c.id))).all()
    friend_users = {
        user.id: user
        for user in User.query.filter(
            User.id.in_(reciprocal_ids)
        ).all()
    }

    # Build the structured raw relevance set without importing Home's card
    # dismissal, cap, or ordering decisions.
    candidates = get_home_idea_candidates(
        user_id=viewer_id,
        today=today,
        through_date=season_end,
    )
    candidate_keys = set()
    candidate_reasons = {}
    wishlist_resorts = set()
    for candidate in candidates:
        if candidate["idea_type"] == "wishlist_overlap":
            wishlist_resorts.add(candidate["resort_id"])
            continue
        if candidate["idea_type"] != "friend_trip" or candidate["friend_count"] < 3:
            continue
        ids = {int(v) for v in str(candidate["friend_ids"] or "").split(",") if v}
        key = (
            candidate["resort_id"], candidate["start_date"], candidate["end_date"]
        )
        candidate_keys.add(key)
        candidate_reasons[key] = "confirmed_friend_trip"

    friend_occurrences = {}

    def add_occurrence(friend_trip, start, end, attendee_id, *, going):
        identity = (friend_trip.id, start, end)
        occurrence = friend_occurrences.setdefault(
            identity,
            {
                "trip": friend_trip,
                "start": start,
                "end": end,
                "key": (friend_trip.resort_id, start, end),
                "going_ids": set(),
                "interested_ids": set(),
            },
        )
        target = "going_ids" if going else "interested_ids"
        occurrence[target].add(attendee_id)

    for friend_trip in friends:
        if not _active(friend_trip, today) or friend_trip.resort_id is None:
            continue
        if friend_trip.user_id in reciprocal_ids:
            add_occurrence(
                friend_trip,
                friend_trip.start_date,
                friend_trip.end_date,
                friend_trip.user_id,
                going=_status(friend_trip.trip_status) == "going",
            )
        for p in friend_trip.participants:
            if p.user_id not in reciprocal_ids or _status(p.status) not in {
                GuestStatus.GOING.value, GuestStatus.INTERESTED.value
            }:
                continue
            start, end = effective_attendance_dates(friend_trip, p)
            if start > season_end:
                continue
            add_occurrence(
                friend_trip,
                start,
                end,
                p.user_id,
                going=_status(p.status) == GuestStatus.GOING.value,
            )
    friend_occurrences = list(friend_occurrences.values())

    # Reciprocal friends' identities are de-duplicated before annotation.
    for own_row in own:
        overlapping_ids = set()
        if own_row.relationship not in {"organizing", "going"}:
            continue
        for occurrence in friend_occurrences:
            friend_trip = occurrence["trip"]
            if friend_trip.id == own_row.trip.id:
                continue
            if friend_trip.resort_id != own_row.trip.resort_id:
                continue
            if not _intersects(
                own_row.attendance_start_date, own_row.attendance_end_date,
                occurrence["start"], occurrence["end"],
            ):
                continue
            overlapping_ids.update(occurrence["going_ids"])
        own_row.overlap_names = sorted(
            {
                friend_users[friend_id].first_name
                for friend_id in overlapping_ids
                if friend_id in friend_users
                and friend_users[friend_id].first_name
            },
            key=str.casefold,
        )

    own_trip_ids = {row.trip.id for row in own}
    overlapped_trip_ids = {
        occurrence["trip"].id
        for own_row in own
        for occurrence in friend_occurrences
        if occurrence["going_ids"]
        if occurrence["trip"].id != own_row.trip.id
        if occurrence["trip"].resort_id == own_row.trip.resort_id
        if _intersects(
            own_row.attendance_start_date,
            own_row.attendance_end_date,
            occurrence["start"],
            occurrence["end"],
        )
        if own_row.relationship in {"organizing", "going"}
    }
    emitted_opportunity_trips = set()
    for occurrence in friend_occurrences:
        friend_trip = occurrence["trip"]
        if (
            friend_trip.id in own_trip_ids
            or friend_trip.id in overlapped_trip_ids
            or friend_trip.id in emitted_opportunity_trips
        ):
            continue
        opportunity_names = {
            friend_id: friend_users[friend_id].first_name
            for friend_id in occurrence["going_ids"]
            if friend_id in friend_users and friend_users[friend_id].first_name
        }
        reason = None
        if (
            candidate_reasons.get(occurrence["key"]) == "confirmed_friend_trip"
            and len(opportunity_names) >= 3
        ):
            reason = f"{len(opportunity_names)} friends going"
        elif friend_trip.resort_id in wishlist_resorts:
            reason = "On your wishlist"
        if reason is None:
            continue
        emitted_opportunity_trips.add(friend_trip.id)
        own.append(BothTripRow(
            trip=friend_trip,
            relationship="friend_trip",
            attendance_start_date=occurrence["start"],
            attendance_end_date=occurrence["end"],
            standalone_reason=reason,
            friend_names=sorted(
                opportunity_names.values(),
                key=str.casefold,
            ),
        ))
    return sorted(
        own,
        key=lambda row: (
            row.attendance_start_date is None,
            row.attendance_start_date or date.max,
            row.attendance_end_date or date.max,
            row.trip.resort_id is None,
            row.trip.resort_id or 0,
            row.trip.id,
            row.relationship,
        ),
    )