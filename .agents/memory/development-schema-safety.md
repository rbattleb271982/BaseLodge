---
name: Startup database safety
description: Keep routine application startup read-only and preserve the production rollout gate around BL-306.
---

Routine application import and worker startup must not perform persistent
schema or historical-data maintenance. Schema changes belong to standalone
Alembic, and one-time DML belongs to guarded, dry-run-first maintenance tooling.

**Why:** A schema-preparation task caused watcher-driven reloads and a direct
Flask migration command to invoke legacy startup routines despite no controlled
production migration being intended. Production also remained behind BL-306
because MountainPageView orphan references required a separate explicit decision.

**How to apply:** BaseLodge runtime selection is explicit and fail-closed:
development/test need their own URL plus a protected-production identity hash;
they never select the shared Supabase URL. Migration commands require a separate
migration URL and explicit migration mode, and must use direct Alembic rather
than Flask app startup. Maintenance requires its own target URL, mode, write
authorization, dry-run/report, singleton lock, and transaction, and must never
import the Flask app or contact push providers. Do not deploy the startup-call
removal to production until production BL-306 has separately succeeded; do not
fold MountainPageView orphan repair into an application rollout.