"""Bounded, trip-centric Friends' Trips retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.orm import joinedload

from models import Friend, GuestStatus, Resort, SkiTrip, SkiTripParticipant, User, db
from services.ski_seasons import get_ski_season_window
from services.trip_attendance import effective_attendance_date_expressions
from services.visibility import reciprocal_friend_predicate


FRIENDS_TRIPS_PAGE_SIZE = 10
_CURSOR_SALT = "friends-trips-trip-feed-v2"


class FriendsTripsCursorError(ValueError):
    """Raised for malformed or cross-viewer paging tokens."""


class FriendsTripsGroupError(ValueError):
    """Retained for compatibility with the retired destination-group API."""


@dataclass(frozen=True)
class FriendsTripRow:
    trip: SkiTrip
    friend_ids: tuple[int, ...]
    friend_names: tuple[str, ...]
    attendance_start_date: date | None
    attendance_end_date: date | None
    overlaps_viewer_trip: bool = False

    @property
    def trip_id(self) -> int:
        return self.trip.id

    @property
    def destination(self) -> str:
        return self.trip.resort.name if self.trip.resort else (self.trip.mountain or "TBD")

    @property
    def destination_key(self) -> str:
        return f"t:{self.trip.id}"

    @property
    def status(self) -> str:
        return "going"

    @property
    def friend_id(self) -> int:
        return self.friend_ids[0]

    @property
    def friend_name(self) -> str:
        return self.friend_names[0]


@dataclass(frozen=True)
class FriendsTripsPage:
    rows: list[FriendsTripRow]
    has_more: bool
    next_cursor: str | None


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=_CURSOR_SALT)


def _active_public():
    return sa.and_(
        SkiTrip.is_public.is_(True),
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
    )


def _entry_union(viewer_id: int, today: date, season_end: date):
    """Return one authorized scalar row per eligible friend/trip source."""
    friend_name = sa.func.coalesce(
        sa.func.nullif(User.first_name, ""), "Friend"
    )
    common = (
        SkiTrip.id.label("trip_id"),
        User.id.label("friend_id"),
        friend_name.label("friend_name"),
        SkiTrip.start_date.label("trip_start"),
        SkiTrip.end_date.label("trip_end"),
        sa.func.coalesce(Resort.name, SkiTrip.mountain, "TBD").label("destination"),
    )
    organizer = (
        sa.select(
            *common,
            SkiTrip.start_date.label("attendance_start"),
            SkiTrip.end_date.label("attendance_end"),
            sa.null().label("participant_id"),
            sa.literal(0).label("source_rank"),
        )
        .select_from(SkiTrip)
        .join(User, User.id == SkiTrip.user_id)
        .outerjoin(Resort, Resort.id == SkiTrip.resort_id)
        .where(
            _active_public(),
            SkiTrip.trip_status == "going",
            SkiTrip.end_date >= today,
            SkiTrip.start_date <= season_end,
            reciprocal_friend_predicate(viewer_id, SkiTrip.user_id),
        )
    )

    participant = SkiTripParticipant.__table__.alias("friends_trip_going")
    effective_start, effective_end = effective_attendance_date_expressions(
        SkiTrip, participant.c
    )
    guest = (
        sa.select(
            *common,
            effective_start.label("attendance_start"),
            effective_end.label("attendance_end"),
            participant.c.id.label("participant_id"),
            sa.literal(1).label("source_rank"),
        )
        .select_from(participant)
        .join(SkiTrip, SkiTrip.id == participant.c.trip_id)
        .join(User, User.id == participant.c.user_id)
        .outerjoin(Resort, Resort.id == SkiTrip.resort_id)
        .where(
            _active_public(),
            participant.c.status == GuestStatus.GOING,
            participant.c.user_id != SkiTrip.user_id,
            effective_end >= today,
            effective_start <= season_end,
            reciprocal_friend_predicate(viewer_id, participant.c.user_id),
            reciprocal_friend_predicate(viewer_id, SkiTrip.user_id),
        )
    )
    return organizer.union_all(guest).subquery("friends_trip_entries")


def _deduped_entries(viewer_id: int, today: date, season_end: date):
    raw = _entry_union(viewer_id, today, season_end)
    ranked = sa.select(
        *raw.c,
        sa.func.row_number().over(
            partition_by=(raw.c.friend_id, raw.c.trip_id),
            order_by=(raw.c.source_rank, raw.c.participant_id),
        ).label("duplicate_rank"),
    ).subquery("friends_trip_ranked")
    return sa.select(
        *[column for column in ranked.c if column.key != "duplicate_rank"]
    ).where(ranked.c.duplicate_rank == 1).subquery("friends_trip_deduped")


def _cursor_payload(row, viewer_id):
    return {
        "v": 2,
        "viewer": int(viewer_id),
        "start": row.trip_start.isoformat(),
        "destination": row.destination,
        "trip": int(row.trip_id),
    }


def _load_cursor(value, viewer_id):
    try:
        payload = _serializer().loads(value)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "viewer", "start", "destination", "trip"}
            or payload["v"] != 2
            or payload["viewer"] != int(viewer_id)
            or type(payload["trip"]) is not int
            or not isinstance(payload["destination"], str)
        ):
            raise ValueError
        return payload, date.fromisoformat(payload["start"])
    except (BadData, KeyError, TypeError, ValueError) as exc:
        raise FriendsTripsCursorError("Invalid Friends' Trips cursor.") from exc


def _trip_units_query(viewer_id, today, season_end, cursor_value=None):
    entries = _deduped_entries(viewer_id, today, season_end)
    units = sa.select(
        entries.c.trip_id,
        entries.c.trip_start,
        entries.c.trip_end,
        entries.c.destination,
    ).group_by(
        entries.c.trip_id,
        entries.c.trip_start,
        entries.c.trip_end,
        entries.c.destination,
    ).subquery("friends_trip_units")
    query = sa.select(*units.c)
    if cursor_value:
        payload, cursor_start = _load_cursor(cursor_value, viewer_id)
        query = query.where(sa.or_(
            units.c.trip_start > cursor_start,
            sa.and_(
                units.c.trip_start == cursor_start,
                units.c.destination > payload["destination"],
            ),
            sa.and_(
                units.c.trip_start == cursor_start,
                units.c.destination == payload["destination"],
                units.c.trip_id > payload["trip"],
            ),
        ))
    return query.order_by(units.c.trip_start, units.c.destination, units.c.trip_id)


def _viewer_occurrences(
    viewer_id: int,
    today: date,
    season_end: date,
    resort_ids: set[int],
    window_start: date,
    window_end: date,
):
    participant = SkiTripParticipant.__table__.alias("friends_viewer_going")
    effective_start, effective_end = effective_attendance_date_expressions(
        SkiTrip, participant.c
    )
    owned = sa.select(
        SkiTrip.resort_id, SkiTrip.start_date, SkiTrip.end_date
    ).where(
        SkiTrip.user_id == viewer_id,
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
        SkiTrip.end_date >= today,
        SkiTrip.start_date <= season_end,
        SkiTrip.resort_id.in_(resort_ids),
        SkiTrip.end_date >= window_start,
        SkiTrip.start_date <= window_end,
    )
    attending = sa.select(
        SkiTrip.resort_id, effective_start, effective_end
    ).select_from(SkiTrip.__table__.join(
        participant, participant.c.trip_id == SkiTrip.id
    )).where(
        participant.c.user_id == viewer_id,
        participant.c.status == GuestStatus.GOING,
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
        effective_end >= today,
        effective_start <= season_end,
        SkiTrip.resort_id.in_(resort_ids),
        effective_end >= window_start,
        effective_start <= window_end,
    )
    return db.session.execute(owned.union_all(attending)).all()


def load_friends_trips_page(
    viewer_id: int,
    *,
    today: date | None = None,
    cursor_value: str | None = None,
    destination_key: str | None = None,
) -> FriendsTripsPage:
    """Return a chronological page of physical trips with eligible friends."""
    if destination_key is not None:
        raise FriendsTripsCursorError("Friends' Trips no longer supports filtering.")
    today = today or date.today()
    _season_start, season_end = get_ski_season_window(today)
    candidates = db.session.execute(
        _trip_units_query(viewer_id, today, season_end, cursor_value)
        .limit(FRIENDS_TRIPS_PAGE_SIZE + 1)
    ).all()
    has_more = len(candidates) > FRIENDS_TRIPS_PAGE_SIZE
    candidates = candidates[:FRIENDS_TRIPS_PAGE_SIZE]
    trip_ids = [row.trip_id for row in candidates]
    trips = (
        SkiTrip.query.options(joinedload(SkiTrip.resort))
        .filter(SkiTrip.id.in_(trip_ids))
        .all()
        if trip_ids else []
    )
    by_id = {trip.id: trip for trip in trips}

    friends_by_trip: dict[int, dict[int, tuple[str, date, date]]] = {
        trip_id: {} for trip_id in trip_ids
    }
    if trip_ids:
        entries = _deduped_entries(viewer_id, today, season_end)
        name_rows = db.session.execute(
            sa.select(
                entries.c.trip_id,
                entries.c.friend_id,
                entries.c.friend_name,
                entries.c.attendance_start,
                entries.c.attendance_end,
            )
            .where(entries.c.trip_id.in_(trip_ids))
            .order_by(entries.c.friend_name, entries.c.friend_id)
        ).all()
        for entry in name_rows:
            friends_by_trip[entry.trip_id][entry.friend_id] = (
                entry.friend_name.strip() or "Friend",
                entry.attendance_start,
                entry.attendance_end,
            )

    page_trips = [by_id[trip_id] for trip_id in trip_ids]
    resort_ids = {trip.resort_id for trip in page_trips if trip.resort_id}
    viewer_occurrences = (
        _viewer_occurrences(
            viewer_id,
            today,
            season_end,
            resort_ids,
            min(trip.start_date for trip in page_trips),
            max(trip.end_date for trip in page_trips),
        )
        if page_trips and resort_ids else []
    )
    rows = []
    for candidate in candidates:
        trip = by_id[candidate.trip_id]
        friends = friends_by_trip[candidate.trip_id]
        overlaps = bool(
            trip.resort_id
            and any(
                occurrence.resort_id == trip.resort_id
                and occurrence.start_date <= attendance_end
                and occurrence.end_date >= attendance_start
                for _name, attendance_start, attendance_end in friends.values()
                for occurrence in viewer_occurrences
            )
        )
        rows.append(FriendsTripRow(
            trip=trip,
            friend_ids=tuple(friends),
            friend_names=tuple(value[0] for value in friends.values()),
            attendance_start_date=trip.start_date,
            attendance_end_date=trip.end_date,
            overlaps_viewer_trip=overlaps,
        ))

    next_cursor = (
        _serializer().dumps(_cursor_payload(candidates[-1], viewer_id))
        if has_more else None
    )
    return FriendsTripsPage(rows, has_more, next_cursor)


def load_friends_trips_context(
    viewer_id: int, *, today: date | None = None
) -> tuple[list, bool]:
    """Return no filter options plus reciprocal friendship presence."""
    has_friend = db.session.scalar(
        sa.select(sa.exists(
            sa.select(1).select_from(Friend).where(
                Friend.user_id == viewer_id,
                reciprocal_friend_predicate(viewer_id, Friend.friend_id),
            )
        ))
    )
    return [], bool(has_friend)


def load_friends_trips_destinations(viewer_id: int, *, today=None) -> list:
    return []


def load_friends_trips_destination_options(viewer_id: int, *, today=None) -> list:
    return []


def load_friends_trips_group(*_args, **_kwargs):
    raise FriendsTripsGroupError("Friends' Trips destination groups were retired.")


load_friends_trips_group_page = load_friends_trips_group