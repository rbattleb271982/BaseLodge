---
name: Reversible messaging cutover
description: Safety invariants for moving exact messaging event families between inline and durable-outbox delivery.
---

Each exact canonical event family owns an independent delivery mode and generation. Capture that choice once inside the domain transaction; never re-read policy after commit to choose the opposite delivery path.

**Why:** A deployment-wide switch can resume inline delivery while old queued work remains deliverable, creating intentional duplicate sends. Expired provider-started leases and ambiguous replay descendants carry the same risk.

**How to apply:** Serialize enqueue and operator transitions on the family policy. A committed pause blocks every not-yet-started provider call. Return to inline only after all processing and deliverable work is resolved. Treat ambiguity across the full replay lineage, require durable acknowledgement and reconciliation evidence, and verify locking behavior on the required PostgreSQL major version.