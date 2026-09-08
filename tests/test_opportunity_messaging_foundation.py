"""Focused Task #502 Slice 1 opportunity-message safety coverage."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from app import app
from models import (
    MessageOutbox,
    MessagingDeliveryPolicy,
    MessagingDeliveryPolicyEvent,
    db,
)
from services.message_dispatch import (
    _rendered_links_are_safe,
    emit_messaging_event,
    enqueue_messaging_event,
    message_outbox_opportunity_start_callback,
    message_outbox_provider_callback,
    message_outbox_safety_callback,
)
from services.message_outbox import (
    claim_messages,
    enqueue_message,
    lock_opportunity_siblings,
    lock_opportunity_trip,
    mark_opportunity_provider_started,
    mark_provider_started,
)
from services.messaging_constants import (
    EventName,
    OPPORTUNITY_EVENT_TYPES,
    SuppressionReason,
    is_opportunity_event,
)
from services.messaging_staging import finish_staged_messaging
from services.messaging_staging import stage_messaging_intents
from services.opportunity_messaging import (
    lock_opportunity_policy_decisions,
    opportunity_activation_boundary,
    opportunity_occurrence_id,
    register_opportunity_policy,
    stage_opportunity_intents,
)
from tests.conftest import _make_trip, _make_user


def _policy(event_name, *, mode="enqueue_only", paused=True, epoch=1, revision=1):
    row = MessagingDeliveryPolicy(
        event_name=event_name,
        delivery_mode=mode,
        claims_paused=paused,
        cutover_epoch=epoch,
        control_revision=revision,
        operator_reason="test opportunity policy",
        audit_identity="test",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _activation_event(
    policy,
    *,
    action="opportunity_registered",
    epoch=None,
    revision=None,
    created_at=None,
    reason="test activation",
    identity="test",
):
    row = MessagingDeliveryPolicyEvent(
        event_name=policy.event_name,
        delivery_mode="enqueue_only",
        cutover_epoch=policy.cutover_epoch if epoch is None else epoch,
        claims_paused=policy.claims_paused,
        control_revision=(
            policy.control_revision if revision is None else revision
        ),
        action=action,
        operator_reason=reason,
        audit_identity=identity,
        created_at=created_at or datetime.utcnow(),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _opportunity_intent(event_name, actor, recipient, trip, **metadata):
    return {
        "event_name": event_name,
        "actor_user_id": actor.id,
        "recipient_user_id": recipient.id,
        "entity_type": "trip",
        "entity_id": trip.id,
        "occurrence_id": opportunity_occurrence_id(event_name, trip.id),
        "metadata": metadata,
        "source_route": "test_opportunity_foundation",
    }


def _enqueue_opportunity(**intent):
    boundary = opportunity_activation_boundary(
        intent["event_name"], session=db.session
    )
    return enqueue_messaging_event(
        **intent,
        activation_boundary=boundary,
        session=db.session,
    )


def _enable_worker_policy(event_name):
    policy = db.session.get(MessagingDeliveryPolicy, event_name)
    if policy is None:
        policy = _policy(event_name, paused=True)
        _activation_event(policy)
    else:
        policy.delivery_mode = "enqueue_only"
        existing_audit = (
            db.session.query(MessagingDeliveryPolicyEvent)
            .filter_by(
                event_name=event_name,
                delivery_mode="enqueue_only",
                cutover_epoch=policy.cutover_epoch,
            )
            .first()
        )
        if existing_audit is None:
            was_paused = policy.claims_paused
            policy.claims_paused = True
            _activation_event(policy)
            policy.claims_paused = was_paused
    policy.claims_paused = False
    db.session.flush()
    return policy


def test_opportunity_classification_and_occurrence_contract():
    assert OPPORTUNITY_EVENT_TYPES == {
        EventName.FRIEND_TRIP_CREATED,
        EventName.WISHLIST_MATCH_DETECTED,
    }
    assert is_opportunity_event(EventName.FRIEND_TRIP_CREATED)
    assert not is_opportunity_event(EventName.FRIEND_REQUEST_CREATED)

    generic = opportunity_occurrence_id(EventName.FRIEND_TRIP_CREATED, 42)
    wishlist = opportunity_occurrence_id(
        EventName.WISHLIST_MATCH_DETECTED, 42
    )
    assert generic == "opportunity.friend_trip.v1.trip:42"
    assert generic == opportunity_occurrence_id(
        EventName.FRIEND_TRIP_CREATED, 42
    )
    assert wishlist == "opportunity.wishlist_match.v1.trip:42"
    assert generic != wishlist
    assert generic != opportunity_occurrence_id(
        EventName.FRIEND_TRIP_CREATED, 43
    )
    assert len(generic) <= 191

    for invalid in (None, True, 0, -1, "42"):
        with pytest.raises(ValueError):
            opportunity_occurrence_id(EventName.FRIEND_TRIP_CREATED, invalid)
    with pytest.raises(ValueError):
        opportunity_occurrence_id(EventName.FRIEND_REQUEST_CREATED, 42)


def test_policy_boundary_requires_current_audited_enqueue_generation(
    client, app_fixture
):
    with app_fixture.app_context():
        event_name = EventName.FRIEND_TRIP_CREATED
        missing = lock_opportunity_policy_decisions(
            (event_name,), session=db.session
        )[event_name]
        assert not missing.eligible
        assert missing.reason == "missing_policy"

        policy = _policy(event_name, mode="inline")
        invalid = lock_opportunity_policy_decisions(
            (event_name,), session=db.session
        )[event_name]
        assert not invalid.eligible
        assert invalid.reason == "invalid_policy"

        policy.delivery_mode = "enqueue_only"
        db.session.flush()
        unaudited = lock_opportunity_policy_decisions(
            (event_name,), session=db.session
        )[event_name]
        assert not unaudited.eligible
        assert unaudited.reason == "missing_activation_audit"

        _activation_event(policy, epoch=policy.cutover_epoch + 1)
        stale = lock_opportunity_policy_decisions(
            (event_name,), session=db.session
        )[event_name]
        assert not stale.eligible

        boundary = datetime.utcnow() - timedelta(minutes=5)
        _activation_event(policy, created_at=boundary)
        valid = lock_opportunity_policy_decisions(
            (event_name,), session=db.session
        )[event_name]
        assert valid.eligible
        assert valid.cutover_epoch == policy.cutover_epoch
        assert valid.claims_paused is True
        assert valid.activation_boundary == boundary
        assert opportunity_activation_boundary(
            event_name, session=db.session
        ) == boundary

        registered, audit = register_opportunity_policy(
            EventName.WISHLIST_MATCH_DETECTED,
            reason="prepare dormant wishlist opportunities",
            audit_identity="test operator",
            production=False,
            session=db.session,
        )
        assert registered.delivery_mode == "enqueue_only"
        assert registered.claims_paused is True
        assert audit.action == "opportunity_registered"
        assert audit.claims_paused is True
        assert opportunity_activation_boundary(
            EventName.WISHLIST_MATCH_DETECTED, session=db.session
        ) == audit.created_at


def test_enqueue_rejects_reused_policy_proof_and_boundary_epoch_mismatch(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-proof-actor")
        recipient = _make_user("opp-proof-recipient")
        trip = _make_trip(actor)
        policy = _policy(EventName.FRIEND_TRIP_CREATED, paused=True)
        _activation_event(policy)
        db.session.commit()
        decision = lock_opportunity_policy_decisions(
            (EventName.FRIEND_TRIP_CREATED,), session=db.session
        )[EventName.FRIEND_TRIP_CREATED]
        boundary = decision.activation_boundary
        db.session.commit()

        policy = db.session.get(
            MessagingDeliveryPolicy, EventName.FRIEND_TRIP_CREATED
        )
        policy.delivery_mode = "inline"
        policy.control_revision += 1
        db.session.commit()
        intent = _opportunity_intent(
            EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
        )
        with pytest.raises(ValueError):
            enqueue_messaging_event(
                **intent,
                configuration_epoch=decision.cutover_epoch,
                activation_boundary=boundary,
                opportunity_policy_decision=decision,
                session=db.session,
            )

        policy.delivery_mode = "enqueue_only"
        policy.cutover_epoch = 2
        policy.control_revision += 1
        policy.claims_paused = True
        _activation_event(policy)
        db.session.commit()
        current_boundary = opportunity_activation_boundary(
            EventName.FRIEND_TRIP_CREATED, session=db.session
        )
        with pytest.raises(ValueError):
            enqueue_messaging_event(
                **intent,
                configuration_epoch=1,
                activation_boundary=current_boundary,
                session=db.session,
            )
        assert db.session.query(MessageOutbox).count() == 0


def test_enqueue_rejects_policy_proof_from_rolled_back_savepoint(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-savepoint-proof-actor")
        recipient = _make_user("opp-savepoint-proof-recipient")
        trip = _make_trip(actor)
        db.session.commit()

        nested = db.session.begin_nested()
        register_opportunity_policy(
            EventName.FRIEND_TRIP_CREATED,
            reason="temporary nested registration",
            audit_identity="test operator",
            production=False,
            session=db.session,
        )
        decision = lock_opportunity_policy_decisions(
            (EventName.FRIEND_TRIP_CREATED,), session=db.session
        )[EventName.FRIEND_TRIP_CREATED]
        boundary = decision.activation_boundary
        nested.rollback()
        assert db.session.get(
            MessagingDeliveryPolicy, EventName.FRIEND_TRIP_CREATED
        ) is None

        with pytest.raises(ValueError):
            enqueue_messaging_event(
                **_opportunity_intent(
                    EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
                ),
                configuration_epoch=decision.cutover_epoch,
                activation_boundary=boundary,
                opportunity_policy_decision=decision,
                session=db.session,
            )
        db.session.rollback()


def test_opportunity_staging_is_paused_safe_atomic_and_has_no_inline_fallback(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-stage-actor")
        first = _make_user("opp-stage-first")
        second = _make_user("opp-stage-second")
        trip = _make_trip(actor)
        policy = _policy(EventName.FRIEND_TRIP_CREATED, paused=True)
        _activation_event(policy)
        db.session.commit()

        intents = (
            _opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, first, trip
            ),
            _opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, second, trip
            ),
        )
        calls = []

        def enqueue_ok(**values):
            calls.append(values)

        plan = stage_opportunity_intents(
            intents, session=db.session, enqueue=enqueue_ok
        )
        assert plan == (True, True)
        assert len(calls) == 2
        assert {call["configuration_epoch"] for call in calls} == {1}
        assert policy.claims_paused is True

        with patch("services.message_dispatch.send_onesignal_push") as provider:
            with pytest.raises(RuntimeError):
                finish_staged_messaging(
                    (False,), (intents[0],), inline_emitter=emit_messaging_event
                )
        provider.assert_not_called()

        calls.clear()
        policy.delivery_mode = "inline"
        db.session.flush()
        assert stage_opportunity_intents(
            (intents[0],), session=db.session, enqueue=enqueue_ok
        ) == (False,)
        assert calls == []

        with pytest.raises(RuntimeError):
            stage_messaging_intents(
                (intents[0],), session=db.session, enqueue=enqueue_ok
            )
        assert calls == []


def test_failed_staging_rolls_back_all_rows_and_evidence_is_bounded(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-rollback-actor")
        first = _make_user("opp-rollback-first")
        second = _make_user("opp-rollback-second")
        trip = _make_trip(actor)
        policy = _policy(EventName.WISHLIST_MATCH_DETECTED)
        _activation_event(policy)
        db.session.commit()
        intents = (
            _opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED,
                actor,
                first,
                trip,
                resort_id=7,
                rsvp_transition_id=9,
            ),
            _opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED,
                actor,
                second,
                trip,
                resort_id=7,
            ),
        )
        call_count = 0

        def enqueue_then_fail(**values):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("forced staging failure")
            return enqueue_messaging_event(**values)

        with pytest.raises(ValueError):
            stage_opportunity_intents(
                intents, session=db.session, enqueue=enqueue_then_fail
            )
        assert db.session.query(MessageOutbox).count() == 0

        assert stage_opportunity_intents(
            (intents[0],),
            session=db.session,
            enqueue=enqueue_messaging_event,
        ) == (True,)
        staged_id = db.session.query(MessageOutbox.id).scalar()
        assert staged_id is not None
        db.session.rollback()
        assert db.session.get(MessageOutbox, staged_id) is None

        row = enqueue_message(
            event_name="test.evidence",
            category="test",
            occurrence_id="test.evidence:valid",
            recipient_user_id=first.id,
            channel="push",
            provider="test",
            evidence_ids=["resort_id:7", "rsvp_transition_id:9"],
            session=db.session,
        )
        assert row.evidence_ids_json == [
            "resort_id:7",
            "rsvp_transition_id:9",
        ]
        db.session.rollback()

        invalid_sets = (
            ["resort_id:0"],
            ["resort_id:not-an-id"],
            ["resort_id:7", {"nested": 9}],
            ["unsupported_id:7"],
            ["resort_id:7"] * 21,
        )
        for index, evidence in enumerate(invalid_sets, start=1):
            with pytest.raises(ValueError):
                enqueue_message(
                    event_name="test.evidence",
                    category="test",
                    occurrence_id=f"test.evidence:invalid:{index}",
                    recipient_user_id=first.id,
                    channel="push",
                    provider="test",
                    evidence_ids=evidence,
                    session=db.session,
                )


def test_generic_emit_and_unstarted_row_cannot_reach_opportunity_provider(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-deny-actor")
        recipient = _make_user("opp-deny-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        db.session.commit()
        intent = _opportunity_intent(
            EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
        )

        with patch("services.message_dispatch.send_onesignal_push") as provider:
            result = emit_messaging_event(**intent)
        assert result.suppression_reason == SuppressionReason.NOT_IMPLEMENTED
        provider.assert_not_called()

        row = _enqueue_opportunity(**intent)
        assert row.provider == "onesignal"
        decision = message_outbox_safety_callback(row)
        assert not decision.allowed
        assert decision.suppression_reason == SuppressionReason.PRIVACY_DENIED

        with patch("services.message_dispatch.send_onesignal_push") as provider:
            outcome = message_outbox_provider_callback(row)
        assert outcome == {
            "status": "dead_letter",
            "error": "opportunity_provider_start_required",
        }
        provider.assert_not_called()


@pytest.mark.parametrize(
    ("path", "safe"),
    (
        ("/friend-trip/1", True),
        ("/friend-trip/987654", True),
        ("/friend-trip/0", False),
        ("/friend-trip/-1", False),
        ("/friend-trip/not-a-number", False),
        ("/friend-trip/1?next=/admin", False),
        ("/friend-trip/../admin", False),
        ("https://evil.example/friend-trip/1", False),
        ("//evil.example/friend-trip/1", False),
    ),
)
def test_friend_trip_deep_link_allowlist(path, safe):
    rendered = {"push_data": {"deep_link": path, "url": path}}
    assert _rendered_links_are_safe(rendered) is safe


def test_trip_mutex_and_wishlist_precedence_start_only_one_sibling(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-arb-actor")
        recipient = _make_user("opp-arb-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED,
                actor,
                recipient,
                trip,
                resort_id=7,
            )
        )
        db.session.commit()
        claimed = claim_messages("opp-worker", limit=2, session=db.session)
        tokens = {row.id: row.lease_token for row in claimed}
        db.session.commit()

        result = mark_opportunity_provider_started(
            wishlist.id,
            tokens[wishlist.id],
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert result.status == "started"
        assert result.winner_outbox_id == wishlist.id
        assert result.suppressed_outbox_ids == (generic.id,)
        db.session.commit()

        generic = db.session.get(MessageOutbox, generic.id)
        wishlist = db.session.get(MessageOutbox, wishlist.id)
        assert generic.status == "suppressed"
        assert generic.provider_phase == "not_started"
        assert wishlist.status == "processing"
        assert wishlist.provider_phase == "started"
        assert wishlist.attempt_count == 1


@pytest.mark.parametrize(
    ("generic_status", "generic_phase"),
    (
        ("provider_accepted", "accepted"),
        ("delivery_unknown", "unknown"),
    ),
)
def test_locked_sibling_refresh_preserves_irreversible_external_state(
    client, app_fixture, generic_status, generic_phase
):
    with app_fixture.app_context():
        actor = _make_user(f"opp-stale-actor-{generic_status}")
        recipient = _make_user(f"opp-stale-recipient-{generic_status}")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        db.session.commit()
        claimed = claim_messages("stale-worker", limit=2, session=db.session)
        tokens = {row.id: row.lease_token for row in claimed}
        generic_id = generic.id
        wishlist_id = wishlist.id
        db.session.commit()

        # Keep stale processing/not_started state in the primary identity map.
        assert db.session.get(MessageOutbox, generic_id).status == "processing"
        external = sa.orm.Session(db.engine)
        try:
            external.execute(
                sa.update(MessageOutbox)
                .where(MessageOutbox.id == generic_id)
                .values(
                    status=generic_status,
                    provider_phase=generic_phase,
                    lease_token=None,
                    lease_owner=None,
                    leased_at=None,
                    lease_expires_at=None,
                    completed_at=datetime.utcnow(),
                )
            )
            external.commit()
        finally:
            external.close()

        result = mark_opportunity_provider_started(
            wishlist_id,
            tokens[wishlist_id],
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert result.status == "suppressed"
        db.session.rollback()
        db.session.expire_all()
        preserved = db.session.get(MessageOutbox, generic_id)
        assert preserved.status == generic_status
        assert preserved.provider_phase == generic_phase


def test_locked_sibling_refresh_detects_replaced_claim(client, app_fixture):
    with app_fixture.app_context():
        actor = _make_user("opp-replaced-actor")
        recipient = _make_user("opp-replaced-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        row = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        db.session.commit()
        claimed = claim_messages("old-worker", limit=1, session=db.session)
        old_token = claimed[0].lease_token
        row_id = row.id
        db.session.commit()
        assert db.session.get(MessageOutbox, row_id).lease_token == old_token

        external = sa.orm.Session(db.engine)
        try:
            external.execute(
                sa.update(MessageOutbox)
                .where(MessageOutbox.id == row_id)
                .values(lease_token="replacement-lease", lease_owner="new-worker")
            )
            external.commit()
        finally:
            external.close()

        result = mark_opportunity_provider_started(
            row_id,
            old_token,
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert result.status == "lease_lost"
        db.session.rollback()
        db.session.expire_all()
        assert (
            db.session.get(MessageOutbox, row_id).lease_token
            == "replacement-lease"
        )


def test_lease_expiry_during_authorization_rolls_back_sibling_suppression(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-expiry-actor")
        recipient = _make_user("opp-expiry-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        db.session.commit()
        started_at = datetime.utcnow()
        claimed = claim_messages(
            "expiring-worker",
            limit=2,
            lease_seconds=1,
            now=started_at,
            session=db.session,
        )
        tokens = {row.id: row.lease_token for row in claimed}
        generic_id = generic.id
        wishlist_id = wishlist.id
        db.session.commit()

        with patch(
            "services.message_outbox._now",
            side_effect=(
                started_at,
                started_at + timedelta(seconds=2),
                started_at + timedelta(seconds=2),
            ),
        ):
            result = mark_opportunity_provider_started(
                wishlist_id,
                tokens[wishlist_id],
                safety_callback=lambda _row: True,
                session=db.session,
            )
        assert result.status == "lease_lost"
        db.session.rollback()
        db.session.expire_all()
        generic = db.session.get(MessageOutbox, generic_id)
        wishlist = db.session.get(MessageOutbox, wishlist_id)
        assert generic.status == "processing"
        assert generic.provider_phase == "not_started"
        assert wishlist.status == "processing"
        assert wishlist.provider_phase == "not_started"


def test_stale_epoch_wishlist_does_not_block_current_generic(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-stale-epoch-actor")
        recipient = _make_user("opp-stale-epoch-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        wishlist_policy = _enable_worker_policy(
            EventName.WISHLIST_MATCH_DETECTED
        )
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        generic_id = generic.id
        wishlist_id = wishlist.id
        db.session.commit()

        wishlist_policy.cutover_epoch = 2
        wishlist_policy.control_revision += 1
        wishlist_policy.claims_paused = True
        _activation_event(wishlist_policy)
        wishlist_policy.claims_paused = False
        db.session.commit()
        claimed = claim_messages(
            "current-generic-worker", limit=2, session=db.session
        )
        assert [row.id for row in claimed] == [generic_id]
        token = claimed[0].lease_token
        db.session.commit()

        result = mark_opportunity_provider_started(
            generic_id,
            token,
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert result.status == "started"
        assert wishlist_id in result.suppressed_outbox_ids
        db.session.commit()
        assert db.session.get(MessageOutbox, wishlist_id).status == "suppressed"


def test_irreversible_generic_suppresses_later_wishlist_and_normal_start_denies(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-irreversible-actor")
        recipient = _make_user("opp-irreversible-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        db.session.commit()
        claimed = claim_messages("generic-worker", limit=1, session=db.session)
        generic_token = claimed[0].lease_token
        db.session.commit()

        assert not mark_provider_started(
            generic.id, generic_token, session=db.session
        )
        started = mark_opportunity_provider_started(
            generic.id,
            generic_token,
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert started.status == "started"
        db.session.commit()

        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED,
                actor,
                recipient,
                trip,
                resort_id=7,
            )
        )
        wishlist_id = wishlist.id
        db.session.commit()
        provider_calls = []
        from services.message_outbox_worker import run_worker

        result = run_worker(
            lambda: db.session,
            owner="wishlist-worker",
            safety_callback=lambda _row: True,
            provider_callback=lambda row: provider_calls.append(row.id),
            opportunity_start_callback=message_outbox_opportunity_start_callback,
            batch_size=1,
            max_batches=1,
        )
        assert result.suppressed == 1
        assert provider_calls == []
        assert db.session.get(MessageOutbox, wishlist_id).status == "suppressed"


def test_arbitration_and_staging_changes_are_rollback_safe(client, app_fixture):
    with app_fixture.app_context():
        actor = _make_user("opp-tx-actor")
        recipient = _make_user("opp-tx-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        generic_id = generic.id
        wishlist_id = wishlist.id
        db.session.commit()
        claimed = claim_messages("rollback-worker", limit=2, session=db.session)
        tokens = {row.id: row.lease_token for row in claimed}
        db.session.commit()

        result = mark_opportunity_provider_started(
            wishlist.id,
            tokens[wishlist.id],
            safety_callback=lambda _row: True,
            session=db.session,
        )
        assert result.status == "started"
        db.session.rollback()

        generic = db.session.get(MessageOutbox, generic.id)
        wishlist = db.session.get(MessageOutbox, wishlist.id)
        assert generic.status == "processing"
        assert generic.provider_phase == "not_started"
        assert wishlist.status == "processing"
        assert wishlist.provider_phase == "not_started"
        assert wishlist.attempt_count == 0

        denied = mark_opportunity_provider_started(
            wishlist.id,
            tokens[wishlist.id],
            safety_callback=lambda _row: {
                "allowed": False,
                "suppression_reason": "privacy_denied",
            },
            session=db.session,
        )
        assert denied.status == "suppressed"
        db.session.rollback()
        assert db.session.get(MessageOutbox, wishlist.id).status == "processing"


def test_worker_uses_locked_opportunity_start_and_calls_provider_once_after_commit(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-worker-actor")
        recipient = _make_user("opp-worker-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        generic = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        wishlist = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.WISHLIST_MATCH_DETECTED, actor, recipient, trip
            )
        )
        generic_id = generic.id
        wishlist_id = wishlist.id
        db.session.commit()
        provider_rows = []

        def provider_callback(row):
            persisted = db.session.get(MessageOutbox, row.id)
            assert persisted.provider_phase == "started"
            assert persisted.attempt_count == 1
            provider_rows.append(row.id)
            return {
                "status": "provider_accepted",
                "provider_message_id": "opportunity-test-accepted",
            }

        from services.message_outbox_worker import run_worker

        result = run_worker(
            lambda: db.session,
            owner="opportunity-worker",
            safety_callback=lambda _row: True,
            provider_callback=provider_callback,
            opportunity_start_callback=message_outbox_opportunity_start_callback,
            batch_size=2,
            max_batches=1,
        )
        assert result.claimed == 2
        assert result.suppressed == 1
        assert result.provider_accepted == 1
        assert provider_rows == [wishlist_id]
        assert db.session.get(MessageOutbox, generic_id).status == "suppressed"
        assert (
            db.session.get(MessageOutbox, wishlist_id).status
            == "provider_accepted"
        )


def test_opportunity_worker_without_locked_start_hook_never_calls_provider(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-no-hook-actor")
        recipient = _make_user("opp-no-hook-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        db.session.commit()
        provider_calls = []

        from services.message_outbox_worker import run_worker

        result = run_worker(
            lambda: db.session,
            owner="opportunity-worker-no-hook",
            safety_callback=lambda _row: True,
            provider_callback=lambda row: provider_calls.append(row.id),
            batch_size=1,
            max_batches=1,
        )
        assert result.lease_lost == 1
        assert provider_calls == []
        row = db.session.query(MessageOutbox).one()
        assert row.status == "retryable"
        assert row.provider_phase == "not_started"


def test_sibling_lock_query_shape_is_constant_with_recipient_count(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-query-actor")
        recipient = _make_user("opp-query-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        first = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        for index in range(20):
            other_recipient = _make_user(f"opp-query-recipient-{index}")
            _enqueue_opportunity(
                **_opportunity_intent(
                    EventName.FRIEND_TRIP_CREATED,
                    actor,
                    other_recipient,
                    trip,
                )
            )
        db.session.commit()
        first_id = first.id
        trip_id = trip.id
        db.session.expunge_all()

        statements = []

        def before_cursor_execute(
            _conn, _cursor, statement, _parameters, _context, _executemany
        ):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
        try:
            locked_trip, siblings = lock_opportunity_siblings(
                first_id, session=db.session
            )
        finally:
            sa.event.remove(
                db.engine, "before_cursor_execute", before_cursor_execute
            )
        assert locked_trip.id == trip_id
        assert [row.id for row in siblings] == [first_id]
        assert len(statements) <= 3


def test_provider_start_lock_order_is_trip_then_policies_then_siblings(
    client, app_fixture
):
    with app_fixture.app_context():
        actor = _make_user("opp-lock-order-actor")
        recipient = _make_user("opp-lock-order-recipient")
        trip = _make_trip(actor)
        _enable_worker_policy(EventName.FRIEND_TRIP_CREATED)
        _enable_worker_policy(EventName.WISHLIST_MATCH_DETECTED)
        row = _enqueue_opportunity(
            **_opportunity_intent(
                EventName.FRIEND_TRIP_CREATED, actor, recipient, trip
            )
        )
        db.session.commit()
        claimed = claim_messages("lock-order-worker", limit=1, session=db.session)
        token = claimed[0].lease_token
        db.session.commit()
        order = []

        from services import message_outbox as module

        original_trip = module.lock_opportunity_trip
        original_policy = module.lock_opportunity_policy_decisions
        original_siblings = module._lock_opportunity_siblings_after_trip

        def trip_lock(*args, **kwargs):
            order.append("trip")
            return original_trip(*args, **kwargs)

        def policy_lock(*args, **kwargs):
            order.append("policies")
            return original_policy(*args, **kwargs)

        def sibling_lock(*args, **kwargs):
            order.append("siblings")
            return original_siblings(*args, **kwargs)

        with patch.object(module, "lock_opportunity_trip", trip_lock), patch.object(
            module, "lock_opportunity_policy_decisions", policy_lock
        ), patch.object(
            module, "_lock_opportunity_siblings_after_trip", sibling_lock
        ):
            result = mark_opportunity_provider_started(
                row.id,
                token,
                safety_callback=lambda _row: True,
                session=db.session,
            )
        assert result.status == "started"
        assert order[:3] == ["trip", "policies", "siblings"]


def test_trip_mutex_rejects_invalid_or_missing_trip(client, app_fixture):
    with app_fixture.app_context():
        for invalid in (None, True, 0, -1, "1"):
            with pytest.raises(ValueError):
                lock_opportunity_trip(invalid, session=db.session)
        with pytest.raises(LookupError):
            lock_opportunity_trip(99999999, session=db.session)