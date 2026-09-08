"""Focused BL-16 wishlist-match producer and delivery coverage."""

from datetime import date, datetime, timedelta, timezone
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
    SkiTripRsvpTransition,
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
from services.message_outbox import mark_opportunity_provider_started
from services.message_outbox_worker import run_worker
from services.messaging_constants import EventName, SuppressionReason
from services.opportunity_messaging import (
    opportunity_occurrence_id,
    opportunity_timestamp_at_or_after,
)
from services.rsvp_transitions import transition_rsvp
from services.wishlist_match_opportunities import (
    stage_wishlist_match_opportunity,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    form_post,
    json_post,
)


def _register(event_name=EventName.WISHLIST_MATCH_DETECTED, *, paused=True,
              boundary=None):
    policy = MessagingDeliveryPolicy(
        event_name=event_name,
        delivery_mode="enqueue_only",
        claims_paused=True,
        cutover_epoch=1,
        control_revision=1,
        operator_reason=f"test {event_name}",
        audit_identity="test",
    )
    db.session.add(policy)
    db.session.flush()
    activation = MessagingDeliveryPolicyEvent(
        event_name=event_name,
        delivery_mode="enqueue_only",
        claims_paused=True,
        cutover_epoch=1,
        control_revision=1,
        action="opportunity_registered",
        operator_reason=f"test {event_name} activation",
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


def _token(user, *, active=True):
    db.session.add(PushDeviceToken(
        user_id=user.id,
        token=f"bl16-token-{user.id}",
        platform="ios",
        active=active,
    ))
    db.session.flush()


def _rows(trip):
    return MessageOutbox.query.filter_by(
        event_name=EventName.WISHLIST_MATCH_DETECTED,
        object_type="trip",
        object_id=trip.id,
    ).order_by(MessageOutbox.recipient_user_id).all()


def _recipient_row(trip, recipient, event_name=EventName.WISHLIST_MATCH_DETECTED):
    return MessageOutbox.query.filter_by(
        event_name=event_name,
        object_id=trip.id,
        recipient_user_id=recipient.id,
    ).one()


def _organizer_stage(trip):
    return stage_wishlist_match_opportunity(
        trip.id,
        actor_user_id=trip.user_id,
        session=db.session,
        source_route="test_bl16_organizer",
    )


def _organizer_setup(*, paused=True, wishlist=True):
    _register(paused=paused)
    owner = _make_user("bl16-owner")
    owner.first_name = "Avery"
    recipient = _make_user("bl16-recipient")
    recipient.wish_list_resorts = []
    resort = _make_resort("Canonical Peak")
    if wishlist:
        recipient.wish_list_resorts = [resort.id]
    _connect(owner, recipient)
    trip = _make_trip(owner, resort)
    _token(recipient)
    result = _organizer_stage(trip)
    db.session.flush()
    return owner, recipient, resort, trip, result


def _going_setup(*, paused=True, old_trip=False):
    _register(paused=paused)
    owner = _make_user("bl16-going-owner")
    actor = _make_user("bl16-going-actor")
    actor.first_name = "Jordan"
    recipient = _make_user("bl16-going-recipient")
    resort = _make_resort("Transition Peak")
    recipient.wish_list_resorts = [resort.id]
    _connect(actor, recipient)
    trip = _make_trip(owner, resort)
    if old_trip:
        trip.created_at = datetime.utcnow() - timedelta(days=365)
    _add_participant(trip, actor, GuestStatus.INTERESTED)
    _token(recipient)
    result = transition_rsvp(
        trip_id=trip.id,
        user_id=actor.id,
        new_status=GuestStatus.GOING,
        source="self_rsvp",
        actor_user_id=actor.id,
    )
    db.session.flush()
    return owner, actor, recipient, resort, trip, result


def _set_processing(row):
    row.status = "processing"
    row.lease_token = f"lease-{row.id}"
    row.lease_owner = "test-worker"
    row.leased_at = datetime.utcnow()
    row.lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
    row.provider_phase = "not_started"
    db.session.flush()


def test_organizer_public_creation_stages_marker_and_matching_friend(client):
    with app.app_context():
        owner, recipient, resort, trip, result = _organizer_setup()
        assert result.consumed is True
        assert result.recipient_user_ids == (recipient.id,)
        assert {row.recipient_user_id for row in _rows(trip)} == {
            owner.id, recipient.id
        }
        row = _recipient_row(trip, recipient)
        assert row.evidence_ids_json == [f"resort_id:{resort.id}"]
        assert row.occurrence_id == opportunity_occurrence_id(
            EventName.WISHLIST_MATCH_DETECTED, trip.id
        )


def test_organizer_no_match_stages_only_first_public_marker(client):
    with app.app_context():
        owner, recipient, _resort, trip, result = _organizer_setup(
            wishlist=False
        )
        assert result.consumed is True
        assert result.recipient_user_ids == ()
        assert [row.recipient_user_id for row in _rows(trip)] == [owner.id]
        recipient.wish_list_resorts = [trip.resort_id]
        assert _organizer_stage(trip).consumed is False
        assert MessageOutbox.query.filter_by(
            object_id=trip.id,
            recipient_user_id=recipient.id,
        ).count() == 0


@pytest.mark.parametrize(
    "mutation",
    ["private", "cancelled", "completed", "past", "missing_dates",
     "pre_boundary", "missing_resort", "inactive_resort", "region"],
)
def test_organizer_ineligible_states_are_silent(client, mutation):
    with app.app_context():
        boundary = datetime.utcnow() - timedelta(seconds=1)
        _register(boundary=boundary)
        owner = _make_user(f"bl16-ineligible-{mutation}")
        recipient = _make_user(f"bl16-ineligible-recipient-{mutation}")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        if mutation == "private":
            trip.is_public = False
        elif mutation in {"cancelled", "completed"}:
            trip.lifecycle_state = mutation
        elif mutation == "past":
            trip.start_date = date.today() - timedelta(days=3)
            trip.end_date = date.today() - timedelta(days=1)
        elif mutation == "missing_dates":
            trip.start_date = None
        elif mutation == "pre_boundary":
            trip.created_at = boundary - timedelta(seconds=1)
        elif mutation == "missing_resort":
            trip.resort_id = None
        elif mutation == "inactive_resort":
            resort.is_active = False
        elif mutation == "region":
            resort.is_region = True
        db.session.flush()
        assert _organizer_stage(trip).consumed is False
        assert _rows(trip) == []


def test_missing_audited_policy_fails_closed(client):
    with app.app_context():
        owner = _make_user("bl16-no-policy")
        trip = _make_trip(owner, _make_resort())
        result = _organizer_stage(trip)
        assert result.consumed is False
        assert result.reason == "missing_policy"
        assert _rows(trip) == []


@pytest.mark.parametrize("raw_wishlist", [
    lambda resort_id: [resort_id],
    lambda resort_id: [str(resort_id)],
    lambda resort_id: ["bad", resort_id, str(resort_id), resort_id],
])
def test_exact_normalized_wishlist_matches_once(client, raw_wishlist):
    with app.app_context():
        _register()
        owner = _make_user("bl16-normal-owner")
        recipient = _make_user("bl16-normal-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = raw_wishlist(resort.id)
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        assert _organizer_stage(trip).recipient_user_ids == (recipient.id,)
        assert MessageOutbox.query.filter_by(
            object_id=trip.id,
            recipient_user_id=recipient.id,
        ).count() == 1


@pytest.mark.parametrize("relationship", [
    "nonfriend", "one_way", "removed", "self",
])
def test_only_current_reciprocal_nonself_friends_are_candidates(
    client, relationship
):
    with app.app_context():
        _register()
        owner = _make_user(f"bl16-social-owner-{relationship}")
        recipient = owner if relationship == "self" else _make_user(
            f"bl16-social-recipient-{relationship}"
        )
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        if relationship in {"one_way", "removed"}:
            _connect(owner, recipient, reciprocal=False)
        if relationship == "removed":
            Friend.query.filter_by(
                user_id=owner.id, friend_id=recipient.id
            ).delete()
        trip = _make_trip(owner, resort)
        assert _organizer_stage(trip).recipient_user_ids == ()


def test_authoritative_transition_to_going_stages_typed_evidence(client):
    with app.app_context():
        _owner, actor, recipient, resort, trip, transition_result = _going_setup()
        row = _recipient_row(trip, recipient)
        assert transition_result.changed is True
        assert transition_result.transition is not None
        assert row.actor_user_id == actor.id
        assert set(row.evidence_ids_json) == {
            f"resort_id:{resort.id}",
            f"rsvp_transition_id:{transition_result.transition.id}",
        }


def test_post_boundary_going_on_old_trip_is_eligible(client):
    with app.app_context():
        _owner, _actor, recipient, _resort, trip, _result = _going_setup(
            old_trip=True
        )
        assert _recipient_row(trip, recipient) is not None


def test_pre_boundary_going_transition_is_silent(client):
    with app.app_context():
        boundary = datetime.utcnow() + timedelta(minutes=5)
        _register(boundary=boundary)
        owner = _make_user("bl16-pre-going-owner")
        actor = _make_user("bl16-pre-going-actor")
        recipient = _make_user("bl16-pre-going-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(actor, recipient)
        trip = _make_trip(owner, resort)
        _add_participant(trip, actor, GuestStatus.INTERESTED)
        result = transition_rsvp(
            trip_id=trip.id,
            user_id=actor.id,
            new_status="going",
            source="self_rsvp",
        )
        assert result.transition is not None
        assert _rows(trip) == []


def test_old_already_going_state_is_not_replayed(client):
    with app.app_context():
        owner = _make_user("bl16-old-going-owner")
        actor = _make_user("bl16-old-going-actor")
        recipient = _make_user("bl16-old-going-recipient")
        resort = _make_resort()
        trip = _make_trip(owner, resort)
        _add_participant(trip, actor, GuestStatus.GOING)
        _connect(actor, recipient)
        recipient.wish_list_resorts = [resort.id]
        db.session.flush()
        _register()
        result = transition_rsvp(
            trip_id=trip.id,
            user_id=actor.id,
            new_status="going",
            source="self_rsvp",
        )
        assert result.changed is False
        assert result.transition is None
        assert _rows(trip) == []


@pytest.mark.parametrize(
    ("initial", "target", "source"),
    [
        (GuestStatus.PENDING, GuestStatus.INTERESTED, "invite_response"),
        (GuestStatus.PENDING, GuestStatus.DECLINED, "invite_response"),
        (GuestStatus.INTERESTED, GuestStatus.REMOVED, "organizer_remove"),
        (GuestStatus.GOING, GuestStatus.DECLINED, "participant_leave"),
    ],
)
def test_non_going_transitions_are_silent(client, initial, target, source):
    with app.app_context():
        _register()
        owner = _make_user(f"bl16-nongoing-owner-{target.value}")
        actor = _make_user(f"bl16-nongoing-actor-{target.value}")
        recipient = _make_user(f"bl16-nongoing-recipient-{target.value}")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(actor, recipient)
        trip = _make_trip(owner, resort)
        _add_participant(trip, actor, initial)
        transition_rsvp(
            trip_id=trip.id,
            user_id=actor.id,
            new_status=target,
            source=source,
        )
        assert _rows(trip) == []


def test_organizer_then_going_and_multiple_actors_keep_one_recipient_occurrence(
    client
):
    with app.app_context():
        owner, recipient, resort, trip, _result = _organizer_setup()
        actor = _make_user("bl16-second-actor")
        second_actor = _make_user("bl16-third-actor")
        for going_actor in (actor, second_actor):
            _connect(going_actor, recipient)
            _add_participant(trip, going_actor, GuestStatus.INTERESTED)
            transition_rsvp(
                trip_id=trip.id,
                user_id=going_actor.id,
                new_status="going",
                source="self_rsvp",
            )
        row = _recipient_row(trip, recipient)
        assert row.actor_user_id == owner.id
        assert row.evidence_ids_json == [f"resort_id:{resort.id}"]
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            object_id=trip.id,
            recipient_user_id=recipient.id,
        ).count() == 1


@pytest.mark.parametrize("existing_status", ["pending", "retryable"])
def test_duplicate_going_trigger_cannot_suppress_an_older_valid_occurrence(
    client, existing_status
):
    with app.app_context():
        _register()
        owner = _make_user(f"bl16-dedupe-owner-{existing_status}")
        first_actor = _make_user(f"bl16-dedupe-first-{existing_status}")
        second_actor = _make_user(f"bl16-dedupe-second-{existing_status}")
        recipient = _make_user(f"bl16-dedupe-recipient-{existing_status}")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _token(recipient)
        trip = _make_trip(owner, resort)
        for actor in (first_actor, second_actor):
            _connect(actor, recipient)
            _add_participant(trip, actor, GuestStatus.INTERESTED)

        first = transition_rsvp(
            trip_id=trip.id,
            user_id=first_actor.id,
            new_status=GuestStatus.GOING,
            source="self_rsvp",
        )
        row = _recipient_row(trip, recipient)
        row.status = existing_status
        recipient.push_notifications_enabled = False
        db.session.flush()

        transition_rsvp(
            trip_id=trip.id,
            user_id=second_actor.id,
            new_status=GuestStatus.GOING,
            source="self_rsvp",
        )
        assert row.status == existing_status
        assert row.actor_user_id == first_actor.id
        assert row.evidence_ids_json == [
            f"resort_id:{resort.id}",
            f"rsvp_transition_id:{first.transition.id}",
        ]

        recipient.push_notifications_enabled = True
        db.session.flush()
        assert row.status == existing_status
        assert message_outbox_safety_callback(row).allowed is True


def test_different_trips_are_independently_eligible(client):
    with app.app_context():
        _register()
        owner = _make_user("bl16-two-owner")
        recipient = _make_user("bl16-two-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trips = [
            _make_trip(owner, resort),
            _make_trip(
                owner,
                resort,
                start_date=date.today() + timedelta(days=100),
                end_date=date.today() + timedelta(days=102),
            ),
        ]
        for trip in trips:
            _organizer_stage(trip)
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            recipient_user_id=recipient.id,
        ).count() == 2


def test_repeated_organizer_producer_does_not_duplicate_rows(client):
    with app.app_context():
        _owner, recipient, _resort, trip, first = _organizer_setup()
        first_ids = [row.id for row in _rows(trip)]
        for _index in range(4):
            repeated = _organizer_stage(trip)
            assert repeated.consumed is False
            assert repeated.reason == "organizer_trigger_already_consumed"
        assert first.consumed is True
        assert [row.id for row in _rows(trip)] == first_ids
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            object_id=trip.id,
            recipient_user_id=recipient.id,
        ).count() == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "wishlist_removed", "friend_removed", "private", "cancelled",
        "completed", "past", "direct_invite", "pending", "interested",
        "going", "push_disabled", "tokenless", "inactive_token",
        "resort_changed", "resort_inactive", "resort_region",
    ],
)
def test_organizer_send_time_reauthorization_suppresses_stale_state(
    client, mutation
):
    with app.app_context():
        owner, recipient, resort, trip, _result = _organizer_setup()
        if mutation == "wishlist_removed":
            recipient.wish_list_resorts = []
        elif mutation == "friend_removed":
            Friend.query.filter_by(
                user_id=recipient.id, friend_id=owner.id
            ).delete()
        elif mutation == "private":
            trip.is_public = False
        elif mutation in {"cancelled", "completed"}:
            trip.lifecycle_state = mutation
        elif mutation == "past":
            trip.end_date = date.today() - timedelta(days=1)
        elif mutation == "direct_invite":
            db.session.add(Invitation(
                sender_id=owner.id,
                receiver_id=recipient.id,
                trip_id=trip.id,
                invite_type=InviteType.OUTBOUND,
                status="pending",
            ))
        elif mutation in {"pending", "interested", "going"}:
            _add_participant(trip, recipient, GuestStatus(mutation))
        elif mutation == "push_disabled":
            recipient.push_notifications_enabled = False
        elif mutation == "tokenless":
            PushDeviceToken.query.filter_by(user_id=recipient.id).delete()
        elif mutation == "inactive_token":
            PushDeviceToken.query.filter_by(user_id=recipient.id).update({
                PushDeviceToken.active: False,
            })
        elif mutation == "resort_changed":
            trip.resort_id = _make_resort("Replacement Peak").id
        elif mutation == "resort_inactive":
            resort.is_active = False
        elif mutation == "resort_region":
            resort.is_region = True
        db.session.flush()
        decision = message_outbox_safety_callback(
            _recipient_row(trip, recipient)
        )
        assert decision.allowed is False
        expected = (
            SuppressionReason.USER_OPTED_OUT
            if mutation == "push_disabled"
            else SuppressionReason.NO_DEVICE_TOKEN
            if mutation in {"tokenless", "inactive_token"}
            else SuppressionReason.PRIVACY_DENIED
        )
        assert decision.suppression_reason == expected


