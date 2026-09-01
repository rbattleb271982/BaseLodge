---
name: Rate-limit storage validation
description: Prevent credential disclosure and process-local enforcement when configuring Production limiter storage.
---

Validate credential-bearing rate-limit storage configuration before passing it
to Flask-Limiter or its storage dependency. Production accepts only a native TLS
Redis URI and must reject missing, blank, memory-backed, plaintext, malformed,
or shell-assignment-formatted input with a static error that never includes the
supplied value.

**Why:** A malformed storage secret reached the dependency initializer, whose
configuration exception echoed the complete supplied input into startup logs.
Production also runs multiple workers, so process-local memory cannot provide
the intended shared enforcement.

**How to apply:** Keep in-memory fallback behavior for Development and tests.
For Production, perform scheme and locality validation first, then construct
the limiter only after the configuration passes. Never log the URI, and use a
native TLS Redis connection rather than REST credentials.