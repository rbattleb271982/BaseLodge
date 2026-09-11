# Trip Detail — synthesis notes

One direction. Ledger identity · Open Items participant rows · Roster sentence + graphics · Index three-part structure. Trip is always the default tab.

**Heights at 390 px** — Trip 916 px · People 1,097 px (5 people) / 1,449 px (13 people, 3 requests) · You 960 px. The current build runs past three screens with less content.

---

## Unresolved visual questions

### 1. Header density — **recommend C (Hybrid)**
`00-header-comparison/`

| | Header + tabs |
|---|---|
| A — Full Ledger | 275 px |
| B — Compressed | 189 px |
| **C — Hybrid** | **217 px** |

**Tried.** A reads beautifully in isolation but spends 86 px of every screen on three labels for facts that never change, and the labels (`WHEN` / `SHARING` / `YOU`) compete with the section labels underneath — two micro-caps systems stacked. B is the cheapest but gives the date the same weight as visibility, so the one fact people actually scan for gets no emphasis. C gives the date its own line at 18 px/600, then drops relationship and visibility to a single quiet metadata line with the relationship as a small accent token.

**Recommend C.** It costs 28 px more than B and buys a real hierarchy: mountain → when → context. It is also the only one of the three that still reads correctly when a host name is appended (`INVITED · Visible to friends · Dana Whitfield is organizing`).

### 2. People tab badge — **recommend treatment 1**
`02-people/SPEC-tab-badge-treatments.png`

**Tried.** (1) plain grey numeral + filled accent badge; (2) outlined count pill + filled badge; (3) badge only, count moved into the section.

**Recommend 1.** The rule it establishes: **a plain grey numeral is inventory; a filled accent badge is the only shape in the product that means "waiting on you."** The You tab uses the same badge and never a numeral, so the two meanings stay separable across the whole tab row. (2) is a stronger distinction at 10 px but gives People two containers and makes it visibly heavier than its neighbours. (3) is the cleanest row but hides the group size until you open the tab.

### 3. Passes graphic — **recommend share-of-group rows**
`02-people/`

**Tried.** First a bar-per-pass scaled to the largest value. At 13 people it read well; at 5 people (Epic 2 · Ikon 2 · No pass 1) two bars both hit 100 % and the graphic said nothing.

**Now.** Each bar is a share of the whole group against a visible track, so the three bars read as portions of one thing. Fill is neutral ink, not the participation palette — participation encodes *category* and needs distinct colours, passes encodes *magnitude* and should not. `No pass` is a lighter tint of the same ink, so absence reads as less rather than as a fourth category.

**Flag.** Below about six people the graphic still earns its place only weakly. Consider suppressing it when the group has fewer than five people or only one pass type, and showing the counts as a line instead.

### 4. Availability — **recommend the day strip**
`03-you/SPEC-availability-three-states.png`

**Tried.** A day strip against the trip's actual dates: weekday label, day number, and a bar under each day. Filled = free, hairline = not free or not said. Weekday labels are derived from the trip dates (Jan 15 2027 is a Friday), not invented.

Three states render: all four days, two of four with the range named, and nothing entered. The action changes with the state — `Update ›` when something exists, `Add availability ›` when it does not — so the user never has to leave and rediscover the trip.

### 5. Roster expansion — **recommend a cap of 4, flagged**
The dense specimen caps each status group at **3** and offers `Show 5 more going ⌄`, which expands in place. 3 was chosen so the expand affordance is visible in a 13-person fixture; **4 is probably the right production number** — it clears most real groups without any expansion at all. The cap applies per group, so Interested (2) and Invited (2) render whole.

### 6. Disclosure chevron on person rows
Every person row carries a quiet chevron so the tap target to Friend Profile is discoverable. At 13 rows that is 13 chevrons. **Tried without them** — the rows read better but nothing signals they are tappable. Kept, at reduced opacity. Worth one round of on-device judgement.

### 7. Invited user — RSVP appears once, never twice
The invitation band sits under the header on the **Trip** and **People** tabs. On the **You** tab it is absent, because `YOUR STATUS` carries the same three-option control there. The decision is always one tap away and never duplicated on one screen.

---

## Data support — This Mountain

The brief asked for three social signals and asked me to flag any the inventory does not support.

| Signal | Support |
|---|---|
| `2 friends have Northstar trips planned` | **Underlying relationship verified.** Inventory §3.9: Trip Detail already links to "your friends' trips at {Mountain}". **The count itself is not verified** — the current link shows no number. |
| `6 friends have skied Northstar` | **Not verified.** No "has visited / has skied" signal appears anywhere in the Trip Detail inventory. The Mountains screen renders a per-mountain friend count, but its semantics are not established. **Confirm before building.** |
| `4 friends want to ski Northstar` | **Partially verified.** Wishlist exists — §3.5 observed `On 1 friend' wishlists` on the trip hero, and Mountains carries wishlist flags. **A per-mountain friend-wishlist count on Trip Detail is not verified.** |

All three are rendered so you can judge the layout. None should be built before the counts are confirmed.

---

## Copy that needs confirming

| Rendered | Note |
|---|---|
| `Bringing own` / `Renting` / `Not sure yet` | Only **`Bringing own`** is a verified product string (§3.8). The other two follow your direction and need confirming against what BaseLodge actually stores. |
| `Yes` / `No` / `Not sure yet` (Lessons) | The verified string is `No lesson`. These three follow your direction. |
| `No pass` | Locked by you for the passes graphic. I have used it in the roster rows too, replacing the current `No pass yet`, so one label means one thing on one screen. |
| Planning categories `Travel` / `Terrain` / `Gear` | Only **`Lodging`** is verified. The others exercise the row; the taxonomy is still open. |

---

## Rules this direction establishes

- **Blush means one thing:** something is waiting on a human answer. Join requests and the invitation band use it. Nothing else does.
- **One destructive treatment,** used once per screen, always confirmed: Cancel trip (organizer, foot of the Trip tab) and Leave trip (participant, foot of the You tab).
- **One section label per section.** No `TRIP PARTICIPANTS` above `Trip participants`.
- **Status is stated by the group heading, never repeated as a pill on the row.**
- **Trip opens by default, every time.** The last tab is not remembered.
- **The `You ②` badge counts unanswered trip-specific questions only** — Equipment and Lessons. Availability is optional and is not counted.
- **No circles anywhere.** The `RB` account chip is removed from the top bar, and the dead `.avatar` rule has been stripped out of the shared stylesheet so it cannot grow back.

---

## Where the locked requirements fought the layout

1. **Two graphics under a sentence, above everything else.** Participation + passes cost about 150 px before a single name appears. At organizer/normal the first person lands right at the first fold; at dense the roster starts just past it. It works, but the People tab has no room left for a third graphic — which is the strongest argument for the "no skiers vs snowboarders" decision being the right one.
2. **"Trip Planning is the first content under the tabs" + "Trip is always the default."** On a trip with no planning items yet, Trip Detail opens onto an empty section. The composer carries it (`+ Share an idea or link` is the content, not a placeholder), but the first screen of a brand-new trip is the weakest screen in the system, and nothing is allowed to sit above it.
3. **"Number of people" and "attention count" in one tab label.** People is the only tab in the product carrying two numbers. Treatment 1 makes them distinguishable; it does not make the tab row as quiet as it was.
