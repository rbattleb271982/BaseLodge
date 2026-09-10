---
name: Capture transient UI controls
description: Deterministic progressive-state capture behavior in the Replit browser environment.
---

For deterministic capture-only loading and failure states, prefer browser-injected state controls that call the real component’s existing state functions when managed request routing does not intercept reliably.

**Why:** Multiple Playwright page-route patterns and fetch replacement attempts did not intercept the Mountain social request with the available system Chromium/driver combination. A browser-injected global consumed by the existing component produced distinct real Loading and Error/Retry states without a fake server route or mock page.

**How to apply:** Keep the control inert unless the browser injects it before page scripts run. Reuse the production component’s own loading/failure rendering, and retain tests proving the normal path still performs its real request when no control is present.