@pytest.mark.parametrize(
    "initial_state",
    ["push_disabled", "tokenless", "inactive_token", "participant", "invite"],
)
def test_initial_ineligibility_is_terminal_and_never_resurrects(
    client, initial_state
):
    with app.app_context():
        _register()
        owner = _make_user(f"bl16-initial-owner-{initial_state}")
        recipient = _make_user(f"bl16-initial-recipient-{initial_state}")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        if initial_state == "push_disabled":
            recipient.push_notifications_enabled = False
            _token(recipient)
        elif initial_state == "inactive_token":
            _token(recipient, active=False)
        elif initial_state == "participant":
            _add_participant(trip, recipient, GuestStatus.INTERESTED)
            _token(recipient)
        elif initial_state == "invite":
            _token(recipient)
            db.session.add(Invitation(
                sender_id=owner.id,
                receiver_id=recipient.id,
                trip_id=trip.id,
                invite_type=InviteType.OUTBOUND,
                status="pending",
            ))
        db.session.flush()
        _organizer_stage(trip)
        row = _recipient_row(trip, recipient)
        assert row.status == "suppressed"
        assert row.provider_phase == "not_started"

        recipient.push_notifications_enabled = True
        if initial_state == "tokenless":
            _token(recipient)
        elif initial_state == "inactive_token":
            PushDeviceToken.query.filter_by(user_id=recipient.id).update({
                PushDeviceToken.active: True,
            })
        if initial_state == "participant":
            SkiTripParticipant.query.filter_by(
                trip_id=trip.id, user_id=recipient.id
            ).one().status = GuestStatus.DECLINED
        if initial_state == "invite":
            Invitation.query.filter_by(
                trip_id=trip.id, receiver_id=recipient.id
            ).delete()
        db.session.flush()
        assert _organizer_stage(trip).consumed is False
        assert row.status == "suppressed"
        assert message_outbox_safety_callback(row).allowed is True


