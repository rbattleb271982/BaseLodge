---
name: Mountain availability overlap
description: Privacy and data-resolution rules for friend availability on mountain detail pages.
---

Mountain availability is a derived, trip-scoped signal: it appears only for the signed-in user's upcoming or in-progress effective trip windows at that resort and only includes direct confirmed friends with an explicit date intersection.

**Why:** Availability is global rather than mountain-specific, so showing it without an own-trip date anchor would imply unsupported mountain availability. The feature must not reveal raw schedules, notes, or availability source metadata.

**How to apply:** Resolve each friend's availability table-first, with legacy dates only when no active table-backed row exists; batch-load data rather than querying per friend. Preserve exact counts when suppressing names already visible in Going or Interested. Do not change the availability editor's “Only you can see your availability” copy as part of this feature; review that wording separately if product policy changes.