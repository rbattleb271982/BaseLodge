# Trip Detail Implementation Readiness

## 1. Executive verdict

The locked Trip Detail design is implementable in stages against BaseLodge's current architecture. Most visual structure, participant presentation, existing actions, and owner/active-participant views are **A — presentation only** or **B — small backend/query extension**.

Three requirements are not presentation-only:

1. **Invited users reading Trip Planning** requires a new permission distinction. Pending invitees currently may view enough Trip Detail to RSVP but are denied the planning board and preview.
2. **Non-participant friends viewing a reduced Trip Detail** requires a new authorization/presentation capability. The current Trip Detail route returns 404 to non-participant friends, even when a separate join-request capability would let them request access.
3. **An honest Lessons unanswered state** requires a schema/default migration or a separate explicit-answer marker. `SkiTripParticipant.taking_lesson` defaults to `no`, so current rows cannot distinguish “never answered” from “answered No.”

No schema change is required for the hybrid header, tabs, two-item planning preview, mountain counts, participation graphic, pass distribution, grouped roster, join-request controls, invite entry point, profile-derived Riding/Ability/Pass, status controls, current-user availability comparison, equipment control, cancellation confirmation, leave confirmation, past-trip mountain identity, or removal of Stay from this screen.

Important data-language constraints:

- Use **visited**, not **skied**, for the general friend count. `visited_resort_ids` may be set explicitly and is not proof of a logged ski day.
- Do not expose another user's raw availability.
- Treat `SkiTripParticipant.status='pending'` as the target display state **Invited**.
- Treat the organizer as a role derived from trip ownership, not another RSVP bucket.
- Normalize pass strings before grouping; current data can contain multiple comma-separated and legacy-form values.

## 2. Locked target design summary

This audit treats the following as fixed:

- Hybrid trip header
- `Trip | People | You`, with Trip selected by default
- Trip Planning first, with two newest items
- This Mountain social context
- Sentence-style People summary
- Participation and pass-distribution graphics
- Join requests before the grouped roster
- Compact, expandable participant groups and an Invite action
- Profile-derived Riding, Ability, and Pass at the start of You
- Trip-specific Status, Availability, Equipment, and Lessons
- Visual current-user availability
- Direct Equipment and Lessons controls
- Equipment/Lessons-only unanswered badge
- Confirmed Cancel Trip and Leave Trip actions
- No Stay block, photography, photos, avatar circles, or initials avatars
- Persistent mountain identity and read-only behavior for past trips
- Informational, non-tappable dates

No Planning → Confirmed trip lifecycle should be introduced. “Upcoming/Past” is timing; “Organizing/Going/Interested/Invited” is viewer relationship.

## 3. This Mountain data audit

### Other upcoming friend trips

**Classification: B — small backend/query extension.**

BaseLodge already has the necessary entities and privacy primitives:

- `SkiTrip` stores canonical `resort_id`, dates, ownership, public visibility, and lifecycle state (`models.py:737-998`).
- Reciprocal friendship is the current social authorization basis.
- `_build_mountain_availability_overlaps` and `_build_mountain_social_context` already derive mountain-specific friend context (`app.py:13838-14080`).
- `/mountain/<slug>` and `/api/mountain/<slug>/social` expose related mountain context (`app.py:14083+`).
- `build_trip_detail_friend_overlaps` derives privacy-safe, same-resort, date-overlapping friend trips for the current Trip Detail (`app.py:5474+`).
- Home's friend-trip opportunities use separate retrieval logic in `services/ideas_retrieval.py`.

An accurate unique-friend count is possible by selecting reciprocal friends who own or actively participate in a non-terminal upcoming trip at the same canonical resort, then deduplicating by friend ID. Visibility must reuse the existing authorized/public-trip rules rather than merely checking friendship.

Current overlap logic is narrower than the target row because it emphasizes overlapping dates. The target “other upcoming trips” row needs a dedicated same-resort/upcoming aggregation that does not require date overlap.

No schema change is required.

There is no single existing list route whose contract is exactly “authorized friends with upcoming trips at this mountain.” The smallest destination is a filtered mountain-social list backed by the same query used for the count.

Evidence/tests:

- `tests/test_trip_detail_friend_overlaps.py`
- `tests/test_home_ideas_retrieval.py`
- `tests/test_friend_trip_opportunities.py`
- `templates/mountain_detail.html`
- `static/js/mountain-detail.js`

### Friends who have visited

**Classification: B for “visited”; E for an unconditional “skied” claim.**

Current sources:

