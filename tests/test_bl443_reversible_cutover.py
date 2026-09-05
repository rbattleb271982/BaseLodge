"""Focused SQLite behavior for reversible per-family messaging controls."""

from datetime import datetime, timedelta
from unittest.mock import patch

from app import _finish_route_messaging_events, _stage_route_messaging_events
from models import (
    MessageEventLog,
    MessageOutbox,
    MessagingDeliveryPolicy,
    MessagingDeliveryPolicyEvent,
    db,
)
from services.messaging_cutover import (
    guarded_transition_inline,
    lock_policy_decisions,
    mutate_policy,
    terminalize_eligible,
)
from services.message_outbox import claim_messages, enqueue_message, mark_provider_started
from services.message_outbox_worker import run_worker
from services.messaging_staging import (
    finish_staged_messaging,
    stage_messaging_intents,
)


def _policy(name, mode="inline", paused=True, epoch=1, revision=1):
    row = MessagingDeliveryPolicy(
        event_name=name, delivery_mode=mode, cutover_epoch=epoch,
        claims_paused=paused, control_revision=revision,
        operator_reason="test bootstrap", audit_identity="test",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _outbox(name, occurrence, epoch=1, status="pending"):
    row = MessageOutbox(
        event_name=name, category="system", occurrence_id=occurrence,
        channel="push", provider="onesignal", context_json={},
        evidence_ids_json=[], configuration_epoch=epoch, status=status,
        next_attempt_at=datetime.utcnow(),
    )
    db.session.add(row)
    db.session.flush()
    return row


def test_missing_policy_fails_inline_and_staging_is_per_intent(client, app_fixture):
    with app_fixture.app_context():
        _policy("founder.invite_share", "enqueue_only", False)
        _policy("founder.app_open", "inline", True)
        db.session.commit()
        missing = lock_policy_decisions(["missing.event"], session=db.session)
        assert missing["missing.event"].delivery_mode == "inline"

        intents = (
            {"event_name": "founder.invite_share"},
            {"event_name": "founder.app_open"},
        )
        with patch("app.enqueue_messaging_event") as enqueue:
            plan = _stage_route_messaging_events(*intents)
        assert plan == (True, False)
        assert enqueue.call_count == 1
        with patch("app.emit_messaging_event", return_value="inline") as emit:
            assert _finish_route_messaging_events(plan, *intents) == ["inline"]
        emit.assert_called_once_with(**intents[1])


def test_claim_and_provider_start_require_active_unpaused_epoch(client, app_fixture):
    with app_fixture.app_context():
        policy = _policy("family.a", "enqueue_only", False, epoch=2)
        active = _outbox("family.a", "active", epoch=2)
        _outbox("family.a", "stale", epoch=1)
        db.session.commit()
        claimed = claim_messages("worker", session=db.session)
        assert [row.id for row in claimed] == [active.id]
        token = claimed[0].lease_token
        db.session.commit()

        policy = db.session.get(MessagingDeliveryPolicy, "family.a")
        policy.claims_paused = True
        policy.control_revision += 1
        db.session.commit()
        assert not mark_provider_started(active.id, token, session=db.session)
        assert db.session.get(MessageOutbox, active.id).attempt_count == 0


def test_terminalize_then_guarded_inline_transition_preserves_evidence(
    client, app_fixture
):
    with app_fixture.app_context():
        policy = _policy("family.a", "enqueue_only", True, epoch=3, revision=7)
        row = _outbox("family.a", "terminalize-me", epoch=3)
        db.session.commit()
        assert terminalize_eligible(
            "family.a", 3, reason="operator elected not to send",
            audit_identity="user:1", session=db.session,
        ) == 1
        db.session.commit()
        row = db.session.get(MessageOutbox, row.id)
        assert row.status == "operator_terminalized"
        assert row.final_event_log_id is not None
        assert db.session.get(MessageEventLog, row.final_event_log_id).delivery_status == "skipped"

        transitioned = guarded_transition_inline(
            "family.a", expected_revision=7, expected_epoch=3,
            reason="queue drained", audit_identity="user:1", session=db.session,
        )
        assert transitioned.delivery_mode == "inline"
        assert transitioned.cutover_epoch == 4
        assert transitioned.control_revision == 8
        assert db.session.query(MessagingDeliveryPolicyEvent).filter_by(
            action="transition_inline"
        ).count() == 1


def test_stale_revision_rejected_and_pause_does_not_advance_epoch(
    client, app_fixture
):
    with app_fixture.app_context():
        _policy("family.a", "inline", True, epoch=1, revision=2)
        db.session.commit()
        try:
            mutate_policy(
                "family.a", expected_revision=1, expected_epoch=1,
                claims_paused=False, reason="stale", audit_identity="user:1",
                session=db.session,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("stale control revision was accepted")
        db.session.rollback()
        row = mutate_policy(
            "family.a", expected_revision=2, expected_epoch=1,
            claims_paused=False, reason="ready for cutover",
            audit_identity="user:1", session=db.session,
        )
        assert row.cutover_epoch == 1
        assert row.control_revision == 3


def test_expired_pre_provider_claim_can_be_terminalized_but_started_cannot(
    client, app_fixture
):
    with app_fixture.app_context():
        _policy("family.a", "enqueue_only", True)
        old = datetime.utcnow() - timedelta(minutes=2)
        safe = _outbox("family.a", "safe-expired", status="processing")
        safe.provider_phase = "not_started"
        safe.lease_token = "safe"
        safe.lease_expires_at = old
        unsafe = _outbox("family.a", "unsafe-expired", status="processing")
        unsafe.provider_phase = "started"
        unsafe.lease_token = "unsafe"
        unsafe.lease_expires_at = old
        db.session.commit()
        assert terminalize_eligible(
            "family.a", 1, reason="drain", audit_identity="user:1",
            session=db.session,
        ) == 1
        db.session.commit()
        assert db.session.get(MessageOutbox, safe.id).status == "operator_terminalized"
        assert db.session.get(MessageOutbox, unsafe.id).status == "processing"


def test_expired_lease_cannot_cross_provider_boundary(client, app_fixture):
    with app_fixture.app_context():
        _policy("family.a", "enqueue_only", False)
        row = _outbox("family.a", "expired-start")
        db.session.commit()
        now = datetime.utcnow()
        claimed = claim_messages(
            "worker", now=now, lease_seconds=1, session=db.session
        )
        db.session.commit()
        assert not mark_provider_started(
            row.id, claimed[0].lease_token, now=now + timedelta(seconds=2),
            session=db.session,
        )
        assert db.session.get(MessageOutbox, row.id).attempt_count == 0


def test_staging_and_worker_use_exactly_one_sink_after_blocked_inline_rollback(
    client, app_fixture
):
    with app_fixture.app_context():
        family = "founder.invite_share"
        policy = _policy(family, "enqueue_only", True)
        db.session.commit()
        intent = {
            "event_name": family, "actor_user_id": 1, "recipient_user_id": 2,
            "occurrence_id": "sqlite-one-sink",
        }

        def enqueue_hook(**values):
            return enqueue_message(
                event_name=values["event_name"], category="system",
                occurrence_id=values["occurrence_id"],
                actor_user_id=values["actor_user_id"],
                recipient_user_id=values["recipient_user_id"],
                channel="push", provider="test", context={}, evidence_ids=[],
                configuration_epoch=values["configuration_epoch"],
                session=values["session"],
            )

        plan = stage_messaging_intents(
            (intent,), session=db.session, enqueue=enqueue_hook
        )
        db.session.commit()
        try:
            guarded_transition_inline(
                family, expected_revision=1, expected_epoch=1,
                reason="rollback race", audit_identity="operator",
                session=db.session,
            )
        except RuntimeError:
            db.session.rollback()
        else:
            raise AssertionError("inline transition bypassed queued work")

        sinks = {"inline": 0, "provider": 0}
        finish_staged_messaging(
            plan, (intent,), inline_emitter=lambda **_values: sinks.__setitem__(
                "inline", sinks["inline"] + 1
            ),
        )
        policy = db.session.get(MessagingDeliveryPolicy, family)
        policy.claims_paused = False
        policy.control_revision += 1
        db.session.commit()
        result = run_worker(
            lambda: db.session, owner="sqlite-sink-worker",
            safety_callback=lambda _row: True,
            provider_callback=lambda _row: (
                sinks.__setitem__("provider", sinks["provider"] + 1)
                or {"status": "provider_accepted"}
            ),
            batch_size=1, max_batches=1,
        )
        assert result.provider_accepted == 1
        assert sinks["inline"] + sinks["provider"] == 1
