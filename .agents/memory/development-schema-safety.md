---
name: Development schema safety
description: Prevent local Flask reloads and migration commands from unintentionally executing legacy startup DDL against production.
---

Local development must not run with a production database URL while startup
schema routines remain in application import paths. Flask's file watcher reloads
the app after source edits, and each import can execute those routines.

**Why:** A schema-preparation task caused watcher-driven reloads and a direct
Flask migration command to invoke legacy startup routines despite no controlled
production migration being intended.

**How to apply:** BaseLodge runtime selection is explicit and fail-closed:
development/test need their own URL plus a protected-production identity hash;
they never select the shared Supabase URL. Migration commands require a separate
migration URL and explicit migration mode, and must use direct Alembic rather
than Flask app startup. The legacy shared Supabase URL is a temporary,
production-runtime-only deployment compatibility path. Keep the pre-import
SQLite test guard. For production, run one controlled migration process with
startup DDL disabled, not from application workers or a watched development
server. The standalone bootstrap imports root-level runtime configuration, so
direct script execution must retain the repository root on Python's import path
(for example, `PYTHONPATH="$PWD"`); this path must never be replaced with a
Flask/app import.