@pytest.mark.parametrize(
    "mutation",
    [
        "actor_left", "transition_missing", "transition_wrong_actor",
        "transition_wrong_trip", "transition_wrong_status",
        "transition_pre_boundary",
    ],
)
def test_going_evidence_is_reauthorized(client, mutation):
    with app.app_context():
        _owner, actor, recipient, _resort, trip, result = _going_setup()
        row = _recipient_row(trip, recipient)
        transition = result.transition
        if mutation == "actor_left":
            SkiTripParticipant.query.filter_by(
                trip_id=trip.id, user_id=actor.id
            ).one().status = GuestStatus.DECLINED
        elif mutation == "transition_missing":
            row.evidence_ids_json = [
                value for value in row.evidence_ids_json
                if not value.startswith("rsvp_transition_id:")
            ] + ["rsvp_transition_id:9999999"]
        elif mutation == "transition_wrong_actor":
            transition.user_id = recipient.id
        elif mutation == "transition_wrong_trip":
            other = _make_trip(_make_user("bl16-other-owner"), _make_resort())
            transition.trip_id = other.id
        elif mutation == "transition_wrong_status":
            other_owner = _make_user("bl16-status-owner")
            other_actor = _make_user("bl16-status-actor")
            other_trip = _make_trip(other_owner, _make_resort())
            _add_participant(other_trip, other_actor, GuestStatus.PENDING)
            other_result = transition_rsvp(
                trip_id=other_trip.id,
                user_id=other_actor.id,
                new_status=GuestStatus.INTERESTED,
                source="invite_response",
            )
            row.evidence_ids_json = [
                value for value in row.evidence_ids_json
                if not value.startswith("rsvp_transition_id:")
            ] + [f"rsvp_transition_id:{other_result.transition.id}"]
        elif mutation == "transition_pre_boundary":
            policy_event = MessagingDeliveryPolicyEvent.query.filter_by(
                event_name=EventName.WISHLIST_MATCH_DETECTED
            ).one()
            transition.changed_at = policy_event.created_at - timedelta(seconds=1)
        db.session.flush()
        decision = message_outbox_safety_callback(row)
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.PRIVACY_DENIED


