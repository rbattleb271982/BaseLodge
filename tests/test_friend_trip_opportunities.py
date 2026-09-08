"""Focused BL-110 friend-trip discovery producer and delivery coverage."""

from datetime import date, datetime, timedelta
import json
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from app import app
from models import (
    Friend,
    GuestStatus,
    Invitation,
    InviteType,
    MessageOutbox,
    MessagingDeliveryPolicy,
    MessagingDeliveryPolicyEvent,
    PushDeviceToken,
    SkiTrip,
    SkiTripParticipant,
    db,
)
from services.friend_trip_opportunities import (
    stage_friend_trip_created_opportunity,
)
from services.message_dispatch import (
    message_outbox_opportunity_start_callback,
    message_outbox_provider_callback,
    message_outbox_safety_callback,
)
from services.message_outbox_worker import run_worker
from services.messaging_constants import EventName, SuppressionReason
from services.opportunity_messaging import opportunity_occurrence_id
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    form_post,
    json_post,
)


def _register_bl110(*, paused=True, boundary=None):
    policy = MessagingDeliveryPolicy(
        event_name=EventName.FRIEND_TRIP_CREATED,
        delivery_mode="enqueue_only",
        claims_paused=True,
        cutover_epoch=1,
        control_revision=1,
        operator_reason="test BL-110",
        audit_identity="test",
    )
    db.session.add(policy)
    db.session.flush()
    activation = MessagingDeliveryPolicyEvent(
        event_name=policy.event_name,
        delivery_mode=policy.delivery_mode,
        cutover_epoch=policy.cutover_epoch,
        claims_paused=True,
        control_revision=policy.control_revision,
        action="opportunity_registered",
        operator_reason="test BL-110 activation",
        audit_identity="test",
        created_at=boundary or datetime.utcnow() - timedelta(seconds=1),
    )
    db.session.add(activation)
    db.session.flush()
    policy.claims_paused = paused
    db.session.flush()
    return policy, activation


def _connect(first, second, *, reciprocal=True):
    db.session.add(Friend(user_id=first.id, friend_id=second.id))
    if reciprocal:
        db.session.add(Friend(user_id=second.id, friend_id=first.id))
    db.session.flush()


def _stage(trip):
    return stage_friend_trip_created_opportunity(
        trip.id,
        session=db.session,
        source_route="test_bl110",
    )


def _rows(trip_id):
    return MessageOutbox.query.filter_by(
        event_name=EventName.FRIEND_TRIP_CREATED,
        object_type="trip",
        object_id=trip_id,
    ).order_by(MessageOutbox.recipient_user_id).all()


def _recipient_row(trip, recipient):
    return MessageOutbox.query.filter_by(
        event_name=EventName.FRIEND_TRIP_CREATED,
        object_id=trip.id,
        recipient_user_id=recipient.id,
    ).one()


def _add_token(user, *, active=True):
    db.session.add(PushDeviceToken(
        user_id=user.id,
        token=f"token-{user.id}",
        platform="ios",
        active=active,
    ))
    db.session.flush()


def _deliverable_setup(*, resort=True, legacy_mountain=None, paused=True):
    _register_bl110(paused=paused)
    owner = _make_user("bl110-owner")
    owner.first_name = "Avery"
    friend = _make_user("bl110-friend")
    _connect(owner, friend)
    canonical = _make_resort("Canonical Peak") if resort else None
    trip = _make_trip(
        owner,
        resort=canonical,
        **(
            {}
            if canonical
            else {"mountain": legacy_mountain or "Legacy Peak"}
        ),
    )
    if legacy_mountain is not None:
        trip.mountain = legacy_mountain
    _add_token(friend)
    result = _stage(trip)
    db.session.flush()
    return owner, friend, trip, result


