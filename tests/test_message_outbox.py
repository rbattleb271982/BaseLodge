"""Focused behavioral coverage for durable outbox primitives."""

from datetime import datetime, timedelta

from models import MessageOutbox, MessagingDeliveryPolicy, db
from services.message_outbox import (
    claim_messages,
    deterministic_backoff,
    enqueue_message,
    finalize_message,
    mark_provider_started,
    queue_health,
    recover_expired_leases,
    sanitize_error,
)
from services.message_outbox_worker import run_worker


def _enqueue(occurrence, recipient=101):
    if db.session.get(MessagingDeliveryPolicy, "test.event") is None:
        db.session.add(MessagingDeliveryPolicy(
            event_name="test.event", delivery_mode="enqueue_only",
            cutover_epoch=1, claims_paused=False, control_revision=1,
            operator_reason="test", audit_identity="test",
        ))
        db.session.flush()
    return enqueue_message(
        event_name="test.event",
        category="test",
        occurrence_id=occurrence,
        recipient_user_id=recipient,
        channel="push",
        provider="test",
        context={"route": "/test"},
        evidence_ids=["policy:1"],
    )


def test_enqueue_is_transaction_neutral_and_claim_is_token_guarded(
    client, app_fixture
):
    with app_fixture.app_context():
        row = _enqueue("outbox:transaction")
        row_id = row.id
        db.session.rollback()
        assert db.session.get(MessageOutbox, row_id) is None

        row = _enqueue("outbox:claim")
        db.session.commit()
        claimed = claim_messages("worker-a", session=db.session)
        assert [item.id for item in claimed] == [row.id]
        assert claimed[0].attempt_count == 0
        token = claimed[0].lease_token
        db.session.commit()

        assert not finalize_message(
            row.id, "wrong-token", "provider_accepted", session=db.session
        )
        assert mark_provider_started(row.id, token, session=db.session)
        assert db.session.get(MessageOutbox, row.id).attempt_count == 1
        assert finalize_message(
            row.id,
            token,
            "provider_accepted",
            provider_message_id="provider-1",
            session=db.session,
        )
        db.session.commit()
        finished = db.session.get(MessageOutbox, row.id)
        assert finished.status == "provider_accepted"
        assert finished.provider_phase == "accepted"


def test_expired_started_lease_is_never_blindly_retried(client, app_fixture):
    with app_fixture.app_context():
        safe = _enqueue("outbox:safe")
        unsafe = _enqueue("outbox:unsafe", recipient=102)
        db.session.commit()
        now = datetime.utcnow()
        claimed = claim_messages(
            "worker-a", limit=2, lease_seconds=10, now=now, session=db.session
        )
        tokens = {row.id: row.lease_token for row in claimed}
        assert mark_provider_started(
            unsafe.id, tokens[unsafe.id], now=now, session=db.session
        )
        db.session.commit()

        result = recover_expired_leases(
            now=now + timedelta(seconds=11), session=db.session
        )
        db.session.commit()
        assert result == {"reclaimed": 1, "delivery_unknown": 1}
        assert db.session.get(MessageOutbox, safe.id).status == "retryable"
        assert db.session.get(MessageOutbox, unsafe.id).status == "delivery_unknown"


def test_backoff_health_and_bounded_worker(client, app_fixture):
    with app_fixture.app_context():
        first = deterministic_backoff(3, identity=44)
        assert first == deterministic_backoff(3, identity=44)
        assert 120 <= first <= 3600
        _enqueue("outbox:worker")
        db.session.commit()

        result = run_worker(
            lambda: db.session,
            owner="worker-test",
            safety_callback=lambda row: True,
            provider_callback=lambda row: {
                "status": "provider_accepted",
                "provider_message_id": "accepted-1",
            },
            batch_size=1,
            max_batches=1,
        )
        assert result.claimed == 1
        assert result.provider_accepted == 1
        health = queue_health(session=db.session)
        assert health["counts"]["provider_accepted"] == 1


