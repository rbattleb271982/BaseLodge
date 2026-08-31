"""BL-78 — route-level coverage for private canonical RSVP history."""

from datetime import date, timedelta
from unittest import mock

import pytest

from app import app
from models import (
    Friend,
    GuestStatus,
    Invitation,
    InviteType,
    SkiTrip,
    SkiTripParticipant,
    SkiTripRsvpTransition,
    TripInviteToken,
    db,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_trip,
    _make_user,
    form_post,
    json_post,
)


def _history(trip_id, user_id):
    return [
        (row.previous_status, row.new_status, row.source, row.actor_user_id)
        for row in SkiTripRsvpTransition.query.filter_by(
            trip_id=trip_id, user_id=user_id
        ).order_by(SkiTripRsvpTransition.id)
    ]


def _trip_payload(friend_id):
    start = date.today() + timedelta(days=120)
    return {
        "mountain": "BL78 Peak",
        "state": "CO",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=3)).isoformat(),
        "friend_id": friend_id,
    }


def test_creation_optional_guest_records_initial_invite_but_not_owner(client):
    with app.app_context():
        owner, guest = _make_user("create-owner"), _make_user("create-guest")
        db.session.add(Friend(user_id=owner.id, friend_id=guest.id))
        db.session.commit()
        owner_id, guest_id = owner.id, guest.id

    _login(client, owner_id)
    assert json_post(client, "/api/trip/create", _trip_payload(guest_id)).status_code == 200

    with app.app_context():
        trip_id = SkiTripParticipant.query.filter_by(user_id=guest_id).one().trip_id
        assert _history(trip_id, guest_id) == [
            (None, "pending", "trip_creation_invite", owner_id)
        ]
        assert _history(trip_id, owner_id) == []


def test_organizer_invite_and_cancel_are_idempotent_history_transitions(client):
    with app.app_context():
        owner, guest = _make_user("invite-owner"), _make_user("invite-guest")
        trip = _make_trip(owner)
        db.session.add(Friend(user_id=owner.id, friend_id=guest.id))
        db.session.commit()
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id

    _login(client, owner_id)
    assert form_post(client, f"/trips/{trip_id}/invite", {"friend_ids": str(guest_id)}).status_code == 302
    # A duplicate pending invite is deliberately a no-op.
    assert form_post(client, f"/trips/{trip_id}/invite", {"friend_ids": str(guest_id)}).status_code == 302
    assert form_post(client, f"/trips/{trip_id}/invite/cancel", {"user_id": guest_id}).status_code == 302
    # The general invite route can also reinvite a terminal relationship.
    assert form_post(client, f"/trips/{trip_id}/invite", {"friend_ids": str(guest_id)}).status_code == 302

    with app.app_context():
        assert _history(trip_id, guest_id) == [
            (None, "pending", "organizer_invite", owner_id),
            ("pending", "removed", "invite_cancel", owner_id),
            ("removed", "pending", "organizer_invite", owner_id),
        ]


def test_token_response_establishes_or_answers_pending_without_duplicate(client):
    with app.app_context():
        owner, absent, pending = (
            _make_user("token-owner"),
            _make_user("token-absent"),
            _make_user("token-pending"),
        )
        trip = _make_trip(owner)
        _add_participant(trip, pending, GuestStatus.PENDING)
        token = TripInviteToken(token="bl78-token", trip_id=trip.id, inviter_user_id=owner.id)
        db.session.add(token)
        db.session.commit()
        trip_id, owner_id, absent_id, pending_id = trip.id, owner.id, absent.id, pending.id

    _login(client, absent_id)
    assert form_post(client, "/trip-invite/bl78-token/accept", {"response": "interested"}).status_code == 302
    _login(client, pending_id)
    assert form_post(client, "/trip-invite/bl78-token/accept", {"response": "going"}).status_code == 302
    # Active repeat is intercepted before the transition service.
    assert form_post(client, "/trip-invite/bl78-token/accept", {"response": "going"}).status_code == 302

    with app.app_context():
        assert _history(trip_id, absent_id) == [
            (None, "interested", "token_response", absent_id)
        ]
        assert _history(trip_id, pending_id) == [
            ("pending", "going", "token_response", pending_id)
        ]
        assert SkiTripParticipant.query.filter_by(trip_id=trip_id, user_id=owner_id).one()


@pytest.mark.parametrize("response_status", ["going", "declined"])
def test_token_response_records_each_remaining_initial_guest_state(
    client, response_status
):
    with app.app_context():
        owner = _make_user(f"token-initial-owner-{response_status}")
        guest = _make_user(f"token-initial-guest-{response_status}")
        trip = _make_trip(owner)
        token_value = f"bl78-token-initial-{response_status}"
        db.session.add(TripInviteToken(
            token=token_value,
            trip_id=trip.id,
            inviter_user_id=owner.id,
        ))
        db.session.commit()
        trip_id, guest_id = trip.id, guest.id

    _login(client, guest_id)
    response = form_post(
        client,
        f"/trip-invite/{token_value}/accept",
        {"response": response_status},
    )

    assert response.status_code == 302
    with app.app_context():
        assert _history(trip_id, guest_id) == [
            (None, response_status, "token_response", guest_id)
        ]
        assert (
            db.session.get(SkiTrip, trip_id).is_group_trip
            is (response_status == "going")
        )


