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

When source history has multiple heads, diagnose the live database revision before
choosing a parent. Extend the verified live branch for an independently approved
migration; do not merge heads or traverse another branch without separate approval.

**Why:** A generic upgrade-to-head can apply unrelated migrations when the live
database is anchored on only one source branch.

**How to apply:** Inspect source heads, compare them with the protected live revision,
and target the approved revision explicitly rather than using an ambiguous `head`.