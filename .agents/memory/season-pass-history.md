---
name: Season-specific pass history
description: Transition contract between the current pass field and normalized season history.
---

Normalized season rows are the sole authority for historical pass ownership, keyed by the season's June 1 start year. `User.pass_type` remains the current product-facing read source during the initial rollout and must be synchronized transactionally whenever a valid current pass is saved.

**Why:** This preserves existing product behavior while establishing queryable history without fabricating prior-season ownership. It also avoids competing JSON and relational history sources.

**How to apply:** Treat explicit no-pass values as meaningful corrections, blank input as no change, and unknown values as invalid. New-season writes create a row without changing prior rows; same-season writes correct the existing row. Do not infer history from prior-pass fields, trips, signup dates, analytics, or legacy JSON.