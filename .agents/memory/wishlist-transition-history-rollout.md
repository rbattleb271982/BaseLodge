---
name: Wishlist transition history rollout
description: Persistent environment rollout state and no-backfill boundary for wishlist transition history.
---

Supabase Development was migrated from BL-80 to `bl87_wishlist_history` on August 31, 2026. The new history table was empty immediately after migration, and the exact current-wishlist checksum was unchanged. Persistent Replit and Production were not migrated during this rollout.

**Why:** Wishlist history intentionally begins at cutover. Existing membership must not be mistaken for a historical add event, and future migration work must know which persistent environment has crossed that boundary.

**How to apply:** Treat pre-cutover wishlist history as unknown. Before another rollout, independently verify the selected database identity and current Alembic revision; never infer another environment's revision from Supabase Development.