"""Bounded, deterministic retrieval for the Friends directory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import sqlalchemy as sa
from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from models import Friend, GuestStatus, SkiTrip, SkiTripParticipant, User, db


FRIENDS_PAGE_SIZE = 20
_CURSOR_VERSION = 1
_CURSOR_TYPE = "friends-directory"
_CURSOR_MAX_LENGTH = 768
_HEX = frozenset("0123456789abcdef")


class FriendsCursorError(ValueError):
    """Raised when a cursor is malformed or belongs to another result set."""


@dataclass(frozen=True)
class FriendsCursor:
    viewer_id: int
    first_name: str
    last_name: str
    friend_row_id: int
    scope: str

    @property
    def friend_id(self) -> int:
        """Backward-friendly name for the directed Friend row tiebreaker."""
        return self.friend_row_id


@dataclass(frozen=True)
class FriendDirectoryRow:
    """One template-facing friend, with only bounded supporting state."""

    user: User
    friendship: Friend
    upcoming_trip_count: int

    def __getattr__(self, name):
        # Existing templates can treat a row like the User they previously received.
        return getattr(self.user, name)

    @property
    def _trip_invites_allowed(self) -> bool:
        return bool(self.friendship.trip_invites_allowed)

    @property
    def _is_new_friend(self) -> bool:
        return not self.friendship.has_viewed_profile

    @property
    def _upcoming_trip_count(self) -> int:
        return self.upcoming_trip_count

    @property
    def _trip_count(self) -> int:
        return self.upcoming_trip_count

    @property
    def _has_upcoming_trip(self) -> bool:
        return self.upcoming_trip_count > 0


@dataclass(frozen=True)
class FriendAlphaGroup:
    letter: str
    friends: list[FriendDirectoryRow]

    def __getitem__(self, key):
        # Supports the dictionary access pattern as well as Jinja attribute access.
        if key in ("letter", "friends"):
            return getattr(self, key)
        raise KeyError(key)


@dataclass(frozen=True)
class FriendsPage:
    rows: list[FriendDirectoryRow]
    has_more: bool
    next_cursor: str | None
    authorized_count: int
    matching_count: int

    @property
    def friend_count(self) -> int:
        return self.authorized_count

    @property
    def total_count(self) -> int:
        return self.authorized_count

    @property
    def alpha_groups(self) -> list[FriendAlphaGroup]:
        groups: list[FriendAlphaGroup] = []
        for row in self.rows:
            letter = (row.first_name or "?")[0].upper()
            if not groups or groups[-1].letter != letter:
                groups.append(FriendAlphaGroup(letter=letter, friends=[]))
            groups[-1].friends.append(row)
        return groups


def _normalize_values(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = values.split(",")
    return tuple(sorted({
        value.strip().lower()
        for value in values
        if isinstance(value, str) and value.strip()
    }))


def _normalized_filters(*, q="", passes=None, riders=None, skills=None):
    return (
        (q or "").strip().lower(),
        _normalize_values(passes),
        _normalize_values(riders),
        _normalize_values(skills),
    )


def _filter_scope(q, passes, riders, skills) -> str:
    raw = json.dumps(
        {"q": q, "pass": passes, "rider": riders, "skill": skills},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def encode_friends_cursor(cursor: FriendsCursor) -> str:
    if (
        not isinstance(cursor, FriendsCursor)
        or type(cursor.viewer_id) is not int
        or cursor.viewer_id <= 0
        or not isinstance(cursor.first_name, str)
        or not isinstance(cursor.last_name, str)
        or type(cursor.friend_row_id) is not int
        or cursor.friend_row_id <= 0
        or not isinstance(cursor.scope, str)
        or len(cursor.scope) != 24
        or any(character not in _HEX for character in cursor.scope)
    ):
        raise FriendsCursorError("Invalid Friends cursor.")
    payload = {
        "v": _CURSOR_VERSION,
        "t": _CURSOR_TYPE,
        "u": cursor.viewer_id,
        "f": cursor.first_name,
        "l": cursor.last_name,
        "i": cursor.friend_row_id,
        "s": cursor.scope,
    }
    return URLSafeSerializer(
        current_app.config["SECRET_KEY"],
        salt="friends-directory-page",
    ).dumps(payload)


def decode_friends_cursor(
    value: str,
    *,
    viewer_id: int | None = None,
    scope: str | None = None,
) -> FriendsCursor:
    if not isinstance(value, str) or not value or len(value) > _CURSOR_MAX_LENGTH:
        raise FriendsCursorError("Invalid Friends cursor.")
    try:
        payload = URLSafeSerializer(
            current_app.config["SECRET_KEY"],
            salt="friends-directory-page",
        ).loads(value)
    except (BadData, ValueError, TypeError) as exc:
        raise FriendsCursorError("Invalid Friends cursor.") from exc
    expected = {"v", "t", "u", "f", "l", "i", "s"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise FriendsCursorError("Invalid Friends cursor.")
    if type(payload["v"]) is not int or payload["v"] != _CURSOR_VERSION:
        raise FriendsCursorError("Invalid Friends cursor.")
    if payload["t"] != _CURSOR_TYPE:
        raise FriendsCursorError("Invalid Friends cursor.")
    if type(payload["u"]) is not int or payload["u"] <= 0:
        raise FriendsCursorError("Invalid Friends cursor.")
    if viewer_id is not None and payload["u"] != int(viewer_id):
        raise FriendsCursorError("Invalid Friends cursor.")
    if not isinstance(payload["f"], str) or not isinstance(payload["l"], str):
        raise FriendsCursorError("Invalid Friends cursor.")
    if type(payload["i"]) is not int or payload["i"] <= 0:
        raise FriendsCursorError("Invalid Friends cursor.")
    if (
        not isinstance(payload["s"], str)
        or len(payload["s"]) != 24
        or any(character not in _HEX for character in payload["s"])
    ):
        raise FriendsCursorError("Invalid Friends cursor.")
    if scope is not None and payload["s"] != scope:
        raise FriendsCursorError("Invalid Friends cursor.")
    return FriendsCursor(
        viewer_id=payload["u"],
        first_name=payload["f"],
        last_name=payload["l"],
        friend_row_id=payload["i"],
        scope=payload["s"],
    )


def _matching_predicate(q, passes, riders, skills):
    predicates = []
    if q:
        searchable = sa.func.lower(
            sa.func.coalesce(User.first_name, "")
            + sa.literal(" ")
            + sa.func.coalesce(User.last_name, "")
            + sa.literal(" ")
            + sa.func.coalesce(User.pass_type, "")
            + sa.literal(" ")
            + sa.func.coalesce(User.skill_level, "")
        )
        # Match String.indexOf semantics, including literal % and _ characters.
        predicates.append(searchable.contains(q, autoescape=True))
    if passes:
        # Comma-delimited exact token matching, retaining the template's OR rule.
        pass_tokens = (
            sa.literal(",")
            + sa.func.replace(sa.func.lower(sa.func.coalesce(User.pass_type, "")), " ", "")
            + sa.literal(",")
        )
        predicates.append(sa.or_(*[
            pass_tokens.contains(
                f",{value.replace(' ', '')},",
                autoescape=True,
            )
            for value in passes
        ]))
    if riders:
        # JSON string matching is portable across SQLite and PostgreSQL and exact
        # for canonical rider values (rather than substring matching a rider).
        rider_json = sa.func.lower(sa.cast(User.rider_types, sa.Text))
        predicates.append(sa.or_(*[
            rider_json.contains(f'"{value}"', autoescape=True)
            for value in riders
        ]))
    if skills:
        predicates.append(
            sa.func.lower(sa.func.coalesce(User.skill_level, "")).in_(skills)
        )
    return sa.and_(*predicates) if predicates else sa.true()


def build_friends_candidate_query(
    viewer_id: int,
    *,
    q: str = "",
    passes: Iterable[str] | str | None = None,
    riders: Iterable[str] | str | None = None,
    skills: Iterable[str] | str | None = None,
    cursor: FriendsCursor | None = None,
):
    """Build the scalar-only reciprocal friend candidate query."""
    q, passes, riders, skills = _normalized_filters(
        q=q, passes=passes, riders=riders, skills=skills
    )
    reverse = Friend.__table__.alias("reverse_friend")
    first_key = sa.func.lower(sa.func.coalesce(User.first_name, "")).label(
        "first_name_key"
    )
    last_key = sa.func.lower(sa.func.coalesce(User.last_name, "")).label(
        "last_name_key"
    )
    query = (
        db.session.query(
            User.id.label("user_id"),
            Friend.id.label("friend_row_id"),
            first_key,
            last_key,
        )
        .select_from(Friend)
        .join(User, User.id == Friend.friend_id)
        .join(
            reverse,
            sa.and_(
                reverse.c.user_id == Friend.friend_id,
                reverse.c.friend_id == Friend.user_id,
            ),
        )
        .filter(
            Friend.user_id == viewer_id,
            Friend.friend_id != viewer_id,
            _matching_predicate(q, passes, riders, skills),
        )
    )
    if cursor is not None:
        query = query.filter(sa.or_(
            first_key > cursor.first_name,
            sa.and_(
                first_key == cursor.first_name,
                sa.or_(
                    last_key > cursor.last_name,
                    sa.and_(
                        last_key == cursor.last_name,
                        Friend.id > cursor.friend_row_id,
                    ),
                ),
            ),
        ))
    return query.order_by(first_key.asc(), last_key.asc(), Friend.id.asc())


def _directory_counts(viewer_id, matching):
    reverse = Friend.__table__.alias("count_reverse_friend")
    authorized = (
        db.session.query(
            sa.func.count(Friend.id),
            sa.func.sum(sa.case((matching, 1), else_=0)),
        )
        .select_from(Friend)
        .join(User, User.id == Friend.friend_id)
        .join(
            reverse,
            sa.and_(
                reverse.c.user_id == Friend.friend_id,
                reverse.c.friend_id == Friend.user_id,
            ),
        )
        .filter(Friend.user_id == viewer_id, Friend.friend_id != viewer_id)
    )
    authorized_count, matching_count = authorized.one()
    return int(authorized_count or 0), int(matching_count or 0)


def _upcoming_trip_counts_query(friend_ids, today):
    if not friend_ids:
        return None
    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__
    live_public = sa.and_(
        trip.c.is_public.is_(True),
        sa.or_(trip.c.lifecycle_state.is_(None), trip.c.lifecycle_state == "active"),
        trip.c.end_date >= today,
    )
    owned = sa.select(
        trip.c.user_id.label("friend_id"),
        trip.c.id.label("trip_id"),
    ).where(trip.c.user_id.in_(friend_ids), live_public)
    participating = (
        sa.select(
            participant.c.user_id.label("friend_id"),
            participant.c.trip_id.label("trip_id"),
        )
        .select_from(participant.join(trip, trip.c.id == participant.c.trip_id))
        .where(
            participant.c.user_id.in_(friend_ids),
            participant.c.status.in_((GuestStatus.GOING, GuestStatus.INTERESTED)),
            live_public,
        )
    )
    visible = owned.union(participating).subquery("visible_friend_trips")
    return (
        sa.select(
            visible.c.friend_id,
            sa.func.count(visible.c.trip_id).label("trip_count"),
        )
        .group_by(visible.c.friend_id)
        .subquery("visible_friend_trip_counts")
    )


def load_friends_page(
    viewer_id: int,
    *,
    q: str = "",
    passes: Iterable[str] | str | None = None,
    riders: Iterable[str] | str | None = None,
    skills: Iterable[str] | str | None = None,
    cursor_value: str | None = None,
    today: date | None = None,
) -> FriendsPage:
    """Load one friend page plus complete counts and bounded scalar aggregates."""
    if type(viewer_id) is not int or viewer_id <= 0:
        raise ValueError("viewer_id must be a positive integer.")
    today = today or date.today()
    q, passes, riders, skills = _normalized_filters(
        q=q, passes=passes, riders=riders, skills=skills
    )
    scope = _filter_scope(q, passes, riders, skills)
    cursor = (
        decode_friends_cursor(
            cursor_value, viewer_id=viewer_id, scope=scope
        ) if cursor_value else None
    )
    matching = _matching_predicate(q, passes, riders, skills)
    authorized_count, matching_count = _directory_counts(viewer_id, matching)
    candidates = (
        build_friends_candidate_query(
            viewer_id,
            q=q,
            passes=passes,
            riders=riders,
            skills=skills,
            cursor=cursor,
        )
        .limit(FRIENDS_PAGE_SIZE + 1)
        .all()
    )
    has_more = len(candidates) > FRIENDS_PAGE_SIZE
    page_candidates = candidates[:FRIENDS_PAGE_SIZE]
    if not page_candidates:
        return FriendsPage(
            rows=[],
            has_more=False,
            next_cursor=None,
            authorized_count=authorized_count,
            matching_count=matching_count,
        )

    user_ids = [candidate.user_id for candidate in page_candidates]
    friend_row_ids = [candidate.friend_row_id for candidate in page_candidates]
    trip_counts_query = _upcoming_trip_counts_query(user_ids, today)
    hydrated_query = (
        db.session.query(
            User,
            Friend,
            sa.func.coalesce(trip_counts_query.c.trip_count, 0),
        )
        .join(Friend, Friend.friend_id == User.id)
        .outerjoin(
            trip_counts_query,
            trip_counts_query.c.friend_id == User.id,
        )
        .filter(Friend.id.in_(friend_row_ids))
    )
    hydrated = hydrated_query.all()
    users_by_id = {user.id: user for user, _friendship, _count in hydrated}
    friendships_by_id = {
        friendship.id: friendship
        for _user, friendship, _count in hydrated
    }
    trip_counts = {
        user.id: int(count)
        for user, _friendship, count in hydrated
    }
    rows = [
        FriendDirectoryRow(
            user=users_by_id[candidate.user_id],
            friendship=friendships_by_id[candidate.friend_row_id],
            upcoming_trip_count=trip_counts.get(candidate.user_id, 0),
        )
        for candidate in page_candidates
    ]
    next_cursor = None
    if has_more:
        last = page_candidates[-1]
        next_cursor = encode_friends_cursor(FriendsCursor(
            viewer_id=viewer_id,
            first_name=last.first_name_key,
            last_name=last.last_name_key,
            friend_row_id=last.friend_row_id,
            scope=scope,
        ))
    return FriendsPage(
        rows=rows,
        has_more=has_more,
        next_cursor=next_cursor,
        authorized_count=authorized_count,
        matching_count=matching_count,
    )