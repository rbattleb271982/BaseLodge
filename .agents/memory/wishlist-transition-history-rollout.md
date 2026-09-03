---
name: Wishlist transition history rollout
description: Persistent environment rollout state and no-backfill boundary for wishlist transition history.
---

Supabase Development was migrated from BL-80 to `bl87_wishlist_history` on August 31, 2026. Protected Supabase Production was migrated through the bounded BL-78/79/80/87 path on September 2, 2026. Each new Production history table was empty immediately after migration, lifecycle columns remained nullable, and existing core row counts were preserved. Replit-managed databases were not part of the Production migration.

**Why:** Wishlist history intentionally begins at cutover. Existing membership must not be mistaken for a historical add event, and future migration work must know which persistent environment has crossed that boundary.

**How to apply:** Treat pre-cutover wishlist history as unknown. Before another rollout, independently verify the selected database identity and current Alembic revision; never infer another environment's revision from Supabase Development.