def test_missing_resort_evidence_suppresses_without_legacy_fallback(client):
    with app.app_context():
        _owner, recipient, _resort, trip, _result = _organizer_setup()
        row = _recipient_row(trip, recipient)
        row.evidence_ids_json = []
        trip.mountain = "Legacy Must Not Render"
        db.session.flush()
        decision = message_outbox_safety_callback(row)
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.PRIVACY_DENIED


@pytest.mark.parametrize("trigger", ["organizer", "going"])
def test_copy_and_deep_link_use_live_canonical_records(client, trigger):
    with app.app_context():
        if trigger == "organizer":
            _actor, recipient, _resort, trip, _result = _organizer_setup()
            expected = (
                "Avery added a trip to Canonical Peak, which is on your wishlist."
            )
        else:
            _owner, _actor, recipient, _resort, trip, _result = _going_setup()
            expected = "Jordan is going to Transition Peak—on your wishlist."
        row = _recipient_row(trip, recipient)
        row.provider_phase = "started"
        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "bl16-copy",
            },
        ) as send:
            response = message_outbox_provider_callback(row)
        assert response["status"] == "provider_accepted"
        recipient_ids, title, body, payload = send.call_args.args
        assert recipient_ids == [recipient.id]
        assert title == "Wishlist match"
        assert body == expected
        assert payload["trip_id"] == trip.id
        assert payload["deep_link"] == f"/friend-trip/{trip.id}"
        assert payload["url"] == f"/friend-trip/{trip.id}"


