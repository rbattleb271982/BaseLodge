# BaseLodge Attention Architecture Review

## 1. Executive summary

BaseLodge does not have one attention system. It has three related but independent systems:

1. **Canonical action state** in domain records: `Invitation`, `SkiTripParticipant`, `Friend`, trip lifecycle records, and planning posts.
2. **In-app notification history** in `Activity`, plus pending connection requests queried directly from `Invitation`.
3. **Outbound delivery** through the messaging event registry, outbox/delivery policy, provider integrations, and `MessageEventLog`.

The product distinction between “know” and “do” is therefore real in the data architecture but inconsistently communicated in the interface. Home’s **Needs You** section is the clearest action projection: it combines unresolved friend requests, trip invitations, and join requests and lets the user resolve them inline. Notifications is primarily a recent activity list, but it also directly embeds incoming connection actions. Friends and Trip Detail remain the strongest contextual action destinations. Trips separately calls out pending trip invitations.

Notification “read” state is not stored per item. Opening Notifications posts a session timestamp, `notif_last_viewed_at`; it neither mutates `Activity` nor resolves a domain action. Resolving an action does not mark an Activity row read. This separation is conceptually sound, but the interface does not explain it and several counts represent unresolved domain state rather than unread history.

No privacy or authorization defect was confirmed. Focused tests passed **144/144** using repository-enforced disposable in-memory SQLite. Home’s pending-action projection stays bounded at five SELECTs in the heavy tested state and caps display at 12 rows. Trip Detail’s tested projection also remains bounded.

The review identifies **0 P0, 0 P1, 9 P2, and 3 P3 attention-related findings**. Two P2 findings were previously established by the full application audit: notification database failures render as an empty inbox, and notification actions lack adequate pending/failure feedback. The remaining findings are high-confidence source/test findings; the responsive overflow findings remain source-derived because a safe isolated visual runtime was not available.

Four unranked future architectures are presented. Some can reuse current domain state without a schema migration; others would require an explicit attention/read projection and migration.

## 2. Current attention architecture

| Layer | Current owner | Purpose | Important boundary |
|---|---|---|---|
| Current friendship | Reciprocal `Friend` rows | Authoritative social relationship | Connection history does not grant access |
| Friend request | `Invitation` with no trip and outbound type | Unresolved incoming/outgoing request | Status is pending/accepted/declined |
| Trip invitation | `Invitation` plus `SkiTripParticipant` RSVP | Invite lifecycle and current participation | Participant RSVP is current trip state |
| Join request | `Invitation` with request type and trip | Organizer decision | Owner-only action state |
| Trip participation | `SkiTripParticipant` | Pending/interested/going/declined/removed state | Active participation is Interested or Going |
| In-app notification | `Activity` | Recipient-specific recent event projection | No per-row read/resolved fields |
| Notifications acknowledgement | Session timestamp | Records that the page was displayed | Not durable across devices; not per event |
| Home pending summary | Server-built projection | Unresolved invitations and requests requiring action | Capped at 12 rows |
| Navigation attention | Direct count queries | Friends badge; Trips invitation count | Counts unresolved state, not unread history |
| Outbound delivery | Message registry/outbox/MEL/providers | Push/email channel delivery and audit | Not the source for `/notifications` |

The architecture correctly treats current state as authoritative and histories as evidence. The weakness is projection fragmentation: each surface derives attention independently, so mutation refresh behavior and wording can diverge.

## 3. Attention surface map

| Surface | What appears | Action there? | Persists after resolution? | Read state? | Canonical source |
|---|---|---:|---:|---:|---|
| Home / Needs You | Friend requests, trip invitations, join requests | Yes | No after refreshed projection | No | Domain invitation/participant state |
| Notifications / Connection requests | Incoming friend requests | Accept only | Row hidden after local success | Page-view timestamp only | `Invitation` |
| Notifications / Recent | Connection acceptance, trip invitation/result, join request/result, trip location/pass changes, suggestions | Usually deep link; not direct resolution | Activity can remain, except inactive trip-backed rows are filtered | No per row | `Activity` |
| Friends | Incoming/outgoing requests, directory, suggestions | Accept, decline, withdraw, send | Current request rows change with state | No | `Invitation`, `Friend`, cooldown/suggestion state |
| Trips / Mine | Pending invitations and invitation attention count | Contextual response path | Invitation leaves pending presentation after response | No | Invitation/participant projection |
| Trip Detail / People and You | Invitee RSVP, owner join requests, participant status/actions | Yes | Current state changes; history is elsewhere | No | Participant and invitation state |
| Planning / Ideas | New planning content and opportunity context | Contextual contribution | Post persists as trip content | No notification read model | Planning posts/domain activity |
| Bottom navigation | Friends pending-request badge | Navigates to Friends | Badge persists until canonical request resolution and rerender | No | Direct pending `Invitation` count |
| Home connection toast | Connection acknowledgement | Dismiss/acknowledge presentation | Separate dismissal record/endpoint | Dismissed, not “read” | Dismissed insight state |
| Push settings | Server preference and native registration workflow | Yes, configuration | Persists as preference/device state | Not applicable | User preference, device/provider state |
| Toasts/inline errors | Immediate mutation feedback | Retry sometimes | Ephemeral | No | Client mutation result |

