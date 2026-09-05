---
name: Worker CI process isolation
description: Why standalone worker PostgreSQL tests must run separately from ordinary Flask-SQLAlchemy tests.
---

Run standalone worker PostgreSQL coverage in a dedicated test process, then run the ordinary web suite in a fresh SQLite-only process.

**Why:** Standalone worker setup intentionally replaces the extension-level scoped ORM session for a dedicated worker process. If worker coverage and web tests share a test process, later web fixtures can remain bound to the disposable PostgreSQL engine after its schema is gone.

**How to apply:** Scope PostgreSQL-required flags and PostgreSQL tool discovery to the dedicated worker test command. Do not expose either to the subsequent full web-suite command.