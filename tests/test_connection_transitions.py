import pytest
from sqlalchemy.exc import IntegrityError

from app import app
from conftest import _make_user
from models import Friend, FriendConnectionEvent, db
from services.connection_transitions import transition_connection


def _users(label):
    first = _make_user(f"{label}-first")
    second = _make_user(f"{label}-second")
    return first, second


def _directions(first_id, second_id):
    return {
        (row.user_id, row.friend_id)
        for row in Friend.query.filter(
            Friend.user_id.in_((first_id, second_id)),
            Friend.friend_id.in_((first_id, second_id)),
        )
    }


def test_formation_creates_canonical_pair_and_single_formed_event(client):
    with app.app_context():
        first, second = _users("form")
        result = transition_connection(
            user_id=second.id, other_user_id=first.id, connected=True,
            source="friend_request_accept", actor_user_id=second.id,
        )

        assert (result.user_a_id, result.user_b_id) == (first.id, second.id)
        assert result.changed is True
        assert result.formed is True
        assert _directions(first.id, second.id) == {
            (first.id, second.id), (second.id, first.id),
        }
        event = FriendConnectionEvent.query.one()
        assert (event.user_a_id, event.user_b_id, event.event_type) == (
            first.id, second.id, "formed"
        )


def test_formation_retry_and_reverse_order_are_idempotent(client):
    with app.app_context():
        first, second = _users("retry")
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=True,
            source="qr_connect",
        )
        retry = transition_connection(
            user_id=second.id, other_user_id=first.id, connected=True,
            source="qr_connect",
        )

        assert retry.changed is False
        assert retry.repaired is False
        assert retry.preexisting_row_count == 2
        assert retry.event is None
        assert FriendConnectionEvent.query.count() == 1


def test_removal_retry_is_idempotent(client):
    with app.app_context():
        first, second = _users("remove-retry")
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=True,
            source="invite_token_accept",
        )
        removed = transition_connection(
            user_id=first.id, other_user_id=second.id, connected=False,
            source="api_unfriend",
        )
        retry = transition_connection(
            user_id=second.id, other_user_id=first.id, connected=False,
            source="api_unfriend",
        )

        assert removed.removed is True
        assert retry.changed is False
        assert retry.event is None
        assert Friend.query.count() == 0
        assert [event.event_type for event in FriendConnectionEvent.query.order_by(
            FriendConnectionEvent.id
        )] == ["formed", "removed"]


def test_reconnection_appends_ordered_lifecycle_chain(client):
    with app.app_context():
        first, second = _users("chain")
        for connected, source in (
            (True, "shared_trip_connect"),
            (False, "web_unfriend"),
            (True, "group_trip_accept"),
        ):
            transition_connection(
                user_id=first.id, other_user_id=second.id,
                connected=connected, source=source,
            )

        events = FriendConnectionEvent.query.order_by(
            FriendConnectionEvent.id
        ).all()
        assert [event.event_type for event in events] == [
            "formed", "removed", "formed"
        ]
        assert all(
            (event.user_a_id, event.user_b_id) == (first.id, second.id)
            for event in events
        )


def test_one_sided_formation_repairs_without_formed_event(client):
    with app.app_context():
        first, second = _users("repair")
        db.session.add(Friend(user_id=first.id, friend_id=second.id))
        db.session.flush()

        result = transition_connection(
            user_id=second.id, other_user_id=first.id, connected=True,
            source="qr_connect",
        )

        assert result.changed is True
        assert result.repaired is True
        assert result.event is None
        assert _directions(first.id, second.id) == {
            (first.id, second.id), (second.id, first.id),
        }
        assert FriendConnectionEvent.query.count() == 0


def test_one_sided_removal_deletes_row_and_emits_removed_event(client):
    with app.app_context():
        first, second = _users("one-sided-remove")
        db.session.add(Friend(user_id=second.id, friend_id=first.id))
        db.session.flush()

        result = transition_connection(
            user_id=first.id, other_user_id=second.id, connected=False,
            source="web_unfriend",
        )

        assert result.preexisting_row_count == 1
        assert result.changed is True
        assert result.removed is True
        assert Friend.query.count() == 0


def test_transition_is_atomic_under_caller_rollback(client):
    with app.app_context():
        first, second = _users("rollback")
        first_id, second_id = first.id, second.id
        db.session.commit()

        transition_connection(
            user_id=first_id, other_user_id=second_id, connected=True,
            source="friend_request_accept",
        )
        db.session.rollback()

        assert _directions(first_id, second_id) == set()
        assert FriendConnectionEvent.query.count() == 0


@pytest.mark.parametrize(
    ("user_id", "other_user_id", "source"),
    [(1, 1, "qr_connect"), ("1", 2, "qr_connect"), (1, 2, "invalid")],
)
def test_rejects_self_noninteger_subjects_and_invalid_source(
    client, user_id, other_user_id, source
):
    with app.app_context():
        with pytest.raises(ValueError):
            transition_connection(
                user_id=user_id, other_user_id=other_user_id,
                connected=True, source=source,
            )


def test_history_model_constraints_and_events_are_append_only(client):
    with app.app_context():
        first, second = _users("checks")
        first_id, second_id = first.id, second.id
        db.session.commit()
        for values in (
            {"user_a_id": second_id, "user_b_id": first_id, "event_type": "formed",
             "source": "qr_connect"},
            {"user_a_id": first_id, "user_b_id": second_id, "event_type": "other",
             "source": "qr_connect"},
            {"user_a_id": first_id, "user_b_id": second_id, "event_type": "formed",
             "source": "unknown"},
        ):
            db.session.add(FriendConnectionEvent(**values))
            with pytest.raises(IntegrityError):
                db.session.flush()
            db.session.rollback()

        transition_connection(
            user_id=first_id, other_user_id=second_id, connected=True,
            source="qr_connect",
        )
        transition_connection(
            user_id=first_id, other_user_id=second_id, connected=False,
            source="api_unfriend",
        )
        assert [event.event_type for event in FriendConnectionEvent.query.order_by(
            FriendConnectionEvent.id
        )] == ["formed", "removed"]