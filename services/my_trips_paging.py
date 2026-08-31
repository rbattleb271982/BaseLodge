"""Bounded, deterministic paging for the viewer's My Trips feeds."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import aliased, joinedload

from models import (
    GuestStatus,
    ParticipantRole,
    SkiTrip,
    SkiTripParticipant,
    db,
)
from services.trip_attendance import effective_attendance_date_expressions


MY_TRIPS_PAGE_SIZE = 20
_CURSOR_VERSION = 1
_VALID_SECTIONS = frozenset({"upcoming", "history"})


class MyTripsCursorError(ValueError):
    """Raised when a My Trips cursor is malformed or used for another feed."""


@dataclass(frozen=True)
class MyTripsCursor:
    section: str
    source_rank: int
    null_rank: int
    sort_date: date | None
    trip_id: int


@dataclass(frozen=True)
class MyTripRow:
    trip: SkiTrip
    attendance_start_date: date | None
    attendance_end_date: date | None
    source_rank: int
    participant_id: int | None
    participant_status: str | None
    active_guest_count: int

    @property
    def is_guest(self) -> bool:
        return self.source_rank == 1

    @property
    def mountain_name(self) -> str:
        return (
            self.trip.resort.name
            if self.trip.resort
            else (self.trip.mountain or "Mountain TBD")
        )

    @property
    def trip_location(self) -> str | None:
        if not self.trip.resort:
            return self.trip.state
        resort = self.trip.resort
        if resort.country_code and resort.country_code != "US":
            return resort.display_country_name
        return resort.state_code

    @property
    def trip_status(self) -> str:
        return self.trip.trip_status or "planning"

    @property
    def lifecycle_state(self) -> str:
        return self.trip.lifecycle_state or "active"


@dataclass(frozen=True)
class MyTripsPage:
    rows: list[MyTripRow]
    has_more: bool
    next_cursor: str | None


def encode_my_trips_cursor(cursor: MyTripsCursor) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "s": cursor.section,
        "r": cursor.source_rank,
        "n": cursor.null_rank,
        "d": cursor.sort_date.isoformat() if cursor.sort_date else None,
        "i": cursor.trip_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_my_trips_cursor(value: str, section: str) -> MyTripsCursor:
    if section not in _VALID_SECTIONS or not value or len(value) > 256:
        raise MyTripsCursorError("Invalid My Trips cursor.")
    try:
        padded = value + ("=" * (-len(value) % 4))
        payload = json.loads(
            base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MyTripsCursorError("Invalid My Trips cursor.") from exc

    if not isinstance(payload, dict) or set(payload) != {"v", "s", "r", "n", "d", "i"}:
        raise MyTripsCursorError("Invalid My Trips cursor.")
    if payload["v"] != _CURSOR_VERSION or payload["s"] != section:
        raise MyTripsCursorError("Invalid My Trips cursor.")
    if type(payload["r"]) is not int or payload["r"] not in (0, 1):
        raise MyTripsCursorError("Invalid My Trips cursor.")
    if type(payload["n"]) is not int or payload["n"] not in (0, 1):
        raise MyTripsCursorError("Invalid My Trips cursor.")
    if type(payload["i"]) is not int or payload["i"] <= 0:
        raise MyTripsCursorError("Invalid My Trips cursor.")
    if payload["n"] == 1:
        if payload["d"] is not None:
            raise MyTripsCursorError("Invalid My Trips cursor.")
        sort_date = None
    else:
        if not isinstance(payload["d"], str):
            raise MyTripsCursorError("Invalid My Trips cursor.")
        try:
            sort_date = date.fromisoformat(payload["d"])
        except ValueError as exc:
            raise MyTripsCursorError("Invalid My Trips cursor.") from exc

    return MyTripsCursor(
        section=section,
        source_rank=payload["r"],
        null_rank=payload["n"],
        sort_date=sort_date,
        trip_id=payload["i"],
    )


def _after_cursor_predicate(
    section,
    cursor,
    source_rank,
    null_rank,
    sort_date,
):
    if section == "upcoming":
        date_after = (
            sa.false()
            if cursor.sort_date is None
            else sort_date > cursor.sort_date
        )
        return sa.or_(
            null_rank > cursor.null_rank,
            sa.and_(
                null_rank == cursor.null_rank,
                sa.or_(
                    date_after,
                    sa.and_(
                        sort_date == cursor.sort_date,
                        sa.or_(
                            source_rank > cursor.source_rank,
                            sa.and_(
                                source_rank == cursor.source_rank,
                                SkiTrip.id > cursor.trip_id,
                            ),
                        ),
                    ),
                ),
            ),
        )

    # History intentionally keeps all owned rows before all guest rows.
    date_after = (
        sa.false()
        if cursor.sort_date is None
        else sort_date < cursor.sort_date
    )
    return sa.or_(
        source_rank > cursor.source_rank,
        sa.and_(
            source_rank == cursor.source_rank,
            sa.or_(
                null_rank > cursor.null_rank,
                sa.and_(
                    null_rank == cursor.null_rank,
                    sa.or_(
                        date_after,
                        sa.and_(
                            sort_date == cursor.sort_date,
                            SkiTrip.id > cursor.trip_id,
                        ),
                    ),
                ),
            ),
        ),
    )


def _candidate_query(viewer_id: int, section: str, today: date, cursor):
    participant = aliased(SkiTripParticipant, name="viewer_participation")
    source_rank = sa.case((SkiTrip.user_id == viewer_id, 0), else_=1).label(
        "source_rank"
    )
    effective_start, effective_end = effective_attendance_date_expressions(
        SkiTrip, participant
    )

    owner = SkiTrip.user_id == viewer_id
    active_guest = sa.and_(
        SkiTrip.user_id != viewer_id,
        participant.user_id == viewer_id,
        participant.status.in_((GuestStatus.GOING, GuestStatus.INTERESTED)),
    )
    authorized = sa.or_(owner, active_guest)

    if section == "upcoming":
        sort_date = effective_start.label("sort_date")
        section_filter = sa.and_(
            sa.or_(
                SkiTrip.lifecycle_state.is_(None),
                SkiTrip.lifecycle_state == "active",
            ),
            SkiTrip.end_date >= today,
            sa.or_(owner, sa.and_(active_guest, effective_end >= today)),
        )
    else:
        sort_date = SkiTrip.start_date.label("sort_date")
        section_filter = sa.or_(
            SkiTrip.end_date < today,
            SkiTrip.lifecycle_state.in_(("completed", "cancelled")),
        )

    null_rank = sa.case((sort_date.is_(None), 1), else_=0).label("null_rank")
    query = (
        db.session.query(
            SkiTrip.id.label("trip_id"),
            participant.id.label("participant_id"),
            participant.status.label("participant_status"),
            effective_start.label("attendance_start_date"),
            effective_end.label("attendance_end_date"),
            source_rank,
            null_rank,
            sort_date,
        )
        .outerjoin(
            participant,
            sa.and_(
                participant.trip_id == SkiTrip.id,
                participant.user_id == viewer_id,
            ),
        )
        .filter(authorized, section_filter)
    )

    if cursor is not None:
        query = query.filter(
            _after_cursor_predicate(
                section, cursor, source_rank, null_rank, sort_date
            )
        )

    if section == "upcoming":
        query = query.order_by(
            null_rank.asc(),
            sort_date.asc(),
            source_rank.asc(),
            SkiTrip.id.asc(),
        )
    else:
        query = query.order_by(
            source_rank.asc(),
            null_rank.asc(),
            sort_date.desc(),
            SkiTrip.id.asc(),
        )
    return query


def load_my_trips_page(
    viewer_id: int,
    section: str,
    *,
    today: date | None = None,
    cursor_value: str | None = None,
) -> MyTripsPage:
    """Load one authorized viewer-feed page without hydrating the lookahead row."""
    if section not in _VALID_SECTIONS:
        raise ValueError("Unknown My Trips section.")
    today = today or date.today()
    cursor = (
        decode_my_trips_cursor(cursor_value, section) if cursor_value else None
    )
    candidates = (
        _candidate_query(viewer_id, section, today, cursor)
        .limit(MY_TRIPS_PAGE_SIZE + 1)
        .all()
    )
    has_more = len(candidates) > MY_TRIPS_PAGE_SIZE
    page_candidates = candidates[:MY_TRIPS_PAGE_SIZE]
    if not page_candidates:
        return MyTripsPage(rows=[], has_more=False, next_cursor=None)

    trip_ids = [candidate.trip_id for candidate in page_candidates]
    trips = (
        SkiTrip.query.options(joinedload(SkiTrip.resort))
        .filter(SkiTrip.id.in_(trip_ids))
        .all()
    )
    trips_by_id = {trip.id: trip for trip in trips}

    active_guest_counts = {}
    if section == "upcoming":
        active_guest_counts = {
            trip_id: count
            for trip_id, count in (
                db.session.query(
                    SkiTripParticipant.trip_id,
                    sa.func.count(SkiTripParticipant.id),
                )
                .filter(
                    SkiTripParticipant.trip_id.in_(trip_ids),
                    SkiTripParticipant.status.in_(
                        (GuestStatus.GOING, GuestStatus.INTERESTED)
                    ),
                    SkiTripParticipant.role == ParticipantRole.GUEST,
                )
                .group_by(SkiTripParticipant.trip_id)
                .all()
            )
        }

    rows = []
    for candidate in page_candidates:
        trip = trips_by_id[candidate.trip_id]
        if section == "upcoming":
            trip.attendance_start_date = candidate.attendance_start_date
            trip.attendance_end_date = candidate.attendance_end_date
        status = candidate.participant_status
        rows.append(
            MyTripRow(
                trip=trip,
                attendance_start_date=candidate.attendance_start_date,
                attendance_end_date=candidate.attendance_end_date,
                source_rank=candidate.source_rank,
                participant_id=candidate.participant_id,
                participant_status=getattr(status, "value", status),
                active_guest_count=active_guest_counts.get(candidate.trip_id, 0),
            )
        )

    next_cursor = None
    if has_more:
        last = page_candidates[-1]
        next_cursor = encode_my_trips_cursor(
            MyTripsCursor(
                section=section,
                source_rank=last.source_rank,
                null_rank=last.null_rank,
                sort_date=last.sort_date,
                trip_id=last.trip_id,
            )
        )
    return MyTripsPage(rows=rows, has_more=has_more, next_cursor=next_cursor)