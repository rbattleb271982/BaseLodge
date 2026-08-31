---
name: Connection lifecycle history
description: Privacy, concurrency, and rollout rules for durable friendship lifecycle events.
---

Treat reciprocal live friendship rows as the only current-state and authorization truth. Lifecycle events are private append-only history and must never restore access, visibility, recommendations, messaging eligibility, or social counts after removal.

**Why:** Historical relationships are useful for future analytics and debugging, but using them as product state would expose former relationships and undermine current privacy boundaries.

**How to apply:** Serialize pair transitions by locking both subject users in canonical ID order before reading friendship rows. Repair one-sided drift without inventing a formation event. The migration chain is BL-78 → BL-79 → deferred BL-70; deploy BL-79 by exact revision while BL-70 remains deferred.