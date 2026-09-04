"""Focused BL-147 synchronous message send-safety coverage."""

from dataclasses import replace
import threading
from unittest.mock import MagicMock, patch

import pytest

from app import app
from models import (
    Invitation,
    InviteType,
    Friend,
    GuestStatus,
    MessageEventLog,
    ParticipantRole,
    PushDeviceToken,
    SkiTripParticipant,
    db,
)
from services.message_dispatch import (
    _EVENT_REGISTRY,
    emit_messaging_event,
)
from services.push_providers import send_onesignal_push
from services.messaging_constants import (
    DeliveryStatus,
    EventName,
    SuppressionReason,
)
from tests.conftest import _make_trip, _make_user


def _add_token(user):
    db.session.add(
        PushDeviceToken(
            user_id=user.id,
            token=f"token-{user.id}",
            platform="ios",
            active=True,
        )
    )


def _friend_request(sender, recipient):
    invitation = Invitation(
        sender_id=sender.id,
        receiver_id=recipient.id,
        invite_type=InviteType.OUTBOUND,
        status="pending",
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation


def _emit(invitation, sender, recipient, **overrides):
    kwargs = {
        "event_name": EventName.FRIEND_REQUEST_CREATED,
        "actor_user_id": sender.id,
        "recipient_user_id": recipient.id,
        "entity_type": "user",
        "entity_id": sender.id,
        "metadata": {
            "actor_name": sender.first_name,
            "invitation_id": invitation.id,
        },
        "source_route": "test_message_send_safety",
    }
    kwargs.update(overrides)
    return emit_messaging_event(**kwargs)


def test_preference_opt_out_suppresses_before_provider(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user(
            "recipient",
            push_notifications_enabled=False,
        )
        invitation = _friend_request(sender, recipient)

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(invitation, sender, recipient)

        assert result.status == DeliveryStatus.SKIPPED
        assert result.suppression_reason == SuppressionReason.USER_OPTED_OUT
        provider.assert_not_called()
        row = db.session.get(MessageEventLog, result.mel_id)
        assert row.suppression_reason == SuppressionReason.USER_OPTED_OUT


def test_missing_recipient_fails_closed_before_provider(client):
    with app.app_context():
        sender = _make_user("sender")
        db.session.commit()

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = emit_messaging_event(
                event_name=EventName.FRIEND_REQUEST_CREATED,
                actor_user_id=sender.id,
                recipient_user_id=None,
                entity_type="user",
                entity_id=sender.id,
                metadata={"actor_name": sender.first_name},
                source_route="test_missing_recipient",
            )

        assert result.suppression_reason == SuppressionReason.INVALID_RECIPIENT
        provider.assert_not_called()


def test_actor_without_authoritative_invitation_is_denied(client):
    with app.app_context():
        sender = _make_user("sender")
        impostor = _make_user("impostor")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(
                invitation,
                impostor,
                recipient,
                occurrence_id="impostor-attempt",
            )

        assert result.suppression_reason == SuppressionReason.PRIVACY_DENIED
        provider.assert_not_called()


def test_missing_render_context_suppresses_instead_of_empty_string(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(
                invitation,
                sender,
                recipient,
                metadata={"invitation_id": invitation.id},
            )

        assert (
            result.suppression_reason
            == SuppressionReason.MISSING_REQUIRED_PAYLOAD
        )
        provider.assert_not_called()


def test_unsafe_deep_link_is_denied(client, monkeypatch):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)
        original = _EVENT_REGISTRY[EventName.FRIEND_REQUEST_CREATED]
        monkeypatch.setitem(
            _EVENT_REGISTRY,
            EventName.FRIEND_REQUEST_CREATED,
            replace(original, deep_link_template="//evil.example"),
        )

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(invitation, sender, recipient)

        assert result.suppression_reason == SuppressionReason.INVALID_DEEP_LINK
        provider.assert_not_called()


def test_channel_lookup_failure_fails_closed(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        invitation = _friend_request(sender, recipient)

        with patch.object(
            db.session,
            "query",
            side_effect=RuntimeError("database unavailable"),
        ), patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(invitation, sender, recipient)

        assert (
            result.suppression_reason
            == SuppressionReason.RECIPIENT_INELIGIBLE
        )
        provider.assert_not_called()


def test_invalid_runtime_environment_suppresses(client, monkeypatch):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)
        monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "unknown")

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = _emit(invitation, sender, recipient)

        assert (
            result.suppression_reason
            == SuppressionReason.ENVIRONMENT_BLOCKED
        )
        provider.assert_not_called()


def test_logical_occurrence_is_claimed_at_most_once(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)
        provider_result = {
            "success": True,
            "skipped": False,
            "provider_message_id": "provider-1",
        }

        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value=provider_result,
        ) as provider:
            first = _emit(invitation, sender, recipient)
            duplicate = _emit(invitation, sender, recipient)

        assert first.status == DeliveryStatus.SENT
        assert duplicate.suppression_reason == SuppressionReason.DUPLICATE_EVENT
        provider.assert_called_once()
        occurrence_rows = MessageEventLog.query.filter(
            MessageEventLog.occurrence_id.is_not(None)
        ).all()
        assert len(occurrence_rows) == 1
        assert occurrence_rows[0].delivery_status == DeliveryStatus.SENT


