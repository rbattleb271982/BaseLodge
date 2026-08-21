---
name: SkiDay display privacy
description: Visibility and aggregation rule for all-time SkiDay totals in Mountains Visited.
---

Per-resort logged-day totals are shown only in the signed-in user's Mountains Visited selector. Confirmed-friend Mountains Visited remains a simple read-only list and does not receive a count map or SkiDay metadata.

**Why:** The available BL-91 implementation requirement specified the signed-in user's totals but did not explicitly authorize exposing SkiDay-derived history to friends.

**How to apply:** Use one grouped aggregate of persisted `SkiDay` records for the owner view; render a positive count only beside mountains currently selected as visited. Do not expose dates, source, trip links, correction history, or totals in friend views without an explicit product requirement.