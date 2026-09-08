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

Continuous worker identity is a delivery fence, not only a monitoring label. Verify and lock heartbeat ownership in the same transaction immediately before claim and again immediately before provider-start; every ownership-loss path must terminate the fenced process.

**Why:** Post-cycle heartbeat checks leave an inter-cycle window where a replaced process can claim and send before discovering that a new process owns its stable identity.

**How to apply:** Roll back pre-provider work on fence loss and make the ownership-loss category fatal. Once provider-start commits, preserve normal finalization and `delivery_unknown` handling rather than using fencing to guess whether delivery occurred.

Production has the durable-outbox, reversible-policy, and worker-heartbeat schema installed, while delivery remains inline, every policy remains paused, and no worker is active.

**Why:** Schema rollout was intentionally separated from application deployment, worker provisioning, and event-family cutover so that no notification behavior changed during migration.

**How to apply:** Treat Production schema migration as complete. Any deployment, worker startup, unpause, enqueue-only transition, or canary remains a separate approval boundary.

Opportunity-message authorization is a send-time transaction contract: lock the trip, then sorted policies, then deterministic sibling rows; refresh locked ORM state; authorize under those locks; and re-check lease time immediately before provider-start.

**Why:** SQLAlchemy identity-map objects can stay stale across `FOR UPDATE`, SQLite savepoints can escape caller rollback without an explicit outer transaction, and a policy proof from a rolled-back savepoint no longer represents a held lock.

**How to apply:** Use `populate_existing` for locked ORM reads, bind reusable policy decisions to the exact active root/nested transaction scope, invalidate them after commit/rollback, and commit provider-start before any provider call.