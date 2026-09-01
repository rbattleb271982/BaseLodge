"""Focused BL-79 connection lifecycle event and current-state privacy tests."""
from datetime import date, timedelta

import pytest

from app import app, _apply_invite_token, _connect_pending_inviter
from models import (
    db, Friend, FriendConnectionEvent, GroupTrip, GuestStatus, Invitation,
    InviteToken, InviteType, TripGuest,
)
from services.connection_transitions import transition_connection
from tests.conftest import _make_user, _login, form_post, json_delete, json_post


def _events(first_id, second_id):
    a_id, b_id = sorted((first_id, second_id))
    return FriendConnectionEvent.query.filter_by(
        user_a_id=a_id, user_b_id=b_id,
    ).order_by(FriendConnectionEvent.id).all()


def _assert_one_formed(first_id, second_id, *, actor_id, source):
    events = _events(first_id, second_id)
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "formed"
    assert event.actor_user_id == actor_id
    assert event.source == source


def _group_trip(host, *guests):
    trip = GroupTrip(
        host_id=host.id,
        title="BL-79 group trip",
        start_date=date.today() + timedelta(days=20),
        end_date=date.today() + timedelta(days=23),
    )
    db.session.add(trip)
    db.session.flush()
    for guest in guests:
        db.session.add(TripGuest(
            trip_id=trip.id, user_id=guest.id, status=GuestStatus.INVITED,
        ))
    db.session.flush()
    return trip


def _shared_trip(host, *members):
    trip = _group_trip(host, *members)
    db.session.add(TripGuest(
        trip_id=trip.id, user_id=host.id, status=GuestStatus.ACCEPTED,
    ))
    for guest in trip.guests:
        guest.status = GuestStatus.ACCEPTED
    return trip


def test_friend_request_accept_records_one_formed_event_and_is_noop_when_repeated(client):
    with app.app_context():
        sender, receiver = _make_user("request-sender"), _make_user("request-receiver")
        invitation = Invitation(
            sender_id=sender.id, receiver_id=receiver.id, trip_id=None,
            invite_type=InviteType.OUTBOUND, status="pending",
        )
        db.session.add(invitation)
        db.session.commit()
        sender_id, receiver_id, invitation_id = sender.id, receiver.id, invitation.id

    _login(client, receiver_id)
    assert json_post(client, f"/api/friends/invite/{invitation_id}/accept").status_code == 200
    assert json_post(client, f"/api/friends/invite/{invitation_id}/accept").status_code == 200
    with app.app_context():
        _assert_one_formed(
            sender_id, receiver_id, actor_id=receiver_id, source="friend_request_accept",
        )


def test_invite_token_helper_records_one_formed_event_and_is_idempotent(client):
    with app.app_context():
        inviter, recipient = _make_user("token-inviter"), _make_user("token-recipient")
        token = InviteToken(token="bl79-token", inviter_id=inviter.id)
        db.session.add(token)
        db.session.commit()
        assert _apply_invite_token(token, recipient) is True
        assert _apply_invite_token(token, recipient) is False
        _assert_one_formed(
            inviter.id, recipient.id, actor_id=recipient.id, source="invite_token_accept",
        )


@pytest.mark.parametrize("existing_direction", ["recipient_to_inviter", "inviter_to_recipient"])
def test_invite_token_confirm_repairs_one_sided_friendship_without_formed_event(
    client, existing_direction
):
    with app.app_context():
        inviter = _make_user(f"token-drift-inviter-{existing_direction}")
        recipient = _make_user(f"token-drift-recipient-{existing_direction}")
        token = InviteToken(
            token=f"bl79-token-drift-{existing_direction}",
            inviter_id=inviter.id,
        )
        if existing_direction == "recipient_to_inviter":
            db.session.add(Friend(user_id=recipient.id, friend_id=inviter.id))
        else:
            db.session.add(Friend(user_id=inviter.id, friend_id=recipient.id))
        db.session.add(token)
        db.session.commit()
        inviter_id, recipient_id, token_value = inviter.id, recipient.id, token.token

    _login(client, recipient_id)
    landing = client.get(f"/invite/{token_value}")
    assert landing.status_code == 200
    response = form_post(client, f"/invite/{token_value}/confirm")
    assert response.status_code == 200

    with app.app_context():
        assert Friend.query.filter(
            Friend.user_id.in_((inviter_id, recipient_id)),
            Friend.friend_id.in_((inviter_id, recipient_id)),
        ).count() == 2
        assert _events(inviter_id, recipient_id) == []


def test_pending_invite_token_continuation_repairs_drift_without_formed_event(client):
    with app.app_context():
        inviter = _make_user("continuation-drift-inviter")
        recipient = _make_user("continuation-drift-recipient")
        token = InviteToken(
            token="bl79-continuation-drift",
            inviter_id=inviter.id,
        )
        db.session.add_all([
            token,
            Friend(user_id=recipient.id, friend_id=inviter.id),
        ])
        db.session.commit()
        inviter_id, recipient_id = inviter.id, recipient.id

        with app.test_request_context("/"):
            from flask import session

            session["invite_token"] = token.token
            assert _connect_pending_inviter(recipient) is False

        assert Friend.query.filter(
            Friend.user_id.in_((inviter_id, recipient_id)),
            Friend.friend_id.in_((inviter_id, recipient_id)),
        ).count() == 2
        assert _events(inviter_id, recipient_id) == []


