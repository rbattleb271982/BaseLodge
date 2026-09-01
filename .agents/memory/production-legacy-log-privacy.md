---
name: Production legacy log privacy
description: Durable boundary for privacy-safe Production diagnostics.
---

Production free-form application and access logs must be reduced to allowlisted operational metadata before handlers receive them. Legacy stdout diagnostics must follow the same rule in Production. BL-178 structured request observability remains an independent safe channel.

**Why:** Active legacy diagnostics historically included identities, request fingerprints, tokens, provider payloads, tracking IDs, and raw exception text. Sanitizing only known call sites leaves future and overlooked paths exposed.

**How to apply:** Keep raw values out of Production diagnostic sinks. Retain event/severity, environment, static route/endpoint, server-owned request ID, validated status, source location, and exception class where available. New logger names or stdout modules must join the same boundary.