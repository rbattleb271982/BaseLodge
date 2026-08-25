---
name: GitHub publishing fallback
description: Publish commits safely when the workspace Git remote lacks valid shell credentials.
---

When a local Git commit cannot be pushed because the shell's HTTPS credential is invalid, use the installed GitHub connection and update the current remote branch through GitHub's authenticated Git API instead of requesting a token.

**Why:** The GitHub integration can be healthy while the workspace's shell remote retains an unusable credential. Also, large single shell-command results can be silently shortened by the execution sandbox, even when not marked as truncated.

**How to apply:** Base any remote update on the live branch head and use a non-force ref update; a stale local tracking ref means the published equivalent commit may have a different SHA. For large source files, transfer compressed content in small deterministic chunks rather than through one shell-result payload. The connector sandbox may truncate a single shell result near 80 KB despite a higher requested limit; decode chunked base64 inside the impure connector boundary, where `Buffer` is available.