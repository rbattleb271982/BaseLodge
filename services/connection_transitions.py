"""Transaction-neutral direct connection lifecycle operations."""

from dataclasses import dataclass
from typing import FrozenSet, Optional

from models import Friend, FriendConnectionEvent, User, db


CONNECTION_EVENT_TYPES: FrozenSet[str] = frozenset(("formed", "removed"))
CONNECTION_EVENT_SOURCES: FrozenSet[str] = frozenset(
    (
        "friend_request_accept",
        "invite_token_accept",
        "qr_connect",
        "group_trip_accept",
        "shared_trip_connect",
        "api_unfriend",
        "web_unfriend",
    )
)


@dataclass(frozen=True)
class ConnectionTransitionResult:
    user_a_id: int
    user_b_id: int
    connected: bool
    changed: bool
    repaired: bool
    preexisting_row_count: int
    event: Optional[FriendConnectionEvent]

    @property
    def formed(self) -> bool:
        return self.event is not None and self.event.event_type == "formed"

    @property
    def removed(self) -> bool:
        return self.event is not None and self.event.event_type == "removed"


def transition_connection(
    *,
    user_id: int,
    other_user_id: int,
    connected: bool,
    source: str,
    actor_user_id: Optional[int] = None,
) -> ConnectionTransitionResult:
    """Set one canonical pair's live state and append at most one event.

    Both subject User rows are locked in ascending ID order before the directed
    Friend rows are refreshed. The caller owns commit/rollback.
    """
    if not isinstance(user_id, int) or not isinstance(other_user_id, int):
        raise ValueError("Connection subject IDs must be integers")
    if user_id == other_user_id:
        raise ValueError("A user cannot connect to themselves")
    if source not in CONNECTION_EVENT_SOURCES:
        raise ValueError(f"Invalid connection event source: {source!r}")

    user_a_id, user_b_id = sorted((user_id, other_user_id))

    with db.session.no_autoflush:
        for subject_id in (user_a_id, user_b_id):
            (
                User.query.filter_by(id=subject_id)
                .populate_existing()
                .with_for_update()
                .one()
            )

        rows = (
            Friend.query.filter(
                db.or_(
                    db.and_(
                        Friend.user_id == user_a_id,
                        Friend.friend_id == user_b_id,
                    ),
                    db.and_(
                        Friend.user_id == user_b_id,
                        Friend.friend_id == user_a_id,
                    ),
                )
            )
            .populate_existing()
            .with_for_update()
            .all()
        )

    rows_by_direction = {
        (row.user_id, row.friend_id): row
        for row in rows
    }
    preexisting_row_count = len(rows_by_direction)
    event = None
    repaired = False
    changed = False

    if connected:
        missing_directions = (
            (user_a_id, user_b_id),
            (user_b_id, user_a_id),
        )
        for direction in missing_directions:
            if direction not in rows_by_direction:
                db.session.add(
                    Friend(user_id=direction[0], friend_id=direction[1])
                )
                changed = True

        if preexisting_row_count == 0:
            event = FriendConnectionEvent(
                user_a_id=user_a_id,
                user_b_id=user_b_id,
                event_type="formed",
                actor_user_id=actor_user_id,
                source=source,
            )
            db.session.add(event)
        elif preexisting_row_count == 1:
            repaired = True
    else:
        if rows_by_direction:
            for row in rows_by_direction.values():
                db.session.delete(row)
            changed = True
            event = FriendConnectionEvent(
                user_a_id=user_a_id,
                user_b_id=user_b_id,
                event_type="removed",
                actor_user_id=actor_user_id,
                source=source,
            )
            db.session.add(event)

    db.session.flush()
    return ConnectionTransitionResult(
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        connected=connected,
        changed=changed,
        repaired=repaired,
        preexisting_row_count=preexisting_row_count,
        event=event,
    )