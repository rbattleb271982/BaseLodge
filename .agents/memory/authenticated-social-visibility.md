---
name: Authenticated social visibility
description: Product-level rules for current friendship, friend-public trips, roster identities, and availability-detail disclosure.
---

Friend-only data requires reciprocal current friendship rows. Pending, declined, former, one-sided, and historical connection states never authorize.

**Why:** A single stale directed friendship row previously exposed detailed social data after the mutually confirmed relationship no longer existed.

**How to apply:** Use current reciprocal state for profiles, APIs, invitations, social queries, and derived context. History remains audit-only.

“Public” trips are authenticated friend-social, not globally public. A current reciprocal friend may qualify through the organizer or a current Going/Interested participant; private, terminal, ended, and ended-attendance contexts do not qualify.

**Why:** Social discovery includes participant-derived trip context, but public labeling was never intended to expose trips to unrelated users or preserve discovery after the relevant current state ends.

**How to apply:** Keep canonical member access separate from friend-public discovery and apply current lifecycle/date/attendance checks at direct-detail boundaries.

Going and Interested identities form the active roster visible to admitted trip viewers. Pending and Declined identities are organizer-only invitation-management state; Removed identities are not a normal user-facing roster.

**Why:** Invitation outcomes disclose relationship-management information that non-organizer participants do not need.

**How to apply:** Filter unauthorized status rows before hydrating related user identities where practical.

Availability overlap may be shown as a bounded derived signal, but detail URLs must not let users choose arbitrary friend/date scopes. Server-issued availability cards use short-lived, viewer-bound signed capabilities and revalidate current state.

**Why:** Plain query parameters turn an overlap detail route into a day-by-day availability oracle.

**How to apply:** Treat user-supplied identifiers as locators, not authorization; derive sensitive detail scope from a server-issued capability and current authoritative availability.