Notifications is not a primary-navigation destination. Home, Trips, Friends, and Mountains are the shared bottom-nav destinations. This makes unresolved actions discoverable primarily through contextual badges and Home rather than through a global notification badge.

## 4. Event/action matrix

| Event | Actor | Recipient | Notification created? | Action required? | Surfaced / resolved | Persists until resolved? | Read behavior | Canonical state |
|---|---|---|---|---:|---|---:|---|---|
| Incoming friend request | Sender | Receiver | Direct pending row; not an `Activity` | Yes | Home, Friends, Notifications, Friends nav badge / Home or Friends or Notifications | Yes by query | Page view unrelated | Pending `Invitation` |
| Friend request accepted | Receiver | Sender | `connection_accepted` Activity | No | Notifications, Home toast/context / already resolved | Historical Activity | No per-row state | Reciprocal `Friend` rows |
| Friend request declined | Receiver | Sender | No supported in-app Activity found | No further action | Request disappears; cooldown applies | No | None | Invitation status + cooldown |
| Friend request withdrawn | Sender | Receiver | No supported in-app Activity found | No further action | Outgoing/current request projections | No | None | Invitation status + cooldown |
| Trip invitation | Organizer | Invitee | `trip_invite_received` Activity and outbound event where configured | Yes | Home, Trips, Trip Detail, Notifications deep link / Home or Trip Detail | Pending domain state persists | Activity acknowledgement unrelated | Invitation + participant RSVP |
| Invitation accepted/going | Invitee | Organizer | `trip_invite_accepted` Activity | No | Notifications and Trip Detail | Historical Activity may remain | No per-row state | Participant RSVP |
| Invitation interested | Invitee | Organizer/context | Current RSVP state; no distinct notification type confirmed | Usually no immediate action | Trip Detail/Trips | Contextual state | None | Participant RSVP |
| Invitation declined | Invitee | Organizer | `trip_invite_declined` Activity type exists; outbound event is registered but prior audit found it not emitted | No | Notifications if Activity emitted; Trip Detail state | Historical if emitted | No per-row state | Participant RSVP/history |
| Join request | Requester | Organizer | `join_request_received` Activity and immediate push event | Yes | Home, Trip Detail People, Notifications deep link / Home or Trip Detail | Yes by request state | Activity acknowledgement unrelated | Request `Invitation` |
| Join request approved | Organizer | Requester | `join_request_accepted` Activity | No | Notifications, Trip Detail | Historical Activity may remain | No per-row state | Participant RSVP + transition history |
| Join request rejected | Organizer | Requester | `join_request_declined` Activity | No | Notifications without action link | Historical Activity may remain | No per-row state | Invitation/transition state |
| RSVP/status change | Participant/organizer | Relevant trip users | Some transitions create Activity/outbound events; not every RSVP transition is a notification | Context dependent | Trip Detail / Trip Detail | Current status persists | None | `SkiTripParticipant` |
| Participant leaves | Participant | Organizer/participants as implemented | Messaging support varies by event | Usually contextual follow-up only | Trip Detail | Current absence persists | None | Participant state + transition history |
| Participant removed | Organizer | Participant | Messaging support varies by event | No response required | Trip Detail | Current removal persists | None | Participant state + transition history |
| Trip location changed | Organizer | Relevant participants | `trip_location_changed` Activity and registered outbound event | No | Notifications deep link, Trip Detail | Activity retained while trip active | No per-row state | Trip current location + Activity |
| Trip pass/details changed | Organizer | Relevant participants | `trip_pass_changed` Activity / registered outbound event | No | Notifications deep link, Trip Detail | Activity retained while trip active | No per-row state | Trip current pass + Activity |
| Trip cancellation | Organizer/system | Participants | Outbound messaging exists in architecture; inactive trip-backed Activities are filtered from Notifications | No | Contextual trip surfaces and delivery channel | Terminal state persists; live notification may disappear | None | Trip lifecycle state/history |
| Trip completion | System/user lifecycle | Participants | No specific in-app notification behavior established | No | Historical trip surfaces | Terminal state | None | Trip lifecycle state/history |
| Planning post created | Participant | Eligible trip members | Registered messaging event; no matching `ActivityType` notification row confirmed | Contextual attention | Trip planning/Trip Detail | Post persists | No per-row notification state | Planning post |
| Friend suggestion received | User/system | Recipient | `friend_suggestions_received` Activity; push path also exists | Optional action | Notifications/Friends suggestions | Suggestion state may persist | No per-row state | Suggestion + Activity |

The matrix shows that “notification created” is channel-specific. An Activity, a messaging event log, a push delivery, and a pending-domain projection are not interchangeable.

## 5. Notification state model

`Activity` contains actor, recipient, type, object type/id, creation time, and optional JSON metadata. It has no read timestamp, dismissed timestamp, resolution pointer, or delivery status. The notification route selects ten supported Activity types, newest first, capped at 50.