def test_distinct_occurrences_on_same_entity_are_both_sent(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)
        provider_result = {
            "success": True,
            "skipped": False,
            "provider_message_id": "provider-1",
        }

        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value=provider_result,
        ) as provider:
            first = _emit(
                invitation,
                sender,
                recipient,
                occurrence_id="transition-1",
            )
            second = _emit(
                invitation,
                sender,
                recipient,
                occurrence_id="transition-2",
            )

        assert first.status == second.status == DeliveryStatus.SENT
        assert provider.call_count == 2


def test_provider_failure_finalizes_claim_with_sanitized_error(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)

        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": False,
                "skipped": False,
                "error": "secret provider response body",
            },
        ):
            result = _emit(invitation, sender, recipient)

        row = db.session.get(MessageEventLog, result.mel_id)
        assert result.status == DeliveryStatus.FAILED
        assert row.delivery_status == DeliveryStatus.FAILED
        assert row.error_message == "provider_error"
        assert row.occurrence_id
        assert "secret" not in str(row.payload_json)
        assert row.payload_json == {
            "source_route": "test_message_send_safety",
            "event": EventName.FRIEND_REQUEST_CREATED,
        }


@pytest.mark.parametrize(
    "allowlisted,expected",
    [
        (False, SuppressionReason.PRIVACY_DENIED),
        (True, DeliveryStatus.SENT),
    ],
)
def test_founder_event_requires_exact_allowlisted_recipient(
    client,
    monkeypatch,
    allowlisted,
    expected,
):
    with app.app_context():
        actor = _make_user("actor")
        founder = _make_user(
            "founder",
            email="richardbattlebaxter@gmail.com",
        )
        _add_token(founder)
        db.session.commit()
        monkeypatch.setenv(
            "ALLOWED_ADMIN_EMAILS",
            founder.email if allowlisted else "another-admin@test.bl",
        )

        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "founder-provider-id",
            },
        ) as provider:
            result = emit_messaging_event(
                event_name=EventName.FOUNDER_NEW_USER,
                actor_user_id=actor.id,
                recipient_user_id=founder.id,
                entity_type="user",
                entity_id=actor.id,
                metadata={
                    "subject_user_id": actor.id,
                    "alert_body": "A user joined.",
                },
                source_route="test_founder_authorization",
            )

        if allowlisted:
            assert result.status == expected
            provider.assert_called_once()
        else:
            assert result.suppression_reason == expected
            provider.assert_not_called()


def test_founder_event_rejects_other_allowlisted_admin(client, monkeypatch):
    with app.app_context():
        actor = _make_user("actor")
        other_admin = _make_user("admin", email="admin@test.bl")
        _add_token(other_admin)
        db.session.commit()
        monkeypatch.setenv("ALLOWED_ADMIN_EMAILS", other_admin.email)

        with patch(
            "services.message_dispatch.send_onesignal_push"
        ) as provider:
            result = emit_messaging_event(
                event_name=EventName.FOUNDER_APP_OPEN,
                actor_user_id=actor.id,
                recipient_user_id=other_admin.id,
                entity_type="user",
                entity_id=actor.id,
                metadata={
                    "subject_user_id": actor.id,
                    "alert_body": "A user opened the app.",
                    "app_open_occurrence": "2026-09-04",
                },
                source_route="test_wrong_founder",
            )

        assert result.suppression_reason == SuppressionReason.PRIVACY_DENIED
        provider.assert_not_called()


def test_trip_update_requires_current_member_recipient(client):
    with app.app_context():
        owner = _make_user("owner")
        member = _make_user("member")
        outsider = _make_user("outsider")
        trip = _make_trip(owner, lifecycle_state="active")
        db.session.add(
            SkiTripParticipant(
                trip_id=trip.id,
                user_id=member.id,
                status=GuestStatus.GOING,
                role=ParticipantRole.GUEST,
            )
        )
        _add_token(member)
        _add_token(outsider)
        db.session.commit()
        trip_id = trip.id

        with patch(
            "services.message_dispatch.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "trip-provider-id",
            },
        ) as provider:
            allowed = emit_messaging_event(
                event_name=EventName.TRIP_DATES_UPDATED,
                actor_user_id=owner.id,
                recipient_user_id=member.id,
                entity_type="trip",
                entity_id=trip_id,
                occurrence_id="trip-change-1",
                metadata={
                    "actor_name": owner.first_name,
                    "resort": trip.mountain,
                    "trip_id": trip_id,
                },
            )
            denied = emit_messaging_event(
                event_name=EventName.TRIP_DATES_UPDATED,
                actor_user_id=owner.id,
                recipient_user_id=outsider.id,
                entity_type="trip",
                entity_id=trip_id,
                occurrence_id="trip-change-2",
                metadata={
                    "actor_name": owner.first_name,
                    "resort": trip.mountain,
                    "trip_id": trip_id,
                },
            )

        assert allowed.status == DeliveryStatus.SENT
        assert denied.suppression_reason == SuppressionReason.PRIVACY_DENIED
        provider.assert_called_once()


