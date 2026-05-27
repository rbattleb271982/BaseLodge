---
name: Admin console architecture
description: How the admin pages are structured — template extension, sidebar, CSS classes, and active_tab pattern.
---

## Rule
All admin pages extend `admin_console.html`. The `active_tab` variable drives both the sidebar highlight and the submenu.

**Why:** `admin_console.html` owns the sidebar nav. The `{% if active_tab == 'X' %}` block inside each `<li>` conditionally renders the submenu for the active page only. New pages must pass `active_tab='X'` to render_template.

## How to apply
1. New admin template: `{% extends "admin_console.html" %}` + `{% block page_title %}{% endblock %}` + `{% block content %}`.
2. New sidebar item: add `<li class="{{ 'ac-active' if active_tab == 'X' else '' }}">` with `{% if active_tab == 'X' %}<ul class="ac-subnav-list">...</ul>{% endif %}` inside.
3. Pass `active_tab='X'` in the route's `render_template` call.
4. Bar chart CSS classes (`.ad-bar-list`, `.ad-bar-row`, `.ad-bar-name`, `.ad-bar-track`, `.ad-bar-fill`, `.ad-bar-count`) are NOT in the shared base — define them in each template's `{% block head %}` style block.
5. KPI card classes (`.ad-card`, `.ad-card-label`, `.ad-card-value`, `.ad-card-sub`) are also per-template.
