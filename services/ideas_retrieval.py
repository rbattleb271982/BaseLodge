"""Exact, bounded retrieval for the Home Ideas section.

The statement built here intentionally performs source expansion, suppression,
concept reduction, dismissal, ranking, and the render limit in the database.
Only the five final presentation rows cross the Python/SQL boundary.
"""

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from models import (
    DismissedInsightCard,
    Friend,
    GuestStatus,
    Resort,
    SkiTrip,
    SkiTripParticipant,
    User,
    UserAvailability,
    db,
)
from services.ideas_engine import _fmt_date_range_short, _fmt_social_names
from services.visibility import reciprocal_friend_predicate
from utils.formatting import format_name


HOME_IDEAS_RENDER_CAP = 5
_FIELD_SEPARATOR = "\x1f"


class _JsonValues(sa.sql.expression.FromClause):
    """A named one-column JSON-array relation on both supported databases."""

    inherit_cache = False
    named_with_column = True

    def __init__(self, expression, name):
        super().__init__()
        self.expression = expression
        self.name = name
        self._setup_collections()
        self._columns.add(
            sa.sql.elements.ColumnClause("value", _selectable=self)
        )


@compiles(_JsonValues, "sqlite")
def _compile_json_values_sqlite(element, compiler, **kw):
    value = compiler.process(element.expression, **kw)
    guarded = (
        f"CASE WHEN json_valid({value}) "
        f"THEN CASE WHEN json_type({value}) = 'array' "
        f"THEN {value} ELSE '[]' END "
        f"ELSE '[]' END"
    )
    return f"json_each({guarded}) AS {element.name}"


@compiles(_JsonValues, "postgresql")
def _compile_json_values_postgresql(element, compiler, **kw):
    value = compiler.process(element.expression, **kw)
    typed = f"CAST({value} AS JSONB)"
    guarded = (
        f"CASE WHEN jsonb_typeof({typed}) = 'array' "
        f"THEN {typed} ELSE CAST('[]' AS JSONB) END"
    )
    return (
        f"jsonb_array_elements_text({guarded}) "
        f"AS {element.name}(value)"
    )


class _safe_date(FunctionElement):
    """Parse legacy YYYY-MM-DD values without allowing bad JSON to abort SQL."""

    inherit_cache = True
    type = sa.Date()
    name = "ideas_safe_date"


@compiles(_safe_date, "sqlite")
def _compile_safe_date_sqlite(element, compiler, **kw):
    value = compiler.process(list(element.clauses)[0], **kw)
    return f"date(CASE WHEN {value} GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' THEN {value} END)"


@compiles(_safe_date, "postgresql")
def _compile_safe_date_postgresql(element, compiler, **kw):
    value = compiler.process(list(element.clauses)[0], **kw)
    text = f"CAST({value} AS TEXT)"
    year = f"CAST(substring({text} FROM 1 FOR 4) AS INTEGER)"
    month = f"CAST(substring({text} FROM 6 FOR 2) AS INTEGER)"
    day = f"CAST(substring({text} FROM 9 FOR 2) AS INTEGER)"
    leap_year = (
        f"(({year} %% 400 = 0) OR "
        f"({year} %% 4 = 0 AND {year} %% 100 <> 0))"
    )
    days_in_month = (
        f"CASE WHEN {month} = 2 "
        f"THEN CASE WHEN {leap_year} THEN 29 ELSE 28 END "
        f"WHEN {month} IN (4, 6, 9, 11) THEN 30 ELSE 31 END"
    )
    return (
        f"CASE WHEN {text} ~ "
        f"'^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' "
        f"THEN CASE WHEN {year} BETWEEN 1 AND 9999 "
        f"AND {month} BETWEEN 1 AND 12 "
        f"AND {day} BETWEEN 1 AND {days_in_month} "
        f"THEN CAST({text} AS DATE) END END"
    )


class _safe_int(FunctionElement):
    inherit_cache = True
    type = sa.Integer()
    name = "ideas_safe_int"


