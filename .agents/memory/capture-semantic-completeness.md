---
name: Capture semantic completeness
description: Why complete screenshot file sets still require state-level integrity validation.
---

A screenshot corpus is complete only when every output both maps to its manifest identity and visibly represents the declared state. Exact file counts, dimensions, unique IDs, and successful browser completion are necessary but insufficient.

**Why:** Full runs can generate every expected file with correct dimensions while some rows silently render redirects, error pages, default states, or unresolved interactions. File-level completeness alone can mislabel a corpus as audit-ready.

**How to apply:** Give each non-default manifest state a semantic success marker or interaction assertion, detect unexpected redirects and error pages, and review exact-image duplicate groups before approving a full corpus. Put exact-state assertion branches before broad prefix branches so a generic match cannot silently bypass a stronger regression contract.