- `User.visited_resort_ids` is the current normalized user-level set (`models.py:164-168`).
- `User.mountains_visited` remains legacy compatibility storage.
- `User.get_visited_resorts()` and `visited_resorts_count` expose the normalized concept (`models.py:396-415`).
- `SkiDay` is stronger evidence of actual skiing (`models.py:995-1114`).
- `sync_ski_day_to_visited_resorts` adds the resort to visited storage when a ski day is recorded.
- `/mountains-visited/<user_id>` is an existing friend-visible per-user destination (`app.py:14403-14436`).

The inverse unique-friend count can be calculated from reciprocal friends whose normalized visited set includes the resort. Current data does not prove that every such friend skied there: users can manage visited mountains separately, and the visited set does not preserve per-resort source provenance.

Use wording such as:

> 6 friends have visited Northstar

Do not use “have skied Northstar” unless the query is intentionally limited to friends with qualifying `SkiDay` rows. That would produce a different, smaller metric.

No migration is needed for the visited count. A new relational visit-history model would be required only if product later demands provenance, visit dates, or a definitive skiing claim for every entry.

### Friends with this mountain on their wishlist

**Classification: B — small backend/query extension.**

Current support:

- `User.get_wishlist_resorts()` and `wishlist_resorts_count` (`models.py:427-437`)
- Canonical normalization in `services/wishlist.py`
- Settings and instant add/remove routes (`app.py:14220-14396`)
- Current Trip Detail `friends_wishlist_count` computation (`app.py:15555-15569`)
- Existing copy in `templates/trip_detail.html`
- Per-user `/wishlist/<user_id>` route (`app.py:14439-14468`)
- Append-only `WishlistResortEvent` history (`models.py:1197-1249`)

The existing count can be reused after verifying it applies reciprocal-current-friend rules consistently. A list destination requires an inverse friend lookup and a filtered view; the current route lists one user's wishlist rather than all friends matching one resort.

No migration is required.

## 4. Trip Planning audit

**Classification: A for the two-item preview and existing actions; C for invited read-only access; D only if a separate persisted title is mandatory.**

Canonical model:

- `SkiTripPlanningPost` (`models.py:2290-2319`)
- Fields: `trip_id`, `user_id`, `category`, `body`, optional `link_url`, `created_at`, `updated_at`
- Author relationship: `post.author`

Supported categories are:

- Lodging
- Transportation
- Activities
- Food & Drink
- Lessons
- Other

`Travel`, `Terrain`, and `Gear` are not current category values.

There is no separate title field. The current `body` is the persisted post text. The target can treat the body as the displayed title/summary without a migration. If product requires both a title and body, that requires a schema change.

The full board exists at:

```text
/trips/<trip_id>/planning
```

Planning APIs create, update, and delete the same persisted post model (`app.py:15810-15972`). Links are optional and validated as HTTP(S). The full board and preview order newest-first by `created_at DESC`; deterministic ties should add `id DESC`.

The existing Trip Detail preview helper returns the newest three posts (`app.py:15167-15184`). Showing two is a small presentation/query-limit adjustment.

Trip Planning posts and Home Ideas are not the same objects:

- Planning posts are persisted, trip-owned collaboration records.
- Home Ideas are service-produced recommendation dictionaries/cards.

Current permissions:

| Viewer | Read planning | Contribute |
|---|---:|---:|
| Organizer | Yes | Yes |
| Going | Yes | Yes |
| Interested | Yes | Yes |
| Pending/Invited | No | No |
| Non-participant friend | No | No |

Target delta: invited users must gain **read-only** planning access. This should be an explicit capability split such as read versus contribute, not an expansion of `is_active_trip_member`, because pending invitees must remain unable to create/update/delete.

Evidence/tests:

- `tests/test_trip_planning.py`
- `tests/test_trip_detail_planning_preview.py`
- `tests/test_bl173_targeted_social_refresh.py`
- `templates/trip_planning.html`
- `templates/partials/trip_detail_planning_region.html`

## 5. Participation/state audit

Canonical participant statuses (`models.py:37-59`, `models.py:1270+`):

- `pending`
- `interested`
- `going`
- `declined`
- `removed`

Target mapping:

| Target copy | Current source |
|---|---|
| Organizing | `SkiTrip.user_id` / owner role |
| Going | participant `going` |
| Interested | participant `interested` |
| Invited | participant `pending` |

`SkiTrip.trip_status='planning'` is a legacy trip-level field, not a participant relationship and not a Planning → Confirmed lifecycle.

The organizer is derived from ownership and has an owner participant row initialized as Interested. Presentation must elevate ownership to Organizing and count that person once.

Going ↔ Interested changes use canonical RSVP transitions in `services/rsvp_transitions.py`. Declined and removed rows persist for history.

“Not going” transitions a participant to `declined`. The dedicated Leave route also transitions an active participant to `declined`, but it uses a distinct route/source and notification behavior. Storage alone therefore does not distinguish the user's product intent after the transition; RSVP history/source does.