@compiles(_safe_int, "sqlite")
def _compile_safe_int_sqlite(element, compiler, **kw):
    value = compiler.process(list(element.clauses)[0], **kw)
    return (
        f"CASE WHEN CAST({value} AS TEXT) <> '' "
        f"AND CAST({value} AS TEXT) NOT GLOB '*[^0-9]*' "
        f"AND length(CAST({value} AS TEXT)) <= 9 "
        f"THEN CAST({value} AS INTEGER) END"
    )


@compiles(_safe_int, "postgresql")
def _compile_safe_int_postgresql(element, compiler, **kw):
    value = compiler.process(list(element.clauses)[0], **kw)
    return (
        f"CASE WHEN CAST({value} AS TEXT) ~ '^[0-9]+$' "
        f"AND length(CAST({value} AS TEXT)) <= 9 "
        f"THEN CAST({value} AS INTEGER) END"
    )


class _day_gap(FunctionElement):
    inherit_cache = True
    type = sa.Integer()
    name = "ideas_day_gap"


@compiles(_day_gap, "sqlite")
def _compile_day_gap_sqlite(element, compiler, **kw):
    later, earlier = list(element.clauses)
    return (
        f"CAST(julianday({compiler.process(later, **kw)}) - "
        f"julianday({compiler.process(earlier, **kw)}) AS INTEGER)"
    )


@compiles(_day_gap, "postgresql")
def _compile_day_gap_postgresql(element, compiler, **kw):
    later, earlier = list(element.clauses)
    return (
        f"({compiler.process(later, **kw)} - "
        f"{compiler.process(earlier, **kw)})"
    )


class _ordered_concat(FunctionElement):
    inherit_cache = True
    type = sa.String()
    name = "ideas_ordered_concat"


@compiles(_ordered_concat, "sqlite")
def _compile_concat_sqlite(element, compiler, **kw):
    value, separator, order_key = list(element.clauses)
    return (
        f"group_concat({compiler.process(value, **kw)}, "
        f"{compiler.process(separator, **kw)} ORDER BY "
        f"{compiler.process(order_key, **kw)})"
    )


@compiles(_ordered_concat, "postgresql")
def _compile_concat_postgresql(element, compiler, **kw):
    value, separator, order_key = list(element.clauses)
    rendered = compiler.process(value, **kw)
    return (
        f"string_agg(CAST({rendered} AS TEXT), "
        f"{compiler.process(separator, **kw)} ORDER BY "
        f"{compiler.process(order_key, **kw)})"
    )


@dataclass(frozen=True)
class _ResortCard:
    id: int
    name: str
    slug: str
    state_code: str | None


def _json_elements(column, name):
    return _JsonValues(column, name)


def _available_days(*, user_id, today):
    """Return the normalized-first availability CTE for viewer and friends."""
    availability = UserAvailability.__table__
    user = User.__table__
    friendship = Friend.__table__

    relevant_users = sa.union(
        sa.select(sa.literal(user_id).label("user_id")),
        sa.select(friendship.c.friend_id).where(
            friendship.c.user_id == user_id,
            reciprocal_friend_predicate(user_id, friendship.c.friend_id),
        ),
    ).cte("ideas_relevant_users")

    normalized = (
        sa.select(
            availability.c.user_id.label("user_id"),
            availability.c.date.label("available_date"),
        )
        .where(
            availability.c.user_id.in_(sa.select(relevant_users.c.user_id)),
            availability.c.is_available.is_(True),
            availability.c.date >= today,
        )
    )

    legacy_values = _json_elements(user.c.open_dates, "legacy_open_date")
    has_normalized = sa.exists(
        sa.select(sa.literal(1)).where(
            availability.c.user_id == user.c.id,
            availability.c.is_available.is_(True),
        )
    )
    legacy = (
        sa.select(
            user.c.id.label("user_id"),
            _safe_date(legacy_values.c.value).label("available_date"),
        )
        .select_from(user, relevant_users, legacy_values)
        .where(
            relevant_users.c.user_id == user.c.id,
            ~has_normalized,
            sa.func.length(sa.cast(legacy_values.c.value, sa.String())) == 10,
            _safe_date(legacy_values.c.value) >= today,
        )
    )
    return sa.union(normalized, legacy).cte("ideas_available_days")


