---
name: Supabase pooler identity collision
description: Safety limitation when distinguishing Supabase projects from shared regional pooler URLs.
---

Supabase pooler connection URLs place the project reference in the username while sharing the same regional hostname, port, and database name across projects. Pooler identity must hash the validated project reference while excluding the password and role.

**Why:** Host/database-only identity collides across projects. Treating arbitrary usernames as identity would expose credentials and weaken generic behavior, so only recognized Supabase pooler usernames are parsed. DNS terminal dots must be canonicalized to prevent bypass.

Production migration ownership must be anchored to the already verified live
Production pooler. A newly supplied URL and companion migration hash can prove
only that they match each other, not that either belongs to Production.

**Why:** Repeated manual URL selection reached unrelated Supabase projects, and
modern pooler identities were incorrectly compared with the historical
endpoint-only Production hash. The historical endpoint hash remains valid for
the live pooler when checked separately from its protected project reference.

**How to apply:** Keep the existing production endpoint hash and require the
explicit SHA-256 production project-reference hash independently. Production
migration resolution uses the protected live pooler, rejects contradictory
explicit targets, and retains explicit mode/target/confirmation gates. Missing
or malformed pooler identity fails closed across all database tooling.