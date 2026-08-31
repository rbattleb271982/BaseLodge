---
name: Terminal trip isolation
description: Why retained completed and cancelled trips need explicit lifecycle filtering outside approved history views.
---

Live trip consumers must explicitly accept only legacy `NULL` or `active`
lifecycle rows. Do not infer operational status from future dates, public
visibility, trip planning status, or an active/pending participant row.

**Why:** Cancellation preserves the canonical trip and its participant history.
A retained trip may still have future dates and public metadata, so old queries
that were safe only because deletion was physical can leak history into social,
discovery, notification, overlap, invitation, or availability surfaces.

**How to apply:** Add the lifecycle predicate to every query or in-memory input
feeding a live surface. Keep explicit exceptions narrow: authorized terminal
Trip Detail and My Trips history. Account/privacy deletion remains physical.