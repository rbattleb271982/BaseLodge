---
name: Alembic revision ID limit
description: Avoid schema migration failures caused by the database version table's revision-ID length cap.
---

New Alembic revision identifiers must be 32 characters or fewer.

**Why:** The deployed `alembic_version.version_num` column is `VARCHAR(32)`. A longer
revision can run its DDL but fail when Alembic tries to record the new version, causing
the transactional migration to roll back.

**How to apply:** Before adding a migration, count the `revision` identifier as well as
the filename. Prefer short, stable IDs such as `bl60_mtn_filter_edu`.