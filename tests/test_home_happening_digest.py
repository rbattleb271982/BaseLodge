"""Evidence, privacy, bounds, and query-budget tests for the M digest."""

from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from app import app
from models import (
    Friend,
    FriendConnectionEvent,
    GuestStatus,
    SkiTripPlanningPost,
    SkiTripRsvpTransition,
    db,
)
from services.happening import get_home_happening_digest
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


NOW = datetime(2026, 9, 12, 12, 0, 0)
TODAY = date(2026, 9, 12)


def _connect(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


def _category_map(rows):
    return {row["key"]: row for row in rows}


def test_digest_uses_only_durable_sources_in_fixed_category_order(client):
    with app.app_context():
        viewer = _make_user("digest-viewer")
        friend = _make_user("digest-friend")
        guest = _make_user("digest-guest")
        resort = _make_resort("Digest Peak")
        _connect(viewer, friend)

        owned = _make_trip(
            viewer,
            resort,
            start_date=TODAY + timedelta(days=2),
            end_date=TODAY + timedelta(days=5),
        )
        participant = _add_participant(owned, guest, GuestStatus.GOING)
        db.session.flush()
        db.session.add(SkiTripRsvpTransition(
            trip_id=owned.id,
            user_id=guest.id,
            previous_status="pending",
            new_status="going",
            source="invite_response",
            changed_at=NOW - timedelta(days=1),
        ))
        db.session.add(SkiTripPlanningPost(
            trip_id=owned.id,
            user_id=viewer.id,
            category="Lodging",
            body="Booked the lodge",
            created_at=NOW - timedelta(days=2),
        ))

        forming = _make_trip(
            friend,
            resort,
            start_date=TODAY + timedelta(days=8),
            end_date=TODAY + timedelta(days=10),
            is_public=True,
        )
        forming.created_at = NOW - timedelta(days=1)
        db.session.flush()
        db.session.add(FriendConnectionEvent(
            user_a_id=min(viewer.id, friend.id),
            user_b_id=max(viewer.id, friend.id),
            event_type="formed",
            occurred_at=NOW.replace(tzinfo=timezone.utc) - timedelta(days=1),
            actor_user_id=viewer.id,
            source="friend_request_accept",
        ))
        db.session.commit()
        guest_name = f"{guest.first_name} {guest.last_name}".strip()
        forming_id = forming.id
        viewer_id = viewer.id
        friend_id = friend.id

        rows = get_home_happening_digest(
            user_id=viewer_id,
            friend_ids=[friend_id],
            now=NOW,
            today=TODAY,
        )

    assert [row["key"] for row in rows] == [
        "on_your_trips",
        "trips_forming",
        "your_people",
    ]
    categories = _category_map(rows)
    assert categories["on_your_trips"]["items"][0]["headline"] == f"{guest_name} joined"
    assert categories["trips_forming"]["items"][0]["trip_id"] == forming_id
    assert "new connection" in categories["your_people"]["items"][0]["headline"]


def test_digest_omits_old_mutable_updates_private_trips_and_nonfriends(client):
    with app.app_context():
        viewer = _make_user("digest-private-viewer")
        friend = _make_user("digest-private-friend")
        nonfriend = _make_user("digest-private-nonfriend")
        resort = _make_resort("Private Digest Peak")
        _connect(viewer, friend)
        old = _make_trip(
            friend,
            resort,
            start_date=TODAY + timedelta(days=3),
            end_date=TODAY + timedelta(days=5),
        )
        old.created_at = NOW - timedelta(days=20)
        old.updated_at = NOW
        private = _make_trip(
            friend,
            resort,
            start_date=TODAY + timedelta(days=3),
            end_date=TODAY + timedelta(days=5),
            is_public=False,
        )
        private.created_at = NOW
        outsider = _make_trip(
            nonfriend,
            resort,
            start_date=TODAY + timedelta(days=3),
            end_date=TODAY + timedelta(days=5),
        )
        outsider.created_at = NOW
        db.session.commit()

        rows = get_home_happening_digest(
            user_id=viewer.id,
            friend_ids=[friend.id],
            now=NOW,
            today=TODAY,
        )

    assert _category_map(rows).get("trips_forming") is None


def test_digest_query_count_is_constant_and_at_most_three(client):
    with app.app_context():
        viewer = _make_user("digest-budget-viewer")
        friend = _make_user("digest-budget-friend")
        resort = _make_resort("Budget Digest Peak")
        _connect(viewer, friend)
        for index in range(30):
            trip = _make_trip(
                friend,
                resort,
                start_date=TODAY + timedelta(days=index + 1),
                end_date=TODAY + timedelta(days=index + 2),
            )
            trip.created_at = NOW - timedelta(hours=index)
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            rows = get_home_happening_digest(
                user_id=viewer_id,
                friend_ids=[friend_id],
                now=NOW,
                today=TODAY,
            )
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)

    assert len(statements) == 3
    assert len(_category_map(rows)["trips_forming"]["items"]) == 3


def test_digest_rollup_dismissal_is_bounded_idempotent_and_user_scoped(client):
    with app.app_context():
        viewer = _make_user("digest-dismiss-viewer")
        viewer_id = viewer.id
        db.session.commit()
    _login(client, viewer_id)
    data = {
        "csrf_token": "test-csrf-fixed-value-baselodge-regression",
        "card_keys": ["happening:connection:1", "happening:connection:2"],
    }
    assert client.post("/dismiss-happening-digest", data=data).status_code == 204
    assert client.post("/dismiss-happening-digest", data=data).status_code == 204

    with app.app_context():
        from models import DismissedInsightCard
        assert DismissedInsightCard.query.filter_by(
            user_id=viewer_id,
            card_type="happening",
        ).count() == 2