The route preloads referenced active trips. If a trip-backed Activity points to a deleted, completed, or cancelled trip, it is omitted rather than rendered with a stale Trip Detail link.

Opening Notifications triggers `POST /api/notifications/viewed`, which writes an ISO timestamp to the current session. The request failure is swallowed by the client. This is page-level acknowledgement, not an item state model. It is browser-session scoped and cannot represent different read positions across devices.

Pending connection requests are inserted above the Activity list through a separate direct query. Therefore Notifications is a composite of current actionable state and historical event rows.

## 6. Pending-action state model

Pending actions are domain queries:

- Friend request: pending outbound, no-trip `Invitation` received by the user.
- Trip invitation: invitation/participant state for the invitee.
- Join request: pending request-type `Invitation` owned contextually by the trip organizer.

Home builds three independent families and merges them into a **Needs You** projection. Passing tests show three family SELECTs when empty and five SELECTs in a heavy mixed fixture, with a 12-row cap.

The Friends bottom-nav badge counts only incoming pending friend requests and displays `9+` above nine. Trips uses a separate pending invitation count. There is no single global unresolved-action total.

This is a federated pending-state architecture: each domain remains authoritative, while surfaces calculate projections. It avoids a second source of truth but requires consistent query predicates and mutation invalidation.

## 7. Read versus unresolved findings

| Combination | Current behavior |
|---|---|
| Unread + unresolved | A new Activity may coexist with an unresolved domain request; the request also appears through direct pending queries |
| Read + unresolved | Opening Notifications records page viewed but leaves the request pending everywhere |
| Unread + resolved elsewhere | Resolution changes domain state; an Activity can remain in Recent because it is historical and has no per-row read field |
| Read + resolved | Page acknowledgement and domain resolution coexist independently |

**Answer:** marking Notifications viewed has no effect on the underlying action. Resolving the action has no effect on the session’s notification-view timestamp and does not mutate historical Activity rows.

This separation is correct at the architecture level. The defect is presentation ambiguity: actionable and historical items share one page without explicit status labels, and the page has no visible unread marker even though it records a viewed timestamp.

## 8. Friend-request journey

1. User A sends a request to User B. Canonical state is a pending no-trip outbound `Invitation`.
2. User A sees outgoing request state in Friends. User B sees it in Home Needs You, Friends, Notifications’ Connection requests, and the Friends bottom-nav badge.
3. Acceptance from any supported action route creates reciprocal `Friend` rows and terminal request state. Focused tests confirm repeat acceptance is idempotent and creates one connection-history event.
4. Decline creates a pair cooldown and blocks immediate re-request. Withdrawal removes the pending presentation; a repeated stale withdrawal returns conflict behavior.
5. Acceptance creates an informational `connection_accepted` Activity for the sender. It does not require another action.
6. On Notifications, successful acceptance hides only the local request row. The server-rendered Friends nav badge remains stale until another render.
7. If acceptance fails in Notifications, the row re-enables without visible error or retry explanation.

Tests also confirm malformed null-trip request variants are excluded from Friends, Profile, search, Notifications, and the nav badge and cannot be accepted or cancelled.

## 9. Trip-invitation journey

1. An organizer invites User B. Current state is represented by invitation and participant RSVP records.
2. The invitee can discover the action in Home Needs You, Trips/Mine invitation treatment, Trip Detail, and an Activity-backed Notifications deep link.
3. Home offers Decline and Accept/Going. Trip Detail owns the full current participation context and may support Interested as an additional state.
4. The organizer sees the invitee’s participation state on Trip Detail rather than as an unresolved action for the organizer.
5. A Going response makes the participant active; Interested is also an active participation state but remains distinct. Decline is terminal for the current invitation response.
6. Existing tests cover token expiry/inactivity, repeated acceptance, cross-account protection, participant reconciliation, recipient targeting, and reusable/permanent invite semantics.
7. The in-app Activity type for invite decline exists. Prior push audit evidence found the outbound `trip.invite.declined` event registered but not emitted, demonstrating channel divergence.

## 10. Join-request journey

1. User B requests to join an eligible trip. Canonical action state is a request-type trip `Invitation`.
2. The organizer sees the request in Home Needs You, Trip Detail People, and Notifications through a `join_request_received` Activity. The requester sees their contextual pending state.
3. Home and Trip Detail both support Approve/Accept and No/Decline.
4. Approval updates participant state and records RSVP transition history; the requester receives a `join_request_accepted` Activity.
5. Rejection terminates the request; the requester receives `join_request_declined`, which has no action link.
6. Focused tests confirm exact join-request push title/body/deep link, recipient targeting, duplicate/accepted/self-request suppression, fallback resort metadata, and no direct OneSignal call.
7. Owner-only authorization remains authoritative. No evidence showed join requests exposed to unrelated users.

## 11. Informational-notification journey

**Representative event: trip location change.**

