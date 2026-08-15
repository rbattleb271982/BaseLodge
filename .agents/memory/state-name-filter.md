---
name: state_name Jinja2 filter
description: Converts USPS/Canada 2-letter state abbreviation to full name. Use `| state_name` in templates.
---

A `state_name` Jinja2 filter is registered in `app.py` (near the other template filters).

**Usage:** `{{ user.home_state | state_name }}` → `"Colorado"` (given `"CO"`)

**Why:** The existing `state_fullname` filter only handles Resort ORM objects; it passes plain strings through unchanged. `state_name` is designed for raw 2-letter codes stored on User.home_state.

**How to apply:**
- Use `| state_name` wherever `user.home_state` is displayed as a full name (selector, suggested friends tab, friend profile if added).
- The backing dict `_STATE_ABBREV_TO_NAME` in app.py covers all 50 US states + DC + 13 Canadian provinces/territories.
- Falls back to the original string for unrecognized codes.
