"""Bounded, viewer-scoped retrieval for Suggested Friends cards."""
from dataclasses import dataclass
from datetime import datetime
import sqlalchemy as sa
from itsdangerous import BadData, URLSafeSerializer
from models import FriendCooldown, FriendSuggestion, Invitation, User, db
from services.visibility import reciprocal_friend_predicate

SUGGESTIONS_PAGE_SIZE = 20
_VERSION = 1
_TYPE = "friends-suggestions"

class FriendSuggestionsCursorError(ValueError):
    pass

@dataclass(frozen=True)
class FriendSuggestionsCursor:
    viewer_id: int
    latest_at: datetime
    suggested_user_id: int

@dataclass(frozen=True)
class FriendSuggestionsPage:
    rows: list
    has_more: bool
    next_cursor: str | None

def _serializer():
    from flask import current_app
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="friends-suggestions-page")

def encode_suggestions_cursor(cursor):
    if not isinstance(cursor, FriendSuggestionsCursor) or cursor.viewer_id <= 0 or cursor.suggested_user_id <= 0:
        raise FriendSuggestionsCursorError("Invalid Suggested Friends cursor.")
    return _serializer().dumps({"v": _VERSION, "t": _TYPE, "u": cursor.viewer_id,
                                 "d": cursor.latest_at.isoformat(), "i": cursor.suggested_user_id})

def decode_suggestions_cursor(value, viewer_id):
    if not isinstance(value, str) or not value or len(value) > 768:
        raise FriendSuggestionsCursorError("Invalid Suggested Friends cursor.")
    try:
        payload = _serializer().loads(value)
        if set(payload) != {"v", "t", "u", "d", "i"} or payload["v"] != _VERSION or payload["t"] != _TYPE:
            raise ValueError
        if payload["u"] != viewer_id or type(payload["i"]) is not int or payload["i"] <= 0:
            raise ValueError
        latest = datetime.fromisoformat(payload["d"])
        return FriendSuggestionsCursor(viewer_id, latest, payload["i"])
    except (BadData, ValueError, TypeError, KeyError) as exc:
        raise FriendSuggestionsCursorError("Invalid Suggested Friends cursor.") from exc

def count_active_suggestions(viewer_id):
    return db.session.query(sa.func.count(sa.distinct(FriendSuggestion.suggested_user_id))).filter(
        FriendSuggestion.recipient_id == viewer_id,
        FriendSuggestion.dismissed_at.is_(None),
        FriendSuggestion.expires_at > datetime.utcnow(),
        ~reciprocal_friend_predicate(
            viewer_id, FriendSuggestion.suggested_user_id
        ),
    ).scalar() or 0