def _wishlist_pairs(*, user_id):
    user = User.__table__
    friendship = Friend.__table__
    viewer = user.alias("ideas_wishlist_viewer")
    friend_user = user.alias("ideas_wishlist_friend")
    viewer_values = _json_elements(
        viewer.c.wish_list_resorts, "ideas_viewer_wishlist"
    )
    friend_values = _json_elements(
        friend_user.c.wish_list_resorts, "ideas_friend_wishlist"
    )
    return (
        sa.select(
            friendship.c.friend_id.label("friend_id"),
            _safe_int(viewer_values.c.value).label("resort_id"),
        )
        .select_from(
            friendship,
            viewer,
            friend_user,
            viewer_values,
            friend_values,
        )
        .where(
            friendship.c.user_id == user_id,
            reciprocal_friend_predicate(user_id, friendship.c.friend_id),
            viewer.c.id == friendship.c.user_id,
            friend_user.c.id == friendship.c.friend_id,
            _safe_int(friend_values.c.value)
            == _safe_int(viewer_values.c.value),
            _safe_int(viewer_values.c.value).is_not(None),
        )
        .distinct()
        .cte("ideas_wishlist_pairs")
    )


def _trip_candidates(*, user_id, today, available_days):
    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__
    friendship = Friend.__table__
    friend_user = User.__table__.alias("ideas_trip_friend")

    owner_rows = (
        sa.select(
            trip.c.id.label("trip_id"),
            trip.c.resort_id,
            trip.c.start_date.label("start_date"),
            trip.c.end_date.label("end_date"),
            trip.c.user_id.label("friend_id"),
            sa.func.coalesce(trip.c.trip_status, "planning").label("status"),
        )
        .select_from(
            trip.join(
                friendship,
                sa.and_(
                    friendship.c.user_id == user_id,
                    friendship.c.friend_id == trip.c.user_id,
                ),
            )
        )
        .where(
            sa.or_(
                trip.c.lifecycle_state.is_(None),
                trip.c.lifecycle_state == "active",
            ),
            trip.c.end_date >= today,
            trip.c.is_public.is_(True),
            trip.c.resort_id.is_not(None),
            reciprocal_friend_predicate(user_id, trip.c.user_id),
        )
    )
    going_override = sa.and_(
        participant.c.status == GuestStatus.GOING,
        participant.c.start_date.is_not(None),
        participant.c.end_date.is_not(None),
    )
    effective_start = sa.case(
        (going_override, participant.c.start_date), else_=trip.c.start_date
    )
    effective_end = sa.case(
        (going_override, participant.c.end_date), else_=trip.c.end_date
    )
    participant_rows = (
        sa.select(
            trip.c.id.label("trip_id"),
            trip.c.resort_id,
            effective_start.label("start_date"),
            effective_end.label("end_date"),
            participant.c.user_id.label("friend_id"),
            sa.case(
                (participant.c.status == GuestStatus.GOING, "going"),
                else_="planning",
            ).label("status"),
        )
        .select_from(
            trip.join(participant, participant.c.trip_id == trip.c.id).join(
                friendship,
                sa.and_(
                    friendship.c.user_id == user_id,
                    friendship.c.friend_id == participant.c.user_id,
                ),
            )
        )
        .where(
            participant.c.status.in_(
                (GuestStatus.INTERESTED, GuestStatus.GOING)
            ),
            sa.or_(
                trip.c.lifecycle_state.is_(None),
                trip.c.lifecycle_state == "active",
            ),
            trip.c.user_id != participant.c.user_id,
            trip.c.end_date >= today,
            effective_end >= today,
            trip.c.is_public.is_(True),
            trip.c.resort_id.is_not(None),
            reciprocal_friend_predicate(user_id, participant.c.user_id),
        )
    )
    occurrences = sa.union_all(owner_rows, participant_rows).cte(
        "ideas_trip_occurrences"
    )
    named = (
        sa.select(
            occurrences,
            friend_user.c.first_name.label("first_name"),
        )
        .select_from(
            occurrences.join(
                friend_user, friend_user.c.id == occurrences.c.friend_id
            )
        )
        .order_by(occurrences.c.friend_id, occurrences.c.trip_id)
        .cte("ideas_named_trip_occurrences")
    )
    trip_people = (
        sa.select(
            named.c.resort_id,
            named.c.start_date,
            named.c.end_date,
            named.c.friend_id,
        )
        .distinct()
        .cte("ideas_distinct_trip_people")
    )
    trip_id_lists = (
        sa.select(
            trip_people.c.resort_id,
            trip_people.c.start_date,
            trip_people.c.end_date,
            _ordered_concat(
                trip_people.c.friend_id, ",", trip_people.c.friend_id
            ).label("friend_ids"),
        )
        .group_by(
            trip_people.c.resort_id,
            trip_people.c.start_date,
            trip_people.c.end_date,
        )
        .cte("ideas_trip_friend_ids")
    )
    user_days = available_days.alias("ideas_trip_user_days")
    has_overlap = sa.exists(
        sa.select(sa.literal(1)).where(
            user_days.c.user_id == user_id,
            user_days.c.available_date.between(
                named.c.start_date, named.c.end_date
            ),
        )
    )
    return (
        sa.select(
            named.c.resort_id,
            named.c.start_date,
            named.c.end_date,
            sa.func.count().label("friend_count"),
            sa.func.sum(sa.case((named.c.status == "going", 1), else_=0)).label(
                "going_count"
            ),
            sa.func.sum(
                sa.case((named.c.status != "going", 1), else_=0)
            ).label("considering_count"),
            sa.func.max(trip_id_lists.c.friend_ids).label("friend_ids"),
            _ordered_concat(
                sa.case(
                    (named.c.status == "going", named.c.first_name), else_=None
                ),
                _FIELD_SEPARATOR,
                named.c.friend_id,
            ).label("going_names"),
            _ordered_concat(
                sa.case(
                    (named.c.status != "going", named.c.first_name), else_=None
                ),
                _FIELD_SEPARATOR,
                named.c.friend_id,
            ).label("considering_names"),
            sa.func.min(named.c.trip_id).label("source_id"),
            sa.case((has_overlap, 1), else_=0).label("has_user_date_overlap"),
        )
        .select_from(
            named.join(
                trip_id_lists,
                sa.and_(
                    trip_id_lists.c.resort_id == named.c.resort_id,
                    trip_id_lists.c.start_date == named.c.start_date,
                    trip_id_lists.c.end_date == named.c.end_date,
                ),
            )
        )
        .group_by(named.c.resort_id, named.c.start_date, named.c.end_date)
        .cte("ideas_trip_candidates")
    )