def test_enqueue_duplicate_is_transaction_neutral_and_context_is_restricted(
    client, app_fixture
):
    with app_fixture.app_context():
        first = _enqueue("outbox:duplicate")
        duplicate = _enqueue("outbox:duplicate")
        assert duplicate is first
        assert db.session.query(MessageOutbox).count() == 1
        db.session.rollback()

        forbidden_contexts = (
            {"title": "not allowed"},
            {"push_token": "not allowed"},
            {"route": {"nested": "not allowed"}},
            {"unknown": "not allowed"},
            {"route": ["not allowed"]},
        )
        for context in forbidden_contexts:
            try:
                enqueue_message(
                    event_name="test.event",
                    category="test",
                    occurrence_id="outbox:invalid:" + str(context),
                    recipient_user_id=101,
                    channel="push",
                    provider="test",
                    context=context,
                )
            except ValueError:
                pass
            else:
                raise AssertionError("restricted context was accepted")


def test_provider_failure_dictionary_without_status_is_not_accepted(
    client, app_fixture
):
    with app_fixture.app_context():
        _enqueue("outbox:provider-failure")
        db.session.commit()
        result = run_worker(
            lambda: db.session,
            owner="worker-test",
            safety_callback=lambda row: True,
            provider_callback=lambda row: {"error": "provider timed out"},
            batch_size=1,
            max_batches=1,
        )
        assert result.delivery_unknown == 1
        row = db.session.query(MessageOutbox).one()
        assert row.status == "delivery_unknown"


def test_retry_after_is_bounded_and_definitive_retryable_outcome_is_retried(
    client, app_fixture
):
    with app_fixture.app_context():
        row = _enqueue("outbox:retry-after")
        db.session.commit()
        now = datetime.utcnow()
        claimed = claim_messages("worker-a", now=now, session=db.session)
        token = claimed[0].lease_token
        assert mark_provider_started(row.id, token, now=now, session=db.session)
        assert finalize_message(
            row.id, token, "retryable", now=now, retry_after_seconds=9999,
            backoff_maximum_seconds=120, session=db.session,
        )
        db.session.commit()
        assert db.session.get(MessageOutbox, row.id).next_attempt_at == (
            now + timedelta(seconds=120)
        )

        _enqueue("outbox:definitive-transient", recipient=102)
        db.session.commit()
        result = run_worker(
            lambda: db.session,
            owner="worker-test",
            safety_callback=lambda row: True,
            provider_callback=lambda row: {
                "status": "retryable", "error": "http_429", "retry_after": 90,
            },
            batch_size=1,
            max_batches=1,
        )
        assert result.retryable == 1
        assert result.delivery_unknown == 0


def test_enqueue_rejects_protected_identifiers_and_sanitizes_diagnostics(
    client, app_fixture
):
    with app_fixture.app_context():
        invalid_occurrences = (
            "contains whitespace", "https://example.test/path?token=secret",
            "person@example.test", "Bearer secret-value", "id?signature=abc",
        )
        for occurrence in invalid_occurrences:
            try:
                _enqueue(occurrence)
            except ValueError:
                pass
            else:
                raise AssertionError("protected occurrence was accepted")
        for evidence in (
            ["person@example.test"], ["policy:not-an-id"], ["unknown:1"],
            ["policy:1"] * 21,
        ):
            try:
                enqueue_message(
                    event_name="test.event", category="test",
                    occurrence_id="outbox:evidence:" + str(len(evidence)),
                    recipient_user_id=101, channel="push", provider="test",
                    evidence_ids=evidence,
                )
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe evidence was accepted")
        error = sanitize_error(
            "Authorization: Bearer abc.def https://host.test/callback?X-Amz-Signature=xyz"
        )
        assert "abc.def" not in error
        assert "X-Amz-Signature" not in error
        assert "host.test" not in error