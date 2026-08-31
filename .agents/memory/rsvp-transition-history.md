---
name: RSVP transition history
description: Privacy, status, and migration-order decisions for durable RSVP audit history.
---

Keep RSVP audit history private and canonical while treating the participant's current RSVP as the operational product truth. Record only explicit canonical state changes; do not infer history from attendance or legacy rows.

**Why:** The history is intended for future analytics, debugging, and lifecycle features without changing current trip behavior or exposing private timeline data. BL-70 was confirmed unapplied before its migration ancestry was safely moved after BL-78.

**How to apply:** Preserve atomic current-state/history writes and trip-before-participant locking. While BL-70 remains deferred, deploy BL-78 by its exact revision rather than upgrading to the repository head, which would also apply BL-70.