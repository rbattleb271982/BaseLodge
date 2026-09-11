# BaseLodge Trips — final synthesis specification

**Design synthesis only.** No application code, fixtures, routes, backend behaviour, migrations or deployments were touched.
Fixture: the corpus mountains, months and 15-trip shape from `screenshots/trips/`, with real state codes and the locked relationship vocabulary.
Account rendered throughout: **9 of my trips · 3 invitations · 3 already skied · 18 friends' trips across 9 friends**.

Screen heights at 390 px: Mine 746 / 1,214 · Both 726 / 1,094 · Friends' 610 / 1,192 (normal / heavy). The current build renders a comparable account in roughly 1,900 px of list alone.

---

## 1. Page frame

```
┌───────────────────────────────────────────────┐
│ Trips                        Season Snapshot ›│   top bar, 52 px
├───────────────────────────────────────────────┤
│ 9 trips ahead · 3 already skied  + Plan a trip│   season line, 46 px
├───────────────────────────────────────────────┤
│ Mine 9 ③    Both    Friends'                  │   views, 42 px
└───────────────────────────────────────────────┘
```

- **Season Snapshot** occupies the top-bar action slot. **+ Plan a trip** occupies the secondary slot on the season line. (Swapped from the earlier exploration, as decided.)
- The season line is **the same on all three views** — it describes my season and the create action, both of which are view-independent, so it sits above the tabs and never changes as you switch.
- **No season timeline graphic.** No filter. No tagline.
- **No account chip / initials circle**, matching Trip Detail.
- The bottom tab bar shows **Trips** active. (The current build highlights nothing.)

**Tab badges.** A plain grey numeral is inventory — the count of my upcoming trips. The filled accent badge is attention — the count of invitations awaiting my answer. That is the only accent in the header zone, and the rule is the same one Trip Detail uses on its `People` and `You` tabs. The badge appears on `Mine` only, because invitations live only in Mine.

---

## 2. The three views

| | Question it answers | Contains | Never contains |
|---|---|---|---|
| **Mine** | *What am I doing?* | Trips I organize · trips I'm going to · trips I'm interested in · **pending invitations, inline at their date** | Friends' trips · overlap annotations |
| **Both** | *Where do my season and my friends' season intersect?* | My trips, **annotated** where friends coincide · friend trips surfaced as standalone rows **only** when the shared Home Ideas logic finds them relevant, each showing why | **Invitations** · unfiltered friends' trips |
| **Friends'** | *What are my friends doing?* | Every visible friend trip across the season, chronological, **trip-centric and consolidated**, relevance-independent | Invitations · my own trips |

Default view is **Mine**. The view is not remembered between sessions.

---

## 3. Row anatomy

Two rows. Always two rows. Mountain-led, date right-aligned, one quiet metadata line.

```
Indy Basin, CO                              12 – 15
ORGANIZING · +7 others
```