Declined/removed users cannot self-reactivate. The organizer can reinvite them, returning them to `pending`. There is no trip-specific cooldown.

**Classification: A for vocabulary presentation and Going/Interested controls; C if product requires Leave and Not going to produce distinguishable current states.**

Evidence:

- `services/rsvp_transitions.py`
- `tests/test_rsvp_transitions.py`
- `tests/test_trip_self_rsvp.py`
- `tests/test_trip_organizer_participants.py`
- `tests/test_bl78_rsvp_transition_routes.py`

## 6. People counts and Passes audit

### Counts

The target associated-person total should include exactly once:

- Organizer
- Going
- Interested
- Invited/pending

It should exclude:

- Declined
- Removed
- Cancelled/terminal invitation-only records

`get_active_participants()` includes Interested and Going. Pending participants are available separately. `accepted_guest_count` excludes the owner by role. The safest target projection should explicitly aggregate by participant role/status rather than add several existing display properties and risk counting the owner twice.

The required rows can be joined to users in one bounded query with eager loading. No migration is needed.

**Classification: B — small backend/query extension.**

### Pass distribution

Canonical current profile source is `User.pass_type`, a nullable string that can contain comma-separated multiple passes. Season-normalized rows also exist, but current product reads still commonly use `User.pass_type`. `SkiTripParticipant.pass_type` can hold a trip snapshot, and `SkiTrip.pass_type` is legacy trip-level data.

Observed forms include canonical and legacy casing/tokens, multiple comma-separated values, and `No Pass`/`no_pass`. Use the existing pass normalization/display helpers in `app.py:1165-1241`.

Rules needed before implementation:

- Use one documented precedence rule, preferably participant snapshot when present, otherwise current profile.
- Split and normalize multiple passes.
- Count one person in each pass bucket they hold.
- Represent null, empty, or explicit no-pass values as `No pass`.
- Include pending/invited participants because their user profile is available.

No migration is required for the graphic. A migration would only be needed if the product demanded a historically immutable authoritative trip-time pass snapshot.

**Classification: B — small backend/query extension.**

## 7. Roster audit

Field sources:

- Riding: `User.rider_types` JSON, displayed through `riding_type_display`; older rider fields are deprecated compatibility data.
- Ability: `User.skill_level`.
- Pass: `User.pass_type`, with the same normalization/precedence decision described above.

These are profile-derived values. Participant-level pass/equipment fields exist, but Riding and Ability should not become trip-specific.

Organizer and active participants may see active participant identities under current Trip Detail rules. Owners additionally load pending and declined management rows. Pending invitees currently receive a restricted RSVP view. Non-participant friends currently cannot access the route.

The canonical destination for another user is the existing Friend Profile route/template, not the retired self `/profile` surface. Navigation must continue to enforce current reciprocal/profile visibility. A participant is not automatically guaranteed to be a reciprocal friend of every other participant, so the implementation must define a safe non-friend participant destination or render the row non-navigable. It must not assume every participant can open Friend Profile.

The current relationship can be loaded without a new API. A compact initial subset and in-place expansion are presentation-only at current group sizes if all authorized rows are already server-rendered. For robust dense rosters, use deterministic organizer-first, then normalized-name, then user-ID ordering. No final preview cap is selected here.

**Classification: A for grouping/expansion; B for deterministic projection and safe profile-link capability.**

## 8. Join request audit

Join requests use the shared `Invitation` model:

- Sender: requesting user
- Receiver: trip owner
- `trip_id`: target trip
- `status`: `pending`, `accepted`, or `declined`

Creation:

```text
POST /trips/<trip_id>/request-join
```

The capability in `services/visibility.py` limits requests to eligible reciprocal friends for active friend-visible trips and excludes organizers/existing participants. Duplicate pending requests return idempotent success. Creation stages owner-facing activity/messaging.

Organizer response:

```text
POST /trips/requests/<request_id>/respond
```

- Owner only
- Accept creates/transitions the requester to **Interested**, not Going
- Decline marks the request declined
- Both paths emit the corresponding side effects

Requester cancellation:

```text
DELETE /trips/requests/<request_id>
```

It is requester-only and pending-only. Current cancellation deletes the request rather than preserving a cancelled request status.

Multiple different users may have simultaneous pending requests. The owner query already loads pending join requests for Trip Detail, so inline rows and the People badge need presentation/query wiring rather than a new lifecycle.

The response path locks the mutable trip, but no dedicated concurrent duplicate-request test was found. The shared uniqueness involving nullable fields and historical declined rows deserves PostgreSQL regression coverage.

Use the established destructive/primary order: **Decline, then Accept**.

**Classification: A for inline actions using current rows/routes; B for the People count/badge; C for stronger concurrency guarantees if required.**

