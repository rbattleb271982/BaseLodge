---
name: Capture fixture request lifecycle
description: Why capture-state transitions must not retain ORM instances across Flask requests.
---

Capture registries that survive across Flask requests must store scalar database identities for mutable fixture rows, then re-query or issue ID-based updates inside the current request.

**Why:** Committed SQLAlchemy objects are expired and detached at request teardown. Later assignments can fail on attribute access or appear to succeed without persisting, causing captures to show the wrong scenario while the prepare endpoint reports success.

**How to apply:** When a capture prepare endpoint activates, cancels, or otherwise changes seeded rows, keep integer IDs in the registry and perform the mutation through the current scoped session. Semantic capture assertions should check exact scenario membership.