| Slot | Content | Type |
|---|---|---|
| Line 1 left | `Mountain, ST` | 15.5 px / 500, ink, truncates with ellipsis |
| Line 1 right | date range, **month omitted** (the group heading carries it) | 13 px / 500, ink2, tabular numerals, never wraps |
| Line 2 left | `RELATIONSHIP · count` | relationship 11.5 px / 600 micro-caps ink2; count 11.5 px / 400 ink3 |
| Line 2 right | overlap (Both) or `Overlap` marker (Friends') | see §7 / §8 |

**Status is stated exactly once**, on line 2. It never appears as both an eyebrow and a right-hand token.

**Count grammar.** Never `GOING · 4 going`.

| Viewer's relationship | Count phrase |
|---|---|
| Organizing, Going | `+N others` where N = headcount − 1 |
| Interested, Invited | `N going` |
| Any, where the count would be 1 | **omitted entirely** — no `1 going` |

`+N others` is Home's own grammar (`Friend01, Friend02, Friend03 +5 others going`), used here so the two screens read as one product. Note that this means **the same trip shows a different number to different viewers**, which is correct and should be stated so it does not look like a bug.

**Cross-month ranges** render as `24 – Mar 1`. The closing month is printed; the opening month is not, because the group heading already supplied it.

**Next trip.** The chronologically next upcoming trip carries a 2 px accent rail on the left edge, a very light accent wash, and the mountain at 600 instead of 500. **Same two-row footprint, no label, no badge.** If the next trip is an invitation, the invitation treatment wins and the rail is not applied.

---

## 4. Invitations

**Treatment I1 — buttons on line two. Mine only.**

```
Whistler, BC                                25 – 29
Dana invited you · 5 going    [ Decline ] [ Accept ]
```

- The row sits on the blush ground with hairline accent rules above and below — the treatment reserved product-wide for *something is waiting on a human answer*. The date renders in accent instead of ink2.
- **The inviter is named**, then the headcount.
- `Decline` and `Accept` are **equal, explicit actions** — outlined and filled, side by side. No action strip, no text-only decline.
- Row height ≈ 96 px against ≈ 62 px for an ordinary row. Three invitations cost ≈ 100 px more than three ordinary rows.
- **Placement is chronological**, in the month the trip falls in. No inbox, no attention block, no pinning to the top.
- Buttons are 34 px of visual chrome; the **hit area must be padded to ≥ 44 pt**. This is deliberate, not an oversight.
- On acceptance the row becomes an ordinary `GOING` row in place. On decline it leaves the list. The invitation badge on the `Mine` tab decrements.

---

## 5. Month grouping

**Always.** No threshold, no volume condition.

```
JANUARY                                     4 trips
FEBRUARY                                    3 trips
```

- Heading is micro-caps ink2 with a hairline rule beneath; the right-hand count is ink3.
- Month name only — **no year** — for months inside the current season. A season spans one calendar-year boundary, so `DECEMBER` and `JANUARY` are unambiguous in context. If a trip ever falls outside the season window the heading takes the year.
- The count noun is `trips` in Mine and Friends', `entries` in Both (because a Both group can contain my trips and friend opportunities together).
- A month with nothing in it is not rendered. Months are never padded to show an empty run.

---

## 6. Friend-trip consolidation (Friends' only)

**Rule: identical mountain AND identical start AND identical end → one row.**

```
Indy Basin, CO                              12 – 15
Dana, Theo + 1 other · going                Overlap
```

- Names read `First`, `First, First`, then `First, First + N other(s)`.
- If the consolidated friends have the same relationship, it is printed (`going`). If they differ, the row reads `going / interested`.
- **Different date ranges stay separate rows.** Deliberately no partial-overlap consolidation. The Friends' heavy screen shows both rules adjacently: `Telluride, CO · 24 – Mar 1 · Elena, Jonah` and `Telluride, CO · 26 – Mar 1 · Priya` are two rows.
- Consolidation is **not** applied in Both. Both annotates my row instead of creating friend rows (§7).
- Sort within a month: start date, then mountain name.
- 18 friends' trips render as 14 rows in the heavy state.

---

## 7. Overlap in Both

**Definition:** a friend's trip at the **same mountain** with **intersecting dates** against a trip I am actually on.

```
Indy Basin, CO                              12 – 15
ORGANIZING · +7 others   Dana + 2 others overlap your dates
```

- Grammar: `X overlaps your dates` · `X + 1 other overlap your dates` · `X + N others overlap your dates`. Lead name is the alphabetically first given name; this is Home's `+N others` shape.
- Right-aligned on line 2, accent, **one line, never wrapped, never a second row**.
- **It annotates my existing row. It never creates a duplicate friend row.**
- Trips with no overlap carry nothing. In the heavy Both screen, **3 of 9** of my trips carry an overlap line and 6 carry none.
- A pending invitation is **not** a trip I am on, so it generates no overlap. (Visible in the mockups: Whistler carries a friend trip but no `Overlap` marker, because my Whistler is still an invitation.)

### Friend trips that appear standalone in Both

Only when the **shared Home Ideas logic** determines they are relevant, and the row must say why.

```
Big Sky, MT                                    2 – 5
FRIEND TRIP · Maeve going          On your wishlist

Sun Valley, ID                              12 – 15
FRIEND TRIP · Win, Maeve + 1 other going   3 friends going
```

- Rendered quieter than my rows: mountain in ink2 at regular weight, a faint neutral tint, `FRIEND TRIP` where a relationship would be.
- The reason is the right-hand slot, in accent — the same slot overlap uses on my rows.
- **Availability alone is not a reason.** "You're free these dates" was tested and dropped: being free is a precondition Home uses for ranking, not an argument for inserting a trip into my season.

---

## 8. Overlap signal in Friends'

A quiet right-aligned `Overlap` marker in ink3 micro-caps on line 2. No sentence, no name, no repetition of "same days as you".

The richer explanation belongs in Both. Friends' only needs to tell you the row is worth a second look.

---

## 9. Relationship to Home Ideas

Home already renders exactly two kinds of idea, in exactly this grammar:

```
FRIEND TRIP                      WISHLIST
Indy Basin, CO                   Big Sky, CO
Friend01, Friend02, Friend03     You and 1 friend have this
+5 others going · Jan 12–15      on your wishlist
```

and Home's availability sheet states the relation in the product's own words: *"Your availability helps BaseLodge surface trip ideas and plans that match when you and your friends are free."*

**Both is the season-ordered expression of the same relation, from the other end.**

| | Home Ideas | Trips → Both |
|---|---|---|
| Anchor | a mountain I am **not** committed to | a trip I **am** on |
| Output | a suggestion card | an annotation on my row, or a standalone entry |
| Grammar | `Friend01, Friend02 +5 others going` | `Dana + 2 others overlap your dates` |
| Kinds | `FRIEND TRIP`, `WISHLIST` | the same two, unchanged |

**The recommendation logic must be written once and shared.** Concretely: the service that produces Home's Ideas should expose the same relevance output to Trips, which orders it by date instead of by rank and renders it as rows instead of cards. Trips must not get a second definition of "relevant". If Home's rule changes, Both changes with it.

---

## 10. Empty and sparse states

| State | Treatment |
|---|---|
| **Mine, no trips at all** | Keep the current build's `GET STARTED` blush card — "Plan your first trip / Pick a mountain, choose your dates, and invite friends to join you" + `Plan a trip`. It is the one thing in today's Trips worth preserving unchanged. Season line reads `No trips yet`. |
| **Mine, only invitations** | The invitation rows render alone, under their month headings. No empty-state card — there is content, it just all needs an answer. |
| **Mine, one trip** | One heading, one row. No padding, no filler. The season line reads `1 trip ahead`. |
| **Both, no overlaps and no opportunities** | Renders identically to Mine minus the invitations, plus one quiet line under the tabs: *"Nothing of yours overlaps a friend's trip yet."* No illustration. |
| **Friends', no friend trips** | Reuse the current copy: "No trips planned yet. None of your friends have upcoming trips." plus `Invite friends →`. Drop the `Plan a trip` button that currently sits there — it answers the wrong question on this tab. |
| **Friends', no friends at all** | Distinct from the above: *"You haven't added any friends yet."* + `Find friends →`. The current build conflates these two. |
| **Loading** | Skeleton rows that reserve the two-row height, under a real month heading if the month is known. Not the current `Loading friends' trips…` body text. |
| **Error** | A stated error line plus a styled `Try again` in the product's own button system, replacing — not sitting above — the loading line. The current unstyled browser button is a defect. |

---

## 11. Past and terminal behaviour

- Past trips live behind **`Earlier this season ⌄`**, a collapsed toggle at the **foot of Mine and Both**, above the tab bar. It expands **in place**; it is not a separate screen.
- Expanded past rows use the same two-row anatomy, quieted: mountain in ink2 at regular weight, no relationship token (the trip is over), date unchanged. **The state code is retained** — the current build drops it.
- No `· Completed` suffix. The section heading already says these are earlier trips; repeating it per row is the same defect as `1 going`.
- `Earlier this season` is **not** shown on Friends'.
- **End of season.** When every trip in the season is in the past, `Mine` shows the season line as `No trips ahead · 15 already skied`, the upcoming ledger is replaced by a single quiet line — *"Your 2026/27 season is finished."* — with `+ Plan a trip` still in place, and `Earlier this season` opens **expanded by default**, because it is now the only content. `Season Snapshot` stays in the top bar; this is the moment it is most useful.
- **Season rollover** is quiet, per the locked BaseLodge decision (1 August → 31 July, no ceremony). On rollover the ledger empties to the sparse state and `Earlier this season` reverts to collapsed, now describing the new season.

---

## 12. Privacy assumptions

These are assumptions the design makes. Each needs confirming against the actual visibility model.

1. **Friends' shows only what the current Friends' Trips tab already shows** — mountain, dates, the friend's name, and their relationship to that trip. It adds no headcount, no participant identities, and no trip content. Consolidating three friends into one row reveals only that those three friends are each going, which the unconsolidated list already revealed.
2. **Overlap is computed from two sets I can already see** — my own trips, and friends' trips already visible to me on the Friends' tab. It surfaces no new fact; it states a coincidence between two visible facts.
3. **Both's standalone friend rows are Home Ideas.** They inherit Home's visibility rules exactly. If Home would not show me that idea, Trips must not either.
4. **`+N others` on my own rows counts participants on a trip I am on**, which Trip Detail already shows me in full.
5. **No non-friend is ever named** anywhere in Trips.

---

## 13. Implementation reading

**Presentation-only** — no new data required, assuming the Trips payload already carries what today's rows render:

- month grouping and the shortened in-month date
- the two-row anatomy, the metadata line, status-stated-once
- `+N others` / `N going` / suppress-at-one phrasing
- the next-trip rail
- `Earlier this season` collapse, and the past-row quieting
- removal of the mountain filter, the tagline and the account chip
- the top-bar / season-line placement swap
- the invitation row's layout

**Existing backend that appears reusable** (each needs confirming — no code was read):

- the upcoming-trips list with mountain, state, dates, relationship and a going-count — all four are rendered by today's rows
- the pending-invitations list — rendered today, at the bottom of Mine
- the past-trips list — rendered today
- the friends'-trips list with per-trip friend and relationship — rendered today, already month-grouped
- **Home's Ideas relevance output** — already computed for Home

**Likely new projection / backend work:**

1. **Consolidation** of friends' trips by `(mountain, start, end)` with a name list. Today's Friends' Trips returns one row per friend-trip.
2. **Overlap computation** — my trips × visible friends' trips, matched on mountain and intersecting dates, returned as a per-trip annotation. Requires both sets in one projection; today they are two separate tabs.
3. **Exposing Ideas to Trips** — Home's Ideas output, reshaped from a ranked card stack into date-ordered rows carrying their reason string.
4. **Accept / Decline from the Trips list.** Today invitations on Trips are inert; the RSVP write exists on Trip Detail but not as a list-level action.
5. **An invitation count** for the `Mine` tab badge. Today's tab badge exists (`My Trips ①`) so this may already be there — needs confirming that it counts invitations and nothing else.

**Requires a data answer before any of it is built:** see §15 questions 1 and 2.

---

## 14. Where the locked decisions conflict with current behaviour

| # | Locked decision | Current product | Consequence |
|---|---|---|---|
| 1 | Vocabulary is `Organizing / Going / Interested / Invited` | Trips renders `GOING`, `PLANNING`, `YOU'RE A GUEST` | **`PLANNING` has no target equivalent.** Either it maps to `Interested`, or it is a distinct stored state that Trip Detail's locked vocabulary does not cover. This is a data question, not a copy question. |
| 2 | Invitations are actionable inline | Invitations on Trips have no controls at all | A new write path on this screen |
| 3 | No mountain filter | `Filter for a mountain` ships today on Friends' Trips | **Shipped functionality is being removed.** Deliberate, per the decision, but it is a removal. |
| 4 | `1 going` suppressed | Rendered under nearly every row | Presentation change only |
| 5 | Past rows keep the state code | Past rows render `Big Sky`, not `Big Sky, CO` | Presentation change only |
| 6 | Both reuses Home's Ideas logic | Ideas is Home-only and card-shaped | Needs the shared service in §13 |
| 7 | Friends' is trip-centric and consolidated | Friends' Trips is person-centric, one row per friend-trip | Needs the projection in §13 |
| 8 | Three views, `Season Snapshot` as a top-bar action | The tab row is two tabs plus a link (`Season Snapshot →`) that navigates away | Fixes a navigation-model inconsistency; also worth fixing that the Snapshot screen orphans the bottom nav |
| 9 | No account chip | Trips renders an initials circle | Matches Trip Detail |
| 10 | — | **Friends' Trips has no verified populated state anywhere in the corpus** — the capture named "heavy" never resolves past `Loading friends' trips…` | Everything drawn for Friends' is reconstructed from the filter-sheet capture. **Confirm against the real screen before building.** |
| 11 | — | The corpus renders every mountain as `, CO` | A seeding artefact; real state codes used here |

---

## 15. Unresolved — decisions I need from you

1. **Does the headcount include me?** The current row renders `8 going`. If that 8 includes the viewer, `+7 others` is correct as drawn. If it excludes the viewer, every `+N others` in these screens is off by one. This is the single highest-risk assumption in the spec.
2. **Is there an interested-count?** Today's rows render `1 planning` alongside `1 going`. If `planning` is the old word for `interested`, then `INTERESTED · 2 going` needs to be checked: is the `2` the number *going*, or the number *interested*? As drawn it is the number going.
3. **Does `PLANNING` map to `Interested`, or is it something else?** (§14.1.)
4. **Season line — keep or drop the counts?** "Stripped-down without the season graphic" was read as the counts line plus the link, since the create action needs a secondary position to occupy. If you meant no counts at all, the line becomes `+ Plan a trip` alone on an otherwise empty row, which looks unbalanced — worth a look before it is built.
5. **Does Both inherit Ideas dismissal?** Home's idea cards carry an `×`. Both's standalone rows currently do not. If they should, the row needs a third affordance and the dismissal has to be shared state with Home.
6. **`Both` month-count noun.** Rendered as `3 entries` where a month mixes my trips and opportunities. `trips` would be wrong; `entries` is accurate but slightly cold. Open.
7. **What is "visible" in Friends'?** The design shows every friend trip the current Friends' tab shows. Whether private trips, or trips of friends-of-friends, are in scope is a visibility-model question I could not answer from the package.
8. **Does the `Mine` badge count only invitations?** Today's `My Trips ①` badge is assumed to be the invitation count. If it counts something else, the attention/inventory rule in §1 needs restating.
