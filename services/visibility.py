"""Current-state visibility predicates for authenticated social surfaces."""

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from flask import current_app
from itsdangerous import BadData, URLSafeTimedSerializer

from models import Friend, GuestStatus, SkiTripParticipant, db

AVAILABILITY_IDEA_CAPABILITY_MAX_AGE_SECONDS = 3600
_AVAILABILITY_IDEA_CAPABILITY_SALT = "bl133-availability-idea-v1"


def reciprocal_friend_predicate(viewer_id, target_id):
    """SQL predicate requiring both live directed Friend rows."""
    outgoing = Friend.__table__.alias("visibility_friend_outgoing")
    incoming = Friend.__table__.alias("visibility_friend_incoming")
    return sa.and_(
        sa.exists(
            sa.select(sa.literal(1)).where(
                outgoing.c.user_id == viewer_id,
                outgoing.c.friend_id == target_id,
            )
        ),
        sa.exists(
            sa.select(sa.literal(1)).where(
                incoming.c.user_id == target_id,
                incoming.c.friend_id == viewer_id,
            )
        ),
    )


def reciprocal_friend_ids(user_id):
    """Return the bounded set of IDs with reciprocal current Friend rows."""
    reverse = db.aliased(Friend)
    return {
        friend_id
        for (friend_id,) in (
            db.session.query(Friend.friend_id)
            .join(
                reverse,
                db.and_(
                    reverse.user_id == Friend.friend_id,
                    reverse.friend_id == Friend.user_id,
                ),
            )
            .filter(Friend.user_id == user_id)
            .all()
        )
    }


def is_reciprocal_friend(viewer_id, target_id):
    """Return whether two distinct users are reciprocal current friends."""
    if viewer_id == target_id:
        return False
    return (
        db.session.query(sa.literal(1))
        .filter(reciprocal_friend_predicate(viewer_id, target_id))
        .first()
        is not None
    )


def friend_api_view(user):
    """Minimal allowlisted friend identity; contact fields are never included."""
    return {
        "id": user.id,
        "name": f"{user.first_name} {user.last_name}",
        "pass_type": user.pass_type or "No Pass",
    }


def issue_availability_idea_capability(
    *,
    viewer_id,
    friend_ids,
    start_date,
    end_date,
    resort_id=None,
):
    """Sign the exact scope of a server-generated availability Idea."""
    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=_AVAILABILITY_IDEA_CAPABILITY_SALT,
    )
    return serializer.dumps({
        "purpose": "availability_idea",
        "version": 1,
        "viewer_id": int(viewer_id),
        "friend_ids": sorted({int(friend_id) for friend_id in friend_ids}),
        "start_date": str(start_date),
        "end_date": str(end_date),
        "resort_id": int(resort_id) if resort_id is not None else None,
    })


def load_availability_idea_capability(token, *, viewer_id):
    """Verify and return a viewer-bound availability Idea scope."""
    if not token:
        return None
    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"],
        salt=_AVAILABILITY_IDEA_CAPABILITY_SALT,
    )
    try:
        claims = serializer.loads(
            token,
            max_age=AVAILABILITY_IDEA_CAPABILITY_MAX_AGE_SECONDS,
        )
        friend_ids = sorted({
            int(friend_id) for friend_id in claims["friend_ids"]
        })
        resort_id = claims.get("resort_id")
        normalized = {
            "purpose": claims["purpose"],
            "version": int(claims["version"]),
            "viewer_id": int(claims["viewer_id"]),
            "friend_ids": friend_ids,
            "start_date": str(claims["start_date"]),
            "end_date": str(claims["end_date"]),
            "resort_id": int(resort_id) if resort_id is not None else None,
        }
    except (BadData, KeyError, TypeError, ValueError):
        return None
    if (
        normalized["purpose"] != "availability_idea"
        or normalized["version"] != 1
        or normalized["viewer_id"] != int(viewer_id)
        or not normalized["friend_ids"]
        or len(normalized["friend_ids"]) > 50
    ):
        return None
    return normalized


def has_reciprocal_trip_friend(viewer_id, trip):
    """Return whether the viewer has a current friend on an active trip."""
    if not trip.end_date or trip.end_date < date.today():
        return False
    participant = SkiTripParticipant.__table__.alias(
        "visibility_trip_friend_participant"
    )
    going_override = sa.and_(
        participant.c.status == GuestStatus.GOING,
        participant.c.start_date.is_not(None),
        participant.c.end_date.is_not(None),
    )
    effective_end = sa.case(
        (going_override, participant.c.end_date),
        else_=trip.end_date,
    )
    active_participant_friend = sa.exists(
        sa.select(sa.literal(1)).where(
            participant.c.trip_id == trip.id,
            participant.c.status.in_(
                (GuestStatus.GOING, GuestStatus.INTERESTED)
            ),
            effective_end >= date.today(),
            reciprocal_friend_predicate(viewer_id, participant.c.user_id),
        )
    )
    return (
        db.session.query(sa.literal(1))
        .filter(
            sa.or_(
                reciprocal_friend_predicate(viewer_id, trip.user_id),
                active_participant_friend,
            )
        )
        .first()
        is not None
    )


@dataclass(frozen=True)
class TripViewCapability:
    allowed: bool
    organizer: bool
    active_participant: bool
    pending_invitee: bool
    friend_public: bool
    terminal: bool


def trip_view_capability(
    trip,
    viewer_id,
    *,
    participant=None,
    allow_friend_public=False,
):
    """Decide current trip visibility without consulting audit/history tables."""
    terminal = (trip.lifecycle_state or "active") in {"completed", "cancelled"}
    organizer = trip.user_id == viewer_id
    if participant is None and not organizer:
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id, user_id=viewer_id
        ).first()
    active_participant = bool(
        participant
        and participant.status in (GuestStatus.GOING, GuestStatus.INTERESTED)
    )
    pending_invitee = bool(
        not terminal
        and participant
        and participant.status == GuestStatus.PENDING
    )
    friend_public = bool(
        allow_friend_public
        and not terminal
        and trip.is_public
        and has_reciprocal_trip_friend(viewer_id, trip)
    )
    return TripViewCapability(
        allowed=organizer or active_participant or pending_invitee or friend_public,
        organizer=organizer,
        active_participant=active_participant,
        pending_invitee=pending_invitee,
        friend_public=friend_public,
        terminal=terminal,
    )