1. The organizer changes an active trip’s location.
2. Relevant recipients receive a `trip_location_changed` Activity with resort metadata; outbound messaging is separately registered.
3. Notifications renders “Trip location changed to …” with a Trip Detail deep link.
4. Opening Notifications records the page-view timestamp only. The Activity remains in the latest-50 history.
5. The event needs no response. Trip Detail owns the current location.
6. If the trip later becomes terminal or is deleted, the notification route omits the trip-backed Activity to avoid a stale live link.

This is historical/contextual coexistence: Activity records that the change happened; Trip Detail owns what is true now.

## 12. Cross-surface resolution findings

- Home actions are designed around canonical unresolved state and include inline status regions.
- Friends remains the richest social action destination for accept, decline, withdraw, suggestion, and search context.
- Trip Detail remains the richest trip action destination for invitation, RSVP, organizer, join-request, and participant context.
- Notifications accepts friend requests directly but does not coordinate client-side refresh of the shared Friends badge.
- Server rerender restores consistency because every main projection re-queries canonical state.
- Historical Activity can legitimately remain after an action is resolved. It becomes misleading only when copy or controls still imply that an action is pending.
- Terminal trip filtering prevents stale trip-backed deep links but also removes historical events from the in-app list, so historical retention differs by object lifecycle.

## 13. Badge/count inventory

| Badge/count | Meaning | Source | Unread or unresolved? | Refresh behavior |
|---|---|---|---|---|
| Friends bottom-nav badge | Incoming pending friend requests | Direct `Invitation` count | Unresolved | Server render; can remain stale after inline Notifications accept |
| Friends badge display | Exact through 9, then `9+` | Same count | Unresolved | Server render |
| Home Requests pill/count | Total rows projected into Needs You | Three pending families | Unresolved | Home render and local mutation behavior |
| Home Needs You heading | Number of unresolved requests shown/projected | Needs You projection | Unresolved | Home render |
| Trips Mine invitation attention | Pending trip invitations | Trips projection | Unresolved | Trips render |
| Trips inventory count | Trips ahead excluding invitation attention | Trips projection | Inventory, not attention | Trips render |
| Trip Detail People attention | Owner-only join request/pending people context | Trip Detail projection | Unresolved/contextual | Region refresh/render |
| Notification count | No user-visible global count confirmed | None | Neither | Not applicable |

The strongest semantic choice is Trips separating ordinary inventory from invitation attention. The main inconsistency is that each badge counts a different domain family, while no visual legend explains the distinction.

## 14. Notifications product assessment

Notifications is currently:

- **Primarily an activity history:** chronological Activity rows with relative timestamps and contextual links.
- **Secondarily an action surface:** incoming friend requests can be accepted inline.
- **Not a true inbox:** no per-item read state, folders, dismissal, durable cursor, or cross-device acknowledgement.
- **Not a complete action center:** trip invitations and join requests resolve elsewhere.
- **Not a complete delivery history:** MessageEventLog and push/email delivery are separate and not queried.

It caps Activity at 50 without pagination or load-more. It does not group events. Resolved state is inferred from domain behavior rather than recorded on the Activity. Database exceptions are rolled back and rendered as empty arrays, making an outage indistinguishable from “No notifications yet.”

## 15. Home attention assessment

Home is the broadest unresolved-action summary and is aligned with the locked rule that Home covers what is happening now. Needs You includes all three major action families, provides direct buttons, names the request type, and displays an unresolved count.

The 12-row cap protects density and query cost, but there is no evidence of an overflow affordance in the rendered section itself. Therefore a user with more than 12 unresolved actions may need to discover additional items through Friends, Trips, or Trip Detail.

The action section is meaningfully stronger than normal Home content and uses inline status feedback. This is bounded action summarization, not generic configuration or historical notification history.

## 16. Friends attention assessment

Friends is both the canonical social action destination and a contextual presentation:

- It owns the richest friend-request workflow: incoming, outgoing, accept, decline, withdraw, and suggestion/search context.
- Its bottom-nav badge gives friend requests globally visible attention.
- It does not own trip invitations or join requests.
- Accepted connection history is presented in Notifications/Home rather than retained as an actionable Friends request.

Suggested Friends has explicit loading and retry text, but its dynamic status is not announced through a live region. Friend request buttons are smaller than the app’s 44–48px interaction convention.

## 17. Trips/Trip Detail attention assessment

Trips distinguishes invitation attention from ordinary trip inventory. Trip Detail owns the canonical context for:

- Invitee RSVP and participation status.
- Organizer visibility into invitees and participants.
- Owner-only join-request decisions.
- Participant removal/leave and trip lifecycle controls.
- Planning content and current trip facts.

This contextual ownership is justified because permission and lifecycle rules are trip-specific. Notifications and Home appropriately point into or summarize Trip Detail rather than reproducing its full model.

The Trip Detail invite modal provides loading/error regions, retry, initial search focus, and focus restoration, but lacks Escape close and focus trapping. Several other Trip Detail mutations provide toasts, rollback, or re-enable controls.

## 18. Useful contextual repetition