def _availability_candidates(*, user_id, available_days, wishlist_pairs):
    friendship = Friend.__table__
    friend_user = User.__table__.alias("ideas_overlap_friend")
    mine = available_days.alias("ideas_my_days")
    theirs = available_days.alias("ideas_friend_days")
    matches = (
        sa.select(
            mine.c.available_date.label("match_date"),
            friendship.c.friend_id,
            friend_user.c.first_name,
            friend_user.c.last_name,
        )
        .select_from(
            mine.join(
                friendship,
                friendship.c.user_id == user_id,
            )
            .join(
                theirs,
                sa.and_(
                    theirs.c.user_id == friendship.c.friend_id,
                    theirs.c.available_date == mine.c.available_date,
                ),
            )
            .join(friend_user, friend_user.c.id == friendship.c.friend_id)
        )
        .where(
            mine.c.user_id == user_id,
            reciprocal_friend_predicate(user_id, friendship.c.friend_id),
        )
        .distinct()
        .cte("ideas_availability_matches")
    )
    dates = sa.select(matches.c.match_date).distinct().cte(
        "ideas_overlap_dates"
    )
    lagged = sa.select(
        dates.c.match_date,
        sa.func.lag(dates.c.match_date)
        .over(order_by=dates.c.match_date)
        .label("previous_date"),
    ).cte("ideas_lagged_overlap_dates")
    marked = sa.select(
        lagged.c.match_date,
        sa.case(
            (
                sa.or_(
                    lagged.c.previous_date.is_(None),
                    _day_gap(
                        lagged.c.match_date, lagged.c.previous_date
                    )
                    != 1,
                ),
                1,
            ),
            else_=0,
        ).label("starts_window"),
    ).cte("ideas_marked_overlap_dates")
    grouped_dates = sa.select(
        marked.c.match_date,
        sa.func.sum(marked.c.starts_window)
        .over(order_by=marked.c.match_date)
        .label("window_id"),
    ).cte("ideas_grouped_overlap_dates")
    windows = (
        sa.select(
            grouped_dates.c.window_id,
            sa.func.min(grouped_dates.c.match_date).label("start_date"),
            sa.func.max(grouped_dates.c.match_date).label("end_date"),
        )
        .group_by(grouped_dates.c.window_id)
        .cte("ideas_overlap_windows")
    )
    membership = (
        sa.select(
            windows.c.window_id,
            windows.c.start_date,
            windows.c.end_date,
            matches.c.friend_id,
            matches.c.first_name,
            matches.c.last_name,
        )
        .select_from(
            windows.join(
                matches,
                matches.c.match_date.between(
                    windows.c.start_date, windows.c.end_date
                ),
            )
        )
        .distinct()
        .cte("ideas_overlap_membership")
    )
    ranked_membership = sa.select(
        membership,
        sa.func.row_number()
        .over(
            partition_by=membership.c.window_id,
            order_by=(
                sa.func.lower(
                    sa.func.coalesce(membership.c.first_name, "")
                    + " "
                    + sa.func.coalesce(membership.c.last_name, "")
                ),
                membership.c.friend_id,
            ),
        )
        .label("anchor_rank"),
    ).cte("ideas_ranked_overlap_membership")
    resort_for_window = (
        sa.select(
            ranked_membership.c.window_id,
            sa.func.min(Resort.__table__.c.id).label("resort_id"),
        )
        .select_from(
            ranked_membership.outerjoin(
                wishlist_pairs,
                wishlist_pairs.c.friend_id == ranked_membership.c.friend_id,
            ).outerjoin(
                Resort.__table__,
                sa.and_(
                    Resort.__table__.c.id == wishlist_pairs.c.resort_id,
                    Resort.__table__.c.is_active.is_(True),
                    Resort.__table__.c.is_region.is_(False),
                ),
            ),
        )
        .group_by(ranked_membership.c.window_id)
        .cte("ideas_overlap_resorts")
    )
    return (
        sa.select(
            resort_for_window.c.resort_id,
            ranked_membership.c.start_date,
            ranked_membership.c.end_date,
            sa.func.count().label("friend_count"),
            sa.literal(0).label("going_count"),
            sa.func.count().label("considering_count"),
            _ordered_concat(
                ranked_membership.c.friend_id,
                ",",
                ranked_membership.c.friend_id,
            ).label(
                "friend_ids"
            ),
            sa.cast(sa.null(), sa.String()).label("going_names"),
            sa.cast(sa.null(), sa.String()).label("considering_names"),
            sa.func.min(ranked_membership.c.friend_id).label("source_id"),
            sa.literal(1).label("has_user_date_overlap"),
            sa.func.min(
                sa.case(
                    (
                        ranked_membership.c.anchor_rank == 1,
                        ranked_membership.c.friend_id,
                    )
                )
            ).label("anchor_friend_id"),
            sa.func.min(
                sa.case(
                    (
                        ranked_membership.c.anchor_rank == 1,
                        ranked_membership.c.first_name,
                    )
                )
            ).label("anchor_first_name"),
        )
        .select_from(
            ranked_membership.join(
                resort_for_window,
                resort_for_window.c.window_id
                == ranked_membership.c.window_id,
            )
        )
        .group_by(
            resort_for_window.c.resort_id,
            ranked_membership.c.window_id,
            ranked_membership.c.start_date,
            ranked_membership.c.end_date,
        )
        .cte("ideas_availability_candidates")
    )


