---
name: Home activity digest evidence
description: Durable evidence and privacy rules for claims in the Home Happening digest.
---

Home Happening answers “What changed that I should know about?” in a rolling seven-day digest. Claims must be anchored to durable RSVP transitions, authorized planning-post creation, trip creation, or connection-formation events. Current counts and dates may appear only as context for one of those events. Do not infer change from mutable trip update timestamps, generic activity rows, availability, wishlist, or ski-day state.

**Why:** Mutable state cannot prove what changed or when, and planning posts plus social activity can reveal information the viewer was never authorized to see.

**How to apply:** Keep the fixed order On Your Trips, Trips Forming, Your People; enforce current trip and relationship visibility in retrieval; order ties with authoritative event IDs; keep the retrieval budget bounded by category family rather than result count.