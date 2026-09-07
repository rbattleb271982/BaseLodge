---
name: Remember-cookie age enforcement
description: The difference between Flask-Login browser cookie expiry and server-enforced remember-credential age.
---

Treat remember-credential age as server-enforced only when the signed credential carries an issuance time that restoration validates against a fixed maximum. A browser `Expires` attribute alone is not a credential lifetime.

**Why:**
Under Flask-Login 0.6.3, the default remember value is a deterministic signed identity with no timestamp. An isolated copied-cookie replay remained restorable after the nominal 30-day browser expiry. Password change/reset still revoke it through the password-derived identity version, and account deletion fails because the user no longer loads.

**How to apply:**
For bounded remember age, use a versioned timed envelope and reject untimed legacy remember cookies. Do not reuse `password_changed_at` as a general revocation marker: current identity versioning does not include it, and it also carries password-history/reset-token semantics.