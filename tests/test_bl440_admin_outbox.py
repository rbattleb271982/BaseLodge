"""Focused authorization and data-minimization coverage for outbox operations."""

import os
from unittest.mock import patch

from app import app
from models import db, MessageOutbox, MessagingDeliveryPolicy
from tests.conftest import _login, _make_user, json_post


HEALTH = "/api/admin/message-outbox/health"
TERMINAL = "/api/admin/message-outbox/terminal"


def _row(recipient_id, *, status="dead_letter", occurrence="outbox-test",
         context=None, evidence=None):
    if db.session.get(MessagingDeliveryPolicy, "test.event") is None:
        db.session.add(MessagingDeliveryPolicy(
            event_name="test.event", delivery_mode="enqueue_only",
            cutover_epoch=1, claims_paused=False, control_revision=1,
            operator_reason="test", audit_identity="test",
        ))
    row = MessageOutbox(
        event_name="test.event",
        category="system",
        occurrence_id=occurrence,
        recipient_user_id=recipient_id,
        channel="push",
        provider="onesignal",
        context_json={"token": "must-not-appear"} if context is None else context,
        evidence_ids_json=(
            ["recipient:private"] if evidence is None else evidence
        ),
        status=status,
        last_error="token=private recipient@example.test",
        provider_message_id="provider-id",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _admin(client):
    with app.app_context():
        user = _make_user("outbox-admin", email="outbox-admin@bl.test")
        db.session.commit()
        result = (user.id, user.email)
    _login(client, result[0])
    return result


def test_health_and_terminal_require_admin(client):
    admin_id, admin_email = _admin(client)
    response = client.get(HEALTH)
    assert response.status_code == 403

    _login(client, admin_id)
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        response = client.get(HEALTH)
    assert response.status_code == 200


def test_terminal_projection_redacts_payload_and_error_pii(client):
    admin_id, admin_email = _admin(client)
    with app.app_context():
        row = _row(admin_id)
        db.session.commit()
        row_id = row.id

    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        payload = client.get(TERMINAL).get_json()
    result = next(item for item in payload["rows"] if item["id"] == row_id)
    serialized = str(result)
    assert "private" not in serialized
    assert "recipient@example.test" not in serialized
    assert "context_json" not in result
    assert result["reason"] == "token=<redacted> <redacted-email>"


def test_replay_requires_csrf_and_creates_linked_new_row(client):
    admin_id, admin_email = _admin(client)
    with app.app_context():
        original = _row(
            admin_id,
            occurrence="original",
            context={},
            evidence=["policy:1"],
        )
        db.session.commit()
        original_id = original.id

    route = f"/api/admin/message-outbox/{original_id}/replay"
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        assert client.post(route, json={}).status_code == 403
        with patch("app.message_outbox_safety_callback", return_value=True):
            response = json_post(client, route, {
                "reason": "focused test replay",
                "idempotency_key": "focused-replay-1",
                "expected_source_status": "dead_letter",
            })
    assert response.status_code == 201
    replay_id = response.get_json()["replay"]["id"]
    with app.app_context():
        original = db.session.get(MessageOutbox, original_id)
        replay = db.session.get(MessageOutbox, replay_id)
        assert original.status == "dead_letter"
        assert replay.replay_of_outbox_id == original.id
        assert replay.occurrence_id != original.occurrence_id
        with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
            again = json_post(client, route, {
                "reason": "focused test replay",
                "idempotency_key": "focused-replay-1",
                "expected_source_status": "dead_letter",
            })
        assert again.status_code == 200
        with app.app_context():
            assert MessageOutbox.query.filter_by(
                replay_of_outbox_id=original_id
            ).count() == 1


def test_delivery_unknown_replay_acknowledgement_and_production_denial(client):
    admin_id, admin_email = _admin(client)
    with app.app_context():
        row = _row(
            admin_id,
            status="delivery_unknown",
            context={},
            evidence=["policy:1"],
        )
        db.session.commit()
        row_id = row.id
    route = f"/api/admin/message-outbox/{row_id}/replay"

    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        assert json_post(client, route).status_code == 400
        with patch.dict(app.config, {"BASELODGE_RUNTIME_ENV": "production"}):
            response = json_post(
                client, route, {"duplicate_risk_acknowledged": True}
            )
    assert response.status_code == 403


def test_replay_lineage_ambiguity_cannot_be_bypassed_via_original(client):
    admin_id, admin_email = _admin(client)
    with app.app_context():
        original = _row(
            admin_id, status="dead_letter", occurrence="lineage-original",
            context={}, evidence=["policy:1"],
        )
        child = _row(
            admin_id, status="delivery_unknown", occurrence="lineage-child",
            context={}, evidence=["policy:1"],
        )
        child.replay_of_outbox_id = original.id
        db.session.commit()
        original_id = original.id
    route = f"/api/admin/message-outbox/{original_id}/replay"
    base = {
        "reason": "reconciled lineage replay",
        "idempotency_key": "lineage-second-request",
        "expected_source_status": "dead_letter",
    }
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        with patch("app.message_outbox_safety_callback", return_value=True):
            assert json_post(client, route, base).status_code == 400
            assert json_post(client, route, {
                **base, "duplicate_risk_acknowledged": True,
            }).status_code == 400
            response = json_post(client, route, {
                **base,
                "duplicate_risk_acknowledged": True,
                "reconciliation_notes": "Provider reconciliation found no acceptance.",
            })
    assert response.status_code == 201
    with app.app_context():
        replay = MessageOutbox.query.filter_by(
            replay_of_outbox_id=original_id, status="pending"
        ).one()
        from models import MessagingReplayEvent
        evidence = MessagingReplayEvent.query.filter_by(
            target_outbox_id=replay.id
        ).one()
        assert evidence.duplicate_risk_acknowledged is True
        assert evidence.reconciliation_notes == (
            "Provider reconciliation found no acceptance."
        )


def test_runner_import_does_not_import_flask_application(monkeypatch):
    import builtins
    import importlib

    original_import = builtins.__import__

    def reject_app(name, *args, **kwargs):
        if name == "app":
            raise AssertionError("runner import must not initialize Flask")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_app)
    import sys
    sys.modules.pop("run_message_outbox_worker", None)
    importlib.import_module("run_message_outbox_worker")