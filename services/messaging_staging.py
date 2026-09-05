"""Per-intent messaging route capture shared by web integration and tests."""

from services.messaging_cutover import lock_policy_decisions


def stage_messaging_intents(
    intents,
    *,
    session,
    enqueue,
    producer_release_sha=None,
    require_verified_release=False,
):
    """Capture exact-family decisions once and enqueue in the owning transaction."""
    decisions = lock_policy_decisions(
        [intent.get("event_name") for intent in intents], session=session
    )
    plan = []
    for intent in intents:
        decision = decisions[intent.get("event_name")]
        queued = decision.enqueue_only and decision.cutover_epoch is not None
        if queued:
            if require_verified_release and producer_release_sha is None:
                raise RuntimeError(
                    "verified producer release identity required for enqueue_only"
                )
            enqueue(
                **intent,
                configuration_epoch=decision.cutover_epoch,
                producer_release_sha=producer_release_sha,
                session=session,
            )
        plan.append(queued)
    return tuple(plan)


def finish_staged_messaging(plan, intents, *, inline_emitter):
    """Run only decisions captured as inline, without reading policy again."""
    normalized = (
        plan if isinstance(plan, (tuple, list))
        else tuple(bool(plan) for _ in intents)
    )
    return [
        inline_emitter(**intent)
        for intent, queued in zip(intents, normalized)
        if not queued
    ]