def test_automation_event_uses_same_safety_and_occurrence_claim(client):
    with app.app_context():
        actor = _make_user("actor")
        recipient = _make_user("recipient")
        db.session.add_all((
            Friend(user_id=actor.id, friend_id=recipient.id),
            Friend(user_id=recipient.id, friend_id=actor.id),
        ))
        _add_token(recipient)
        db.session.commit()

        with patch(
            "services.push_providers.send_onesignal_custom_event",
            return_value={"success": True, "sent": 1, "failed": 0},
        ) as provider:
            first = emit_messaging_event(
                event_name=EventName.FRIEND_PASS_CHANGED,
                actor_user_id=actor.id,
                recipient_user_id=recipient.id,
                entity_type="user",
                entity_id=actor.id,
                occurrence_id="pass-transition-1",
                metadata={
                    "actor_first_name": actor.first_name,
                    "new_pass": "ikon",
                    "new_pass_display": "Ikon Pass",
                },
            )
            duplicate = emit_messaging_event(
                event_name=EventName.FRIEND_PASS_CHANGED,
                actor_user_id=actor.id,
                recipient_user_id=recipient.id,
                entity_type="user",
                entity_id=actor.id,
                occurrence_id="pass-transition-1",
                metadata={
                    "actor_first_name": actor.first_name,
                    "new_pass": "ikon",
                    "new_pass_display": "Ikon Pass",
                },
            )

        assert first.status == DeliveryStatus.SENT
        assert duplicate.suppression_reason == SuppressionReason.DUPLICATE_EVENT
        provider.assert_called_once()


def test_overlapping_dispatches_call_provider_once(client):
    with app.app_context():
        sender = _make_user("sender")
        recipient = _make_user("recipient")
        _add_token(recipient)
        invitation = _friend_request(sender, recipient)
        sender_id = sender.id
        recipient_id = recipient.id
        invitation_id = invitation.id

    entered_provider = threading.Event()
    release_provider = threading.Event()
    results = []

    def provider(*_args, **_kwargs):
        entered_provider.set()
        assert release_provider.wait(timeout=5)
        return {
            "success": True,
            "skipped": False,
            "provider_message_id": "concurrent-provider-id",
        }

    def dispatch():
        with app.app_context():
            try:
                results.append(
                    emit_messaging_event(
                        event_name=EventName.FRIEND_REQUEST_CREATED,
                        actor_user_id=sender_id,
                        recipient_user_id=recipient_id,
                        entity_type="user",
                        entity_id=sender_id,
                        occurrence_id="concurrent-occurrence",
                        metadata={
                            "actor_name": "Sender",
                            "invitation_id": invitation_id,
                        },
                    )
                )
            finally:
                db.session.remove()

    with patch(
        "services.message_dispatch.send_onesignal_push",
        side_effect=provider,
    ) as provider_mock:
        first_thread = threading.Thread(target=dispatch)
        second_thread = threading.Thread(target=dispatch)
        first_thread.start()
        assert entered_provider.wait(timeout=5)
        second_thread.start()
        second_thread.join(timeout=5)
        release_provider.set()
        first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert provider_mock.call_count == 1
    assert sorted(result.status for result in results) == ["sent", "skipped"]
    assert any(
        result.suppression_reason == SuppressionReason.DUPLICATE_EVENT
        for result in results
    )


@pytest.mark.parametrize("failure_stage", ["preference", "token"])
def test_provider_eligibility_lookup_failures_never_send(
    client,
    monkeypatch,
    failure_stage,
):
    monkeypatch.setenv("ONESIGNAL_APP_ID", "test-app")
    monkeypatch.setenv("ONESIGNAL_REST_API_KEY", "test-key")
    preference_query = MagicMock()
    preference_query.filter.return_value.all.return_value = []
    query_side_effect = (
        RuntimeError("preference lookup failed")
        if failure_stage == "preference"
        else [preference_query, RuntimeError("token lookup failed")]
    )

    with app.app_context(), patch.object(
        db.session,
        "query",
        side_effect=query_side_effect,
    ), patch("services.push_providers.httpx.post") as provider:
        result = send_onesignal_push(
            [123],
            "Protected title",
            "Protected body",
        )

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skipped_reason"] == "eligibility_error"
    provider.assert_not_called()
