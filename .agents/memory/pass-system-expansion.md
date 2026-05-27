---
name: Full Pass System Expansion
description: Canonical pass slugs, what changed, and durable rules for future pass work.
---

## Canonical pass slugs (as of May 2026)

Real passes (combinable, count toward 3-cap):
  epic, ikon, indy, mountain_collective, powder_alliance, freedom, ski_california, other

Exclusive (non-combinable, clear real passes):
  no_pass, no_pass_yet

## What changed
- `LEGACY_TO_MVP` is now empty — no slug is collapsed to `other` anymore.
- `PASS_NORM_MAP` maps all variants of indy/mountain_collective/powder_alliance/freedom/ski_california to their own slugs.
- `_VALID_PASS_SLUGS` includes all 10 canonical slugs — unknown slugs are still dropped on save.
- `_ideas_normalize_pass()` and `normalize_pass_family()` in app.py: removed `"other"` from their local `_NON_REAL` exclusion set so `other` now displays ("Other pass") instead of falling back to "No pass".
- `EXCLUSIVE_PASSES` in edit_profile.html JS and `OB_PASS_EXCLUSIVE` in identity_setup.html JS: removed `"other"` — it is a real combinable pass.

## Resort data state
- Indy: 15 resorts have `pass_brands=Indy` in `Resort` table; 15 `ResortPass` rows with `pass_name='Indy'` backfilled.
- MountainCollective: 5 resorts; 5 `ResortPass` rows with `pass_name='MountainCollective'` backfilled.
- Powder Alliance, Freedom, Ski California: selectable passes but NO resort mapping data in DB yet.

## _BAD_PASSES in ideas_engine.py
`_BAD_PASSES = {None, "", "no_pass", "no_pass_yet", "other"}` — this excludes `other` from pass-match scoring (intentional catch-all treatment). New specific passes (indy, mc, etc.) are NOT in `_BAD_PASSES` and therefore participate in pass-match scoring correctly.

**Why:** The ideas engine only scores exact pass equality. `other` is too generic to be meaningful for match scoring (two people with `other` might have completely different passes), so it remains excluded from scoring even though it IS a real pass for UI/display purposes.

## Future work
- Add resort mappings for Powder Alliance, Freedom Pass, Ski California (no data exists in DB yet).
- `ideas_engine.py` line 347: `user_pass = _norm_pass_val(user.pass_type) or ""` only reads the FIRST pass for overlap scoring — multi-pass scoring (e.g., epic+indy) is a pre-existing limitation.