def test_qr_direct_connect_records_one_formed_event_and_is_noop_when_repeated(client):
    with app.app_context():
        inviter, recipient = _make_user("qr-inviter"), _make_user("qr-recipient")
        db.session.commit()
        inviter_id, recipient_id = inviter.id, recipient.id

    _login(client, recipient_id)
    assert form_post(client, f"/connect/{inviter_id}/add").status_code == 200
    assert form_post(client, f"/connect/{inviter_id}/add").status_code == 200
    with app.app_context():
        _assert_one_formed(inviter_id, recipient_id, actor_id=recipient_id, source="qr_connect")


def test_legacy_group_trip_accept_records_one_formed_event(client):
    with app.app_context():
        host, guest = _make_user("group-host"), _make_user("group-guest")
        trip = _group_trip(host, guest)
        db.session.commit()
        host_id, guest_id, trip_id = host.id, guest.id, trip.id

    _login(client, guest_id)
    assert form_post(client, f"/group-trip/{trip_id}/accept").status_code == 302
    with app.app_context():
        _assert_one_formed(host_id, guest_id, actor_id=guest_id, source="group_trip_accept")


def test_shared_trip_connect_records_one_formed_event_and_is_noop_when_repeated(client):
    with app.app_context():
        host, other = _make_user("shared-host"), _make_user("shared-other")
        _shared_trip(host, other)
        db.session.commit()
        host_id, other_id = host.id, other.id

    _login(client, host_id)
    assert form_post(client, f"/connect-from-trip/{other_id}").status_code == 302
    assert form_post(client, f"/connect-from-trip/{other_id}").status_code == 302
    with app.app_context():
        _assert_one_formed(
            host_id, other_id, actor_id=host_id, source="shared_trip_connect",
        )


@pytest.mark.parametrize(
    ("route_kind", "source"),
    [("api", "api_unfriend"), ("web", "web_unfriend")],
)
def test_each_unfriend_route_writes_one_removed_event(client, route_kind, source):
    with app.app_context():
        first, second = _make_user(f"{route_kind}-first"), _make_user(f"{route_kind}-second")
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=True,
            source="qr_connect", actor_user_id=first.id,
        )
        db.session.commit()
        first_id, second_id = first.id, second.id

    _login(client, first_id)
    response = (
        json_delete(client, f"/api/friends/{second_id}")
        if route_kind == "api"
        else form_post(client, f"/friends/{second_id}/remove")
    )
    assert response.status_code in (200, 302)
    with app.app_context():
        events = _events(first_id, second_id)
        assert [event.event_type for event in events] == ["formed", "removed"]
        assert events[-1].actor_user_id == first_id
        assert events[-1].source == source


def test_reconnection_preserves_formed_removed_formed_history(client):
    with app.app_context():
        first, second = _make_user("reconnect-first"), _make_user("reconnect-second")
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=True,
            source="qr_connect", actor_user_id=first.id,
        )
        db.session.commit()
        first_id, second_id = first.id, second.id

    _login(client, first_id)
    assert json_delete(client, f"/api/friends/{second_id}").status_code == 200
    with app.app_context():
        transition_connection(
            user_id=first_id, other_user_id=second_id, connected=True,
            source="shared_trip_connect", actor_user_id=second_id,
        )
        db.session.commit()
        events = _events(first_id, second_id)
        assert [event.event_type for event in events] == ["formed", "removed", "formed"]
        assert [event.source for event in events] == [
            "qr_connect", "api_unfriend", "shared_trip_connect",
        ]


def test_historical_event_alone_does_not_authorize_profile_or_trip_invitation(client):
    with app.app_context():
        creator, target = _make_user("historical-creator"), _make_user("historical-target")
        transition_connection(
            user_id=creator.id, other_user_id=target.id, connected=True,
            source="qr_connect", actor_user_id=creator.id,
        )
        transition_connection(
            user_id=creator.id, other_user_id=target.id, connected=False,
            source="api_unfriend", actor_user_id=creator.id,
        )
        db.session.commit()
        creator_id, target_id = creator.id, target.id

    _login(client, creator_id)
    assert client.get(f"/friends/{target_id}").status_code == 403
    start = date.today() + timedelta(days=30)
    response = json_post(client, "/api/trip/create", {
        "mountain": "Privacy Peak", "state": "CO",
        "start_date": start.isoformat(), "end_date": (start + timedelta(days=2)).isoformat(),
        "is_public": True, "friend_id": target_id,
    })
    assert response.status_code == 403


def test_former_friend_loses_friend_profile_access(client):
    with app.app_context():
        first, second = _make_user("former-first"), _make_user("former-second")
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=True,
            source="qr_connect", actor_user_id=first.id,
        )
        transition_connection(
            user_id=first.id, other_user_id=second.id, connected=False,
            source="api_unfriend", actor_user_id=first.id,
        )
        db.session.commit()
        first_id, second_id = first.id, second.id

    _login(client, first_id)
    assert client.get(f"/friends/{second_id}").status_code == 403