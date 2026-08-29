"""Focused BL-121 authorization coverage for POST /api/trip/create."""
from datetime import date, timedelta
from unittest import mock

import pytest

import app as app_module
from app import app
from conftest import _login, _make_user, json_post
from models import (
    Friend,
    GuestStatus,
    Invitation,
    InviteType,
    SkiTrip,
    SkiTripParticipant,
    User,
    db,
)


def _trip_payload(**overrides):
    start_date = date.today() + timedelta(days=30)
    payload = {
        "mountain": "Authorization Peak",
        "state": "CO",
        "start_date": start_date.isoformat(),
        "end_date": (start_date + timedelta(days=2)).isoformat(),
        "is_public": True,
    }
    payload.update(overrides)
    return payload


def _post_with_side_effect_spies(client, payload):
    with (
        mock.patch("app.emit_messaging_event") as messaging,
        mock.patch("app.emit_event") as event,
        mock.patch.object(app_module.ph_analytics, "track") as analytics,
    ):
        response = json_post(client, "/api/trip/create", payload)
    return response, messaging, event, analytics


def _assert_no_side_effects(user_id, messaging, event, analytics):
    with app.app_context():
        user = db.session.get(User, user_id)
        assert SkiTrip.query.count() == 0
        assert SkiTripParticipant.query.count() == 0
        assert user.first_trip_created_at is None
        assert user.first_planning_timestamp is None
        assert user.lifecycle_stage == "active"
    messaging.assert_not_called()
    event.assert_not_called()
    analytics.assert_not_called()


@pytest.mark.parametrize("friend_id", ["abc", "", 1.5, True, [], {}])
def test_malformed_friend_id_is_rejected_without_side_effects(client, friend_id):
    with app.app_context():
        creator = _make_user("malformed-creator")
        db.session.commit()
        creator_id = creator.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=friend_id),
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "Invalid friend_id.",
    }
    _assert_no_side_effects(creator_id, messaging, event, analytics)


def test_self_invite_is_rejected_without_side_effects(client):
    with app.app_context():
        creator = _make_user("self-creator")
        db.session.commit()
        creator_id = creator.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=str(creator_id)),
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "You cannot invite yourself.",
    }
    _assert_no_side_effects(creator_id, messaging, event, analytics)


def test_nonexistent_user_is_rejected_with_generic_forbidden_response(client):
    with app.app_context():
        creator = _make_user("missing-creator")
        db.session.commit()
        creator_id = creator.id
        nonexistent_id = creator_id + 100000

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=nonexistent_id),
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "Not authorized to invite this user.",
    }
    _assert_no_side_effects(creator_id, messaging, event, analytics)


def test_existing_nonfriend_gets_same_generic_forbidden_response(client):
    with app.app_context():
        creator = _make_user("nonfriend-creator")
        nonfriend = _make_user("nonfriend-target")
        db.session.commit()
        creator_id = creator.id
        nonfriend_id = nonfriend.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=nonfriend_id),
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "Not authorized to invite this user.",
    }
    _assert_no_side_effects(creator_id, messaging, event, analytics)


@pytest.mark.parametrize("invitation_status", ["pending", "declined", "cancelled"])
def test_friend_request_record_without_friend_row_does_not_qualify(
    client, invitation_status
):
    with app.app_context():
        creator = _make_user(f"{invitation_status}-creator")
        target = _make_user(f"{invitation_status}-target")
        db.session.add(Invitation(
            sender_id=creator.id,
            receiver_id=target.id,
            status=invitation_status,
            invite_type=InviteType.OUTBOUND,
        ))
        db.session.commit()
        creator_id = creator.id
        target_id = target.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=target_id),
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "Not authorized to invite this user.",
    }
    _assert_no_side_effects(creator_id, messaging, event, analytics)


def test_reverse_only_friend_row_does_not_qualify(client):
    with app.app_context():
        creator = _make_user("reverse-creator")
        target = _make_user("reverse-target")
        db.session.add(Friend(user_id=target.id, friend_id=creator.id))
        db.session.commit()
        creator_id = creator.id
        target_id = target.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=target_id),
    )

    assert response.status_code == 403
    _assert_no_side_effects(creator_id, messaging, event, analytics)


def test_outgoing_friend_row_allows_invite_without_reverse_row(client):
    with app.app_context():
        creator = _make_user("friend-creator")
        friend = _make_user("friend-target")
        db.session.add(Friend(user_id=creator.id, friend_id=friend.id))
        db.session.commit()
        creator_id = creator.id
        friend_id = friend.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(friend_id=str(friend_id)),
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with app.app_context():
        trip = SkiTrip.query.one()
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=friend_id,
        ).one()
        assert participant.status == GuestStatus.PENDING
        assert trip.is_group_trip is True
    messaging.assert_called_once()
    event.assert_called_once()
    analytics.assert_called_once()


@pytest.mark.parametrize("friend_field", [{}, {"friend_id": None}])
def test_absent_or_null_friend_id_preserves_solo_trip_creation(client, friend_field):
    with app.app_context():
        creator = _make_user("solo-creator")
        db.session.commit()
        creator_id = creator.id

    _login(client, creator_id)
    response, messaging, event, analytics = _post_with_side_effect_spies(
        client,
        _trip_payload(**friend_field),
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with app.app_context():
        trip = SkiTrip.query.one()
        participants = SkiTripParticipant.query.filter_by(trip_id=trip.id).all()
        assert len(participants) == 1
        assert participants[0].user_id == creator_id
        assert trip.is_group_trip is False
    messaging.assert_not_called()
    event.assert_called_once()
    analytics.assert_called_once()