def test_provider_callback_requires_specialized_start(client):
    with app.app_context():
        _owner, recipient, _resort, trip, _result = _organizer_setup()
        with patch("services.message_dispatch.send_onesignal_push") as send:
            response = message_outbox_provider_callback(
                _recipient_row(trip, recipient)
            )
        assert response == {
            "status": "dead_letter",
            "error": "opportunity_provider_start_required",
        }
        send.assert_not_called()


def test_pending_bl110_loses_to_valid_bl16(client):
    with app.app_context():
        _register(EventName.FRIEND_TRIP_CREATED, paused=False)
        _register(EventName.WISHLIST_MATCH_DETECTED, paused=False)
        owner = _make_user("bl16-precedence-owner")
        recipient = _make_user("bl16-precedence-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        _token(recipient)
        stage_friend_trip_created_opportunity(
            trip.id, session=db.session, source_route="test_precedence"
        )
        _organizer_stage(trip)
        generic = _recipient_row(
            trip, recipient, EventName.FRIEND_TRIP_CREATED
        )
        wishlist = _recipient_row(trip, recipient)
        _set_processing(wishlist)
        result = mark_opportunity_provider_started(
            wishlist.id,
            wishlist.lease_token,
            safety_callback=message_outbox_safety_callback,
            session=db.session,
        )
        assert result.status == "started"
        assert generic.status == "suppressed"
        assert generic.last_error == "wishlist_precedence"


@pytest.mark.parametrize(
    ("generic_status", "generic_phase"),
    [
        ("processing", "started"),
        ("provider_accepted", "accepted"),
        ("delivery_unknown", "unknown"),
    ],
)
def test_irreversible_bl110_suppresses_bl16(
    client, generic_status, generic_phase
):
    with app.app_context():
        _register(EventName.FRIEND_TRIP_CREATED, paused=False)
        _register(EventName.WISHLIST_MATCH_DETECTED, paused=False)
        owner = _make_user(f"bl16-irrev-owner-{generic_phase}")
        recipient = _make_user(f"bl16-irrev-recipient-{generic_phase}")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        _token(recipient)
        stage_friend_trip_created_opportunity(
            trip.id, session=db.session, source_route="test_irreversible"
        )
        _organizer_stage(trip)
        generic = _recipient_row(
            trip, recipient, EventName.FRIEND_TRIP_CREATED
        )
        wishlist = _recipient_row(trip, recipient)
        generic.status = generic_status
        generic.provider_phase = generic_phase
        _set_processing(wishlist)
        result = mark_opportunity_provider_started(
            wishlist.id,
            wishlist.lease_token,
            safety_callback=message_outbox_safety_callback,
            session=db.session,
        )
        assert result.status == "suppressed"
        assert result.reason == "generic_already_irreversible"
        assert wishlist.provider_phase == "not_started"


def test_direct_invite_suppresses_both_families(client):
    with app.app_context():
        _register(EventName.FRIEND_TRIP_CREATED)
        _register(EventName.WISHLIST_MATCH_DETECTED)
        owner = _make_user("bl16-invite-owner")
        recipient = _make_user("bl16-invite-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        _token(recipient)
        stage_friend_trip_created_opportunity(
            trip.id, session=db.session, source_route="test_invite"
        )
        _organizer_stage(trip)
        db.session.add(Invitation(
            sender_id=owner.id,
            receiver_id=recipient.id,
            trip_id=trip.id,
            invite_type=InviteType.OUTBOUND,
            status="pending",
        ))
        db.session.flush()
        assert message_outbox_safety_callback(
            _recipient_row(trip, recipient, EventName.FRIEND_TRIP_CREATED)
        ).allowed is False
        assert message_outbox_safety_callback(
            _recipient_row(trip, recipient)
        ).allowed is False


def test_worker_restart_retains_occurrence_and_delivers_once(client):
    with app.app_context():
        _owner, recipient, _resort, trip, _result = _organizer_setup(
            paused=False
        )
        recipient_id, trip_id = recipient.id, trip.id
        db.session.commit()
        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "bl16-worker",
            },
        ) as send:
            marker_pass = run_worker(
                db.session,
                owner="bl16-marker-worker",
                safety_callback=message_outbox_safety_callback,
                provider_callback=message_outbox_provider_callback,
                opportunity_start_callback=(
                    message_outbox_opportunity_start_callback
                ),
                batch_size=1,
                max_batches=1,
            )
            delivery_pass = run_worker(
                db.session,
                owner="bl16-delivery-worker",
                safety_callback=message_outbox_safety_callback,
                provider_callback=message_outbox_provider_callback,
                opportunity_start_callback=(
                    message_outbox_opportunity_start_callback
                ),
                batch_size=1,
                max_batches=1,
            )
        assert marker_pass.suppressed == 1
        assert delivery_pass.provider_accepted == 1
        send.assert_called_once()
        row = MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            object_id=trip_id,
            recipient_user_id=recipient_id,
        ).one()
        assert row.status == "provider_accepted"