Evidence:

- `app.py:16532-16711`
- `services/visibility.py:235-270`
- `tests/test_join_request_notification.py`
- `tests/test_bl133_visibility.py`
- `tests/test_friend_request_service.py`

## 9. Invite flow audit

The current trip invite flow is organizer-only. It uses existing candidate rows and trip participant/invitation persistence.

Current safeguards include:

- Owner authorization
- Existing participant detection
- Participant uniqueness
- Invitation pair/trip uniqueness
- Disabled or excluded already-associated candidates
- Organizer cancellation of pending participation
- Organizer reinvite from declined/removed to pending

Cancelling a trip invite is represented primarily by moving the participant to `removed`; it is not the same sender-cancelled social friend-request lifecycle.

The compact People header action can open/reuse the existing invite sheet/flow. No new architecture or schema is needed. The audit recommends preserving the existing candidate query and routes rather than duplicating invitation logic in Trip Detail.

**Classification: A — presentation-only entry point, with B-level verification/refactoring if candidate loading is moved inline.**

Evidence:

- `app.py:16400-16529`
- `templates/partials/trip_invite_candidate_rows.html`
- `tests/test_trip_organizer_participants.py`
- `tests/test_invites.py`

## 10. You — profile fields audit

Profile sources:

- Riding: `User.rider_types`
- Ability: `User.skill_level`
- Pass: `User.pass_type` plus current normalization helpers

They are independently stored; Ability is not inferred from Riding.

Profile management occurs through onboarding/profile settings routes, principally GET/POST `/edit_profile` (`app.py:5266-5392`). Current profile values are read at request time, so default/profile-derived Trip Detail displays update automatically after profile edits unless a trip-specific snapshot is intentionally preferred.

Deprecated rider fields and mixed pass storage remain compatibility concerns, but no schema work is required to display the locked profile-derived block.

**Classification: A — presentation only.**

## 11. You — availability audit

Canonical model:

- `UserAvailability`
- One row per user/date
- Unique `(user_id, date)`
- Full-day Boolean `is_available`
- Private note

Legacy `User.open_dates` remains during compatibility rollout. `services/open_dates.py` gives normalized rows precedence; false rows act as tombstones over legacy values.

Availability is not season-ID scoped. It is date-scoped and limited by current validation to today/future dates. There is no partial-day model.

Trip start/end dates are date values and overlap is inclusive. January 15–18 is four calendar days. Full, partial, and no-entered availability can be derived by intersecting the viewer's available-date set with the inclusive trip-date set:

- Full: overlap count equals trip-day count
- Partial: overlap is greater than zero and less than trip-day count
- None entered: no availability records covering the range

Current overlap helpers already use inclusive date semantics (`app.py:11332+`, `app.py:11477-11520`) and Trip Detail computes the current participant's overlap (`app.py:15398-15435`).

The existing availability editor route can be reused as a destination. Embedding the editor inline would require a reusable component and possibly a focused API contract, but not a schema change.

Only the current user's raw dates may appear in You. Existing friend/mountain features must continue exposing derived overlap only, never another user's date rows or notes.

**Classification: A for the visual comparison; B for embedded Add/Update editing.**

Evidence:

- `models.py:549-562`
- `services/open_dates.py`
- `app.py:14530-14579`
- `tests/test_open_dates_contract.py`
- `tests/test_open_to_ski.py`
- `tests/test_mountain_detail.py`

## 12. You — Equipment audit

Trip-specific participant equipment is:

- `SkiTripParticipant.equipment_status`
- Enum values:
  - `own`
  - `renting`
  - `needs_rentals` as a compatibility value
- Null means no trip-specific answer and falls back to profile display.

Profile-level status uses:

- `have_own_equipment`
- `needs_rentals`

Trip-level `SkiTrip.trip_equipment_status` is a separate owner/trip setup concept and must not be used as the current participant's answer in You.

The participant signals endpoint already updates or clears equipment:

```text
POST /api/trips/<trip_id>/participant/signals
```

Current display maps:

- `own` → Bringing own
- `renting` or `needs_rentals` → Renting
- null → profile fallback / unanswered trip-specific response

`Not sure yet` is not an existing equipment enum value. It can only be represented by clearing the trip-specific answer, but copy must not imply that the user explicitly selected “Not sure yet” unless an explicit value is introduced.

Direct inline selection can reuse the endpoint. No migration is required for the current two explicit answers plus unanswered/null.

**Classification: A — presentation and existing action reuse.**

Evidence:

- `models.py:1273-1277,1328-1344`
- `app.py:17079-17165`
- `templates/trip_detail.html:2115-2130`
- `tests/test_trip_detail_setup.py`

## 13. You — Lessons audit

