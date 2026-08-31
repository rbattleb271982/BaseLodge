---
name: Cross-dialect SQL runtime validation
description: Why custom SQLAlchemy compiler output must be executed on every supported database dialect.
---

Custom SQLAlchemy compiler output used by application requests must be runtime-executed on both SQLite and PostgreSQL; successful compilation is not sufficient validation.

**Why:** Compilation-only checks missed PostgreSQL runtime failures involving distinct-query ordering, psycopg parameter formatting, impossible calendar dates, and non-array JSON expansion.

**How to apply:** Pair focused SQLite behavior tests with a development-PostgreSQL probe that executes the complete statement, exercises malformed date and JSON shapes, confirms its query count, and verifies its result bound.