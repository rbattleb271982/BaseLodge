"""Bounded candidate retrieval for the Home Happening section."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import sqlalchemy as sa

from models import (
    DismissedInsightCard,
    FriendConnectionEvent,
    FriendSuggestion,
    GuestStatus,
    Resort,
    SkiTrip,
    SkiTripParticipant,
    SkiTripPlanningPost,
    SkiTripRsvpTransition,
    User,
    db,
)
from services.visibility import reciprocal_friend_predicate


HOME_HAPPENING_RENDER_CAP = 5
HOME_HAPPENING_WINDOW_DAYS = 7
HOME_HAPPENING_CATEGORY_CAPS = {
    "on_your_trips": 2,
    "trips_forming": 3,
    "your_people": 1,
}


@dataclass(frozen=True)
class HappeningCandidate:
    trip_id: int
    attendance_user_id: int
    mountain: str | None
    resort_name: str | None
    attendance_status: str
    attendance_start_date: date | None
    attendance_end_date: date | None
    created_at: object
    updated_at: object

    @property
    def activity_timestamp(self):
        return self.updated_at or self.created_at

    @property
    def card_key(self):
        return f"happening:{self.trip_id}"


@dataclass(frozen=True)
class SuggestedConnectionCandidate:
    suggestion_id: int
    formation_event_id: int
    recipient_user_id: int
    suggested_user_id: int
    recipient_first_name: str | None
    suggested_first_name: str | None
    formed_at: object

    @property
    def activity_timestamp(self):
        return self.formed_at

    @property
    def card_key(self):
        return f"happening:suggested-connection:{self.formation_event_id}"


def _build_happening_candidates_statement(
    *,
    user_id,
    friend_ids,
    today,
    limit=HOME_HAPPENING_RENDER_CAP,
):
    """Build the cross-dialect final-winner query used by Happening."""
    unique_friend_ids = sorted(set(friend_ids))
    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__
    resort = Resort.__table__
    dismissed = DismissedInsightCard.__table__

    activity_timestamp = sa.func.coalesce(
        trip.c.updated_at,
        trip.c.created_at,
    )

    owner_occurrences = (
        sa.select(
            trip.c.id.label("trip_id"),
            trip.c.user_id.label("attendance_user_id"),
            trip.c.mountain.label("mountain"),
            resort.c.name.label("resort_name"),
            sa.func.coalesce(
                trip.c.trip_status,
                sa.literal("planning"),
            ).label("attendance_status"),
            trip.c.start_date.label("attendance_start_date"),
            trip.c.end_date.label("attendance_end_date"),
            trip.c.created_at.label("created_at"),
            trip.c.updated_at.label("updated_at"),
            activity_timestamp.label("activity_timestamp"),
        )
        .select_from(
            trip.outerjoin(resort, resort.c.id == trip.c.resort_id)
        )
        .where(
            trip.c.user_id.in_(unique_friend_ids),
            sa.or_(
                trip.c.lifecycle_state.is_(None),
                trip.c.lifecycle_state == "active",
            ),
            trip.c.end_date >= today,
            trip.c.is_public.is_(True),
            trip.c.resort_id.is_not(None),
        )
    )

    has_going_override = sa.and_(
        participant.c.status == GuestStatus.GOING,
        participant.c.start_date.is_not(None),
        participant.c.end_date.is_not(None),
    )
    effective_start = sa.case(
        (has_going_override, participant.c.start_date),
        else_=trip.c.start_date,
    )
    effective_end = sa.case(
        (has_going_override, participant.c.end_date),
        else_=trip.c.end_date,
    )
    participant_status = sa.case(
        (participant.c.status == GuestStatus.GOING, sa.literal("going")),
        else_=sa.literal("planning"),
    )

    participant_occurrences = (
        sa.select(
            trip.c.id.label("trip_id"),
            participant.c.user_id.label("attendance_user_id"),
            trip.c.mountain.label("mountain"),
            resort.c.name.label("resort_name"),
            participant_status.label("attendance_status"),
            effective_start.label("attendance_start_date"),
            effective_end.label("attendance_end_date"),
            trip.c.created_at.label("created_at"),
            trip.c.updated_at.label("updated_at"),
            activity_timestamp.label("activity_timestamp"),
        )
        .select_from(
            trip.join(
                participant,
                participant.c.trip_id == trip.c.id,
            ).outerjoin(
                resort,
                resort.c.id == trip.c.resort_id,
            )
        )
        .where(
            participant.c.user_id.in_(unique_friend_ids),
            sa.or_(
                trip.c.lifecycle_state.is_(None),
                trip.c.lifecycle_state == "active",
            ),
            participant.c.status.in_(
                (GuestStatus.INTERESTED, GuestStatus.GOING)
            ),
            trip.c.user_id != participant.c.user_id,
            trip.c.end_date >= today,
            effective_end >= today,
            trip.c.is_public.is_(True),
            trip.c.resort_id.is_not(None),
        )
    )

    occurrences = sa.union_all(
        owner_occurrences,
        participant_occurrences,
    ).subquery("happening_occurrences")

    ranked = sa.select(
        *occurrences.c,
        sa.func.row_number().over(
            partition_by=occurrences.c.attendance_user_id,
            order_by=(
                occurrences.c.activity_timestamp.desc().nulls_last(),
                occurrences.c.trip_id.desc(),
            ),
        ).label("friend_rank"),
    ).subquery("ranked_happening_occurrences")

    dismissed_card_key = (
        sa.literal("happening:")
        + sa.cast(ranked.c.trip_id, sa.String())
    )
    winner_is_dismissed = sa.exists(
        sa.select(sa.literal(1)).where(
            dismissed.c.user_id == user_id,
            dismissed.c.card_type == "happening",
            dismissed.c.card_key == dismissed_card_key,
        )
    )

    final_candidates = (
        sa.select(
            ranked.c.trip_id,
            ranked.c.attendance_user_id,
            ranked.c.mountain,
            ranked.c.resort_name,
            ranked.c.attendance_status,
            ranked.c.attendance_start_date,
            ranked.c.attendance_end_date,
            ranked.c.created_at,
            ranked.c.updated_at,
        )
        .where(
            ranked.c.friend_rank == 1,
            ~winner_is_dismissed,
        )
        .order_by(
            ranked.c.activity_timestamp.desc().nulls_last(),
            ranked.c.trip_id.desc(),
        )
        .limit(limit)
    )
    return final_candidates


def get_happening_candidates(
    *,
    user_id,
    friend_ids,
    today=None,
    limit=HOME_HAPPENING_RENDER_CAP,
):
    """Return final, dismissed-aware Happening winners without loading all trips."""
    unique_friend_ids = sorted(set(friend_ids or []))
    if not unique_friend_ids or limit <= 0:
        return []

    statement = _build_happening_candidates_statement(
        user_id=user_id,
        friend_ids=unique_friend_ids,
        today=today or date.today(),
        limit=limit,
    )
    rows = db.session.execute(statement).mappings().all()
    return [HappeningCandidate(**row) for row in rows]


def _build_suggested_connection_candidates_statement(
    *,
    user_id,
    limit=HOME_HAPPENING_RENDER_CAP,
):
    """Build the bounded, privacy-scoped BL-109 conversion query."""
    suggestion = FriendSuggestion.__table__
    formation = FriendConnectionEvent.__table__.alias(
        "suggested_connection_formation"
    )
    prior_event = FriendConnectionEvent.__table__.alias(
        "suggested_connection_prior_event"
    )
    intervening_removal = FriendConnectionEvent.__table__.alias(
        "suggested_connection_intervening_removal"
    )
    recipient = User.__table__.alias("suggested_connection_recipient")
    suggested = User.__table__.alias("suggested_connection_suggested")

    pair_a = sa.case(
        (
            suggestion.c.recipient_id < suggestion.c.suggested_user_id,
            suggestion.c.recipient_id,
        ),
        else_=suggestion.c.suggested_user_id,
    )
    pair_b = sa.case(
        (
            suggestion.c.recipient_id < suggestion.c.suggested_user_id,
            suggestion.c.suggested_user_id,
        ),
        else_=suggestion.c.recipient_id,
    )

    # Event timestamps can tie. Event ID is the deterministic lifecycle
    # tie-breaker everywhere this query needs "latest" or "earliest".
    state_at_suggestion = (
        sa.select(prior_event.c.event_type)
        .where(
            prior_event.c.user_a_id == pair_a,
            prior_event.c.user_b_id == pair_b,
            prior_event.c.occurred_at <= suggestion.c.created_at,
        )
        .order_by(
            prior_event.c.occurred_at.desc(),
            prior_event.c.id.desc(),
        )
        .limit(1)
        .correlate(suggestion)
        .scalar_subquery()
    )
    removal_before_formation = sa.exists(
        sa.select(sa.literal(1)).where(
            intervening_removal.c.user_a_id == pair_a,
            intervening_removal.c.user_b_id == pair_b,
            intervening_removal.c.event_type == "removed",
            intervening_removal.c.occurred_at > suggestion.c.created_at,
            sa.or_(
                intervening_removal.c.occurred_at < formation.c.occurred_at,
                sa.and_(
                    intervening_removal.c.occurred_at
                    == formation.c.occurred_at,
                    intervening_removal.c.id < formation.c.id,
                ),
            ),
        )
    )

    possible_matches = (
        sa.select(
            suggestion.c.id.label("suggestion_id"),
            suggestion.c.created_at.label("suggestion_created_at"),
            suggestion.c.recipient_id,
            suggestion.c.suggested_user_id,
            recipient.c.first_name.label("recipient_first_name"),
            suggested.c.first_name.label("suggested_first_name"),
            formation.c.id.label("formation_event_id"),
            formation.c.occurred_at.label("formed_at"),
            sa.func.row_number().over(
                partition_by=suggestion.c.id,
                order_by=(
                    formation.c.occurred_at.asc(),
                    formation.c.id.asc(),
                ),
            ).label("formation_rank"),
        )
        .select_from(
            suggestion.join(
                formation,
                sa.and_(
                    formation.c.user_a_id == pair_a,
                    formation.c.user_b_id == pair_b,
                    formation.c.event_type == "formed",
                    formation.c.occurred_at > suggestion.c.created_at,
                ),
            )
            .join(recipient, recipient.c.id == suggestion.c.recipient_id)
            .join(suggested, suggested.c.id == suggestion.c.suggested_user_id)
        )
        .where(
            suggestion.c.suggester_id == user_id,
            sa.func.coalesce(state_at_suggestion, "") != "formed",
            ~removal_before_formation,
            reciprocal_friend_predicate(
                user_id,
                suggestion.c.recipient_id,
            ),
            reciprocal_friend_predicate(
                user_id,
                suggestion.c.suggested_user_id,
            ),
            reciprocal_friend_predicate(
                suggestion.c.recipient_id,
                suggestion.c.suggested_user_id,
            ),
        )
        .subquery("possible_suggested_connection_matches")
    )

    earliest_matches = (
        sa.select(*possible_matches.c)
        .where(possible_matches.c.formation_rank == 1)
        .subquery("earliest_suggested_connection_matches")
    )
    collapsed_matches = (
        sa.select(
            *earliest_matches.c,
            sa.func.row_number().over(
                partition_by=earliest_matches.c.formation_event_id,
                order_by=(
                    earliest_matches.c.suggestion_created_at.asc(),
                    earliest_matches.c.suggestion_id.asc(),
                ),
            ).label("event_rank"),
        )
        .subquery("collapsed_suggested_connection_matches")
    )

    dismissed = DismissedInsightCard.__table__
    card_key = (
        sa.literal("happening:suggested-connection:")
        + sa.cast(collapsed_matches.c.formation_event_id, sa.String())
    )
    is_dismissed = sa.exists(
        sa.select(sa.literal(1)).where(
            dismissed.c.user_id == user_id,
            dismissed.c.card_type == "happening",
            dismissed.c.card_key == card_key,
        )
    )

    return (
        sa.select(
            collapsed_matches.c.suggestion_id,
            collapsed_matches.c.formation_event_id,
            collapsed_matches.c.recipient_id.label("recipient_user_id"),
            collapsed_matches.c.suggested_user_id,
            collapsed_matches.c.recipient_first_name,
            collapsed_matches.c.suggested_first_name,
            collapsed_matches.c.formed_at,
        )
        .where(
            collapsed_matches.c.event_rank == 1,
            ~is_dismissed,
        )
        .order_by(
            collapsed_matches.c.formed_at.desc().nulls_last(),
            collapsed_matches.c.formation_event_id.desc(),
        )
        .limit(limit)
    )


def get_suggested_connection_candidates(
    *,
    user_id,
    limit=HOME_HAPPENING_RENDER_CAP,
):
    """Return bounded BL-109 Happening confirmations for one introducer."""
    if not user_id or limit <= 0:
        return []
    statement = _build_suggested_connection_candidates_statement(
        user_id=user_id,
        limit=limit,
    )
    rows = db.session.execute(statement).mappings().all()
    return [SuggestedConnectionCandidate(**row) for row in rows]


def _dismissed_predicate(user_id, card_key):
    dismissed = DismissedInsightCard.__table__
    return sa.exists(
        sa.select(sa.literal(1)).where(
            dismissed.c.user_id == user_id,
            dismissed.c.card_type == "happening",
            dismissed.c.card_key == card_key,
        )
    )


def _card_key(prefix, identifier):
    return sa.literal(prefix) + sa.cast(identifier, sa.String())


def _format_dates(start_date, end_date):
    if not start_date:
        return None
    if not end_date or end_date == start_date:
        return start_date.strftime("%b %-d")
    if start_date.month == end_date.month:
        return f"{start_date.strftime('%b')} {start_date.day}–{end_date.day}"
    return f"{start_date.strftime('%b')} {start_date.day}–{end_date.strftime('%b')} {end_date.day}"


def _get_on_your_trips(user_id, window_start, today, limit=12):
    trip = SkiTrip.__table__
    participant = SkiTripParticipant.__table__
    transition = SkiTripRsvpTransition.__table__
    post = SkiTripPlanningPost.__table__
    resort = Resort.__table__
    subject = User.__table__.alias("digest_rsvp_subject")

    viewer_is_active = sa.exists(
        sa.select(sa.literal(1)).where(
            participant.c.trip_id == trip.c.id,
            participant.c.user_id == user_id,
            participant.c.status.in_((GuestStatus.INTERESTED, GuestStatus.GOING)),
        )
    )
    visible_trip = sa.or_(trip.c.user_id == user_id, viewer_is_active)
    active_trip = sa.and_(
        sa.or_(trip.c.lifecycle_state.is_(None), trip.c.lifecycle_state == "active"),
        trip.c.end_date >= today,
        trip.c.resort_id.is_not(None),
    )
    total_count = (
        sa.select(sa.func.count())
        .select_from(participant)
        .where(
            participant.c.trip_id == trip.c.id,
            participant.c.status != GuestStatus.REMOVED,
        )
        .correlate(trip)
        .scalar_subquery()
    )
    answered_count = (
        sa.select(sa.func.count())
        .select_from(participant)
        .where(
            participant.c.trip_id == trip.c.id,
            participant.c.status.in_(
                (GuestStatus.INTERESTED, GuestStatus.GOING, GuestStatus.DECLINED)
            ),
        )
        .correlate(trip)
        .scalar_subquery()
    )
    going_count = (
        sa.select(sa.func.count())
        .select_from(participant)
        .where(
            participant.c.trip_id == trip.c.id,
            participant.c.status == GuestStatus.GOING,
        )
        .correlate(trip)
        .scalar_subquery()
    )

    rsvp_key = _card_key("happening:rsvp:", transition.c.id)
    rsvp = (
        sa.select(
            sa.literal("rsvp").label("kind"),
            transition.c.id.label("event_id"),
            trip.c.id.label("trip_id"),
            transition.c.changed_at.label("activity_timestamp"),
            transition.c.new_status.label("status"),
            subject.c.first_name.label("first_name"),
            subject.c.last_name.label("last_name"),
            sa.literal(None).label("category"),
            resort.c.name.label("resort_name"),
            trip.c.start_date,
            trip.c.end_date,
            total_count.label("total_count"),
            answered_count.label("answered_count"),
            going_count.label("going_count"),
            rsvp_key.label("card_key"),
        )
        .select_from(
            transition.join(trip, trip.c.id == transition.c.trip_id)
            .join(subject, subject.c.id == transition.c.user_id)
            .join(resort, resort.c.id == trip.c.resort_id)
        )
        .where(
            visible_trip,
            active_trip,
            transition.c.changed_at >= window_start,
            transition.c.new_status.in_(("interested", "going", "declined", "removed")),
            ~_dismissed_predicate(user_id, rsvp_key),
        )
    )

    post_key = _card_key("happening:planning:", post.c.id)
    planning = (
        sa.select(
            sa.literal("planning_post").label("kind"),
            post.c.id.label("event_id"),
            trip.c.id.label("trip_id"),
            post.c.created_at.label("activity_timestamp"),
            sa.literal(None).label("status"),
            sa.literal(None).label("first_name"),
            sa.literal(None).label("last_name"),
            post.c.category.label("category"),
            resort.c.name.label("resort_name"),
            trip.c.start_date,
            trip.c.end_date,
            total_count.label("total_count"),
            answered_count.label("answered_count"),
            going_count.label("going_count"),
            post_key.label("card_key"),
        )
        .select_from(
            post.join(trip, trip.c.id == post.c.trip_id)
            .join(resort, resort.c.id == trip.c.resort_id)
        )
        .where(
            visible_trip,
            active_trip,
            post.c.created_at >= window_start,
            ~_dismissed_predicate(user_id, post_key),
        )
    )
    combined = sa.union_all(rsvp, planning).subquery("on_your_trips_digest")
    rows = db.session.execute(
        sa.select(combined)
        .order_by(
            combined.c.activity_timestamp.desc().nulls_last(),
            combined.c.event_id.desc(),
        )
        .limit(limit)
    ).mappings().all()

    items = []
    for row in rows:
        if row["kind"] == "planning_post":
            headline = f"New {row['category'].lower()} planning update"
        else:
            person = " ".join(
                part for part in (row["first_name"], row["last_name"]) if part
            ) or "A participant"
            if row["status"] in ("going", "interested"):
                headline = f"{person} joined"
            else:
                headline = f"{person} updated their response"
        total = int(row["total_count"] or 0)
        answered = int(row["answered_count"] or 0)
        going = int(row["going_count"] or 0)
        progress = f"{going} going"
        if total:
            progress += f" · {answered} of {total} answered"
        items.append({
            "headline": headline,
            "detail": progress,
            "resort_name": row["resort_name"],
            "date_range": _format_dates(row["start_date"], row["end_date"]),
            "trip_id": row["trip_id"],
            "timestamp": row["activity_timestamp"],
            "event_id": row["event_id"],
            "card_keys": [row["card_key"]],
        })
    return items


def _get_trips_forming(user_id, friend_ids, window_start, today, limit=18):
    if not friend_ids:
        return []
    trip = SkiTrip.__table__
    transition = SkiTripRsvpTransition.__table__
    resort = Resort.__table__
    person = User.__table__.alias("digest_forming_person")
    eligible_trip = sa.and_(
        sa.or_(trip.c.lifecycle_state.is_(None), trip.c.lifecycle_state == "active"),
        trip.c.end_date >= today,
        trip.c.is_public.is_(True),
        trip.c.resort_id.is_not(None),
    )

    trip_key = _card_key("happening:", trip.c.id)
    created = (
        sa.select(
            sa.literal("trip_created").label("kind"),
            trip.c.id.label("event_id"),
            trip.c.id.label("trip_id"),
            trip.c.created_at.label("activity_timestamp"),
            trip.c.user_id.label("person_id"),
            person.c.first_name,
            person.c.last_name,
            resort.c.name.label("resort_name"),
            trip.c.start_date,
            trip.c.end_date,
            trip_key.label("card_key"),
        )
        .select_from(
            trip.join(person, person.c.id == trip.c.user_id)
            .join(resort, resort.c.id == trip.c.resort_id)
        )
        .where(
            trip.c.user_id.in_(friend_ids),
            eligible_trip,
            trip.c.created_at >= window_start,
            ~_dismissed_predicate(user_id, trip_key),
        )
    )
    transitioned = (
        sa.select(
            sa.literal("friend_joined").label("kind"),
            transition.c.id.label("event_id"),
            trip.c.id.label("trip_id"),
            transition.c.changed_at.label("activity_timestamp"),
            transition.c.user_id.label("person_id"),
            person.c.first_name,
            person.c.last_name,
            resort.c.name.label("resort_name"),
            trip.c.start_date,
            trip.c.end_date,
            trip_key.label("card_key"),
        )
        .select_from(
            transition.join(trip, trip.c.id == transition.c.trip_id)
            .join(person, person.c.id == transition.c.user_id)
            .join(resort, resort.c.id == trip.c.resort_id)
        )
        .where(
            transition.c.user_id.in_(friend_ids),
            transition.c.new_status.in_(("interested", "going")),
            transition.c.changed_at >= window_start,
            eligible_trip,
            ~_dismissed_predicate(user_id, trip_key),
        )
    )
    combined = sa.union_all(created, transitioned).subquery("trips_forming_digest")
    rows = db.session.execute(
        sa.select(combined)
        .order_by(
            combined.c.activity_timestamp.desc().nulls_last(),
            combined.c.event_id.desc(),
        )
        .limit(limit)
    ).mappings().all()

    grouped = {}
    for row in rows:
        item = grouped.setdefault(row["trip_id"], {
            "resort_name": row["resort_name"],
            "date_range": _format_dates(row["start_date"], row["end_date"]),
            "trip_id": row["trip_id"],
            "timestamp": row["activity_timestamp"],
            "event_id": row["event_id"],
            "created_by": None,
            "joined_names": [],
            "card_keys": [row["card_key"]],
        })
        if (row["activity_timestamp"], row["event_id"]) > (
            item["timestamp"], item["event_id"]
        ):
            item["timestamp"] = row["activity_timestamp"]
            item["event_id"] = row["event_id"]
        name = " ".join(
            part for part in (row["first_name"], row["last_name"]) if part
        ) or "A friend"
        if row["kind"] == "trip_created":
            item["created_by"] = name
        elif name not in item["joined_names"]:
            item["joined_names"].append(name)
    items = []
    for item in grouped.values():
        if item["created_by"]:
            detail = f"{item['created_by']} started a trip"
        else:
            names = item["joined_names"]
            detail = (
                f"{names[0]} joined"
                if len(names) == 1
                else f"{names[0]} + {len(names) - 1} friends joined"
            )
        item["detail"] = detail
        items.append(item)
    items.sort(key=lambda item: (item["timestamp"], item["event_id"]), reverse=True)
    return items


def _get_your_people(user_id, window_start, limit=18):
    event = FriendConnectionEvent.__table__
    user = User.__table__.alias("digest_connection_person")
    other_id = sa.case(
        (event.c.user_a_id == user_id, event.c.user_b_id),
        else_=event.c.user_a_id,
    )
    direct_key = _card_key("happening:connection:", event.c.id)
    direct = (
        sa.select(
            sa.literal("direct").label("kind"),
            event.c.id.label("event_id"),
            event.c.occurred_at.label("activity_timestamp"),
            user.c.first_name.label("first_name"),
            sa.literal(None).label("second_name"),
            direct_key.label("card_key"),
        )
        .select_from(event.join(user, user.c.id == other_id))
        .where(
            event.c.event_type == "formed",
            event.c.occurred_at >= window_start,
            sa.or_(event.c.user_a_id == user_id, event.c.user_b_id == user_id),
            reciprocal_friend_predicate(user_id, other_id),
            ~_dismissed_predicate(user_id, direct_key),
        )
    )
    suggested_select = _build_suggested_connection_candidates_statement(
        user_id=user_id,
        limit=limit,
    ).subquery("digest_suggested_connections")
    suggested = sa.select(
        sa.literal("suggested").label("kind"),
        suggested_select.c.formation_event_id.label("event_id"),
        suggested_select.c.formed_at.label("activity_timestamp"),
        suggested_select.c.recipient_first_name.label("first_name"),
        suggested_select.c.suggested_first_name.label("second_name"),
        _card_key(
            "happening:suggested-connection:",
            suggested_select.c.formation_event_id,
        ).label("card_key"),
    ).where(suggested_select.c.formed_at >= window_start)
    combined = sa.union_all(direct, suggested).subquery("your_people_digest")
    rows = db.session.execute(
        sa.select(combined)
        .order_by(
            combined.c.activity_timestamp.desc().nulls_last(),
            combined.c.event_id.desc(),
        )
        .limit(limit)
    ).mappings().all()
    if not rows:
        return []
    direct_count = sum(row["kind"] == "direct" for row in rows)
    suggested_count = sum(row["kind"] == "suggested" for row in rows)
    parts = []
    if direct_count:
        parts.append(f"{direct_count} new connection{'s' if direct_count != 1 else ''}")
    if suggested_count:
        parts.append(
            f"{suggested_count} successful introduction"
            f"{'s' if suggested_count != 1 else ''}"
        )
    return [{
        "headline": " · ".join(parts),
        "detail": "Your network changed this week",
        "timestamp": rows[0]["activity_timestamp"],
        "event_id": rows[0]["event_id"],
        "card_keys": [row["card_key"] for row in rows],
    }]


def get_home_happening_digest(*, user_id, friend_ids, now=None, today=None):
    """Return the three-category, evidence-backed Home activity digest."""
    now = now or datetime.utcnow()
    today = today or date.today()
    window_start = now - timedelta(days=HOME_HAPPENING_WINDOW_DAYS)
    try:
        on_your_trips = _get_on_your_trips(user_id, window_start, today)
    except Exception:
        db.session.rollback()
        on_your_trips = []
    try:
        trips_forming = _get_trips_forming(
            user_id,
            sorted(set(friend_ids or [])),
            window_start,
            today,
        )
    except Exception:
        db.session.rollback()
        trips_forming = []
    try:
        your_people = _get_your_people(user_id, window_start)
    except Exception:
        db.session.rollback()
        your_people = []
    categories = [
        {
            "key": "on_your_trips",
            "label": "ON YOUR TRIPS",
            "items": on_your_trips[:HOME_HAPPENING_CATEGORY_CAPS["on_your_trips"]],
            "overflow": max(
                0,
                len(on_your_trips) - HOME_HAPPENING_CATEGORY_CAPS["on_your_trips"],
            ),
        },
        {
            "key": "trips_forming",
            "label": "TRIPS FORMING",
            "items": trips_forming[:HOME_HAPPENING_CATEGORY_CAPS["trips_forming"]],
            "overflow": max(
                0,
                len(trips_forming) - HOME_HAPPENING_CATEGORY_CAPS["trips_forming"],
            ),
        },
        {
            "key": "your_people",
            "label": "YOUR PEOPLE",
            "items": your_people[:HOME_HAPPENING_CATEGORY_CAPS["your_people"]],
            "overflow": 0,
        },
    ]
    return [category for category in categories if category["items"]]