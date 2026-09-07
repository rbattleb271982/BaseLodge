---
name: Client-session expiration ordering
description: Ordering rules for enforcing signed client-session age without bypasses or broken remember restoration.
---

Validate authenticated-session age from the raw signed session before any request hook accesses the login proxy. On invalid or expired state, remove the normal login identity first so the framework can still consume an independently valid remember credential through its normal loader.

**Why:**
The login extension caches the resolved user for the request. Clearing session keys after an earlier hook accesses that proxy does not de-authorize the already cached identity, allowing the current request to continue under expired credentials.

**How to apply:**
Keep age enforcement in the earliest request hook, ahead of authorization, audit, activity, and mutation logic. Metadata required for a restored session must be written outside best-effort logging blocks so logging failure cannot create an authenticated session without its expiration marker.