Trip-specific lesson storage is:

- `SkiTripParticipant.taking_lesson`
- `LessonChoice`:
  - `yes`
  - `no`
  - `maybe`

Display maps to:

- Yes / Taking a lesson
- No / No lesson
- Maybe / Considering a lesson

The participant signals endpoint accepts these values. However, the database column has a non-null/default `no` contract. Current rows therefore cannot reliably distinguish:

- User explicitly answered No
- User never answered and inherited the default

The target Yes / No / Not sure yet control can map `maybe` to Not sure yet without changing the enum. The blocker is the initial unanswered state, not the three explicit choice values.

To support honest unanswered semantics, either:

1. Make `taking_lesson` nullable and remove its default, or
2. Add an explicit “answered” timestamp/flag.

Existing `no` rows cannot be safely backfilled as answered or unanswered without additional evidence.

**Classification: D — schema/migration required for honest unanswered behavior.**

Evidence:

- `models.py:82-85,1277-1281`
- `app.py:17079-17165`
- `templates/trip_detail.html:2133+`
- `tests/test_trip_detail_setup.py`

## 14. You attention badge feasibility

Equipment can honestly be unanswered because the participant-level value is nullable.

Lessons cannot honestly be unanswered because `taking_lesson` defaults to `no`.

Therefore, the exact locked badge counting unanswered Equipment and Lessons is not currently truthful for Lessons.

Availability must not count.

Required behavior after the Lessons data correction:

- New eligible participant: badge count 2
- Answer Equipment: count decreases by 1
- Answer Lessons with yes/no/maybe: count decreases by 1
- Changing one explicit answer to another does not change completion
- Clearing Equipment restores its unanswered count if clearing remains allowed

**Classification: D — blocked by Lessons answer-state representation.**

## 15. Non-participant friend-state audit

Current `trip_detail` authorization uses `trip_view_capability` without enabling friend-public access. It permits:

- Organizer
- Active Going/Interested participants
- Pending invitees in a restricted RSVP view

A random reciprocal friend who is not associated with the trip receives 404, even for a friend-visible trip.

Separate join-request capability does allow an eligible reciprocal friend to request access to an active friend-visible trip. This means discovery/request capability exists outside the full Trip Detail permission.

Current target delta:

- Add a reduced, non-participant friend capability for the Trip Detail route.
- Expose only mountain, location, dates, nights, context/visibility, and aggregate people count.
- Suppress participant identities, planning content, You, join-request queue, and organizer controls.
- Permit Interested and Request to Join actions according to a defined transition.

Current “Interested” is an active participant status and grants participant/planning access. It is not merely a lightweight non-participant expression. Therefore allowing a non-participant to “mark Interested” currently makes them an active participant unless a new separate signal is introduced.

An Interested participant and a pending join request should not coexist under a clean transition: accepting a join request creates Interested, while existing participants are excluded from request creation. Concurrency and stale rows still need tests.

**Classification: C — new authorization and relationship behavior.**

Evidence:

- `services/visibility.py:181-270`
- `app.py:15264-15333`
- `app.py:16532-16680`
- `tests/test_bl133_visibility.py`
- `tests/test_trip_detail_setup.py`

## 16. Invited-user permissions

Current pending invitee behavior:

- May open a restricted Trip Detail view
- May respond Going, Interested, or Not going
- Does not receive the active participant setup editors
- Does not receive planning preview or planning-board access
- Does not contribute planning content

Target behavior requires:

- Read existing planning posts
- No create/update/delete permission
- Contribute only after Going or Interested

Required change: split planning authorization into read and contribute capabilities. Do not redefine pending as active.

Participant identity exposure for pending invitees should remain explicitly limited; the target only grants planning read and does not automatically grant roster identity access.

**Classification: C — new permission behavior.**

## 17. Cancel Trip

Cancellation exists and is owner-only (`app.py:17168-17227`).

The trip is not hard-deleted. It enters a terminal cancelled lifecycle state and remains as read-only history. Participant rows, planning posts, and RSVP history survive. Transient invite tokens/invitations and relevant activities are cleaned up. Active/accepted guests receive cancellation messaging; pending invitees are not notified by the tested contract.

Repeated cancellation is idempotent and does not duplicate notifications. There is no undo.

The current app already has cancellation presentation, but the locked confirmation copy/location may require template work:

- Keep trip
- Cancel trip

No additional copy about notifications should be added.

**Classification: A — presentation using existing lifecycle.**

Evidence:

- `tests/test_trip_deletion.py`
- `templates/trip_detail.html`

## 18. Leave Trip

A dedicated leave route exists (`app.py:17229-17287`).

Rules:

