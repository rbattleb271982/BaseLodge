---
name: Supabase pooler identity collision
description: Safety limitation when distinguishing Supabase projects from shared regional pooler URLs.
---

Supabase pooler connection URLs can place the project reference in the username while sharing the same regional hostname, port, and database name across projects. A credential-safe identity based only on host, port, and database therefore collides across distinct Supabase projects.

**Why:** BaseLodge's production identity protection deliberately omits credentials, including the username. With shared Supabase pooler URLs, a new development project can consequently compare equal to protected production and guarded bootstrap/import tooling must refuse it.

**How to apply:** Prefer a project-specific direct database hostname when connectivity permits. Otherwise, explicitly review and harden the identity scheme to incorporate a non-secret project discriminator before authorizing guarded writes through a shared Supabase pooler.