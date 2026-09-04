"""Focused integration coverage for dispatcher-owned durable outbox rows."""

from app import app
from models import MessageOutbox, db
from services.message_dispatch import (
    _get_event_spec,
    _outbox_render_metadata,
    enqueue_messaging_event,
    message_outbox_provider_callback,
    message_outbox_safety_callback,
    messaging_delivery_mode,
)
from services.messaging_constants import EventName, SuppressionReason
from tests.conftest import _make_user


def test_enqueue_is_transaction_neutral_and_stores_selectors_only(client):
    with app.app_context():
        actor = _make_user("outbox-actor")
        recipient = _make_user("outbox-recipient")
        db.session.commit()

        row = enqueue_messaging_event(
            EventName.FOUNDER_NEW_USER,
            actor.id,
            recipient.id,
            entity_type="user",
            entity_id=actor.id,
            occurrence_id="outbox-safe-occurrence",
            metadata={
                "subject_user_id": actor.id,
                "alert_body": "This must never enter the outbox",
                "actor_name": "This must never enter the outbox",
            },
            source_route="test_outbox_enqueue",
        )

        assert row.status == "pending"
        assert row.context_json == {
            "template": "enqueue_only",
            "object_type": "user",
            "object_id": actor.id,
        }
        assert row.evidence_ids_json == [f"subject_user_id:{actor.id}"]
        persisted = db.session.get(MessageOutbox, row.id)
        assert "alert_body" not in str(persisted.context_json)
        assert "actor_name" not in str(persisted.context_json)
        db.session.rollback()


def test_worker_safety_refuses_non_enqueue_family(client):
    with app.app_context():
        row = MessageOutbox(
            event_name=EventName.PUSH_TEST_SENT,
            category="system",
            occurrence_id="wrong-family",
            recipient_user_id=1,
            channel="push",
            provider="onesignal",
            context_json={"template": "inline"},
            evidence_ids_json=[],
        )
        decision = message_outbox_safety_callback(row)
        assert decision.allowed is False
        assert decision.suppression_reason == SuppressionReason.ENVIRONMENT_BLOCKED


def test_development_defaults_to_enqueue_only(client, monkeypatch):
    with app.app_context():
        monkeypatch.delenv("MESSAGE_DELIVERY_MODE", raising=False)
        monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "development")
        assert messaging_delivery_mode() == "enqueue_only"


def test_pass_change_outbox_rebuilds_pass_properties_from_user_state(client, monkeypatch):
    with app.app_context():
        actor = _make_user("pass-outbox-actor")
        recipient = _make_user("pass-outbox-recipient")
        actor.pass_type = "Epic, Ikon"
        db.session.commit()
        row = enqueue_messaging_event(
            EventName.FRIEND_PASS_CHANGED, actor.id, recipient.id,
            entity_type="user", entity_id=actor.id,
            occurrence_id="friend.pass.changed:user:pass-outbox-actor",
            metadata={"new_pass": "protected caller copy"},
        )
        assert "new_pass" not in row.context_json
        assert row.evidence_ids_json == []
        metadata = _outbox_render_metadata(
            row, _get_event_spec(EventName.FRIEND_PASS_CHANGED)
        )
        assert metadata["new_pass"] == "epic,ikon"
        assert metadata["new_pass_display"] == "Epic · Ikon"
        captured = {}

        def fake_custom_event(user_ids, event_name, properties):
            captured.update(
                user_ids=user_ids, event_name=event_name, properties=properties
            )
            return {
                "success": False, "skipped": False, "retryable": True,
                "retry_after": 45, "error": "http_429",
            }

        monkeypatch.setattr(
            "services.push_providers.send_onesignal_custom_event", fake_custom_event
        )
        outcome = message_outbox_provider_callback(row)
        assert captured["properties"]["new_pass"] == "epic,ikon"
        assert captured["properties"]["new_pass_display"] == "Epic · Ikon"
        assert outcome == {
            "status": "retryable", "error": "http_429", "retry_after": 45,
        }


def test_ambiguous_provider_result_is_never_automatically_retried(client, monkeypatch):
    with app.app_context():
        actor = _make_user("unknown-outbox-actor")
        recipient = _make_user("unknown-outbox-recipient")
        db.session.commit()
        row = enqueue_messaging_event(
            EventName.FOUNDER_NEW_USER,
            actor.id,
            recipient.id,
            entity_type="user",
            entity_id=actor.id,
            occurrence_id="founder.new.user:unknown-outcome",
            metadata={"subject_user_id": actor.id},
        )

        monkeypatch.setattr(
            "services.message_dispatch.send_onesignal_push",
            lambda *args, **kwargs: {
                "success": False,
                "skipped": False,
                "retryable": False,
                "delivery_unknown": True,
                "error": "timeout",
            },
        )
        assert message_outbox_provider_callback(row) == {
            "status": "delivery_unknown",
            "error": "timeout",
        }