def test_json_public_creation_stages_marker_and_friend(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("json-owner")
        friend = _make_user("json-friend")
        resort = _make_resort()
        _connect(owner, friend)
        db.session.commit()
        owner_id, friend_id, resort_id = owner.id, friend.id, resort.id

    _login(client, owner_id)
    start = date.today() + timedelta(days=20)
    response = json_post(client, "/api/trip/create", {
        "resort_id": resort_id,
        "mountain": "ignored legacy label",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "is_public": True,
    })
    assert response.status_code == 200
    trip_id = response.get_json()["trip"]["id"]
    with app.app_context():
        assert {row.recipient_user_id for row in _rows(trip_id)} == {
            owner_id, friend_id
        }


def test_standard_form_public_creation_stages_marker_and_friend(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("form-owner")
        friend = _make_user("form-friend")
        resort = _make_resort()
        _connect(owner, friend)
        db.session.commit()
        owner_id, friend_id, resort_id = owner.id, friend.id, resort.id

    _login(client, owner_id)
    start = date.today() + timedelta(days=20)
    response = form_post(client, "/add_trip", {
        "resort_id": str(resort_id),
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "trip_status": "planning",
        "is_public": "on",
    })
    assert response.status_code == 302
    with app.app_context():
        trip = SkiTrip.query.filter_by(user_id=owner_id).one()
        assert {row.recipient_user_id for row in _rows(trip.id)} == {
            owner_id, friend_id
        }


def test_multi_date_form_consumes_each_trip_independently(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("multi-owner")
        friend = _make_user("multi-friend")
        resort = _make_resort()
        _connect(owner, friend)
        db.session.commit()
        owner_id, friend_id, resort_id = owner.id, friend.id, resort.id

    first = date.today() + timedelta(days=20)
    second = date.today() + timedelta(days=40)
    _login(client, owner_id)
    response = form_post(client, "/add_trip", {
        "resort_id": str(resort_id),
        "date_ranges_json": json.dumps([
            {
                "start_date": first.isoformat(),
                "end_date": (first + timedelta(days=2)).isoformat(),
            },
            {
                "start_date": second.isoformat(),
                "end_date": (second + timedelta(days=3)).isoformat(),
            },
        ]),
        "trip_status": "planning",
        "is_public": "on",
    })
    assert response.status_code == 302
    with app.app_context():
        trips = SkiTrip.query.filter_by(user_id=owner_id).order_by(SkiTrip.id).all()
        assert len(trips) == 2
        for trip in trips:
            assert {row.recipient_user_id for row in _rows(trip.id)} == {
                owner_id, friend_id
            }


def test_private_creation_consumes_only_on_first_public_transition(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("private-owner")
        friend = _make_user("private-friend")
        resort = _make_resort()
        _connect(owner, friend)
        db.session.commit()
        owner_id, friend_id, resort_id = owner.id, friend.id, resort.id

    start = date.today() + timedelta(days=20)
    _login(client, owner_id)
    created = json_post(client, "/api/trip/create", {
        "resort_id": resort_id,
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "is_public": False,
    })
    trip_id = created.get_json()["trip"]["id"]
    with app.app_context():
        assert _rows(trip_id) == []

    public = json_post(
        client,
        f"/api/trip/{trip_id}/update-visibility",
        {"is_public": True},
    )
    assert public.status_code == 200
    private = json_post(
        client,
        f"/api/trip/{trip_id}/update-visibility",
        {"is_public": False},
    )
    assert private.status_code == 200
    public_again = json_post(
        client,
        f"/api/trip/{trip_id}/update-visibility",
        {"is_public": True},
    )
    assert public_again.status_code == 200
    with app.app_context():
        assert {row.recipient_user_id for row in _rows(trip_id)} == {
            owner_id, friend_id
        }
        assert len(_rows(trip_id)) == 2


def test_creation_invitee_consumes_occurrence_but_is_suppressed_at_send(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("creation-invite-owner")
        friend = _make_user("creation-invite-friend")
        resort = _make_resort()
        _connect(owner, friend)
        _add_token(friend)
        db.session.commit()
        owner_id, friend_id, resort_id = owner.id, friend.id, resort.id

    start = date.today() + timedelta(days=20)
    _login(client, owner_id)
    response = json_post(client, "/api/trip/create", {
        "resort_id": resort_id,
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "is_public": True,
        "friend_id": friend_id,
    })
    assert response.status_code == 200
    trip_id = response.get_json()["trip"]["id"]
    with app.app_context():
        row = MessageOutbox.query.filter_by(
            event_name=EventName.FRIEND_TRIP_CREATED,
            object_id=trip_id,
            recipient_user_id=friend_id,
        ).one()
        assert SkiTripParticipant.query.filter_by(
            trip_id=trip_id,
            user_id=friend_id,
            status=GuestStatus.PENDING,
        ).one()
        decision = message_outbox_safety_callback(row)
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.PRIVACY_DENIED


def test_zero_friends_still_writes_non_deliverable_self_marker(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("zero-owner")
        trip = _make_trip(owner)
        result = _stage(trip)
        rows = _rows(trip.id)
        assert result.consumed is True
        assert result.recipient_user_ids == ()
        assert len(rows) == 1
        assert rows[0].recipient_user_id == owner.id
        decision = message_outbox_safety_callback(rows[0])
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.SENDER_IS_RECIPIENT


def test_later_friendship_does_not_resurrect_consumed_trip(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("later-owner")
        later_friend = _make_user("later-friend")
        trip = _make_trip(owner)
        first = _stage(trip)
        _connect(owner, later_friend)
        second = _stage(trip)
        assert first.consumed is True
        assert second.consumed is False
        assert second.reason == "already_consumed"
        assert [row.recipient_user_id for row in _rows(trip.id)] == [owner.id]


def test_only_reciprocal_current_friends_are_selected(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("selection-owner")
        reciprocal = _make_user("reciprocal")
        one_way = _make_user("one-way")
        removed = _make_user("removed")
        _connect(owner, reciprocal)
        _connect(owner, one_way, reciprocal=False)
        _connect(owner, removed)
        Friend.query.filter_by(user_id=removed.id, friend_id=owner.id).delete()
        trip = _make_trip(owner)
        result = _stage(trip)
        assert result.recipient_user_ids == (reciprocal.id,)
        assert {row.recipient_user_id for row in _rows(trip.id)} == {
            owner.id, reciprocal.id
        }


@pytest.mark.parametrize(
    "mutation",
    ["private", "completed", "cancelled", "past", "missing_dates", "pre_boundary"],
)
def test_ineligible_trip_states_do_not_consume(client, mutation):
    with app.app_context():
        boundary = datetime.utcnow() - timedelta(seconds=1)
        _register_bl110(boundary=boundary)
        owner = _make_user(f"ineligible-{mutation}")
        trip = _make_trip(owner)
        if mutation == "private":
            trip.is_public = False
        elif mutation in {"completed", "cancelled"}:
            trip.lifecycle_state = mutation
        elif mutation == "past":
            trip.start_date = date.today() - timedelta(days=4)
            trip.end_date = date.today() - timedelta(days=1)
        elif mutation == "missing_dates":
            trip.start_date = None
        elif mutation == "pre_boundary":
            trip.created_at = boundary - timedelta(seconds=1)
        db.session.flush()
        result = _stage(trip)
        assert result.consumed is False
        assert result.reason == "trip_not_prospective"
        assert _rows(trip.id) == []


def test_missing_audited_policy_fails_closed_without_marker(client):
    with app.app_context():
        owner = _make_user("no-policy-owner")
        trip = _make_trip(owner)
        result = _stage(trip)
        assert result.consumed is False
        assert result.reason == "missing_policy"
        assert _rows(trip.id) == []


@pytest.mark.parametrize(
    "state,expected_reason",
    [
        ("allowed", None),
        ("friend_removed", SuppressionReason.PRIVACY_DENIED),
        ("private", SuppressionReason.PRIVACY_DENIED),
        ("cancelled", SuppressionReason.PRIVACY_DENIED),
        ("completed", SuppressionReason.PRIVACY_DENIED),
        ("past", SuppressionReason.PRIVACY_DENIED),
        ("pending", SuppressionReason.PRIVACY_DENIED),
        ("interested", SuppressionReason.PRIVACY_DENIED),
        ("going", SuppressionReason.PRIVACY_DENIED),
        ("declined", None),
        ("direct_invite", SuppressionReason.PRIVACY_DENIED),
        ("push_disabled", SuppressionReason.USER_OPTED_OUT),
        ("tokenless", SuppressionReason.NO_DEVICE_TOKEN),
        ("inactive_token", SuppressionReason.NO_DEVICE_TOKEN),
    ],
)
def test_send_time_authorization_rechecks_current_state(
    client, state, expected_reason
):
    with app.app_context():
        owner, friend, trip, _result = _deliverable_setup()
        if state == "friend_removed":
            Friend.query.filter_by(
                user_id=friend.id, friend_id=owner.id
            ).delete()
        elif state == "private":
            trip.is_public = False
        elif state in {"cancelled", "completed"}:
            trip.lifecycle_state = state
        elif state == "past":
            trip.start_date = date.today() - timedelta(days=4)
            trip.end_date = date.today() - timedelta(days=1)
        elif state in {"pending", "interested", "going", "declined"}:
            _add_participant(trip, friend, status=GuestStatus(state))
        elif state == "direct_invite":
            db.session.add(Invitation(
                sender_id=owner.id,
                receiver_id=friend.id,
                trip_id=trip.id,
                invite_type=InviteType.OUTBOUND,
                status="pending",
            ))
        elif state == "push_disabled":
            friend.push_notifications_enabled = False
        elif state == "tokenless":
            PushDeviceToken.query.filter_by(user_id=friend.id).delete()
        elif state == "inactive_token":
            PushDeviceToken.query.filter_by(user_id=friend.id).update({
                PushDeviceToken.active: False,
            })
        db.session.flush()

        decision = message_outbox_safety_callback(
            _recipient_row(trip, friend)
        )
        assert decision.allowed is (state in {"allowed", "declined"})
        assert decision.suppression_reason == expected_reason


def test_pending_invitee_consumes_occurrence_but_is_not_deliverable(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("invite-owner")
        friend = _make_user("invite-friend")
        _connect(owner, friend)
        trip = _make_trip(owner)
        result = _stage(trip)
        _add_participant(trip, friend, GuestStatus.PENDING)
        _add_token(friend)
        decision = message_outbox_safety_callback(
            _recipient_row(trip, friend)
        )
        assert result.recipient_user_ids == (friend.id,)
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.PRIVACY_DENIED


@pytest.mark.parametrize(
    "initial_state",
    ["push_disabled", "tokenless", "inactive_token", "participant", "invite"],
)
def test_initial_ineligibility_is_terminal_and_never_resurrects(
    client, initial_state
):
    with app.app_context():
        _register_bl110()
        owner = _make_user(f"bl110-initial-owner-{initial_state}")
        friend = _make_user(f"bl110-initial-friend-{initial_state}")
        _connect(owner, friend)
        trip = _make_trip(owner)
        if initial_state == "push_disabled":
            friend.push_notifications_enabled = False
            _add_token(friend)
        elif initial_state == "inactive_token":
            _add_token(friend, active=False)
        elif initial_state == "participant":
            _add_participant(trip, friend, GuestStatus.INTERESTED)
            _add_token(friend)
        elif initial_state == "invite":
            _add_token(friend)
            db.session.add(Invitation(
                sender_id=owner.id,
                receiver_id=friend.id,
                trip_id=trip.id,
                invite_type=InviteType.OUTBOUND,
                status="pending",
            ))
        db.session.flush()
        _stage(trip)
        row = _recipient_row(trip, friend)
        assert row.status == "suppressed"
        assert row.provider_phase == "not_started"

        friend.push_notifications_enabled = True
        if initial_state == "tokenless":
            _add_token(friend)
        elif initial_state == "inactive_token":
            PushDeviceToken.query.filter_by(user_id=friend.id).update({
                PushDeviceToken.active: True,
            })
        if initial_state == "participant":
            SkiTripParticipant.query.filter_by(
                trip_id=trip.id, user_id=friend.id
            ).one().status = GuestStatus.DECLINED
        if initial_state == "invite":
            Invitation.query.filter_by(
                trip_id=trip.id, receiver_id=friend.id
            ).delete()
        db.session.flush()
        assert _stage(trip).consumed is False
        assert row.status == "suppressed"
        assert message_outbox_safety_callback(row).allowed is True


def test_render_uses_canonical_resort_first_name_and_friend_trip_link(client):
    with app.app_context():
        owner, friend, trip, _result = _deliverable_setup(
            resort=True, legacy_mountain="Stale Legacy Peak"
        )
        row = _recipient_row(trip, friend)
        row.provider_phase = "started"
        db.session.flush()
        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "test-message",
            },
        ) as send:
            result = message_outbox_provider_callback(row)
        assert result["status"] == "provider_accepted"
        recipient_ids, title, body, push_data = send.call_args.args
        assert recipient_ids == [friend.id]
        assert title == "Avery added a trip"
        assert body == (
            "Avery just added a trip to Canonical Peak. Check it out."
        )
        expected_link = f"/friend-trip/{trip.id}"
        assert push_data["trip_id"] == trip.id
        assert push_data["deep_link"] == expected_link
        assert push_data["url"] == expected_link


def test_render_falls_back_to_nonblank_legacy_mountain(client):
    with app.app_context():
        owner, friend, trip, _result = _deliverable_setup(
            resort=False, legacy_mountain="Legacy Ridge"
        )
        row = _recipient_row(trip, friend)
        row.provider_phase = "started"
        db.session.flush()
        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "test-message",
            },
        ) as send:
            message_outbox_provider_callback(row)
        assert send.call_args.args[2] == (
            "Avery just added a trip to Legacy Ridge. Check it out."
        )


def test_missing_destination_suppresses_before_provider(client):
    with app.app_context():
        owner, friend, trip, _result = _deliverable_setup(
            resort=False, legacy_mountain=""
        )
        trip.mountain = "   "
        db.session.flush()
        decision = message_outbox_safety_callback(
            _recipient_row(trip, friend)
        )
        assert decision.allowed is False
        assert (
            decision.suppression_reason
            == SuppressionReason.MISSING_REQUIRED_PAYLOAD
        )


def test_provider_callback_refuses_bl110_without_specialized_start(client):
    with app.app_context():
        _owner, friend, trip, _result = _deliverable_setup()
        row = _recipient_row(trip, friend)
        with patch("services.message_dispatch.send_onesignal_push") as send:
            result = message_outbox_provider_callback(row)
        assert result["status"] == "dead_letter"
        assert result["error"] == "opportunity_provider_start_required"
        send.assert_not_called()


def test_real_worker_resumes_and_delivers_only_after_specialized_start(client):
    with app.app_context():
        _owner, friend, trip, _result = _deliverable_setup(paused=False)
        friend_id, trip_id = friend.id, trip.id
        db.session.commit()
        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "worker-test-message",
            },
        ) as send:
            first = run_worker(
                db.session,
                owner="bl110-worker-before-restart",
                safety_callback=message_outbox_safety_callback,
                provider_callback=message_outbox_provider_callback,
                opportunity_start_callback=(
                    message_outbox_opportunity_start_callback
                ),
                batch_size=1,
                max_batches=1,
            )
            assert first.claimed == 1
            assert first.suppressed == 1
            send.assert_not_called()

            second = run_worker(
                db.session,
                owner="bl110-worker-after-restart",
                safety_callback=message_outbox_safety_callback,
                provider_callback=message_outbox_provider_callback,
                opportunity_start_callback=(
                    message_outbox_opportunity_start_callback
                ),
                batch_size=1,
                max_batches=1,
            )
        assert second.claimed == 1
        assert second.provider_accepted == 1
        send.assert_called_once()
        assert (
            MessageOutbox.query.filter_by(
                event_name=EventName.FRIEND_TRIP_CREATED,
                object_id=trip_id,
                recipient_user_id=friend_id,
            ).one().status
            == "provider_accepted"
        )


def test_repeated_producer_calls_never_mint_new_rows(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("dedupe-owner")
        friend = _make_user("dedupe-friend")
        _connect(owner, friend)
        trip = _make_trip(owner)
        first = _stage(trip)
        first_ids = [row.id for row in _rows(trip.id)]
        for _index in range(4):
            assert _stage(trip).consumed is False
        assert [row.id for row in _rows(trip.id)] == first_ids
        assert first.consumed is True


def test_outer_rollback_removes_marker_and_fanout(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("rollback-owner")
        friend = _make_user("rollback-friend")
        _connect(owner, friend)
        trip = _make_trip(owner)
        trip_id = trip.id
        assert _stage(trip).consumed is True
        db.session.rollback()
        assert MessageOutbox.query.filter_by(object_id=trip_id).count() == 0


@pytest.mark.parametrize("friend_count", [1, 5, 25])
def test_friend_selection_query_count_is_bounded(client, friend_count):
    with app.app_context():
        _register_bl110()
        owner = _make_user(f"budget-owner-{friend_count}")
        for index in range(friend_count):
            _connect(owner, _make_user(f"budget-{friend_count}-{index}"))
        trip = _make_trip(owner)
        statements = []

        def collect(_conn, _cursor, statement, _params, _ctx, _many):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and (
                " from friend " in normalized
                or " join friend " in normalized
                or " from friend as " in normalized
                or " join friend as " in normalized
            ):
                statements.append(normalized)

        sa.event.listen(db.engine, "before_cursor_execute", collect)
        try:
            result = _stage(trip)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", collect)
        assert len(result.recipient_user_ids) == friend_count
        assert len(statements) == 1


def test_occurrence_is_stable_per_trip(client):
    with app.app_context():
        _register_bl110()
        owner = _make_user("occurrence-owner")
        trip = _make_trip(owner)
        _stage(trip)
        assert {
            row.occurrence_id for row in _rows(trip.id)
        } == {
            opportunity_occurrence_id(EventName.FRIEND_TRIP_CREATED, trip.id)
        }