- A friend request on Home, Friends, Notifications, and the Friends badge: each offers either global discovery, social context, or direct action.
- A trip invitation on Home, Trips, Trip Detail, and Notifications: summary, inventory, canonical context, and event history are distinct jobs.
- A join request on Home and Trip Detail: Home prevents missed action; Trip Detail provides organizer context.
- A trip-change Activity plus updated Trip Detail: one records that a change happened; the other shows current truth.

## 19. Redundant duplication

No repeated item was proven wholly redundant. The closest case is Notifications directly accepting friend requests while Friends and Home already provide richer action handling. Whether that convenience justifies another mutation surface is a product decision, not an established defect.

Repeated wording and independently implemented controls create maintenance cost, but repetition alone is not evidence that a surface should be removed.

## 20. Inconsistent duplication

- Notifications hides an accepted connection row locally but does not refresh the Friends nav badge.
- Notification Activity types and outbound messaging event coverage do not match exactly; a user can receive one channel without the other.
- Terminal trip-backed Activities disappear from Notifications, while non-trip historical events remain.
- Failure feedback is stronger on Home and Trip Detail than on Notifications.
- Trips explicitly separates inventory and attention counts; the shared nav does not expose an equivalent trip attention badge.

## 21. Necessary action persistence

Pending actions should remain visible until canonical state resolves them. Current domain queries provide this behavior across reloads. Multiple surfaces are appropriate when they reduce the chance of missing a consequential request:

- Friend requests: Home + Friends + nav badge.
- Trip invitations: Home + Trips + Trip Detail.
- Join requests: Home + owner’s Trip Detail.

The necessary persistence is domain-state persistence, not repeated Activity creation.

## 22. Historical/contextual coexistence

Connection acceptance, invitation response, join-request decision, and trip changes can remain useful as history after current state has moved on. Activity supports this for active objects. Contextual surfaces should show current truth; Notifications can say what changed.

Current terminal-trip filtering prioritizes avoiding dead links over complete history. That is a coherent safety choice but an unresolved product policy: should the historical message disappear, remain without a link, or move to a durable archive?

## 23. Missing connections

1. Notifications has no explicit boundary between “requires action” and “recent history.”
2. Notification page acknowledgement is invisible and not connected to any user-visible unread marker.
3. Inline friend acceptance does not invalidate the shared nav badge.
4. Notification query failures have no distinct error/retry state.
5. The latest-50 cap has no pagination or indication that older history exists.
6. Home caps unresolved rows without a confirmed “view all remaining actions” path.
7. Outbound message events and in-app Activity types do not form one complete event taxonomy.
8. Dynamic loading/failure feedback is not consistently announced to assistive technology.

## 24. Loading/failure findings

| Finding | Severity | Confidence | Evidence |
|---|---|---|---|
| Notification database failures render empty state | P2 | High; previously audited | Broad exception handling returns empty arrays |
| Notification accept failure silently re-enables row | P2 | High | No message, status, or retry explanation |
| Accepted request leaves Friends nav badge stale | P2 | High | Only the request row is hidden client-side |
| Suggested Friends loading/failure not announced | P2 | High | No status/live-region semantics |
| Notification viewed POST failure is swallowed | P3-level operational concern, included within architecture rather than defect count | High | Empty catch handler |

Home and Trip Detail provide stronger patterns: inline status/error regions, `aria-busy` in several mutations, retry buttons, and rollback/re-enable behavior. The inconsistency, not the existence of asynchronous UI, is the main risk.

## 25. Responsive findings

The templates use a valid viewport declaration, safe-area-aware fixed navigation, and reserved page padding. Trip rows deliberately ellipsize long mountain/status labels to protect layout.

Source-derived risks:

- Home’s large empty-state name uses `white-space: nowrap`; long names can overflow at 360px.
- Trips tabs combine fixed height, labels, inventory counts, and invitation attention without a narrow-width rule.
- Trip ledger dates do not shrink, increasing truncation pressure on long names/statuses.
- Notification and Friends action buttons are approximately 30px high.

Existing responsive integration tests passed in the 144-test focused suite where included indirectly, but this execution did not produce safe isolated browser captures at 360, 390, 430, 768, or 1280. Pixel-level clipping and desktop use of space therefore remain unverified in this report.

## 26. Accessibility/interaction findings

Positive patterns:

- Home’s availability sheet has dialog semantics, inert/hidden background management, Escape handling, focus trapping, and focus restoration.
- Friends preview similarly traps focus and marks background content inert.
- Trip invitation loading includes visible status/error regions and retry.
- Bottom-nav friend badges have descriptive `aria-label` text.

Findings:

- Notification and Friends request actions have undersized touch targets (P2).
- Trip Detail’s invite modal lacks Escape handling and a focus trap (P2).
- Invite/resort search inputs rely on placeholder-only labeling (P2).
- Suggested Friends loading/failure lacks live-region semantics (P2).
- Home connection toast lacks status/live-region semantics and an explicit close control (P2).
- Bottom navigation lacks a navigation landmark/label and active links lack `aria-current` (P3).

This is an interaction review, not WCAG certification.

## 27. Privacy/authorization findings

No unauthorized disclosure was confirmed.