- Active non-owner participant only
- Persists the participant as `declined`
- Records transition history/source
- Notifies other active participants
- Does not delete the participant record
- Does not add a cooldown
- Does not allow self-service rejoin
- Organizer may later reinvite

“Not going” also results in `declined`, but follows the RSVP response/change path. The current status does not preserve a different final bucket for Leave versus Not going; history/source can distinguish how it occurred.

The locked separate Leave action can reuse the dedicated route. Add confirmation without changing the transition.

**Classification: A — presentation using existing behavior.**

## 19. Past-trip behavior

Terminal cancelled/completed Trip Detail already has a read-only-history branch and suppresses owner edit/date controls (`templates/trip_detail.html:1822-1853`).

The retained `SkiTrip` keeps:

- Canonical resort/mountain identity
- Location and dates
- Participants
- Planning posts
- RSVP transition history

Cancellation tests prove retained records. Completed-date behavior has less direct coverage than cancellation, and every mutating endpoint must be checked for terminal-trip guards rather than relying only on hidden buttons.

The target should:

- Preserve the hybrid mountain header
- Omit the empty Stay shell
- Suppress RSVP, invite, planning-create, equipment/lesson update, cancel, and leave controls
- Show useful read-only Trip/People content where authorization permits

**Classification: A for presentation; B for comprehensive terminal guards and test coverage.**

## 20. Navigation targets

| Signal | Existing destination | Readiness |
|---|---|---|
| Upcoming friend trips | Mountain detail/social and Home idea routes exist, but no exact filtered list | Add a filtered mountain-social list or sheet using the count query |
| Friends visited | `/mountains-visited/<user_id>` is per friend, not inverse by mountain | Add an inverse authorized-friend list |
| Friends wishlist | `/wishlist/<user_id>` is per friend, not inverse by mountain | Add an inverse authorized-friend list |

All three target rows can remain non-tappable in the first batch if the product requires destinations to be coherent before adding chevrons. Do not route to a semantically different Home Ideas surface merely because it already exists.

## 21. Implementation classification matrix

| Target feature | Current support | Exact evidence | Required backend change | Required frontend change | Migration? | Tests required | Risk | Class |
|---|---|---|---|---|---:|---|---|:---:|
| Hybrid header | Current trip/resort summary exists | `trip_detail`, `templates/trip_detail.html` | None | Recompose locked header | No | owner/guest/past rendering | Low | A |
| Trip / People / You | Data is on one page | `trip_detail` context | None | Add tabs; Trip default | No | state/focus/history/mobile | Low | A |
| Planning 2-item preview | Newest-three preview exists | `_trip_detail_planning_preview_state` | Optional deterministic `id DESC`; limit/slice 2 | Locked card/copy | No | 0/1/2/3+ ordering | Low | A |
| Mountain upcoming friend trips | Adjacent overlap/social queries exist | mountain social and friend-overlap helpers | Same-resort upcoming unique-friend aggregate | Row and optional list | No | privacy, dedupe, terminal, ordering | Medium | B |
| Mountain friends visited | Friend visited sets exist | `User.get_visited_resorts` | Inverse authorized friend count/list | Use “visited” | No | legacy/normalized/privacy | Medium | B |
| Mountain friends wishlist | Count foundations exist | `friends_wishlist_count`, wishlist service | Reusable inverse list/query | Row and destination | No | dedupe/privacy/normalization | Low | B |
| Participation graphic | Status rows already loaded | participant helpers | Explicit owner-once projection | Render graphic | No | mixed statuses, owner once | Low | A |
| Pass graphic | Data exists but needs normalization | `User.pass_type`, participant snapshot | Distribution projection and precedence | Render graphic/legend | No | no pass/multiple/legacy | Medium | B |
| People attention badge | Owner pending requests loaded | `pending_join_requests` | Expose/count consistently | Badge | No | 0/1/3, non-owner hidden | Low | B |
| Join request inline actions | Existing owner rows/routes | request/respond routes | None beyond response presentation | Inline Decline/Accept | No | auth/idempotency/stale/concurrent | Medium | A |
| Compact grouped roster | Participant rows exist | participant helpers | None for initial version | Group compact rows | No | 1/13 people, status groups | Low | A |
| Expandable roster | Full authorized set can be loaded | Trip Detail participant query | Optional bounded query later | Expand/collapse in place | No | keyboard/mobile/dense counts | Low | A |
| Invite action | Organizer flow exists | invite routes/candidate partial | None | Compact entry point | No | organizer-only/candidates | Low | A |
| Profile Riding | Existing profile field | `User.rider_types` | None | Display normalized value | No | multi/empty/legacy | Low | A |
| Profile Ability | Separate field exists | `User.skill_level` | None | Display value | No | empty/Social behavior | Low | A |
| Profile Pass | Existing profile field | `User.pass_type` | None beyond normalization reuse | Display value | No | no/multiple pass | Low | A |
| Status controls | RSVP transitions exist | response/status routes | None | Locked controls/copy | No | Going↔Interested/auth | Low | A |
| Availability comparison | Inclusive overlap exists | availability helpers/current-user state | Shape view model if needed | Visual full/partial/none | No | inclusive/full/partial/none | Low | A |
| Add/Update availability | Separate editor/service exists | `/add-open-dates`, open-dates service | Component/API only for inline editing | Link or embedded editor | No | validation/privacy/refresh | Medium | B |
| Equipment inline control | Nullable participant field/update exists | participant signals route | None | Direct selection | No | own/renting/clear/invalid | Low | A |
| Lessons inline control | yes/no/maybe update exists | `LessonChoice`, signals route | None for explicit choices | Direct selection | No | all values/auth/invalid | Low | A |
| You incomplete badge | Equipment supports null; Lessons does not | participant columns/defaults | New unanswered representation | Badge calculation/display | Yes | explicit No vs unanswered | High | D |
| Non-participant friend view | Current route denies access | visibility capability, `trip_detail` | Reduced capability and safe projection | Reduced view/actions | No* | public/private/leakage | High | C |
| Interested | Canonical active status exists | RSVP transitions | New behavior only if used as nonparticipant signal | Status action/copy | No* | access transition/coexistence | High | C |
| Request to Join | Existing separate queue | request-join routes | None for current semantics | Target action/state | No | private/auth/duplicate | Medium | A |
| Invited read-only planning | Currently denied | planning capability/tests | Split read/contribute permission | Show read-only preview/board | No | pending read/no-write | High | C |
| Cancel confirmation | Lifecycle exists | cancel route/tests | None | Locked confirmation | No | owner/repeat/terminal | Low | A |
| Leave confirmation | Dedicated route exists | leave route/history | None | Locked confirmation | No | owner denied/rejoin/history | Low | A |
| Past read-only treatment | Terminal branch/data retention exist | template and deletion tests | Audit all mutation guards | Locked read-only rendering | No | completed/cancelled/all roles | Medium | B |
| Remove Stay | Stay currently rendered | trip template Stay block | None; preserve stored data | Omit block from target | No | no empty shell/regression | Low | A |
| Person row → Friend Profile | Route exists only where authorized | friend-profile route/privacy | Capability-safe target resolution | Conditional navigation | No | friend/nonfriend/privacy | Medium | B |

