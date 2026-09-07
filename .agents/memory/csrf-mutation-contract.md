---
name: CSRF mutation contract
description: Durable boundary between global CSRF enforcement, native WebView behavior, and intentional versus unsafe safe-method state effects.
---

All cookie-authenticated POST, PUT, PATCH, and DELETE requests must pass the
session synchronizer-token gate before route-owned database, analytics,
messaging, notification, or provider effects. Cookie-backed Capacitor WebView
requests follow the same contract and must not receive a native exemption.

**Why:** The global unsafe-method gate is fail-closed, but ordinary GET/HEAD
render paths and a global activity heartbeat can persist state outside that
gate. Authentication expiry/restore, CSRF token bootstrap, and bounded
post-auth redirect/token handoff also mutate signed session state and must not
be mistaken for domain-write bypasses.

**How to apply:** Keep unsafe-method coverage global and exemption-free. Move
domain, integrity, viewed-state, analytics, and heartbeat persistence off
GET/HEAD/OPTIONS and onto idempotent CSRF-protected POST actions. Explicitly
document and narrowly test retained authentication, navigation, and OAuth
protocol session effects. Treat real-device cookie continuity as something to
prove, never as a reason to bypass CSRF.