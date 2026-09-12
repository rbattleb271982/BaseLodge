"""Bounded Home Needs You projection regressions."""

import sqlalchemy as sa

from app import _build_home_needs_you, app
from models import GuestStatus, Invitation, InviteType, db
from tests.conftest import _add_participant, _make_trip, _make_user


def _capture_selects(call):
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def test_empty_needs_you_uses_three_family_queries(client):
    with app.app_context():
        viewer = _make_user("needs-empty-viewer")
        db.session.commit()
        viewer_id = viewer.id
        rows, statements = _capture_selects(
            lambda: _build_home_needs_you(
                user_id=viewer_id,
                today=_make_trip_date(),
            )
        )
        assert rows == []
        assert len(statements) == 3


def _make_trip_date():
    from datetime import date
    return date.today()


def test_heavy_mixed_needs_you_query_count_is_constant_and_capped(client):
    with app.app_context():
        viewer = _make_user("needs-heavy-viewer")
        for index in range(20):
            trip_owner = _make_user(f"needs-invite-owner-{index}")
            invited_trip = _make_trip(trip_owner)
            _add_participant(invited_trip, viewer, GuestStatus.PENDING)

            requester = _make_user(f"needs-join-sender-{index}")
            owned_trip = _make_trip(viewer)
            db.session.add(Invitation(
                sender_id=requester.id,
                receiver_id=viewer.id,
                trip_id=owned_trip.id,
                invite_type=InviteType.REQUEST,
                status="pending",
            ))

            friend_sender = _make_user(f"needs-friend-sender-{index}")
            db.session.add(Invitation(
                sender_id=friend_sender.id,
                receiver_id=viewer.id,
                invite_type=InviteType.OUTBOUND,
                status="pending",
            ))
        db.session.commit()
        viewer_id = viewer.id

        rows, statements = _capture_selects(
            lambda: _build_home_needs_you(
                user_id=viewer_id,
                today=_make_trip_date(),
            )
        )

        assert len(statements) == 5
        assert len(rows) == 12
        assert {row["type"] for row in rows} == {
            "trip_invitation",
            "join_request",
            "friend_request",
        }
        assert sum(" from user " in f" {' '.join(s.lower().split())} " for s in statements) == 1