def test_direct_response_records_change_only_and_cannot_reactivate(client):
    with app.app_context():
        owner, guest = _make_user("response-owner"), _make_user("response-guest")
        trip = _make_trip(owner)
        participant = _add_participant(trip, guest, GuestStatus.PENDING)
        db.session.commit()
        trip_id, guest_id, participant_id = trip.id, guest.id, participant.id

    _login(client, guest_id)
    assert json_post(client, f"/trips/{trip_id}/respond", {"response": "declined"}).status_code == 200
    assert json_post(client, f"/trips/{trip_id}/respond", {"response": "declined"}).status_code == 200
    assert json_post(client, f"/trips/{trip_id}/respond", {"response": "going"}).status_code == 403
    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).status == GuestStatus.DECLINED
        assert _history(trip_id, guest_id) == [
            ("pending", "declined", "invite_response", guest_id)
        ]


def test_self_and_organizer_rsvp_and_leave_have_distinct_sources(client):
    with app.app_context():
        owner, guest = _make_user("rsvp-owner"), _make_user("rsvp-guest")
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.INTERESTED)
        db.session.commit()
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id

    _login(client, guest_id)
    assert json_post(client, f"/trips/{trip_id}/rsvp", {"response": "going"}).status_code == 200
    assert json_post(client, f"/trips/{trip_id}/rsvp", {"response": "interested"}).status_code == 200
    _login(client, owner_id)
    assert json_post(client, f"/trips/{trip_id}/participants/{guest_id}/rsvp", {"response": "going"}).status_code == 200
    _login(client, guest_id)
    assert form_post(client, f"/trips/{trip_id}/leave").status_code == 302

    with app.app_context():
        assert _history(trip_id, guest_id) == [
            ("interested", "going", "self_rsvp", guest_id),
            ("going", "interested", "self_rsvp", guest_id),
            ("interested", "going", "organizer_rsvp", owner_id),
            ("going", "declined", "participant_leave", guest_id),
        ]


def test_removal_reinvite_and_join_accept_record_expected_actor(client):
    with app.app_context():
        owner, guest, requester = (
            _make_user("manage-owner"),
            _make_user("manage-guest"),
            _make_user("manage-requester"),
        )
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.GOING)
        request = Invitation(
            sender_id=requester.id, receiver_id=owner.id, trip_id=trip.id,
            invite_type=InviteType.REQUEST, status="pending",
        )
        db.session.add(request)
        db.session.commit()
        trip_id, owner_id, guest_id, requester_id, request_id = (
            trip.id, owner.id, guest.id, requester.id, request.id
        )

    _login(client, owner_id)
    assert json_post(client, f"/trips/{trip_id}/participants/{guest_id}/remove", {"confirm": "remove"}).status_code == 200
    assert json_post(client, f"/trips/{trip_id}/participants/{guest_id}/reinvite").status_code == 200
    assert json_post(client, f"/trips/requests/{request_id}/respond", {"action": "accept"}).status_code == 200
    with app.app_context():
        assert _history(trip_id, guest_id)[-2:] == [
            ("going", "removed", "organizer_remove", owner_id),
            ("removed", "pending", "organizer_reinvite", owner_id),
        ]
        assert _history(trip_id, requester_id) == [
            (None, "interested", "join_request_accept", owner_id)
        ]


def test_attendance_changes_do_not_create_history_and_detail_does_not_expose_it(client):
    with app.app_context():
        owner, guest = _make_user("detail-owner"), _make_user("detail-guest")
        trip = _make_trip(owner)
        _add_participant(trip, guest, GuestStatus.GOING)
        db.session.commit()
        trip_id, owner_id, guest_id = trip.id, owner.id, guest.id
        start_date, end_date = trip.start_date, trip.end_date

    _login(client, guest_id)
    assert json_post(client, f"/api/trips/{trip_id}/participant/dates", {
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
    }).status_code == 200
    assert json_post(client, f"/trips/{trip_id}/rsvp", {"response": "going"}).status_code == 200
    with app.app_context():
        assert _history(trip_id, guest_id) == []
        saved = SkiTripParticipant.query.filter_by(trip_id=trip_id, user_id=guest_id).one()
        assert saved.start_date is not None
    _login(client, owner_id)
    html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert 'data-participant-status="going"' in html
    assert "self_rsvp" not in html and "SkiTripRsvpTransition" not in html


def test_leave_commit_or_history_insert_failure_rolls_back_both_records(client):
    for failure_target in ("commit", "history"):
        with app.app_context():
            owner, guest = _make_user(f"fail-owner-{failure_target}"), _make_user(f"fail-guest-{failure_target}")
            trip = _make_trip(owner)
            participant = _add_participant(trip, guest, GuestStatus.GOING)
            db.session.commit()
            trip_id, guest_id, participant_id = trip.id, guest.id, participant.id

        _login(client, guest_id)
        if failure_target == "commit":
            patcher = mock.patch("app.db.session.commit", side_effect=RuntimeError("commit failed"))
        else:
            patcher = mock.patch(
                "services.rsvp_transitions.db.session.add",
                side_effect=RuntimeError("history insert failed"),
            )
        with patcher:
            assert form_post(client, f"/trips/{trip_id}/leave").status_code == 302
        with app.app_context():
            assert SkiTripParticipant.query.get(participant_id).status == GuestStatus.GOING
            assert _history(trip_id, guest_id) == []