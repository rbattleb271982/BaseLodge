---
name: Managed browser QA
description: Browser validation guidance for this workspace when local headless browser libraries are unavailable.
---

When the container's locally installed Playwright browser cannot launch because GUI or media libraries are missing, use the managed app-preview screenshot path rather than installing unrelated system packages.

**Why:** The managed preview has the required browser runtime and can validate the actual Flask workflow without changing package or system configuration.

**How to apply:** Use the real workflow preview for startup and console checks; for populated responsive states, render a temporary fixture outside the repository and serve it only for managed preview screenshots. Do not commit the fixture or temporary server configuration.