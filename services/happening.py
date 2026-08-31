"""Bounded candidate retrieval for the Home Happening section."""

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from models import (
    DismissedInsightCard,
    GuestStatus,
    Resort,
    SkiTrip,
    SkiTripParticipant,
    db,
)


HOME_HAPPENING_RENDER_CAP = 5


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