- Friendship visibility requires reciprocal current `Friend` rows; history does not grant access.
- Malformed null-trip request rows are excluded from user-facing request surfaces and mutation routes in passing tests.
- Join requests remain organizer/owner context.
- Pending invitee and participant capabilities are enforced through current trip visibility and lifecycle rules.
- Terminal/deleted trip-backed Activities are filtered to avoid stale or unauthorized deep links.
- Availability and equipment are not included in the reviewed notification projection.

The polymorphic Invitation table increases the importance of exact trip/type/status predicates. Existing tests demonstrate fail-closed handling for a known malformed category.

## 28. Performance/query observations

Focused tests passed with these reliable observations:

- Home Needs You: three family SELECTs when empty; five SELECTs with heavy mixed requests; display capped at 12.
- Notifications avoids actor N+1 through joined loading and preloads referenced trips/resorts in one batch.
- Profile’s shared-shell request badge contributes to a tested seven-SELECT page budget with exactly one invitation SELECT and no Activity SELECT.
- Trip Detail batch projection does not grow with fixture density in the tested scenario.
- Invitation and social projections passed existing bounded-query tests.

Notifications limits Activity to 50 but has no pagination. This bounds server work while silently truncating history. No severe N+1 defect was confirmed. Response timing and browser payload measurements were not repeated in this execution.

## 29. Backlog reconciliation

| Item | Classification | Relationship |
|---|---|---|
| Task #66 (Show push notification status on Profile) | Already tracked / product-IA dependent | Push configuration, not in-app unresolved state |
| Task #67 (Re-prompt after OS-level denial) | Already tracked | Native permission recovery |
| Task #75 (Notify participants of resort/pass changes) | Merged/implemented | Current Activity and messaging registrations exist |
| Task #77 (Account deletion FK violations) | Already tracked, separate | Future history/attention retention must define deletion behavior |
| Cancelled badge/token/opt-out tasks | Stale or partially represented | Cancellation does not prove provider correctness |
| Notification outage visibility | Previously tracked then cancelled | Confirmed P2 remains in current route |
| Pending/failure feedback | Previously identified | Still present in Notifications |
| OneSignal cold-launch opt-out race | Documented, not reproduced | Provider-layer defect outside this in-app execution |
| Missing `friend.pass.changed` Journey and direct-send MEL bypasses | Documented, not reproduced | Delivery architecture inconsistency |
| Read versus unresolved product policy | Product decision required | No current task should be created before ownership decision |

No task or backlog record was created, edited, or reopened during this review.

## 30. Future-state Option A

**Notifications as history; contextual surfaces own actions.**

- Notifications: informational history only.
- Home: bounded unresolved summary.
- Friends: canonical friend-request actions.
- Trips/Trip Detail: canonical trip invitation, RSVP, join, and participant actions.
- Pending actions: remain projections of domain state.
- Badges: explicitly labeled unresolved counts by domain.
- After resolution: contextual action disappears; historical event remains with resolved wording.
- Deep links: always to current contextual owner.
- Navigation: no new destination required.
- Design: separate “Needs You” from “Recent.”
- Engineering: low-to-medium; remove direct mutation from Notifications and standardize projections.
- Migration: none required if page-view acknowledgement remains coarse; optional migration for durable history read markers.
- Benefits: preserves authoritative domain state and current IA.
- Tradeoffs: users must leave Notifications to act; multiple contextual destinations remain.
- Backlog impact: notification failure state and deep-link consistency become higher priority.

## 31. Future-state Option B

**Notifications as a combined history and action inbox.**

- Notifications: sections for unresolved actions and recent history.
- Home: short summary/deep links, not full duplication.
- Friends: social context and secondary action.
- Trips/Trip Detail: full trip context and secondary action.
- Pending actions: projected into a unified inbox from domain state.
- Badges: one global unresolved count, optionally separate unread history count.
- After resolution: action row becomes resolved history or moves sections.
- Deep links: action can resolve inline or open canonical context.
- Navigation: Notifications needs prominent, persistent access.
- Design: explicit Action required, Resolved, and New labels.
- Engineering: medium-to-high due to unified projection, mutation invalidation, and pagination.
- Migration: likely required for durable per-user read/cursor state; domain actions remain canonical.
- Benefits: one discoverable place for everything requiring response.
- Tradeoffs: duplicates complex permission/context logic and risks making Notifications a second domain UI.
- Backlog impact: creates work beyond current push/profile tasks.

## 32. Future-state Option C, if warranted

**Home as the bounded action summary; Notifications remains mixed but secondary.**

- Notifications: lightweight recent history plus limited convenience actions.
- Home: primary cross-domain “Needs You” summary with overflow navigation.
- Friends: complete friend workflow.
- Trips/Trip Detail: complete trip workflow.
- Pending actions: domain projections, with Home as the primary aggregator.
- Badges: domain-specific unresolved counts; Home may display aggregate total.
- After resolution: Home updates immediately; history remains in Notifications.
- Deep links: Home buttons resolve simple cases; complex cases open context.
- Navigation: preserve current primary nav.
- Design: strengthen overflow and urgency rules without turning Home into configuration.
- Engineering: medium; expand invalidation and overflow handling around existing Needs You.
- Migration: not required unless adding durable read/history state.
- Benefits: evolves the strongest current behavior with minimal IA disruption.
- Tradeoffs: Home can become dense; action discovery depends on visiting Home.
- Backlog impact: requires Home-specific action-refresh and dense-state work.

