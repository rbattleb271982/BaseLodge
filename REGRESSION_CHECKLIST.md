# BaseLodge Regression Checklist

---

## ⚠ BEFORE MERGE — Agent instruction

Before marking any future Agent task complete:

1. Run the checklist items relevant to the changed surfaces.
2. Report **PASS / FAIL / NOT TESTED** for each item.
3. If anything is **NOT TESTED**, explain why (e.g. "requires native TestFlight device", "no UI automation").
4. **Do not mark the task complete if any related regression check FAILS.**

---

## 1. Onboarding

- **Verify** that selecting 3 or more rider types (e.g. Skier + Snowboarder + Telemark) persists all selections and all pills remain highlighted after save.
- **Confirm** that the onboarding flow does not produce any horizontal scrollbar at a 375 px viewport width (iPhone SE / standard portrait).
- **Ensure** that the full ski pass list appears on the pass selection step, including Ikon, Epic, Indy, Freedom, Mountain Collective, and Powder Alliance options.
- **Confirm** that saving "I rent equipment" during onboarding causes the Home screen equipment line to read "Rental gear" (not blank or "Own gear").

---

## 2. Mountains / Resort Search

- **Verify** that after removing a mountain from visited or wishlist, that same mountain immediately appears in the resort search results (no stale exclusion).
- **Confirm** that no mountain appears more than once in the visited list or wishlist — adding the same resort twice must not create duplicate rows.
- **Ensure** that known resorts display a branded pass label rather than generic "Other pass." Spot-check:
  - Killington → Ikon
  - Palisades Tahoe → Ikon
  - Park City → Epic
  - Whiteface → Epic

---

## 3. Home

- **Verify** that when a user has no trip ideas in the Opportunities feed, the empty state displays the polished card with the heading "Add dates to unlock trip ideas" and a muted description.
- **Confirm** that the "Add availability" CTA inside that empty-state card navigates to the Add Availability page (not a 404 or the wrong route).

---

## 4. Friend / Social Graph

- **Verify** that after User A removes User B as a friend, neither user appears in the other's friends list.
- **Confirm** that the removed friend no longer appears in:
  - The Friends tab list
  - The friend profile page (should show "Not connected" state)
  - Trip overlap and availability overlap views
  - Invite pickers when creating or editing a trip
  - Coordination / Ideas recommendations on Home
- **Ensure** that re-friending (sending a new invite after removal) works correctly — the invite is delivered, accepted state is clean, and both users see each other as connected.

---

## 5. Invite Links

- **Verify** that an already-authenticated TestFlight (or logged-in browser) user who opens a friend invite link is taken directly to the invite acceptance screen — no "Continue in Browser" button is shown, and no detour through the login or auth page occurs.
- **Confirm** that an unauthenticated user who opens a friend invite link is routed through the auth flow (login or signup) and lands on the correct invite page after completing authentication.

---

## 6. Plan a Trip Navigation

- **Verify** that when a user navigates to Plan a Trip from the Mountains tab (or any prior screen), tapping the back chevron returns them to that prior context rather than always jumping to Home.
- **Confirm** that when a user opens Plan a Trip directly (e.g. deep link with no prior history), the back chevron falls back safely to Home without a JavaScript error.