\* A schema migration is not inherently required for non-participant Interested if current participant semantics are accepted. A separate lightweight-interest concept would require new state/model design and may require a migration.

## 22. Required tests

Future implementation must cover:

### Roles and privacy

- Organizer normal view and controls
- Going participant
- Interested participant
- Invited/pending user
- Non-participant reciprocal friend
- Unrelated outsider
- Private trip
- Participant-identity suppression
- Planning read/write capability split
- Raw availability and note non-disclosure

### Scale and empty states

- One-person trip
- 13-person mixed-status trip
- Stable organizer-first/group/name ordering
- Zero, one, two, and more than two planning items
- Three join requests and People badge
- Empty mountain signals

### Availability

- Full availability
- Partial availability
- No availability entered
- Inclusive same-day and Jan 15–18 four-day range
- Legacy fallback and normalized false tombstones
- Invalid/past date handling

### Equipment and Lessons

- Equipment unanswered, own, renting, and cleared
- Lessons unanswered, yes, no, and maybe
- Explicit No distinguished from never answered after migration
- Badge count updates and excludes availability
- Unauthorized and terminal update rejection

### Passes

- No pass
- One pass
- Multiple comma-separated passes
- Legacy token normalization
- Invited user with null participant snapshot
- Owner counted once

### Lifecycle

- Going ↔ Interested
- Not going
- Leave confirmation and retained declined/history state
- Reinvite after declined/removed
- Cancel confirmation, idempotency, retained history, and notifications
- Completed and cancelled read-only Trip Detail

### Join requests and invitations

- Request creation/duplicate/cancellation
- Accept produces Interested
- Decline
- Three simultaneous pending request rows
- Stale responses
- Concurrent duplicate creation and accept/decline handling on PostgreSQL
- Candidate exclusions, invite cancellation, and reinvite
- Interested versus pending join-request coexistence prevention

### Interaction/accessibility

- Trip opens by default
- Tab keyboard/focus behavior
- Expand/collapse roster
- Confirmation cancel/keep paths
- Person-row conditional navigation
- Mobile/Capacitor rendering without a separate state path

## 23. Migration requirements

### Required for the exact locked target

An honest Lessons unanswered state requires one of:

- Nullable `taking_lesson` with no default/server default, or
- An explicit answer-state field such as `lesson_answered_at`