def test_outer_rollback_removes_bl16_rows_and_transition(client):
    with app.app_context():
        _owner, _actor, _recipient, _resort, trip, result = _going_setup()
        trip_id = trip.id
        transition_id = result.transition.id
        assert _rows(trip)
        db.session.rollback()
        assert MessageOutbox.query.filter_by(object_id=trip_id).count() == 0
        assert db.session.get(SkiTripRsvpTransition, transition_id) is None


@pytest.mark.parametrize("friend_count", [1, 5, 25])
def test_candidate_selection_query_count_is_bounded(client, friend_count):
    with app.app_context():
        _register()
        owner = _make_user(f"bl16-budget-owner-{friend_count}")
        resort = _make_resort()
        for index in range(friend_count):
            recipient = _make_user(f"bl16-budget-{friend_count}-{index}")
            recipient.wish_list_resorts = [resort.id]
            _connect(owner, recipient)
        trip = _make_trip(owner, resort)
        selection_queries = []

        def collect(_conn, _cursor, statement, _params, _ctx, _many):
            normalized = " ".join(statement.lower().split())
            if (
                normalized.startswith("select")
                and "wish_list_resorts" in normalized
                and " join friend " in normalized
            ):
                selection_queries.append(normalized)

        sa.event.listen(db.engine, "before_cursor_execute", collect)
        try:
            result = _organizer_stage(trip)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", collect)
        assert len(result.recipient_user_ids) == friend_count
        assert len(selection_queries) == 1


