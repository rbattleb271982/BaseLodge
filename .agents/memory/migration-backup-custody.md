---
name: Migration backup custody
description: Approved storage and verification contract for temporary logical migration backups.
---

Use the private Replit App Storage bucket designated for migration backups under the `bl135/development/` prefix. Stream backup output directly through the authenticated App Storage SDK, then verify listing, authenticated download, and checksum before treating the object as a recovery copy. Delete artifacts after the approved rollback window.

**Why:** Synthetic verification proved authenticated stream upload, listing, download, checksum equality, anonymous-read denial, deletion, and post-delete absence without adding credentials.

**How to apply:** Do not use the repository, `attached_assets`, or ordinary workspace storage for backup custody. Use transient `/tmp` staging only if a future stream implementation cannot provide reliable error handling and verification, and delete staging immediately after the verified upload.