Migration design must not relabel every historical `no` as either answered or unanswered without evidence. A compatibility policy is required for legacy rows.

### Not required

No migration is required for:

- Header/tabs/Stay removal
- Planning two-item preview if `body` serves as title
- Mountain counts/lists
- Participation and pass graphics
- Grouped roster
- Join-request/invite UI
- Profile-derived fields
- Availability comparison/editor reuse
- Equipment control
- Planning read/contribute permission split
- Reduced non-participant view
- Cancel/leave confirmations
- Past-trip read-only presentation

### Optional future normalization

Potential later migrations, not prerequisites for the first implementation:

- Relational normalized pass memberships/snapshots
- Relational visited-resort provenance
- Separate planning-post title
- Separate lightweight non-participant “interest” signal
- Stronger partial uniqueness for pending trip requests

## 24. Risks / unresolved product questions

1. **Visited versus skied:** locked copy must choose “visited” unless restricted to `SkiDay` evidence.
2. **Planning title:** confirm that current post body is the target title. A distinct title is schema work.
3. **Invited roster privacy:** planning-read permission must not accidentally expose participant identities or You content.
4. **Non-participant Interested:** current Interested means active participant with planning access. Decide whether the target action intentionally grants that state or needs a separate lightweight signal.
5. **Person navigation:** not every co-participant is necessarily a reciprocal friend. Rows need capability-aware destinations.
6. **Pass precedence:** define profile versus participant snapshot precedence before computing distribution.
7. **Multiple passes:** one person may occupy multiple graphic buckets; percentages may therefore sum above 100% unless the graphic is designed as memberships rather than exclusive shares.
8. **Lessons backfill:** historical default `no` cannot be classified reliably as explicit.
9. **Leave versus Not going:** both end in declined; only transition source/history distinguishes them.
10. **Terminal enforcement:** hidden controls are insufficient; all mutation endpoints must reject terminal trips.
11. **Join-request concurrency:** sequential idempotency exists, but PostgreSQL race coverage is needed.
12. **Navigation destinations:** inverse friend lists do not currently exist for the three mountain rows.

## 25. Recommended implementation batches

1. **Presentation foundation:** hybrid header, tabs, remove Stay, two-item planning preview, profile-derived You block, current status controls, compact/expandable roster, existing invite/join-request actions, and cancel/leave confirmations.
2. **Read projections:** explicit People counts, pass distribution, People badge, deterministic roster ordering, availability visual, and mountain signal counts.
3. **Privacy capability work:** invited read-only planning and reduced non-participant friend view, with identity/planning/You suppression tests.
4. **Inline editing:** embedded availability reuse plus Equipment and Lessons controls.
5. **Lessons answer-state migration:** implement honest unanswered semantics and then enable the You badge.
6. **Navigation and hardening:** mountain inverse-list destinations, safe participant profile navigation, terminal endpoint audit, and concurrency tests.

### READY NOW

- Hybrid header and Trip/People/You structure
- Trip default tab and two-item planning preview
- Participation graphic
- Compact and expandable grouped roster
- Existing join-request inline controls
- Existing Invite action
- Profile-derived Riding, Ability, and Pass
- Going/Interested status controls for current participants
- Current-user availability visualization
- Equipment inline selection
- Explicit Lessons yes/no/maybe selection
- Cancel Trip confirmation
- Leave Trip confirmation
- Remove Stay from the target UI
- Preserve past-trip mountain identity

### NEEDS SMALL BACKEND WORK

- Upcoming same-mountain unique-friend count/list
- Friends-visited count/list using “visited” wording
- Friends-wishlist inverse count/list reuse
- Explicit associated-people aggregates
- Normalized pass distribution
- People join-request badge
- Deterministic roster sorting and profile-link capability
- Embedded Add/Update availability
- Comprehensive past/terminal guards and tests

### NEEDS PRODUCT/ARCHITECTURE WORK

- Invited-user read-only planning capability
- Reduced non-participant friend Trip Detail capability
- Meaning of non-participant “Interested” versus active participant Interested
- Honest Lessons unanswered representation and legacy-row policy
- Safe person-row behavior for co-participants who are not reciprocal friends

### DEFER

- “Friends have skied” based on generic visited data
- A separate planning title unless body-as-title is rejected
- Visit-provenance/history redesign
- Pass compatibility or buddy-pass analysis
- Raw availability for anyone other than the current user
- New photography/avatar/profile-bubble treatments
- New Planning → Confirmed lifecycle
- Large navigation redesign beyond the smallest mountain-filtered list surfaces

The smallest sensible first implementation is Batch 1 followed by the low-risk portions of Batch 2. Permission changes and the Lessons migration should be isolated behind complete role/privacy and legacy-data tests.