def load_suggestions_page(viewer_id, cursor_value=None):
    now = datetime.utcnow()
    cursor = decode_suggestions_cursor(cursor_value, viewer_id) if cursor_value else None
    grouped = db.session.query(
        FriendSuggestion.suggested_user_id,
        sa.func.max(FriendSuggestion.created_at).label("latest_at"),
    ).filter(
        FriendSuggestion.recipient_id == viewer_id,
        FriendSuggestion.dismissed_at.is_(None),
        FriendSuggestion.expires_at > now,
        ~reciprocal_friend_predicate(
            viewer_id, FriendSuggestion.suggested_user_id
        ),
    ).group_by(FriendSuggestion.suggested_user_id)
    grouped = grouped.subquery("suggestion_groups")
    query = db.session.query(
        grouped.c.suggested_user_id, grouped.c.latest_at
    )
    if cursor:
        query = query.filter(sa.or_(
            grouped.c.latest_at < cursor.latest_at,
            sa.and_(grouped.c.latest_at == cursor.latest_at,
                    grouped.c.suggested_user_id > cursor.suggested_user_id),
        ))
    groups = query.order_by(grouped.c.latest_at.desc(),
                            grouped.c.suggested_user_id.asc()).limit(
                                SUGGESTIONS_PAGE_SIZE + 1
                            ).all()
    has_more = len(groups) > SUGGESTIONS_PAGE_SIZE
    groups = groups[:SUGGESTIONS_PAGE_SIZE]
    if not groups:
        return FriendSuggestionsPage([], False, None)
    ids = [row.suggested_user_id for row in groups]
    by_id = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
    ranked = db.session.query(
        FriendSuggestion.suggested_user_id,
        FriendSuggestion.suggester_id,
        sa.func.row_number().over(
            partition_by=FriendSuggestion.suggested_user_id,
            order_by=(FriendSuggestion.created_at.asc(), FriendSuggestion.id.asc()),
        ).label("rank"),
        sa.func.count().over(
            partition_by=FriendSuggestion.suggested_user_id
        ).label("total"),
    ).filter(
        FriendSuggestion.recipient_id == viewer_id,
        FriendSuggestion.suggested_user_id.in_(ids),
        FriendSuggestion.dismissed_at.is_(None),
        FriendSuggestion.expires_at > now,
    ).subquery("ranked_suggesters")
    attribution_rows = db.session.query(
        ranked.c.suggested_user_id, ranked.c.suggester_id,
        ranked.c.rank, ranked.c.total,
    ).filter(ranked.c.rank <= 2).order_by(
        ranked.c.suggested_user_id, ranked.c.rank
    ).all()
    attribution = {i: {"ids": [], "total": 0} for i in ids}
    for row in attribution_rows:
        attribution[row.suggested_user_id]["ids"].append(row.suggester_id)
        attribution[row.suggested_user_id]["total"] = int(row.total)
    inbound_rows = db.session.query(
        Invitation.sender_id, sa.func.min(Invitation.id).label("invitation_id")
    ).filter(
        Invitation.receiver_id == viewer_id,
        Invitation.sender_id.in_(ids),
        Invitation.trip_id.is_(None),
        Invitation.status == "pending",
    ).group_by(Invitation.sender_id).all()
    inbound_by_sender = {row.sender_id: row.invitation_id for row in inbound_rows}
    outgoing_rows = db.session.query(
        Invitation.receiver_id, sa.func.min(Invitation.id).label("invitation_id")
    ).filter(
        Invitation.sender_id == viewer_id,
        Invitation.receiver_id.in_(ids),
        Invitation.trip_id.is_(None),
        Invitation.status == "pending",
    ).group_by(Invitation.receiver_id).all()
    outgoing_by_receiver = {
        row.receiver_id: row.invitation_id for row in outgoing_rows
    }
    cooldown_ids = set()
    cooldown_rows = FriendCooldown.query.filter(
        FriendCooldown.expires_at > now,
        sa.or_(
            sa.and_(
                FriendCooldown.user_a_id == viewer_id,
                FriendCooldown.user_b_id.in_(ids),
            ),
            sa.and_(
                FriendCooldown.user_b_id == viewer_id,
                FriendCooldown.user_a_id.in_(ids),
            ),
        ),
    ).all()
    for cooldown in cooldown_rows:
        cooldown_ids.add(
            cooldown.user_b_id
            if cooldown.user_a_id == viewer_id
            else cooldown.user_a_id
        )
    result = []
    for group in groups:
        user = by_id.get(group.suggested_user_id)
        if not user:
            continue
        result.append({
            "user": user,
            "suggester_ids": attribution[group.suggested_user_id]["ids"],
            "suggester_count": attribution[group.suggested_user_id]["total"],
            "has_inbound_request": group.suggested_user_id in inbound_by_sender,
            "inbound_invitation_id": inbound_by_sender.get(group.suggested_user_id),
            "has_outgoing_request": group.suggested_user_id in outgoing_by_receiver,
            "outgoing_invitation_id": outgoing_by_receiver.get(
                group.suggested_user_id
            ),
            "is_in_cooldown": group.suggested_user_id in cooldown_ids,
            "latest_at": group.latest_at,
        })
    last = groups[-1]
    next_cursor = encode_suggestions_cursor(FriendSuggestionsCursor(viewer_id, last.latest_at, last.suggested_user_id)) if has_more else None
    return FriendSuggestionsPage(result, has_more, next_cursor)