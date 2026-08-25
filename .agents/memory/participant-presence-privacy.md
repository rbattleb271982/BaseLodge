---
name: Participant presence privacy
description: Visibility rule for downstream surfaces that expose a guest's physical attendance.
---

When a downstream surface represents a friend as physically present through a
participant attendance row, only derive that signal from a shared trip that is
visible to the viewer.

**Why:** A direct friend's participation in a private trip hosted by someone
outside the viewer's social graph can otherwise disclose that friend's current
or historical location.

**How to apply:** Keep owner-facing and private shared-trip views governed by
their existing access controls. For broad friend-presence surfaces, require the
shared trip to be public before evaluating a guest's effective attendance
window.