## 33. Future-state Option D, if warranted

**Dedicated Attention destination with domain-backed projections.**

- Notifications: historical event stream.
- Home: concise current summary.
- Friends: social action context.
- Trips/Trip Detail: trip action context.
- Pending actions: dedicated cross-domain Attention projection, always resolved through domain commands.
- Badges: one unresolved Attention count; unread history remains separate.
- After resolution: item leaves Attention and may remain in Notifications history.
- Deep links: directly to the owning contextual state.
- Navigation: requires a new destination or replacement of an existing entry.
- Design: two explicit concepts—To do and Updates.
- Engineering: high; new routing, projection, navigation, authorization, and consistency contracts.
- Migration: likely required for durable user-level presentation/read/dismissal metadata, though unresolved truth remains in current domain tables.
- Benefits: strongest conceptual separation of “do” from “know.”
- Tradeoffs: adds a screen and navigation burden not currently proven necessary.
- Backlog impact: substantial new product and implementation program.

## 34. Decisions required from product owner

**DECISION 1 — What is Notifications primarily for?**

Context: It currently mixes Activity history with direct friend-request action.

BaseLodge example: “Richard accepted your request” is history; “Sarah wants to connect” is unresolved.

A. History and updates only.  
B. Combined history and action inbox.  
C. Secondary mixed surface while Home/context owns primary action.

Implications: This determines every downstream decision about controls, state, badges, and navigation.

**DECISION 2 — Where is the primary cross-domain pending-action summary?**

Context: Home already aggregates three action families, but contextual pages also own them.

BaseLodge example: one user has a friend request, a trip invitation, and a join request to approve.

A. Home Needs You.  
B. Notifications.  
C. A dedicated Attention destination.  
D. No cross-domain owner; rely on contextual destinations and badges.

Implications: This sets discovery, density, and global navigation requirements.

**DECISION 3 — Should Notifications allow direct resolution?**

Context: It currently accepts friend requests but not trip or join requests.

BaseLodge example: a user can accept a friend in Notifications but must open Trip Detail for an invitation.

A. No; deep-link to canonical context.  
B. Yes for simple actions only.  
C. Yes consistently for all supported pending actions.

Implications: More inline resolution increases convenience and consistency obligations.

**DECISION 4 — What should “read” mean?**

Context: Current acknowledgement only says the page was displayed in one session.

BaseLodge example: opening Notifications does not resolve an invitation.

A. Keep coarse page-view acknowledgement.  
B. Add durable per-user read cursor.  
C. Add per-item read state.  
D. Remove read language/state and focus only on unresolved actions.

Implications: Durable cursors/items can require schema and migration work.

**DECISION 5 — What should badges represent?**

Context: Current badges count domain-specific unresolved actions, not unread notifications.

BaseLodge example: Friends shows pending requests while Trips separately shows invitations.

A. Unresolved actions only.  
B. Unread updates only.  
C. Separate visual badges for unresolved and unread.  
D. Keep domain-specific meanings with explicit labels.

Implications: Mixing unread and unresolved will remain ambiguous unless visually separated.

**DECISION 6 — What happens to history after action resolution?**

Context: Activity can remain after resolution, but terminal trip-backed events disappear.

BaseLodge example: an accepted join request may remain in Recent; a cancelled trip event may vanish.

A. Retain all history with resolved wording and safe links.  
B. Retain only informational outcomes.  
C. Remove action-origin events after resolution.  
D. Keep current active-object filtering.

Implications: Retention affects trust, privacy, deletion, and migration policy.

**DECISION 7 — How should Home’s 12-item cap behave?**

Context: The cap controls density, but overflow discovery is not explicit.

BaseLodge example: a trip organizer with many requests sees only the first 12 cross-domain items.

A. Show a View all path to the chosen action owner.  
B. Paginate/expand within Home.  
C. Prioritize by urgency and rely on contextual badges for the remainder.

Implications: This determines whether Home is a summary or complete work queue.

**DECISION 8 — Should friend requests remain actionable in Notifications?**

Context: This is the only direct action family on the page and currently causes stale nav state.

BaseLodge example: accepting there hides the row but leaves the Friends badge until rerender.

A. Remove the action and deep-link to Friends.  
B. Keep it and implement shared invalidation/feedback.  
C. Expand Notifications to support all action families consistently.

Implications: This is the first concrete test of the selected Notifications role.

**DECISION 9 — Should outbound delivery and in-app history share one event taxonomy?**

Context: Activity types and message-event registrations have different coverage and purposes.

BaseLodge example: invite decline exists as Activity but prior audit found the push event registered and not emitted.

A. Keep separate taxonomies with documented mappings.  
B. Create one canonical event taxonomy with channel projections.  
C. Unify only high-value user-visible events.

Implications: Unification improves consistency but increases migration and operational scope.

