"""Bounded, viewer-scoped retrieval for pending outgoing friend requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from flask import current_app
from itsdangerous import BadData, URLSafeSerializer

from models import Invitation, InviteType, User, db


OUTGOING_REQUESTS_PAGE_SIZE = 20
_CURSOR_VERSION = 1
_CURSOR_TYPE = "outgoing-friend-requests"
_CURSOR_MAX_LENGTH = 768


class OutgoingRequestsCursorError(ValueError):
    """Raised when an outgoing-request cursor is invalid for the viewer."""


@dataclass(frozen=True)
class OutgoingRequestCursor:
    viewer_id: int
    created_at: datetime
    invitation_id: int


@dataclass(frozen=True)
class OutgoingRequestRow:
    invitation_id: int
    recipient_id: int
    recipient_first_name: str
    recipient_last_name: str
    created_at: datetime

    @property
    def recipient_name(self) -> str:
        return " ".join(
            part for part in (self.recipient_first_name, self.recipient_last_name)
            if part
        ) or "BaseLodge member"


@dataclass(frozen=True)
class OutgoingRequestsPage:
    rows: list[OutgoingRequestRow]
    has_more: bool
    next_cursor: str | None
    total_count: int


def encode_outgoing_requests_cursor(cursor: OutgoingRequestCursor) -> str:
    if (
        not isinstance(cursor, OutgoingRequestCursor)
        or type(cursor.viewer_id) is not int
        or cursor.viewer_id <= 0
        or not isinstance(cursor.created_at, datetime)
        or type(cursor.invitation_id) is not int
        or cursor.invitation_id <= 0
    ):
        raise OutgoingRequestsCursorError("Invalid outgoing requests cursor.")
    return URLSafeSerializer(
        current_app.config["SECRET_KEY"],
        salt="outgoing-friend-requests-page",
    ).dumps({
        "v": _CURSOR_VERSION,
        "t": _CURSOR_TYPE,
        "u": cursor.viewer_id,
        "d": cursor.created_at.isoformat(),
        "i": cursor.invitation_id,
    })


def decode_outgoing_requests_cursor(
    value: str,
    *,
    viewer_id: int,
) -> OutgoingRequestCursor:
    if not isinstance(value, str) or not value or len(value) > _CURSOR_MAX_LENGTH:
        raise OutgoingRequestsCursorError("Invalid outgoing requests cursor.")
    try:
        payload = URLSafeSerializer(
            current_app.config["SECRET_KEY"],
            salt="outgoing-friend-requests-page",
        ).loads(value)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "t", "u", "d", "i"}
            or payload["v"] != _CURSOR_VERSION
            or payload["t"] != _CURSOR_TYPE
            or type(payload["u"]) is not int
            or payload["u"] != int(viewer_id)
            or type(payload["i"]) is not int
            or payload["i"] <= 0
            or not isinstance(payload["d"], str)
        ):
            raise ValueError
        created_at = datetime.fromisoformat(payload["d"])
    except (BadData, ValueError, TypeError, KeyError) as exc:
        raise OutgoingRequestsCursorError(
            "Invalid outgoing requests cursor."
        ) from exc
    return OutgoingRequestCursor(
        viewer_id=payload["u"],
        created_at=created_at,
        invitation_id=payload["i"],
    )


def _pending_outgoing_predicate(viewer_id: int):
    return sa.and_(
        Invitation.sender_id == viewer_id,
        Invitation.status == "pending",
        Invitation.trip_id.is_(None),
        Invitation.invite_type == InviteType.OUTBOUND,
    )


def load_outgoing_requests_page(
    viewer_id: int,
    cursor_value: str | None = None,
) -> OutgoingRequestsPage:
    cursor = (
        decode_outgoing_requests_cursor(cursor_value, viewer_id=viewer_id)
        if cursor_value else None
    )
    total_count = (
        db.session.query(sa.func.count(Invitation.id))
        .filter(_pending_outgoing_predicate(viewer_id))
        .scalar()
        or 0
    )
    query = (
        db.session.query(
            Invitation.id.label("invitation_id"),
            Invitation.receiver_id.label("recipient_id"),
            Invitation.created_at,
            User.first_name.label("recipient_first_name"),
            User.last_name.label("recipient_last_name"),
        )
        .join(User, User.id == Invitation.receiver_id)
        .filter(_pending_outgoing_predicate(viewer_id))
    )
    if cursor:
        query = query.filter(sa.or_(
            Invitation.created_at < cursor.created_at,
            sa.and_(
                Invitation.created_at == cursor.created_at,
                Invitation.id < cursor.invitation_id,
            ),
        ))
    candidates = (
        query.order_by(Invitation.created_at.desc(), Invitation.id.desc())
        .limit(OUTGOING_REQUESTS_PAGE_SIZE + 1)
        .all()
    )
    has_more = len(candidates) > OUTGOING_REQUESTS_PAGE_SIZE
    candidates = candidates[:OUTGOING_REQUESTS_PAGE_SIZE]
    rows = [
        OutgoingRequestRow(
            invitation_id=row.invitation_id,
            recipient_id=row.recipient_id,
            recipient_first_name=row.recipient_first_name or "",
            recipient_last_name=row.recipient_last_name or "",
            created_at=row.created_at,
        )
        for row in candidates
    ]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_outgoing_requests_cursor(OutgoingRequestCursor(
            viewer_id=viewer_id,
            created_at=last.created_at,
            invitation_id=last.invitation_id,
        ))
    return OutgoingRequestsPage(
        rows=rows,
        has_more=has_more,
        next_cursor=next_cursor,
        total_count=int(total_count),
    )