def test_json_creation_wires_bl16_without_bl110_policy(client):
    with app.app_context():
        _register()
        owner = _make_user("bl16-json-owner")
        recipient = _make_user("bl16-json-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        db.session.commit()
        owner_id, recipient_id, resort_id = owner.id, recipient.id, resort.id
    _login(client, owner_id)
    start = date.today() + timedelta(days=20)
    response = json_post(client, "/api/trip/create", {
        "resort_id": resort_id,
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "is_public": True,
    })
    assert response.status_code == 200
    trip_id = response.get_json()["trip"]["id"]
    with app.app_context():
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            object_id=trip_id,
            recipient_user_id=recipient_id,
        ).count() == 1


def test_form_and_batch_creation_wire_independent_bl16_occurrences(client):
    with app.app_context():
        _register()
        owner = _make_user("bl16-form-owner")
        recipient = _make_user("bl16-form-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        db.session.commit()
        owner_id, recipient_id, resort_id = owner.id, recipient.id, resort.id
    _login(client, owner_id)
    first = date.today() + timedelta(days=20)
    second = date.today() + timedelta(days=40)
    response = form_post(client, "/add_trip", {
        "resort_id": str(resort_id),
        "date_ranges_json": json.dumps([
            {
                "start_date": first.isoformat(),
                "end_date": (first + timedelta(days=2)).isoformat(),
            },
            {
                "start_date": second.isoformat(),
                "end_date": (second + timedelta(days=2)).isoformat(),
            },
        ]),
        "trip_status": "planning",
        "is_public": "on",
    })
    assert response.status_code == 302
    with app.app_context():
        rows = MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            recipient_user_id=recipient_id,
        ).all()
        assert len(rows) == 2
        assert len({row.occurrence_id for row in rows}) == 2