**DECISION 10 — Does attention require a new navigation destination?**

Context: Notifications is secondary today; primary nav is already full.

BaseLodge example: adding Attention could displace Mountains or require another access pattern.

A. No; preserve Home/contextual ownership.  
B. Promote Notifications.  
C. Add a dedicated Attention destination.  
D. Use a global header affordance without changing bottom nav.

Implications: Navigation should follow the chosen ownership model, not precede it.

## 35. Recommended decision order

1. Decide Notifications’ primary role.
2. Decide the primary cross-domain pending-action owner.
3. Decide whether direct resolution belongs in Notifications.
4. Define read separately from resolved.
5. Define badge semantics.
6. Define historical retention after resolution and terminal object changes.
7. Decide Home overflow behavior.
8. Decide friend-request action placement as the first concrete application.
9. Decide event-taxonomy relationship across in-app and outbound systems.
10. Decide navigation only after ownership is settled.

## 36. Implementation dependencies after decisions

- A shared vocabulary for informational, actionable, contextual, historical, and ephemeral items.
- A canonical event/action mapping owned by product and engineering.
- Explicit authorization rules for each projection and deep link.
- A mutation invalidation contract across Home, nav, Friends, Trips, Trip Detail, and Notifications.
- Error, retry, busy, success, and assistive-announcement interaction standards.
- Pagination/overflow policy for both history and pending actions.
- Retention/deletion policy coordinated with account deletion work.
- Channel mapping between Activity, message events, outbox/MEL, push, and email.
- Responsive acceptance fixtures for dense and long-label states.

No implementation should begin until Decisions 1–6 are answered.

## 37. Migration implications

Option A and much of Option C can continue deriving unresolved actions from current domain state and may require **no database migration**. A durable read cursor would need a small user/device acknowledgement model.

Options B and D likely require a durable attention projection or per-user presentation state. A safe migration would need:

- Backfill policy for existing Activity rows.
- A rule that current domain state, not migrated notifications, remains authoritative.
- Idempotent event/projection keys.
- Retention and account-deletion behavior.
- Cross-device read semantics.
- Terminal/deleted object handling.
- Rollback that does not lose canonical invitations, participants, or friendship state.

Unifying Activity and outbound message taxonomies would be a separate migration/program. Existing histories must not be used to reconstruct or grant current authorization.

## 38. Beginning vs ending Git/worktree proof

Beginning state:

- Branch: `main`
- HEAD: `46125d7bfc0aeda055f01f5629c5198961417a24`
- origin/main: `3c7e98d8839aec8463c502a3f6d64e871fafe83d`
- Ahead/behind from `origin/main...HEAD`: 0 behind, 12 ahead
- Tracked diff: empty
- `.replit` SHA-256: `8f07738f655a084bacfef1aeef032f4a175af360dcff14714ffabe6ee801ed34`
- Initial untracked file: the user-provided Task #571 instruction under `attached_assets/`
- Authorized report path: absent

Ending verification is recorded after report creation and cleanup. The expected intentional delta is this report plus the pre-existing user attachment. No application, test, migration, workflow, or `.replit` file is authorized to differ.

Verified ending state:

- Branch, HEAD, origin/main, and ahead/behind are unchanged.
- Tracked diff remains empty.
- `.replit` hash and status are unchanged.
- The only untracked files are the pre-existing user instruction attachment and `reports/bl571-attention-architecture-review.md`.
- All Task #571 temporary SQLite files, captures, browser profiles, caches, measurements, scripts, and `/tmp` audit records were removed.

## 39. Coverage limitations

- No Development or Production database, real user data, live analytics, or external provider was accessed.
- No push, email, SMS, analytics, or real notification was sent.
- Repository test fixtures force disposable in-memory SQLite even when a `/tmp` SQLite URL is supplied.
- Focused coverage was 144 passing tests, not the full test suite.
- No safe isolated browser capture was produced at the five required widths. Responsive conclusions are based on source and existing tests, so pixel-level behavior remains a material limitation.
- Provider defects and delivery telemetry are cited from existing audits rather than reproduced.
- Response timing and payload measurements were not rerun.
- Dead historical routes were not treated as active surfaces unless current code/tests showed an effect.

## 40. Final verdict

BaseLodge already has a defensible foundation: canonical domain state owns unresolved actions, Home provides a bounded cross-domain summary, and Friends/Trip Detail own contextual resolution. The architecture does not need a new source of truth for pending actions.

The unresolved product problem is ownership and communication. Notifications looks like history but contains one direct action family; “viewed” is recorded without visible unread semantics; domain badges are unresolved counts with different meanings; and client-side mutations do not always refresh every projection. Outbound delivery is a separate system and should not be mistaken for in-app history.

The product owner must first decide whether Notifications is history, an inbox, or a secondary mixed surface, then decide where cross-domain pending actions and badge semantics belong. Only after those decisions should BaseLodge address projection consistency, read state, retention, navigation, or schema changes.

PENDING ACTIONS / NOTIFICATIONS REVIEW COMPLETE — PRODUCT DECISIONS REQUIRED