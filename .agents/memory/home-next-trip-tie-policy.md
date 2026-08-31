---
name: Home Next Trip tie policy
description: Deterministic compatibility rules for selecting among equal effective attendance starts.
---

Home Next Trip must prefer an owned candidate over a guest candidate when their effective attendance starts are equal. Within either source, equal starts choose the lowest trip ID.

**Why:** The historical merge was stably owned-first across sources, while database order within a source was formally unspecified but consistently returned the lowest ID. Bounding retrieval required making that observed behavior explicit and cross-dialect deterministic.

**How to apply:** Preserve these tie rules whenever changing Home Next Trip eligibility, effective attendance ordering, or candidate queries. Treat a different tie-breaker as a visible behavior change requiring explicit approval.