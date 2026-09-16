"""PostgreSQL-only two-session concurrency coverage for BL-79."""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
import sqlalchemy as sa

from app import app
from models import (
    Friend,
    FriendConnectionEvent,
    FriendCooldown,
    Invitation,
    InviteType,
    db,
)
from services.connection_transitions import transition_connection
from tests.conftest import (
    _login,
    _make_user,
    _swap_engine,
    json_delete,
    json_post,
)


@pytest.fixture(scope="module")
def postgres_connection_database():
    database_url = os.environ.get("BL79_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("BL79_TEST_POSTGRES_URL is required for lock integration tests")
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    saved_engine = _swap_engine(engine)
    with app.app_context():
        db.drop_all()
        db.create_all()
    try:
        yield
    finally:
        with app.app_context():
            db.session.remove()
            db.drop_all()
        _swap_engine(saved_engine)


def _setup_pair(connected=False):
    with app.app_context():
        first = _make_user(f"pg-connection-first-{os.urandom(5).hex()}")
        second = _make_user(f"pg-connection-second-{os.urandom(5).hex()}")
        db.session.commit()
        if connected:
            transition_connection(
                user_id=first.id, other_user_id=second.id, connected=True,
                source="qr_connect",
            )
            db.session.commit()
        return first.id, second.id


def _concurrently(first_id, second_id, requests):
    barrier = Barrier(len(requests))

    def worker(args):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                result = transition_connection(
                    user_id=first_id, other_user_id=second_id, **args
                )
                db.session.commit()
                return result.changed, result.event.event_type if result.event else None
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(worker, requests))


def _pair_friend_count(first_id, second_id):
    return Friend.query.filter(
        Friend.user_id.in_((first_id, second_id)),
        Friend.friend_id.in_((first_id, second_id)),
    ).count()


def _pair_event_types(first_id, second_id):
    user_a_id, user_b_id = sorted((first_id, second_id))
    return [
        event.event_type
        for event in FriendConnectionEvent.query.filter_by(
            user_a_id=user_a_id,
            user_b_id=user_b_id,
        ).order_by(FriendConnectionEvent.id).all()
    ]


def test_concurrent_formation_writes_one_pair_and_formed_event(postgres_connection_database):
    first_id, second_id = _setup_pair()
    outcomes = _concurrently(first_id, second_id, [
        {"connected": True, "source": "qr_connect"},
        {"connected": True, "source": "qr_connect"},
    ])
    assert sorted(outcome[0] for outcome in outcomes) == [False, True]
    with app.app_context():
        assert _pair_friend_count(first_id, second_id) == 2
        assert _pair_event_types(first_id, second_id) == ["formed"]


def test_concurrent_removal_writes_one_removed_event(postgres_connection_database):
    first_id, second_id = _setup_pair(connected=True)
    outcomes = _concurrently(first_id, second_id, [
        {"connected": False, "source": "api_unfriend"},
        {"connected": False, "source": "api_unfriend"},
    ])
    assert sorted(outcome[0] for outcome in outcomes) == [False, True]
    with app.app_context():
        assert _pair_friend_count(first_id, second_id) == 0
        assert _pair_event_types(first_id, second_id) == ["formed", "removed"]


def test_concurrent_remove_and_reconnect_are_serialized(postgres_connection_database):
    first_id, second_id = _setup_pair(connected=True)
    outcomes = _concurrently(first_id, second_id, [
        {"connected": False, "source": "web_unfriend"},
        {"connected": True, "source": "group_trip_accept"},
    ])
    assert all(outcome[0] in {False, True} for outcome in outcomes)
    with app.app_context():
        events = _pair_event_types(first_id, second_id)
        # Either lock winner is valid, but the recorded history must be one
        # complete serial ordering rather than duplicate or partial events.
        assert events in (
            ["formed", "removed"],
            ["formed", "removed", "formed"],
        )
        assert _pair_friend_count(first_id, second_id) == (
            2 if events[-1] == "formed" else 0
        )


def test_concurrent_friend_request_accept_and_withdraw_serialize(
    postgres_connection_database,
):
    """PostgreSQL proves the Invitation FOR UPDATE behavior SQLite cannot."""
    with app.app_context():
        sender = _make_user(f"pg-invitation-sender-{os.urandom(5).hex()}")
        receiver = _make_user(f"pg-invitation-receiver-{os.urandom(5).hex()}")
        invitation = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add(invitation)
        db.session.commit()
        sender_id = sender.id
        receiver_id = receiver.id
        invitation_id = invitation.id

    barrier = Barrier(2)

    def worker(operation):
        client = app.test_client()
        user_id = receiver_id if operation == "accept" else sender_id
        _login(client, user_id)
        barrier.wait(timeout=10)
        try:
            if operation == "accept":
                response = json_post(
                    client,
                    f"/api/friends/invite/{invitation_id}/accept",
                )
            else:
                response = json_delete(
                    client,
                    f"/api/friends/invite/{invitation_id}",
                )
            return operation, response.status_code
        finally:
            with app.app_context():
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = dict(executor.map(worker, ("accept", "withdraw")))

    assert sorted(outcomes.values()) == [200, 409]
    with app.app_context():
        invitation = db.session.get(Invitation, invitation_id)
        friend_count = _pair_friend_count(sender_id, receiver_id)
        cooldown_count = FriendCooldown.query.filter_by(
            user_a_id=min(sender_id, receiver_id),
            user_b_id=max(sender_id, receiver_id),
        ).count()
        if invitation.status == "accepted":
            assert outcomes == {"accept": 200, "withdraw": 409}
            assert friend_count == 2
            assert cooldown_count == 0
            assert _pair_event_types(sender_id, receiver_id) == ["formed"]
        else:
            assert invitation.status == "cancelled"
            assert outcomes == {"accept": 409, "withdraw": 200}
            assert friend_count == 0
            assert cooldown_count == 1
            assert _pair_event_types(sender_id, receiver_id) == []