"""Bounded Friends' Trips retrieval.

The feed is a person-presence surface: an entry identifies a reciprocal friend
and a public, live trip on which that friend is either the organizer or an
explicitly Going guest.  SQL window functions turn those entries into display
units before the page limit is applied, so a three-trip group never straddles
pages and its details do not ride along with the feed response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from flask import current_app
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy.orm import joinedload

from models import Friend, GuestStatus, Resort, SkiTrip, SkiTripParticipant, User, db
from services.trip_attendance import effective_attendance_date_expressions
from services.visibility import reciprocal_friend_predicate


FRIENDS_TRIPS_PAGE_SIZE = 10
FRIENDS_TRIPS_DETAIL_PAGE_SIZE = 20
FRIENDS_TRIPS_GROUP_PAGE_SIZE = FRIENDS_TRIPS_DETAIL_PAGE_SIZE
_GROUP_SALT = "bl159-friends-trips-group-v1"
_CURSOR_SALT = "bl159-friends-trips-cursor-v1"


class FriendsTripsCursorError(ValueError):
    """Raised for malformed, stale-scope, or cross-viewer paging tokens."""


class FriendsTripsGroupError(ValueError):
    """Raised when a grouped identity is malformed or no longer authorized."""


@dataclass(frozen=True)
class FriendsTripRow:
    friend_id: int
    friend_name: str
    destination: str
    destination_key: str
    status: str
    attendance_start_date: date | None
    attendance_end_date: date | None
    group_start_date: date | None = None
    group_end_date: date | None = None
    trip: SkiTrip | None = None
    grouped_count: int = 1
    group_token: str | None = None

    @property
    def grouped(self) -> bool:
        return self.grouped_count >= 3

    @property
    def trip_id(self) -> int | None:
        return self.trip.id if self.trip is not None else None

    @property
    def formatted_date(self) -> str:
        start = self.attendance_start_date
        end = self.attendance_end_date
        if not start:
            return "Dates TBD"
        if not end or end == start:
            return start.strftime("%b %-d")
        end_format = "%b %-d" if start.month != end.month else "%-d"
        return f"{start.strftime('%b %-d')}–{end.strftime(end_format)}"

    def __getitem__(self, key):
        aliases = {
            "trip_start": self.attendance_start_date,
            "trip_end": self.attendance_end_date,
            "formatted_date": self.formatted_date,
        }
        if key in aliases:
            return aliases[key]
        return getattr(self, key)


@dataclass(frozen=True)
class FriendsTripsPage:
    rows: list[FriendsTripRow]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True)
class FriendsTripsDetailPage:
    rows: list[FriendsTripRow]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True)
class DestinationOption:
    key: str
    name: str


def _serializer(salt):
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=salt)


def _destination_expressions():
    name = sa.func.coalesce(Resort.name, SkiTrip.mountain, "TBD")
    # Preserve the existing UI's displayed-name grouping identity. Resort-backed
    # and manually-entered trips with the same displayed destination are one group.
    key = sa.literal("m:") + name
    return key, name


def _active_public():
    return sa.and_(
        SkiTrip.is_public.is_(True),
        sa.or_(SkiTrip.lifecycle_state.is_(None), SkiTrip.lifecycle_state == "active"),
    )


def _entry_union(viewer_id: int, today: date):
    """Return authorized scalar entries; deliberately does not hydrate Trips."""
    destination_key, destination = _destination_expressions()
    common = (
        SkiTrip.id.label("trip_id"),
        User.id.label("friend_id"),
        (sa.func.coalesce(User.first_name, "") + sa.literal(" ")
         + sa.func.coalesce(User.last_name, "")).label("friend_name"),
        destination_key.label("destination_key"),
        destination.label("destination"),
        sa.func.coalesce(SkiTrip.trip_status, "planning").label("status"),
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
            SkiTrip.end_date >= today,
            reciprocal_friend_predicate(viewer_id, SkiTrip.user_id),
        )
    )

    participant = SkiTripParticipant.__table__.alias("friend_going")
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
            SkiTrip.end_date >= today,
            participant.c.status == GuestStatus.GOING,
            participant.c.user_id != SkiTrip.user_id,
            effective_end >= today,
            reciprocal_friend_predicate(viewer_id, participant.c.user_id),
            # Preserve the pre-BL-159 rule: both people on the trip are direct
            # friends, rather than exposing an unrelated organizer's trip.
            reciprocal_friend_predicate(viewer_id, SkiTrip.user_id),
        )
    )
    return organizer.union_all(guest).subquery("friends_trip_entries")


def _deduped_entries(viewer_id: int, today: date):
    raw = _entry_union(viewer_id, today)
    ranked = sa.select(
        *raw.c,
        sa.func.row_number().over(
            partition_by=(raw.c.friend_id, raw.c.trip_id),
            order_by=(raw.c.source_rank, raw.c.participant_id),
        ).label("duplicate_rank"),
    ).subquery("friends_trip_dedup_rank")
    return sa.select(*[c for c in ranked.c if c.key != "duplicate_rank"]).where(
        ranked.c.duplicate_rank == 1
    ).subquery("friends_trip_deduped")


def _grouped_entries(viewer_id: int, today: date, destination_key=None):
    entries = _deduped_entries(viewer_id, today)
    query = sa.select(
        *entries.c,
        sa.func.count().over(
            partition_by=(entries.c.friend_id, entries.c.destination_key, entries.c.status)
        ).label("group_count"),
        sa.func.row_number().over(
            partition_by=(entries.c.friend_id, entries.c.destination_key, entries.c.status),
            order_by=(
                sa.case((entries.c.attendance_start.is_(None), 1), else_=0),
                entries.c.attendance_start,
                entries.c.trip_id,
            ),
        ).label("group_rank"),
        sa.func.min(entries.c.attendance_start).over(
            partition_by=(entries.c.friend_id, entries.c.destination_key, entries.c.status)
        ).label("group_start"),
        sa.func.max(entries.c.attendance_end).over(
            partition_by=(entries.c.friend_id, entries.c.destination_key, entries.c.status)
        ).label("group_end"),
    )
    if destination_key is not None:
        query = query.where(entries.c.destination_key == destination_key)
    return query.subquery("friends_trip_grouped")


def _cursor_payload(row, viewer_id, destination_key):
    return {
        "v": 1,
        "viewer": int(viewer_id),
        "destination": destination_key,
        "null": int(row.null_rank),
        "start": row.attendance_start.isoformat() if row.attendance_start else None,
        "friend": int(row.friend_id),
        "destination_sort": row.destination_key,
        "status": row.status,
        "trip": int(row.trip_id),
    }


def _load_cursor(value, viewer_id, destination_key):
    try:
        payload = _serializer(_CURSOR_SALT).loads(value)
        expected = {
            "v", "viewer", "destination", "null", "start", "friend",
            "destination_sort", "status", "trip",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError
        if payload["v"] != 1 or payload["viewer"] != int(viewer_id):
            raise ValueError
        if payload["destination"] != destination_key or payload["null"] not in (0, 1):
            raise ValueError
        start = date.fromisoformat(payload["start"]) if payload["start"] else None
        if (start is None) != (payload["null"] == 1):
            raise ValueError
        if type(payload["friend"]) is not int or type(payload["trip"]) is not int:
            raise ValueError
        return payload, start
    except (BadData, KeyError, TypeError, ValueError) as exc:
        raise FriendsTripsCursorError("Invalid Friends' Trips cursor.") from exc


def _after(values, columns):
    """Portable lexicographic keyset predicate with one nullable date."""
    null_rank, start, friend_id, destination_key, status, trip_id = columns
    p, cursor_start = values
    terms = [null_rank > p["null"]]
    prefix = null_rank == p["null"]
    if cursor_start is not None:
        terms.append(sa.and_(prefix, start > cursor_start))
        prefix = sa.and_(prefix, start == cursor_start)
    terms.extend([
        sa.and_(prefix, friend_id > p["friend"]),
        sa.and_(prefix, friend_id == p["friend"], destination_key > p["destination_sort"]),
        sa.and_(prefix, friend_id == p["friend"], destination_key == p["destination_sort"],
                status > p["status"]),
        sa.and_(prefix, friend_id == p["friend"], destination_key == p["destination_sort"],
                status == p["status"], trip_id > p["trip"]),
    ])
    return sa.or_(*terms)


def _display_units_query(viewer_id, today, destination_key=None, cursor_value=None):
    grouped = _grouped_entries(viewer_id, today, destination_key)
    null_rank = sa.case((grouped.c.attendance_start.is_(None), 1), else_=0).label(
        "null_rank"
    )
    query = sa.select(*grouped.c, null_rank).where(
        sa.or_(grouped.c.group_count < 3, grouped.c.group_rank == 1)
    )
    if cursor_value:
        cursor = _load_cursor(cursor_value, viewer_id, destination_key)
        query = query.where(_after(cursor, (
            null_rank, grouped.c.attendance_start, grouped.c.friend_id,
            grouped.c.destination_key, grouped.c.status, grouped.c.trip_id,
        )))
    return query.order_by(
        null_rank, grouped.c.attendance_start, grouped.c.friend_id,
        grouped.c.destination_key, grouped.c.status, grouped.c.trip_id,
    )


def _group_claims(token, viewer_id):
    try:
        claims = _serializer(_GROUP_SALT).loads(token)
        if (
            not isinstance(claims, dict)
            or set(claims) != {"v", "viewer", "friend", "destination", "status"}
            or claims["v"] != 1
            or claims["viewer"] != int(viewer_id)
            or type(claims["friend"]) is not int
            or not isinstance(claims["destination"], str)
            or not isinstance(claims["status"], str)
        ):
            raise ValueError
        return claims
    except (BadData, TypeError, ValueError) as exc:
        raise FriendsTripsGroupError("Invalid Friends' Trips group.") from exc


def _issue_group_token(viewer_id, friend_id, destination_key, status):
    return _serializer(_GROUP_SALT).dumps({
        "v": 1,
        "viewer": int(viewer_id),
        "friend": int(friend_id),
        "destination": destination_key,
        "status": status,
    })


def load_friends_trips_page(
    viewer_id: int,
    *,
    today: date | None = None,
    cursor_value: str | None = None,
    destination_key: str | None = None,
) -> FriendsTripsPage:
    today = today or date.today()
    candidates = db.session.execute(
        _display_units_query(
            viewer_id, today, destination_key, cursor_value
        ).limit(FRIENDS_TRIPS_PAGE_SIZE + 1)
    ).all()
    has_more = len(candidates) > FRIENDS_TRIPS_PAGE_SIZE
    candidates = candidates[:FRIENDS_TRIPS_PAGE_SIZE]
    trip_ids = [r.trip_id for r in candidates if r.group_count < 3]
    trips = (
        SkiTrip.query.options(joinedload(SkiTrip.resort))
        .filter(SkiTrip.id.in_(trip_ids)).all()
        if trip_ids else []
    )
    by_id = {trip.id: trip for trip in trips}
    rows = []
    for candidate in candidates:
        grouped = candidate.group_count >= 3
        rows.append(FriendsTripRow(
            friend_id=candidate.friend_id,
            friend_name=candidate.friend_name.strip() or "Friend",
            destination=candidate.destination,
            destination_key=candidate.destination_key,
            status=candidate.status,
            attendance_start_date=candidate.attendance_start,
            attendance_end_date=candidate.attendance_end,
            group_start_date=candidate.group_start,
            group_end_date=candidate.group_end,
            trip=None if grouped else by_id[candidate.trip_id],
            grouped_count=candidate.group_count if grouped else 1,
            group_token=(
                _issue_group_token(
                    viewer_id, candidate.friend_id, candidate.destination_key,
                    candidate.status,
                ) if grouped else None
            ),
        ))
    next_cursor = None
    if has_more:
        next_cursor = _serializer(_CURSOR_SALT).dumps(
            _cursor_payload(candidates[-1], viewer_id, destination_key)
        )
    return FriendsTripsPage(rows, has_more, next_cursor)


def load_friends_trips_destinations(
    viewer_id: int, *, today: date | None = None
) -> list[DestinationOption]:
    """Return the complete filter domain, independent of the current feed page."""
    options, _has_friends = load_friends_trips_context(
        viewer_id, today=today
    )
    return options


def load_friends_trips_context(
    viewer_id: int, *, today: date | None = None
) -> tuple[list[DestinationOption], bool]:
    """Return complete destination options and friendship presence in one query."""
    entries = _deduped_entries(viewer_id, today or date.today())
    options = sa.select(
        sa.literal("option").label("kind"),
        entries.c.destination_key,
        entries.c.destination,
    ).distinct()
    has_friend = sa.select(
        sa.literal("friend").label("kind"),
        sa.null().label("destination_key"),
        sa.null().label("destination"),
    ).where(
        sa.exists(
            sa.select(1).select_from(Friend).where(
                Friend.user_id == viewer_id,
                reciprocal_friend_predicate(viewer_id, Friend.friend_id),
            )
        )
    )
    rows = db.session.execute(
        sa.union_all(options, has_friend).order_by(
            sa.column("kind"), sa.column("destination"), sa.column("destination_key")
        )
    ).all()
    return (
        [
            DestinationOption(row.destination_key, row.destination)
            for row in rows
            if row.kind == "option"
        ],
        any(row.kind == "friend" for row in rows),
    )


def load_friends_trips_destination_options(
    viewer_id: int, *, today: date | None = None
) -> list[DestinationOption]:
    """Descriptive alias used by route/template integration."""
    return load_friends_trips_destinations(viewer_id, today=today)


def _detail_cursor(token, claims):
    if not token:
        return None
    try:
        value = _serializer(_CURSOR_SALT).loads(token)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "group", "null", "start", "trip"}
            or value["v"] != 1
            or value["group"] != claims
            or value["null"] not in (0, 1)
            or type(value["trip"]) is not int
        ):
            raise ValueError
        start = date.fromisoformat(value["start"]) if value["start"] else None
        if (start is None) != (value["null"] == 1):
            raise ValueError
        return value, start
    except (BadData, TypeError, ValueError) as exc:
        raise FriendsTripsCursorError("Invalid Friends' Trips detail cursor.") from exc


def _group_detail_query(viewer_id, today, claims, cursor_value=None):
    entries = _deduped_entries(viewer_id, today)
    scoped = sa.select(
        *entries.c,
        sa.case((entries.c.attendance_start.is_(None), 1), else_=0).label(
            "null_rank"
        ),
        sa.func.count().over().label("group_total"),
    ).where(
        entries.c.friend_id == claims["friend"],
        entries.c.destination_key == claims["destination"],
        entries.c.status == claims["status"],
    ).subquery("friends_trip_detail_scope")
    query = sa.select(*scoped.c)
    cursor = _detail_cursor(cursor_value, claims)
    if cursor:
        value, cursor_start = cursor
        after_date = (
            sa.false() if cursor_start is None
            else scoped.c.attendance_start > cursor_start
        )
        query = query.where(sa.or_(
            scoped.c.null_rank > value["null"],
            sa.and_(
                scoped.c.null_rank == value["null"],
                sa.or_(
                    after_date,
                    sa.and_(
                        scoped.c.attendance_start == cursor_start,
                        scoped.c.trip_id > value["trip"],
                    ),
                ),
            ),
        ))
    return query.order_by(
        scoped.c.null_rank, scoped.c.attendance_start, scoped.c.trip_id
    )


def load_friends_trips_group(
    viewer_id: int,
    group_token: str,
    *,
    today: date | None = None,
    cursor_value: str | None = None,
) -> FriendsTripsDetailPage:
    """Reauthorize and page one opaque group; never trust stored trip IDs."""
    claims = _group_claims(group_token, viewer_id)
    today = today or date.today()
    candidates = db.session.execute(
        _group_detail_query(
            viewer_id, today, claims, cursor_value
        ).limit(FRIENDS_TRIPS_DETAIL_PAGE_SIZE + 1)
    ).all()
    # The window count is evaluated before the page cursor, so every request
    # independently verifies current authorized group cardinality.
    if not candidates and cursor_value:
        entries = _deduped_entries(viewer_id, today)
        group_total = db.session.scalar(
            sa.select(sa.func.count()).select_from(entries).where(
                entries.c.friend_id == claims["friend"],
                entries.c.destination_key == claims["destination"],
                entries.c.status == claims["status"],
            )
        ) or 0
        if group_total >= 3:
            return FriendsTripsDetailPage([], False, None)
    if not candidates or candidates[0].group_total < 3:
        raise FriendsTripsGroupError("Friends' Trips group is no longer available.")
    has_more = len(candidates) > FRIENDS_TRIPS_DETAIL_PAGE_SIZE
    candidates = candidates[:FRIENDS_TRIPS_DETAIL_PAGE_SIZE]
    trips = (
        SkiTrip.query.options(joinedload(SkiTrip.resort))
        .filter(SkiTrip.id.in_([r.trip_id for r in candidates])).all()
        if candidates else []
    )
    by_id = {trip.id: trip for trip in trips}
    rows = [
        FriendsTripRow(
            friend_id=r.friend_id,
            friend_name=r.friend_name.strip() or "Friend",
            destination=r.destination,
            destination_key=r.destination_key,
            status=r.status,
            attendance_start_date=r.attendance_start,
            attendance_end_date=r.attendance_end,
            trip=by_id[r.trip_id],
        )
        for r in candidates
    ]
    next_cursor = None
    if has_more:
        last = candidates[-1]
        next_cursor = _serializer(_CURSOR_SALT).dumps({
            "v": 1,
            "group": claims,
            "null": last.null_rank,
            "start": last.attendance_start.isoformat() if last.attendance_start else None,
            "trip": last.trip_id,
        })
    return FriendsTripsDetailPage(rows, has_more, next_cursor)


def load_friends_trips_group_page(
    viewer_id: int,
    group_token: str,
    *,
    today: date | None = None,
    cursor_value: str | None = None,
) -> FriendsTripsDetailPage:
    """Descriptive alias for the grouped-detail paging operation."""
    return load_friends_trips_group(
        viewer_id,
        group_token,
        today=today,
        cursor_value=cursor_value,
    )