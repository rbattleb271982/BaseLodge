---
name: Durable messaging outbox
description: Safety and rollout rules for durable product push and OneSignal delivery.
---

Product messaging intent and its domain evidence must be persisted in one owning transaction. Inline compatibility delivery happens only after that transaction commits, and a deployment must never enqueue and send inline for the same intent.

**Why:** A commit before enqueue can permanently lose delivery intent, while a send before commit can notify recipients about state that later rolls back.

**How to apply:** Stage every product event before the domain commit in enqueue-only mode; keep the inline branch deferred until after commit.

Once the worker commits that provider invocation has started, a timeout or connection loss is `delivery_unknown`, not retryable. Only a definitive provider rejection such as a returned 429 or selected 5xx may be retried, honoring a bounded Retry-After hint.

**Why:** Transport failure after the provider boundary cannot prove the provider rejected the request; automatic retry could duplicate user-visible delivery.

**How to apply:** Quarantine ambiguous outcomes for explicit admin review/replay with duplicate-risk acknowledgement. Do not enable enqueue-only in Production until a bounded standalone worker is explicitly configured.