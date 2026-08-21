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

**How to apply:** Clear or replace production database URLs before running local
commands that import the app; preserve the test suite's pre-import SQLite guard.
For production, run one controlled migration process with startup DDL disabled,
not from application workers or a watched development server.