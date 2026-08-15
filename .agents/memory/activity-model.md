---
name: Activity model column name
description: The Activity ORM model uses `type` as the column, not `activity_type`. Common mistake in filter_by calls.
---

The `Activity` model (`models.py`) maps to the `activity` table and stores the activity kind in a column named **`type`**, not `activity_type`.

**Why:** The column was named `type` when first created; `ActivityType` is the Python enum used for valid values, but the ORM column itself is `type`.

**How to apply:**
- Query: `Activity.query.filter_by(type='friend_suggestions_received')` ✅
- Query: `Activity.query.filter_by(activity_type=...)` ❌ — raises `InvalidRequestError`
- Test assertions must also use `.type`, not `.activity_type`
