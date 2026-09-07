---
name: Production backup client compatibility
description: Backup prerequisite for Production database migrations when the local PostgreSQL client may lag the managed server.
---

Before relying on a local logical backup for a Production migration, confirm that `pg_dump` is the same major version as the managed PostgreSQL server. If a compatible client is unavailable, use a verified provider-managed backup with an available Restore action instead.

**Why:** A client/server major-version mismatch can block dump creation or produce a recovery artifact whose compatibility was never established.

**How to apply:** During the preflight, compare `pg_dump --version` with `server_version`. Record either a validated logical-backup artifact or the provider backup type, timestamp, target identity, and restore availability before any schema write.