def _wishlist_candidates(wishlist_pairs):
    ordered = (
        sa.select(wishlist_pairs.c.resort_id, wishlist_pairs.c.friend_id)
        .order_by(wishlist_pairs.c.resort_id, wishlist_pairs.c.friend_id)
        .cte("ideas_ordered_wishlist_pairs")
    )
    return (
        sa.select(
            ordered.c.resort_id,
            sa.func.count().label("friend_count"),
            _ordered_concat(
                ordered.c.friend_id, ",", ordered.c.friend_id
            ).label("friend_ids"),
            sa.func.min(ordered.c.friend_id).label("source_id"),
        )
        .select_from(
            ordered.join(
                Resort.__table__,
                sa.and_(
                    Resort.__table__.c.id == ordered.c.resort_id,
                    Resort.__table__.c.is_active.is_(True),
                    Resort.__table__.c.is_region.is_(False),
                ),
            )
        )
        .group_by(ordered.c.resort_id)
        .cte("ideas_wishlist_candidates")
    )


def _build_home_ideas_statement(
    *, user_id, today, limit=HOME_IDEAS_RENDER_CAP
):
    """Build the complete cross-dialect Home Ideas winner statement."""
    available_days = _available_days(user_id=user_id, today=today)
    wishlist_pairs = _wishlist_pairs(user_id=user_id)
    trips = _trip_candidates(
        user_id=user_id, today=today, available_days=available_days
    )
    overlaps = _availability_candidates(
        user_id=user_id,
        available_days=available_days,
        wishlist_pairs=wishlist_pairs,
    )
    wishlists = _wishlist_candidates(wishlist_pairs)

    candidate_columns = (
        "resort_id",
        "start_date",
        "end_date",
        "friend_count",
        "going_count",
        "considering_count",
        "friend_ids",
        "going_names",
        "considering_names",
        "source_id",
        "has_user_date_overlap",
        "anchor_friend_id",
        "anchor_first_name",
        "signal_type",
        "idea_type",
    )
    trip_rows = sa.select(
        trips.c.resort_id,
        trips.c.start_date,
        trips.c.end_date,
        trips.c.friend_count,
        trips.c.going_count,
        trips.c.considering_count,
        trips.c.friend_ids,
        trips.c.going_names,
        trips.c.considering_names,
        trips.c.source_id,
        trips.c.has_user_date_overlap,
        sa.cast(sa.null(), sa.Integer).label("anchor_friend_id"),
        sa.cast(sa.null(), sa.String()).label("anchor_first_name"),
        sa.literal(1).label("signal_type"),
        sa.literal("friend_trip").label("idea_type"),
    )
    overlap_rows = sa.select(
        overlaps.c.resort_id,
        overlaps.c.start_date,
        overlaps.c.end_date,
        overlaps.c.friend_count,
        overlaps.c.going_count,
        overlaps.c.considering_count,
        overlaps.c.friend_ids,
        overlaps.c.going_names,
        overlaps.c.considering_names,
        overlaps.c.source_id,
        overlaps.c.has_user_date_overlap,
        overlaps.c.anchor_friend_id,
        overlaps.c.anchor_first_name,
        sa.literal(2).label("signal_type"),
        sa.literal("availability_overlap").label("idea_type"),
    )
    wishlist_rows = sa.select(
        wishlists.c.resort_id,
        sa.cast(sa.null(), sa.Date()).label("start_date"),
        sa.cast(sa.null(), sa.Date()).label("end_date"),
        wishlists.c.friend_count,
        sa.literal(0).label("going_count"),
        wishlists.c.friend_count.label("considering_count"),
        wishlists.c.friend_ids,
        sa.cast(sa.null(), sa.String()).label("going_names"),
        sa.cast(sa.null(), sa.String()).label("considering_names"),
        wishlists.c.source_id,
        sa.literal(0).label("has_user_date_overlap"),
        sa.cast(sa.null(), sa.Integer).label("anchor_friend_id"),
        sa.cast(sa.null(), sa.String()).label("anchor_first_name"),
        sa.literal(3).label("signal_type"),
        sa.literal("wishlist_overlap").label("idea_type"),
    )
    candidates = sa.union_all(trip_rows, overlap_rows, wishlist_rows).cte(
        "ideas_all_candidates"
    )
    assert tuple(candidates.c.keys()) == candidate_columns

    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__
    owned_bookings = sa.select(
        trip.c.resort_id,
        trip.c.start_date.label("start_date"),
        trip.c.end_date.label("end_date"),
    ).where(
        trip.c.user_id == user_id,
        sa.or_(
            trip.c.lifecycle_state.is_(None),
            trip.c.lifecycle_state == "active",
        ),
        trip.c.resort_id.is_not(None),
        trip.c.end_date >= today,
    )
    booking_override = sa.and_(
        participant.c.status == GuestStatus.GOING,
        participant.c.start_date.is_not(None),
        participant.c.end_date.is_not(None),
    )
    booking_start = sa.case(
        (booking_override, participant.c.start_date), else_=trip.c.start_date
    )
    booking_end = sa.case(
        (booking_override, participant.c.end_date), else_=trip.c.end_date
    )
    joined_bookings = (
        sa.select(
            trip.c.resort_id,
            booking_start.label("start_date"),
            booking_end.label("end_date"),
        )
        .select_from(trip.join(participant, participant.c.trip_id == trip.c.id))
        .where(
            participant.c.user_id == user_id,
            sa.or_(
                trip.c.lifecycle_state.is_(None),
                trip.c.lifecycle_state == "active",
            ),
            participant.c.status.in_(
                (GuestStatus.INTERESTED, GuestStatus.GOING)
            ),
            trip.c.user_id != user_id,
            trip.c.resort_id.is_not(None),
            trip.c.end_date >= today,
            booking_end >= today,
        )
    )
    bookings = sa.union_all(owned_bookings, joined_bookings).cte(
        "ideas_user_bookings"
    )
    # Express the inclusive seven-day buffer as integer day gaps so the same
    # statement remains valid on SQLite and PostgreSQL.
    overlaps_booking = sa.exists(
        sa.select(sa.literal(1)).where(
            bookings.c.resort_id == candidates.c.resort_id,
            _day_gap(candidates.c.start_date, bookings.c.end_date) <= 7,
            _day_gap(bookings.c.start_date, candidates.c.end_date) <= 7,
        )
    )
    eligible = (
        sa.select(candidates)
        .where(
            sa.or_(
                candidates.c.resort_id.is_(None),
                candidates.c.start_date.is_(None),
                candidates.c.friend_count >= 3,
                ~overlaps_booking,
            )
        )
        .cte("ideas_eligible_candidates")
    )
    concept_key = sa.case(
        (
            eligible.c.resort_id.is_not(None),
            "resort:" + sa.cast(eligible.c.resort_id, sa.String()),
        ),
        else_=(
            "no_resort:"
            + sa.cast(eligible.c.start_date, sa.String())
        ),
    )
    ranked = sa.select(
        eligible,
        sa.func.row_number()
        .over(
            partition_by=concept_key,
            order_by=(
                eligible.c.friend_count.desc(),
                sa.case(
                    (eligible.c.start_date.is_(None), 1), else_=0
                ),
                eligible.c.start_date.asc(),
                eligible.c.signal_type.asc(),
                eligible.c.source_id.asc(),
            ),
        )
        .label("concept_rank"),
    ).cte("ideas_ranked_candidates")

    no_resort_key = (
        ranked.c.idea_type
        + ":"
        + sa.func.replace(ranked.c.friend_ids, ",", "_")
        + ":"
        + sa.cast(ranked.c.start_date, sa.String())
    )
    card_key = sa.case(
        (
            ranked.c.resort_id.is_not(None),
            ranked.c.idea_type
            + ":"
            + sa.cast(ranked.c.resort_id, sa.String()),
        ),
        else_=no_resort_key,
    )
    dismissed = DismissedInsightCard.__table__
    is_dismissed = sa.exists(
        sa.select(sa.literal(1)).where(
            dismissed.c.user_id == user_id,
            dismissed.c.card_type == "opportunity",
            dismissed.c.card_key == card_key,
        )
    )
    resort = Resort.__table__
    return (
        sa.select(
            ranked,
            card_key.label("card_key"),
            resort.c.name.label("resort_name"),
            resort.c.slug.label("resort_slug"),
            resort.c.state_code.label("resort_state_code"),
        )
        .select_from(
            ranked.outerjoin(resort, resort.c.id == ranked.c.resort_id)
        )
        .where(ranked.c.concept_rank == 1, ~is_dismissed)
        .order_by(
            ranked.c.friend_count.desc(),
            sa.case(
                (ranked.c.has_user_date_overlap == 1, 0), else_=1
            ),
            # This is the legacy ``days_away ... else 999`` sort exactly:
            # undated rows sort at 999, so a dated idea beyond that point is
            # deliberately behind a wishlist rather than merely NULL-last.
            sa.func.coalesce(_day_gap(ranked.c.start_date, today), 999).asc(),
            ranked.c.signal_type.asc(),
            ranked.c.resort_id.asc().nulls_last(),
            ranked.c.source_id.asc(),
        )
        .limit(limit)
    )