def test_private_to_public_wires_once_and_public_cycle_does_not_resend(client):
    with app.app_context():
        _register()
        owner = _make_user("bl16-visibility-owner")
        recipient = _make_user("bl16-visibility-recipient")
        resort = _make_resort()
        recipient.wish_list_resorts = [resort.id]
        _connect(owner, recipient)
        trip = _make_trip(owner, resort, is_public=False)
        db.session.commit()
        owner_id, recipient_id, trip_id = owner.id, recipient.id, trip.id
    _login(client, owner_id)
    assert json_post(
        client, f"/api/trip/{trip_id}/update-visibility",
        {"is_public": True},
    ).status_code == 200
    assert json_post(
        client, f"/api/trip/{trip_id}/update-visibility",
        {"is_public": False},
    ).status_code == 200
    assert json_post(
        client, f"/api/trip/{trip_id}/update-visibility",
        {"is_public": True},
    ).status_code == 200
    with app.app_context():
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED,
            object_id=trip_id,
            recipient_user_id=recipient_id,
        ).count() == 1


def test_shared_wishlist_and_interest_without_trip_activity_are_silent(client):
    with app.app_context():
        _register()
        first = _make_user("bl16-silent-first")
        second = _make_user("bl16-silent-second")
        resort = _make_resort()
        first.wish_list_resorts = [resort.id]
        second.wish_list_resorts = [resort.id]
        _connect(first, second)
        db.session.flush()
        assert MessageOutbox.query.filter_by(
            event_name=EventName.WISHLIST_MATCH_DETECTED
        ).count() == 0


def test_activation_comparison_accepts_equivalent_aware_utc_timestamp():
    boundary = datetime(2026, 9, 8, 18, 0, 0)
    candidate = datetime(
        2026, 9, 8, 12, 0, 0,
        tzinfo=timezone(timedelta(hours=-6)),
    )
    assert opportunity_timestamp_at_or_after(candidate, boundary) is True