---
name: Independent backup custody
description: How to describe and verify the failure boundary of an independent logical backup copy.
---

Call a backup copy “independent” only when its storage control plane and administrative recovery path are separate from the live database provider, and name the failure boundary it survives. A Replit App Storage copy may be independent from Supabase project/account deletion, but it is not independent from loss of the Replit account/platform.

Treat an independent copy as recoverable only after an authenticated full read verifies size and checksum, archive readability is checked separately, retention/expiry is defined, and storage access recovery is owned by an authorized operator.

**Why:** Provider-native backups can disappear with their source project/account, while storage in another control plane still fails if that second platform account or its access path is lost. Archive listing alone also does not prove every byte is readable.

**How to apply:** For each DR scenario, state which provider/account failures the copy survives. Keep provider-native recovery plus a separately controlled copy when account/project deletion is in scope; never treat repository, attached prompt assets, or ordinary workspace files as authoritative backup custody.