def _split(value, separator=","):
    if not value:
        return []
    return [item for item in str(value).split(separator) if item]


def get_home_ideas(
    *, user_id, today=None, limit=HOME_IDEAS_RENDER_CAP
):
    """Execute exactly one statement and shape at most ``limit`` Home cards."""
    limit = min(limit, HOME_IDEAS_RENDER_CAP)
    if limit <= 0:
        return []
    statement = _build_home_ideas_statement(
        user_id=user_id,
        today=today or date.today(),
        limit=limit,
    )
    result = []
    for row in db.session.execute(statement).mappings():
        resort = None
        if row["resort_id"] is not None:
            resort = _ResortCard(
                id=row["resort_id"],
                name=row["resort_name"],
                slug=row["resort_slug"],
                state_code=row["resort_state_code"],
            )
        friend_ids = sorted({int(value) for value in _split(row["friend_ids"])})
        if row["idea_type"] == "friend_trip":
            parts = []
            going_names = _split(row["going_names"], _FIELD_SEPARATOR)
            considering_names = _split(
                row["considering_names"], _FIELD_SEPARATOR
            )
            if row["going_count"]:
                parts.append(_fmt_social_names(going_names, "going"))
            if row["considering_count"]:
                parts.append(
                    _fmt_social_names(considering_names, "considering")
                )
            line2 = " · ".join(parts) if parts else "Considering"
        elif row["idea_type"] == "availability_overlap":
            anchor = (
                format_name(row["anchor_first_name"])
                if row["anchor_first_name"]
                else "Your friend"
            )
            line2 = (
                f"{anchor} overlaps with you in "
                f"{row['start_date'].strftime('%B')}"
            )
        else:
            count = row["friend_count"]
            line2 = (
                "You and 1 friend have this on your wishlist"
                if count == 1
                else f"You and {count} friends have this on your wishlist"
            )
        result.append(
            {
                "resort": resort,
                "resort_id": row["resort_id"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "date_range": _fmt_date_range_short(
                    row["start_date"], row["end_date"]
                )
                if row["start_date"]
                else None,
                "friend_count": row["friend_count"],
                "going_count": row["going_count"],
                "considering_count": row["considering_count"],
                "line2": line2,
                "signal_type": row["signal_type"],
                "idea_type": row["idea_type"],
                "friend_ids": friend_ids,
                "has_user_date_overlap": bool(
                    row["has_user_date_overlap"]
                ),
                "anchor_friend_id": row["anchor_friend_id"],
                "anchor_friend_name": (
                    format_name(row["anchor_first_name"])
                    if row["anchor_first_name"]
                    else None
                ),
                "_card_key": row["card_key"],
            }
        )
    return result