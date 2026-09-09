---
name: Privacy-isolated presentation surfaces
description: Required shell isolation for allowlisted personal preview and export pages.
---

Presentation surfaces with an explicit privacy allowlist must suppress every inherited shell channel that can render identity, social state, analytics configuration, or unrelated session text.

**Why:** Passing an allowlisted view model is insufficient when shared templates can still inject authenticated analytics identifiers, account initials, pending-social badges, or flash messages from implicit context.

**How to apply:** For private preview/export pages, audit and override analytics, account/avatar, flash, and navigation blocks; test the fully rendered response with prohibited identity, social, and flash values present. If interaction analytics are required, use an authenticated CSRF-protected endpoint with exact anonymous event/property allowlists rather than restoring the identity-bearing analytics shell.