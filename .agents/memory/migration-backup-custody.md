---
name: Migration backup custody
description: Approved storage and verification contract for temporary logical migration backups.
---

Use the private Replit App Storage bucket designated for migration backups under the `bl135/development/` prefix. Stream backup output directly through the authenticated App Storage SDK, then verify listing, authenticated download, and checksum before treating the object as a recovery copy. Delete artifacts after the approved rollback window.

Use the SDK's default client for the bucket already attached to the Repl. A bucket display name is not necessarily the SDK bucket ID, so passing the display name as `bucketId` can produce a false “bucket does not exist” result.

Verify full-download size/checksum and `pg_restore --list` with independent authenticated reads. `pg_restore --list` may finish before a piped custom archive reaches EOF, so it cannot safely share the stream used for the complete checksum.

**Why:** Synthetic verification proved authenticated stream upload, listing, download, checksum equality, anonymous-read denial, deletion, and post-delete absence without adding credentials. A real backup verifier also showed that early `pg_restore` completion can surface a benign `EPIPE` and race hash finalization.

**How to apply:** Do not use the repository, `attached_assets`, or ordinary workspace storage for backup custody. Use transient `/tmp` staging only if a future stream implementation cannot provide reliable error handling and verification, and delete staging immediately after the verified upload. Keep App Storage as the sole recovery copy.