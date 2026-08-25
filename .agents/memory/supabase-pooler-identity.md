---
name: Supabase pooler identity collision
description: Safety limitation when distinguishing Supabase projects from shared regional pooler URLs.
---

Supabase pooler connection URLs place the project reference in the username while sharing the same regional hostname, port, and database name across projects. Pooler identity must hash the validated project reference while excluding the password and role.

**Why:** Host/database-only identity collides across projects. Treating arbitrary usernames as identity would expose credentials and weaken generic behavior, so only recognized Supabase pooler usernames are parsed. DNS terminal dots must be canonicalized to prevent bypass.

**How to apply:** Keep the existing production endpoint hash and also require an explicit SHA-256 production project-reference hash. Missing/malformed pooler project identity fails closed across runtime, migration, bootstrap, import, maintenance, and dev-user guards.