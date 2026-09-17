# Account-Deletion Message Retention Investigation

**Scope:** Current hard-delete behavior for messaging-related data

**Method:** Read-only source, migration, route, template, and test inspection
**Policy status:** No new retention policy is selected or implemented by this report. The existing public privacy statement requires reconciliation with current behavior.

## Executive summary

BaseLodge does not currently have a direct-message conversation, chat thread, message attachment, or in-app inbox-message model. User-facing notifications are `Activity` rows, trip-planning collaboration is stored as `SkiTripPlanningPost`, and outbound push/automation delivery is recorded in `MessageEventLog` and the durable `MessageOutbox`.

**FACT — Account deletion succeeds today only because the route performs a long, ordered cleanup before deleting the `user` row.** It deletes many non-nullable user references, anonymizes selected audit references, flushes to expose remaining foreign-key failures, and then deletes the user. PostgreSQL cascades are not the primary deletion mechanism.

**FACT — No current messaging reference identified in this investigation should block the existing route when its cleanup completes successfully.**

* `Activity` rows where the account is actor or recipient, plus the user's `EmailLog`, `Event`, `PushDeviceToken`, `InviteShareEvent`, and authored `SkiTripPlanningPost` rows, are explicitly deleted.
* `MessageEventLog.actor_user_id` and `recipient_user_id` have nullable, default `NO ACTION` foreign keys. The route explicitly sets both to `NULL`; without that step they can block deletion.
* `MessageOutbox.actor_user_id` and `recipient_user_id` use PostgreSQL `ON DELETE SET NULL`, so they do not block the final user delete. The route does not explicitly update or delete them.
* `MessagingReplayEvent` has no direct user foreign key and therefore does not block user deletion.
* Delivery-policy and worker-heartbeat tables have no user foreign keys.
* Planning posts and invite-share events have database cascades, but the route explicitly deletes them because SQLAlchemy relationships can try to null their non-nullable user columns before PostgreSQL receives the user delete.

**FACT — Some activity records and durable outbound evidence survive account deletion.** `Activity` rows survive when the deleted user is referenced only inside unconstrained JSON or through a deleted trip ID rather than as actor/recipient. `MessageEventLog` rows survive with actor and recipient foreign keys cleared. `MessageOutbox` rows survive with those foreign keys cleared by PostgreSQL. Replay, policy, and worker records survive.

**RISK — Surviving rows are not necessarily anonymous.** Grouped availability-overlap activities can retain the deleted user's first name, last name, user ID, trip ID, resort ID/name, state, and country inside `extra_data.friends_data`, plus duplicated friend/trip/resort ID arrays and date/location groups. Other retained records may hold message title/body, event and occurrence identifiers, polymorphic object IDs, payload/evidence IDs, routing metadata, provider message IDs, error text, replay/operator fields, release identifiers, and timestamps.

**RISK — Current retention conflicts with the plain-language privacy statement.** The published privacy policy says a user can request deletion of their account “and all associated data.” Retained Activity/MEL/outbox records, user-identified PostHog history, external-provider records, logs, and analytics events may be “associated data” even after direct foreign keys are cleared. Privacy/legal owners must interpret that promise and either align implementation or clarify the policy; this report does not make that determination.

**FACT — Pending outbox rows become non-deliverable after recipient deletion, but deletion does not cancel or terminalize them.** Their `recipient_user_id` becomes `NULL`; worker safety/provider code requires a live recipient. Depending on timing and policy, they can remain pending until claimed and suppressed or can remain queued while claims are paused. A provider call already accepted before deletion cannot be recalled by deleting local rows.

**PRODUCT DECISION — BaseLodge must decide whether participant-authored planning content, grouped activity content, and outbound operational evidence should be erased, retained with anonymized authorship, presented as “Deleted User,” or reduced to limited operational metadata.** Current behavior deletes authored planning content and direct actor/recipient activities, can retain generically visible grouped activities with nested identity, and retains delivery evidence.

## 1. Architecture in plain language

### 1.1 User-facing notification history

The `/notifications` page is built from `Activity` rows. Each row identifies an actor and recipient and may point indirectly to a trip or user through `object_type`, `object_id`, `subject_type`, `subject_id`, and `extra_data`.

Activity producers use `extra_data` for:

* trip-location changes: `resort_name`;
* trip-pass changes: `pass_display`;
* carpool offers: seat count and mountain name;
* friend-suggestion batches: inserted suggestion count; and
* grouped friend-trip/availability overlaps: `friend_ids`, `trip_ids`, overlap dates, `resort_ids`, state/country arrays, and `friends_data`. Each `friends_data` item contains `friend_id`, `trip_id`, `resort_id`, resort name, state, country, first name, and last name.

On account deletion, every activity where the user is actor or recipient is explicitly deleted. That does **not** find a deleted user who appears only as a non-actor member of a grouped `friends_data` list. A multi-friend availability-overlap row can therefore survive for another recipient and retain the deleted user's denormalized name and identifiers.

Activities can also survive with an `object_id`, `subject_id`, `trip_ids`, or nested `friends_data.trip_id` pointing to a trip removed by the account-deletion route when both actor and recipient are surviving users. The dedicated trip-cleanup helpers can delete trip/object or grouped `trip_ids` references, but account deletion bulk-deletes owned trips without calling those helpers.

The current notifications renderer does not read `friends_data`, so the deleted member's nested identity is not shown. However, a surviving grouped availability row is still returned and falls through to generic “Update from {live actor}” copy because it has no dedicated rendering branch. The surviving participant can therefore continue to see a generic notification backed by JSON that still contains the deleted member.

Separately, the renderer skips a trip-object activity when the trip no longer exists. Those deleted-trip-backed rows are hidden from the current page but remain in PostgreSQL. In both cases, unconstrained IDs and JSON remain available to future/admin code.

### 1.2 Legacy event and email bookkeeping

`Event` records high-signal user events with a JSON payload. `EmailLog` tracks email suppression/deduplication and can reference an `Event`.

The deletion route deletes the user's `EmailLog` rows, clears other users' `EmailLog.source_event_id` references to the deleting user's events, and then deletes those events. Current messaging documentation and the admin dashboard identify this table-backed email path as inactive for current social/invite delivery.

Two live SendGrid flows bypass `Event` and `EmailLog`:

* password reset sends the account email, first name, and a tokenized reset URL to the user; and
* feedback sends the user's full name, email, BaseLodge user ID, timestamp, and free-text feedback to an administrator.

The password-reset route also writes the recipient email address to application logs on success. Account deletion does not delete SendGrid records, recipient/admin mailbox copies, or historical application logs. Their retention is external to the database transaction and was not verified.

### 1.3 Push-device delivery

`PushDeviceToken` stores iOS APNs and Android FCM device tokens tied to a user. The deletion route explicitly deletes them.

BaseLodge has three provider paths:

* centralized product messaging through OneSignal, targeting the BaseLodge integer user ID as the provider `external_id`;
* direct APNs delivery per iOS device token; and
* direct FCM delivery per Android device token.

Direct APNs/FCM routes are currently admin test/broadcast functions. They write MEL rows with the local token-row ID, platform, source route, rendered title/body, delivery result, and provider/error data. Deleting `PushDeviceToken` removes the raw local token, but retained MEL payloads still contain the now-orphaned token-row ID.

Provider functions send title, body, and routing data and return provider result identifiers/errors locally. OneSignal, Apple, Firebase, and SendGrid retention or deletion behavior is outside this repository and was not verified here.

### 1.4 Canonical outbound event ledger

`MessageEventLog` (MEL) records outbound event attempts and outcomes. It can contain direct user foreign keys plus rendered title/body, payload JSON, object identifiers, occurrence ID, provider message ID, error text, retry lineage, and timestamps.

Deletion preserves MEL rows but explicitly clears direct actor/recipient user foreign keys.

### 1.5 Durable outbox, worker, and replay evidence

`MessageOutbox` is a provider-bound work item. It stores direct actor/recipient references, event identity, object identity, narrowly allowlisted context, typed evidence IDs, state/attempt/lease data, provider identifiers/errors, final MEL linkage, replay lineage, operator fields, release identifiers, and timestamps.

The worker:

1. claims a pending/retryable row;
2. reruns recipient and object safety checks;
3. commits a `provider_phase=started` boundary;
4. calls the provider;
5. finalizes as accepted, suppressed, retryable, dead-letter, or delivery-unknown.

Deletion does not explicitly cancel outbox work. PostgreSQL clears direct user IDs with `ON DELETE SET NULL`.

`MessagingReplayEvent` records operator replay evidence between two outbox rows. Policy tables record per-event delivery controls and their operator audit history. Worker heartbeat rows contain operational counters and release/worker identity, not application-user references.

### 1.6 Trip-planning collaboration

`SkiTripPlanningPost` contains participant-authored category, body, optional URL, author, and trip. It is visible to the trip owner and accepted participants.

Deletion removes:

* every post authored by the deleting user, including posts on surviving trips; and
* every post on a trip owned by the deleting user, including posts authored by surviving users.

There is no generic “Deleted User” planning-post presentation today because the content itself is removed.

### 1.7 Invite-sharing evidence

`InviteShareEvent` records a share/copy action, token type, optional token-row ID, optional raw token fallback, source, user agent, and timestamp. It represents share intent, not confirmed delivery.

Deletion explicitly removes the user's rows. `token_id` is not a database foreign key despite documenting that it may refer to either invite-token table.

### 1.8 Concepts verified absent

Repository searches and the inspected architecture documents found no:

* direct-message or chat-message model;
* conversation/thread membership model;
* message attachment/blob model;
* read receipt for direct messages;
* retained in-app message transcript.

The notification page is an activity feed, not a conversation store. OS/provider push delivery is not copied into a user-visible transcript.

### 1.9 External analytics and logs related to messaging

The server-side PostHog wrapper sends the BaseLodge integer user ID as `distinct_id` whenever `ph_analytics.track` receives a user. It recursively removes prohibited property keys such as names, email, friend IDs, free-text body/content/message/note fields, and raw tokens, but the distinct user ID and allowed event properties remain.

Messaging/invite-adjacent PostHog events include:

* `invite_generated`: user ID plus `source=invite_page`;
* `invite_share_intent`: user ID plus token type, share action, and source;
* `friend_connected`: user ID plus connection source and whether it was the first friend; and
* `trip_created`: user ID plus trip/resort/location metadata, group status, whether a friend was invited, trip length, and source.

The invite-share route additionally logs the user ID, token type, action, and source to application logs. The PostHog transport itself logs successful/failed captures with event name and distinct ID.

The “Open to Ski” availability-image sharing workflow also sends PostHog telemetry for `availability_share_opened`, `availability_share_generated`, `availability_share_started`, `availability_share_succeeded`, `availability_share_cancelled`, and `availability_share_failed`. Unlike the events above, the server calls PostHog with `user_id=None`. The transport uses a valid cookie-derived anonymous ID when available; if it is absent or invalid, it generates a fresh `anonymous_event:<uuid>` identity for that event. The endpoint accepts only allowlisted `format=png`, delivery mode (`share` or `download`), and bounded error-code properties; it rejects dates, the generated image, and extra/private properties. The repository does not establish whether PostHog has linked a valid cookie-derived browser ID to the authenticated numeric identity through prior browser identification or aliasing.

Browser-side Umami messaging-adjacent events include:

* `trip_planning_post_created`, with planning category and whether a link was included; and
* `trip_invite_shared`, with the share method; and
* `push_preference_updated`, with the new enabled state.

`blTrackProjectEvent` passes these properties to `window.umami.track`. The event properties inspected do not include a BaseLodge user ID, post body, link URL, or invite token, but provider-side visitor/session correlation and retention could not be verified from this repository.

Browser PostHog initialization identifies authenticated users with their numeric BaseLodge user ID and stores an authenticated-user marker in local storage. Generic logout/reset logic can reset the browser client, but the account-deletion transaction does not call a PostHog person/event deletion API or an Umami deletion API.

Account deletion therefore has no effect on previously submitted PostHog/Umami records or historical application logs. These stores cannot block the local database delete.

## 2. Complete data and foreign-key matrix

`NO ACTION` below means no `ON DELETE` action was declared in the migration-managed PostgreSQL foreign key. Such a reference blocks deletion unless the route removes or nulls it first.

| Data / field | PostgreSQL FK behavior | Explicit route behavior | State after deletion | Residual identity or content | Presentation / blocker conclusion |
|---|---|---|---|---|---|
| `Activity.actor_user_id`, `recipient_user_id` | Non-null user FKs; `NO ACTION` | Delete rows where user is actor or recipient | Matching rows deleted | None from those matching rows | Would block without cleanup. Does not catch identity stored only in JSON. |
| Activity `object_type`, `object_id`, `subject_type`, `subject_id` | Polymorphic/unconstrained IDs | No general scrub; matching actor/recipient rows deleted | Can survive when both endpoints are other users | Deleted user/trip/invitation/participant IDs can remain depending on producer | Trip-object rows are skipped by current notifications rendering when the trip is gone, but remain stored. |
| Activity simple `extra_data` producers | JSON, no FK | No field-level scrub | Survives if actor/recipient survive | `resort_name`, `pass_display`, carpool seat/mountain, suggestion count | Usually no direct user identity, but can retain deleted-trip context. |
| Grouped availability Activity `extra_data.friend_ids`, `trip_ids`, `resort_ids`, dates, state/country | JSON, no FK | No membership scrub during account deletion | Survives when deleted user is only a non-actor grouped member | Deleted user ID and owned-trip/resort/location/date correlation remain | Does not block deletion; current renderer ignores these fields. |
| Grouped availability Activity `extra_data.friends_data[]` | JSON, no FK | No nested scrub during account deletion | Survives when deleted user is only a non-actor grouped member | `friend_id`, first/last name, `trip_id`, `resort_id`, resort name, state, country | Direct residual identity in PostgreSQL; hidden rather than erased in current notifications UI. |
| `Event.user_id` | Non-null user FK; `NO ACTION` | Delete user's events | Deleted | `payload` removed with row | Would block without cleanup. |
| `EmailLog.user_id` | Non-null user FK; `NO ACTION` | Delete user's rows | Deleted | None from those rows | Would block without cleanup. |
| `EmailLog.source_event_id` | Nullable event FK; `NO ACTION` | Null references to deleted user's events | Survives for other recipients with source cleared | Email type, send time/count, environment | Does not block after explicit nulling. |
| SendGrid password-reset delivery | External; no local delivery-row FK | No external cleanup | SendGrid/mailbox/provider-dependent | Recipient email, first name, tokenized reset URL; success log includes email | Cannot block local deletion; external copy and historical log can remain. |
| SendGrid feedback delivery | External; no local delivery-row FK | No external cleanup | SendGrid/admin-mailbox-dependent | Full name, email, user ID, timestamp, free-text feedback | Cannot block local deletion; directly identifiable external copy can remain. |
| `PushDeviceToken.user_id` | Non-null user FK; `NO ACTION` | Delete user's tokens | Deleted | Local token removed | Would block without cleanup; provider-side alias state is not verified. |
| Direct APNs/FCM MEL token reference | `payload_json.token_id` is plain JSON, not an FK | No redaction | MEL row survives | Orphaned local token-row ID, platform, source route, title/body, result/error; APNs/FCM provider records external | Does not block deletion; remains correlatable operational evidence. |
| `MessageEventLog.actor_user_id`, `recipient_user_id` | Nullable user FKs; `NO ACTION` | Explicitly set matching fields to `NULL` | Row survives, direct user FKs cleared | See MEL fields below | Can block without explicit nulling; current route prevents it. |
| MEL `payload_json`, `message_title`, `message_body` | No FK | No redaction | Survives | Names, content, user/trip/invite IDs may remain | Operator/admin queries can access rows; current event-list template does not show these fields. |
| MEL `object_type`, `object_id`, `occurrence_id` | No FK | No redaction | Survives | Correlation to user, trip, invitation, share, or batch may remain | Indirect re-identification risk. |
| MEL `provider_message_id`, `error_message`, status, timestamps | No FK | No redaction | Survives | Provider correlation and operational history | Admin surfaces status/provider; provider ID/error are retained in DB. |
| MEL `parent_mel_id` | Nullable self-FK; `NO ACTION` | No change | Survives | Retry lineage | No user-delete blocker because target MEL survives. |
| `MessageOutbox.actor_user_id`, `recipient_user_id` | Nullable user FKs; `ON DELETE SET NULL` | No explicit cleanup | Row survives, PostgreSQL clears direct IDs | See outbox fields below | Does not block user deletion at DB level. |
| Outbox `event_name`, `occurrence_id`, `object_type`, `object_id` | No user FK | No redaction | Survives | Logical event/object correlation | Indirect identity may remain. |
| Outbox `context_json` | No FK; application allowlist limits to scalar routing values | No redaction | Survives | Route/deep link/template/locale/badge/sound/collapse/object identifiers | Lower-content surface than MEL, but still correlatable. |
| Outbox `evidence_ids_json` | No FK; typed strings | No redaction | Survives | May include `subject_user_id:<id>`, invitation, planning post, share, suggestion, resort, lifecycle, RSVP, or policy IDs | Explicit deleted-user ID can survive as text. |
| Outbox provider/status/lease/error fields | No FK | No change | Survives | Provider message ID, bounded sanitized error, attempt and timing metadata | Operational/admin evidence remains. |
| Outbox replay/terminal/operator/release fields | Self-FK or no FK | No change | Survives | Replay reason, operator identity, terminalization reason, release SHAs | Operational identity, not necessarily end-user identity. |
| Outbox `final_event_log_id` | Nullable unique MEL FK; `NO ACTION` | No change | Survives because MEL survives | Links two retained records | Does not block user deletion. |
| Outbox `replay_of_outbox_id` | Nullable self-FK; `NO ACTION` | No change | Survives | Delivery lineage | Does not block user deletion. |
| `MessagingReplayEvent.source_outbox_id`, `target_outbox_id` | Non-null outbox FKs; `NO ACTION` | No change | Survives | Links retained outbox records; reason, notes, audit identity | No direct user blocker. Would constrain future outbox deletion. |
| `MessagingDeliveryPolicy*` | Policy-event FK, no user FK | No change | Survives | Operator reason/audit identity, event configuration | No user blocker. |
| `MessagingWorkerHeartbeat` | No user FK | No change | Survives | Worker/release identity, queue counters, error category | No user blocker. |
| `SkiTripPlanningPost.user_id` | Non-null user FK; `ON DELETE CASCADE` | Explicitly delete authored posts | Deleted | Body/link/category removed | Explicit cleanup avoids ORM null-before-delete failure. |
| `SkiTripPlanningPost.trip_id` | Non-null trip FK; `ON DELETE CASCADE` | Explicitly delete all posts on owned trips before bulk trip delete | Deleted for owned trips | Surviving-user content on deleted trip is also erased | Bulk trip delete bypasses ORM cascade behavior; explicit cleanup is authoritative. |
| `InviteShareEvent.user_id` | Non-null user FK; `ON DELETE CASCADE` | Explicitly delete user's rows | Deleted | Share metadata and raw fallback token removed | Explicit cleanup avoids ORM null-before-delete failure. |
| `InviteShareEvent.token_id` | No FK | Row deleted for user | Deleted | None | Cannot independently block invite-token deletion. |
| `InviteToken.inviter_id` | Non-null user FK; `NO ACTION` | Delete tokens created by user | Deleted | Bearer token removed | Would block without cleanup. |
| `TripInviteToken.inviter_user_id` | Non-null user FK; `ON DELETE CASCADE` | Explicitly delete tokens created by user | Deleted | Bearer token removed | DB cascade exists; explicit route cleanup also covers ORM/bulk behavior. |
| `TripInviteToken.trip_id` | Non-null trip FK; `ON DELETE CASCADE` | Delete rows for owned trips before bulk trip delete | Deleted for owned trips | Token removed | Avoids bulk-trip-delete FK issue. |
| `Invitation.sender_id`, `receiver_id` | Non-null user FKs; `NO ACTION` | Delete sent/received invitations | Deleted | Relationship state removed | Would block without cleanup. |
| `Invitation.trip_id` | Nullable trip FK; `NO ACTION` | Delete invitations on owned trips | Deleted for owned trips | Invite history removed | Would block owned-trip deletion without cleanup. |
| `FriendSuggestion` three user roles | Non-null user FKs; `NO ACTION` | Delete rows containing user in any role | Deleted | Derived suggestion history removed | Would block without complete three-role cleanup. |
| `SuggestionPushCooldown` two user roles | Non-null user FKs; `NO ACTION` | Delete rows containing user | Deleted | Delivery cooldown removed | Would block without cleanup. |
| `FriendCooldown` pair roles | Non-null user FKs; `ON DELETE CASCADE` | No dedicated route delete found | Deleted by PostgreSQL | Pair cooldown removed | Does not block at DB level. |
| `SkiTripRsvpTransition.user_id` | Non-null user FK; `ON DELETE CASCADE` | Delete rows where user is subject | Deleted | Subject history removed | Does not block; explicit privacy deletion. |
| `SkiTripRsvpTransition.actor_user_id` | Nullable user FK; `ON DELETE SET NULL` | Null actor on surviving subjects | Survives anonymized | Status transition, source, trip/user subject remain | No blocker; actor identity removed. |
| `SkiTripLifecycleEvent.actor_user_id` | Nullable user FK; `ON DELETE SET NULL` | Null actor on surviving trips | Survives anonymized | Trip event type/source/time remain | No blocker. |
| `FriendConnectionEvent` subject pair | Non-null user FKs with cascade semantics in migration | Delete any pair involving user | Deleted | Relationship history removed | No retained deleted-user pair history. |
| `FriendConnectionEvent.actor_user_id` | Nullable, nullification semantics | Null actor on unrelated surviving pair events | Survives anonymized | Pair and transition remain | No blocker. |
| `WishlistResortEvent.user_id` | Subject FK with cascade semantics | Delete user's subject rows | Deleted | Wishlist subject history removed | No blocker. |
| `WishlistResortEvent.actor_user_id` | Nullable, nullification semantics | Null actor on other subjects | Survives anonymized | Other subject/resort transition remains | No blocker. |
| `SkiTrip.user_id` | Non-null user FK; `NO ACTION` | Delete owned trips after child cleanup | Deleted | Trip and its planning content removed | Would block without ordered cleanup. |
| `SkiTrip.created_by_user_id` | Nullable user FK; `NO ACTION` | Null on surviving trips organized for someone else | Survives anonymized | Trip still identifies owner/participants, not deleted organizer | Would block without cleanup. |
| `SkiTripParticipant.user_id`, `TripGuest.user_id` | Non-null user FKs; generally `NO ACTION` | Delete user's participation rows | Deleted | Attendance/invite state removed | Would block without cleanup. |
| `SkiDay.user_id` | Non-null user FK with cascade in current schema | Explicitly delete user's rows | Deleted | Confirmed ski history removed | Explicit privacy deletion. |
| `SkiDay.trip_id` | Nullable trip FK with `SET NULL` in current schema | User's rows already removed | Other users' rows can survive trip deletion without trip link | Ski-day history remains for other users | No user blocker. |
| `User.invited_by_user_id` | Nullable self-FK; `NO ACTION` | Null on users invited by deleting user | Survives anonymized | Invite attribution removed | Would block without cleanup. |
| PostHog `invite_generated` | External analytics; user ID is `distinct_id` | No external cleanup | Provider-dependent | BaseLodge user ID and invite-page source | Cannot block local deletion; directly user-correlated external history remains unless separately erased. |
| PostHog `invite_share_intent` | External analytics; user ID is `distinct_id` | Local `InviteShareEvent` deleted, PostHog untouched | Provider-dependent | BaseLodge user ID, token type, action, source | Cannot block deletion; duplicates locally deleted share intent in an external store. |
| PostHog `friend_connected` / `trip_created` | External analytics; user ID is `distinct_id` | No external cleanup | Provider-dependent | Connection source/first-friend status; trip/resort/location/group/invite/length/source metadata | Cannot block deletion; social/invite context remains user-correlated. |
| PostHog `availability_share_*` | External analytics; server supplies no user ID and uses cookie-derived anonymous ID when valid | No external cleanup | Provider-dependent | Open/generated/started/succeeded/cancelled/failed state; PNG format; share/download mode; bounded error code | Not directly user-ID-correlated in the server payload, but provider-side linkage to the authenticated person is unverified. Cannot block deletion. |
| Invite-share application log | Log record; no FK | No historical-log cleanup | Log-retention-dependent | User ID, token type, action, source; failures can include exception context | Cannot block deletion; directly identifiable operational copy remains. |
| PostHog transport log | Log record; no FK | No historical-log cleanup | Log-retention-dependent | Event name, distinct user ID, success/failure and error | Cannot block deletion; external-event correlation remains in logs. |
| Umami `trip_planning_post_created`, `trip_invite_shared`, `push_preference_updated` | External analytics; no local FK | No route cleanup | Provider-dependent | Category/has-link, share method, or enabled state; possible provider session/visitor metadata | Cannot block local deletion; external correlation/retention is unverified. |

## 3. Current deletion and presentation behavior

### 3.1 Transaction behavior

The route validates CSRF, confirmation email, login freshness, and when needed the current password before mutation. Cleanup and user deletion occur in one transaction. A failure triggers rollback, so the account and related data remain rather than being partially deleted.

The explicit `flush()` immediately before deleting the user is useful but is not a complete proof against future references: it surfaces constraints from preceding cleanup, while a new unhandled FK can still fail when the user delete is flushed/committed.

### 3.2 Surviving participant experience

* Activities where the user is a direct actor or recipient disappear.
* A grouped availability activity can remain for a surviving recipient when the deleted user was a non-actor member. It remains visible as generic “Update from {live actor}” notification copy. The copy does not display the deleted member's nested friend data, but the names and IDs remain stored.
* Activities whose only deleted subject is an owned trip can remain stored but are filtered from current notifications when their trip object no longer resolves.
* Planning posts authored by the deleted user disappear rather than showing anonymized authorship.
* Trips owned by the deleted user are deleted, including planning posts by other participants on those trips.
* No direct-message transcript exists to preserve.
* A push already delivered to a device may remain in the operating system's notification center; local deletion cannot retract it.
* Deep links in old pushes may lead to a removed trip/user or a generic list page.

### 3.3 Operator experience

The admin MEL page shows recent event rows, timestamps, category/event, recipient username/email when the relationship resolves, `#<id>` when an unresolved non-null ID remains, and an em dash after account deletion clears the recipient ID. It also shows delivery status, suppression reason, provider, and retry count. It does not currently render full payload JSON, title/body, provider message ID, or error text, though those remain in the database.

The messaging dashboard reports aggregate volume, events, funnel, suppressions, provider/network signals, and outbox health. It states that provider acceptance is not proof of device delivery.

Replay operations create new outbox rows and append replay evidence rather than rewriting the original delivery history.

### 3.4 In-flight outbox state by timing

| State at deletion | Current local effect | Delivery consequence |
|---|---|---|
| `pending` / `retryable` | Direct user IDs become `NULL`; row retained | Cannot pass normal live-recipient safety. It may later suppress if claimed, or remain queued while policy claims are paused. |
| `processing`, provider not started | IDs are nullified by the same user-delete transaction; concurrent locking behavior is not tested | Worker should fail safety/ownership or lose its valid target, but the race needs PostgreSQL coverage. |
| `processing`, provider started | Local IDs nullified; provider boundary already committed | Provider call may still occur or already have occurred. Deletion cannot guarantee cancellation. |
| `provider_accepted` | Historical row and provider ID retained | Provider accepted the push; local deletion cannot retract it. |
| `suppressed` / `dead_letter` | Historical row retained | No new delivery expected; operational evidence remains. |
| `delivery_unknown` | Historical ambiguity retained | Deletion does not resolve whether provider accepted delivery. |
| replayed | Source, target, and replay-event rows retained | Both delivery lineages remain, with direct user IDs cleared but indirect evidence intact. |
| operator-terminalized | Row retained | No new attempt expected; operator reason/identity remains. |

## 4. Verified facts, risks, decisions, and recommendations

### Verified facts

1. **FACT:** Current notification history is activity-based, not conversation-based.
2. **FACT:** The route deletes activities where the account is actor or recipient and deletes authored planning posts; grouped activities can remain visible when the account is referenced only as a non-actor JSON member.
3. **FACT:** MEL survives with explicitly nulled actor/recipient user foreign keys.
4. **FACT:** Outbox survives; PostgreSQL `SET NULL` clears direct actor/recipient FKs.
5. **FACT:** Replay, delivery-policy audit, and worker heartbeat rows survive.
6. **FACT:** Retained MEL/outbox rows can hold indirect user identifiers and rendered/correlation data.
7. **FACT:** Provider-accepted delivery cannot be retracted by local database deletion.
8. **FACT:** The existing PostgreSQL account-deletion test does not exercise MEL, outbox, replay, planning posts, invite shares, activity, event/email, or push-token rows.
9. **FACT:** Direct APNs and FCM admin delivery paths write retained MEL rows containing local token-row IDs even though the token rows themselves are deleted.
10. **FACT:** Messaging-adjacent Umami events are external to the deletion transaction.
11. **FACT:** Live password-reset and feedback emails bypass local `Event`/`EmailLog` retention controls and can leave SendGrid, mailbox, and log copies.
12. **FACT:** Grouped availability activities denormalize every included friend's first/last name, user ID, trip and resort identifiers, and location details into JSON.
13. **FACT:** Deletion removes activities only when the account is actor or recipient; it does not scrub nested grouped membership or all references to owned trips.
14. **FACT:** `invite_generated` and `invite_share_intent` are sent to PostHog with the BaseLodge user ID as `distinct_id`; account deletion does not erase them.
15. **FACT:** Invite-share and PostHog transport logs retain user/event metadata outside the deletion transaction.
16. **FACT:** Open-to-Ski sharing telemetry omits the numeric user ID, dates, and image content. It persists bounded delivery events under a valid cookie-derived PostHog identity when present, otherwise a fresh per-event `anonymous_event:<uuid>`.

### Supported risks

1. **RISK — Incomplete anonymization:** Clearing user FKs does not remove names in rendered MEL copy or IDs in payload, occurrence, object, and evidence fields.
2. **RISK — Pending work is retained, not explicitly cancelled:** A deleted recipient can leave pending/retryable rows awaiting future suppression or paused indefinitely.
3. **RISK — Race at provider boundary:** Deletion concurrent with a worker claim/provider start is not covered by PostgreSQL tests.
4. **RISK — Provider-side persistence:** OneSignal may retain aliases, event properties, notification payloads, and delivery records under its own policy; repository inspection cannot establish provider deletion.
5. **RISK — Historical-content surprise:** Deleting an owner removes other participants' posts on the owner's trip; deleting a participant removes their posts from surviving trips.
6. **RISK — Future FK regressions:** Adding a user-bearing table without extending deletion logic can turn account deletion into a constraint failure.
7. **RISK — Admin/API expansion:** Fields not shown in current templates remain queryable and could later be exposed without a deliberate deleted-user presentation rule.
8. **RISK — Public-policy mismatch:** “All associated data” may reasonably be read more broadly than the current direct-FK cleanup.
9. **RISK — External analytics retention:** Local account deletion does not remove directly user-identified PostHog events or submitted Umami events. PostHog user correlation is verified in code; provider retention/deletion behavior and Umami correlation are unverified.
10. **RISK — External email copies:** Feedback contains direct identity and free text in an administrator mailbox, while password-reset email includes account identity and a tokenized URL. Local deletion does not erase these copies.
11. **RISK — Hidden identity behind a visible activity:** A grouped row can remain visible as generic notification copy while its nested deleted-user names and IDs stay hidden in JSON and remain exposable by future templates, admin tools, exports, or direct queries.
12. **RISK — Stale activity subjects:** Polymorphic and JSON trip references have no FK and can outlive owned-trip bulk deletion, leaving hidden orphan activity evidence.
13. **RISK — Duplicate invite-share evidence:** Deleting local `InviteShareEvent` rows does not remove the same action from PostHog or application logs.
14. **RISK — Anonymous-identity linkage:** The Open-to-Ski server payload is intentionally anonymous, but the repository cannot prove that its browser ID is unlinked from the authenticated PostHog person.

### Product decisions required

1. **PRODUCT DECISION:** Is account deletion intended to erase participant-authored planning content or preserve trip history for surviving participants?
2. **PRODUCT DECISION:** If content is retained, should authorship be permanently anonymous, displayed as “Deleted User,” or recoverable only to a restricted safety function?
3. **PRODUCT DECISION:** Which delivery states need operational retention, and for how long?
4. **PRODUCT DECISION:** Are rendered title/body and payload snapshots necessary after delivery finalization?
5. **PRODUCT DECISION:** Must pending/retryable work be synchronously cancelled during deletion?
6. **PRODUCT DECISION:** What provider-side deletion or alias-removal obligation applies?
7. **PRODUCT DECISION:** Which abuse/safety records, if any, require a separately governed legal/safety hold rather than ordinary product retention?
8. **PRODUCT DECISION:** Does the existing “all associated data” promise require full erasure, bounded de-identification, policy clarification, or some combination?
9. **PRODUCT DECISION:** What retention/deletion obligations apply to SendGrid records, administrator feedback mailboxes, password-reset mailboxes, and application logs?
10. **PRODUCT DECISION:** Should surviving grouped activities be deleted, have only the deleted member removed, be regenerated from current authorized relationships, or be retained under an approved evidence policy?
11. **PRODUCT DECISION:** Must PostHog person/events and messaging-adjacent Umami events be deleted, de-identified, or retained for a bounded period when an account is deleted?
12. **PRODUCT DECISION:** What retention/redaction period applies to invite-share and analytics transport logs?
13. **PRODUCT DECISION:** Should cookie-identified availability-sharing telemetry be included in account erasure even though its server payload has no numeric user ID?

### Recommendations after policy selection

1. **RECOMMENDATION:** Define one written retention schedule by data class and delivery state before changing code.
2. **RECOMMENDATION:** Treat direct FK nullification and content redaction as separate requirements.
3. **RECOMMENDATION:** Add an explicit deletion-time outbox operation: cancel/terminalize, redact, or delete according to the selected policy rather than relying only on `SET NULL`.
4. **RECOMMENDATION:** Keep provider-bound work and immutable audit evidence separate if operational retention is required.
5. **RECOMMENDATION:** Add a PostgreSQL whole-schema audit that enumerates every FK to `user.id` and fails when a new reference lacks a declared deletion policy/test.
6. **RECOMMENDATION:** Implement a single presentation helper for deleted identities if any participant-visible record will survive.
7. **RECOMMENDATION:** Verify OneSignal deletion capabilities and document whether BaseLodge must call them before, during, or asynchronously after local deletion.
8. **RECOMMENDATION:** Obtain privacy/legal interpretation of the existing public deletion promise before selecting an engineering retention option.
9. **RECOMMENDATION:** Verify PostHog person/event deletion and Umami visitor/session deletion capabilities, then implement an idempotent external-erasure workflow if required.
10. **RECOMMENDATION:** Define and implement a SendGrid/mailbox/log retention process, including whether feedback must move to a governed data store with explicit deletion controls.
11. **RECOMMENDATION:** Add an explicit account-deletion operation for every `Activity` JSON membership and polymorphic subject reference; direct actor/recipient filtering is insufficient.
12. **RECOMMENDATION:** Prefer regenerating derived grouped activities from current authorized data over retaining denormalized names and IDs.
13. **RECOMMENDATION:** Remove or pseudonymize user IDs from invite-share and analytics transport logs according to the approved retention policy.

## 5. Policy comparison

| Policy | Privacy | Participant history | Abuse/safety evidence | Referential integrity | UX | Complexity |
|---|---|---|---|---|---|---|
| **Full deletion** — remove authored content and all user-correlatable messaging/audit/activity rows | Strongest ordinary deletion outcome; provider copies still separate | Lowest continuity; planning discussions, grouped activity context, and delivery history disappear | Weak unless evidence is lawfully separated before deletion | Requires ordered deletion across activity JSON and replay/outbox/MEL links | Simple expectation, but old links/history vanish | High migration/cleanup complexity because JSON and replay/outbox/MEL references are not one FK graph |
| **Retained content with anonymized authorship** — keep useful content, remove identity and correlators | Good only if free text, URLs, payloads, IDs, and nested Activity JSON are also reviewed/redacted | Strong continuity | Content may remain useful but attribution is intentionally lost | Requires nullable author or tombstone design and nested JSON rules | Clear if consistently labeled anonymous | High: schema, JSON redaction/regeneration, search/admin, and privacy tests |
| **Generic “Deleted User” presentation** — retain content and render a tombstone identity | Moderate; content and grouped location/date context may itself identify author | Strongest participant continuity | Better narrative evidence, but generic label is not verified attribution | Can use nullable author plus presentation state or a non-reusable tombstone key; grouped JSON still needs rewriting | Familiar collaboration UX | Medium-high; must prevent profile links, nested names/IDs, avatars, and accidental re-identification |
| **Limited operational metadata retention** — delete participant content/rendered copy, retain bounded delivery status/counters for a fixed period | Strong if identifiers, payloads, names, provider IDs, Activity JSON, and free text are removed or tokenized | Planning and notification history depend on separate content choices; outbound audit remains only in aggregate/bounded form | Limited; enough for reliability, not necessarily interpersonal investigation | Best served by a reduced audit schema or scheduled redaction | Little user-visible effect | Medium; requires state-specific redaction and expiry jobs |

These policies can be combined only if the boundary is explicit. For example, planning posts could use “Deleted User” while completed delivery rows are reduced to limited metadata and pending work is cancelled.

## 6. Engineering sequence after a decision

1. **Write the policy contract**
   * data classes in scope;
   * retention duration by state;
   * deleted-author presentation;
   * safety/legal hold exception, if any;
   * provider-side obligation.
   * analytics-person/event and log-retention obligations.
2. **Inventory and classify stored fields**
   * direct user FKs;
   * typed and untyped IDs;
   * rendered/free-text fields;
   * provider identifiers;
   * operator audit fields.
3. **Design schema changes**
   * FK actions and nullability;
   * tombstone/anonymized-author representation if selected;
   * immutable audit versus mutable/redactable delivery work;
   * expiry/redaction timestamps.
4. **Define transaction ordering**
   * delete, rewrite, or regenerate derived Activity rows and JSON memberships;
   * lock/cancel pending work;
   * resolve processing/provider-start races;
   * redact/delete dependent replay and MEL rows;
   * modify participant content;
   * delete user;
   * enqueue provider cleanup only if it can be made durable and privacy-safe.
5. **Implement service-layer operations**
   * central deletion/redaction service rather than adding more route-only queries;
   * state-aware outbox handling;
   * idempotent retry for external provider cleanup.
6. **Implement presentation rules**
   * notifications, trip planning, admin MEL/outbox/replay surfaces;
   * no profile links or leaked IDs for deleted identities.
7. **Backfill existing retained data**
   * dry-run counts;
   * bounded batches;
   * auditable redaction;
   * rollback strategy that does not restore erased personal data unintentionally.
8. **Run focused and full regression validation**
   * SQLite unit coverage for route behavior;
   * disposable PostgreSQL FK and concurrency coverage;
   * worker/provider-boundary simulations;
   * privacy-focused rendering assertions.

## 7. Post-decision test matrix

### Tests required for every policy

* PostgreSQL introspection for every FK to `user.id`, asserting its intended `ON DELETE` rule.
* One account-deletion fixture containing every user-bearing table and every role in multi-user tables.
* Successful deletion plus rollback-on-error atomicity.
* Unrelated users and unrelated records remain unchanged.
* A surviving grouped availability activity containing the deleted user as a non-actor member is deleted, rewritten, regenerated, or retained exactly as the approved policy requires.
* Owned-trip deletion leaves no unapproved `Activity.object_id`, `subject_id`, `trip_ids`, or nested `friends_data.trip_id` reference.
* Admin pages and APIs do not expose deleted email, username, avatar, profile URL, raw user ID, token, or disallowed payload.
* Provider callback is never newly invoked for a recipient deleted before the provider-start boundary.
* Concurrent deletion versus claim, safety check, provider start, finalization, and replay.
* Provider-accepted and delivery-unknown rows are handled according to the written policy without implying confirmed device delivery.
* Direct APNs, FCM, and OneSignal evidence follows the same selected redaction/retention contract.
* External analytics deletion or de-identification behavior matches the approved interpretation of the privacy policy.
* PostHog tests assert the numeric user `distinct_id`, allowed properties, prohibited-field sanitization, and the selected external deletion/de-identification call.
* Open-to-Ski analytics tests continue to reject dates, image content, numeric user identity, and unapproved properties, and verify the chosen handling of a potentially linked anonymous ID.
* Invite-share and analytics transport logs contain only policy-approved fields after deletion.
* SendGrid/mailbox/log behavior matches the approved policy, including password-reset and feedback copies.

### Delivery-state coverage

Create and assert deletion behavior for:

* `pending`;
* `processing/not_started`;
* `processing/started`;
* `retryable`;
* `provider_accepted`;
* `suppressed`;
* `dead_letter`;
* `delivery_unknown`;
* `operator_terminalized`;
* source and target rows of a replay;
* MEL pending, sent, skipped/suppressed, failed, and retry-child rows.

### Policy-specific coverage

**Full deletion**

* No Activity JSON or polymorphic identifier references the deleted user or owned trips.
* MEL/outbox/replay dependency order and cascade behavior.
* No orphan policy references or uniqueness conflicts.
* No participant-authored content remains.
* Aggregate dashboards remain valid when source rows are removed.

**Retained content with anonymized authorship**

* Grouped Activity JSON is rewritten or regenerated without the deleted member's name, ID, trip, resort, and location correlation.
* Author FK is null/tombstoned without deleting the row.
* Body/link text follows the selected content-redaction rule.
* No route, template, API, export, or admin surface can resolve the former author.
* Search/index/cache data is also anonymized.

**Generic “Deleted User” presentation**

* Consistent label and placeholder avatar.
* No clickable profile or raw identifier.
* Multiple deleted users are not accidentally merged where event distinction matters.
* Nested grouped-activity data does not retain the former name or raw user/trip IDs behind the generic label.
* Accessibility text communicates deleted authorship without exposing identity.

**Limited operational metadata retention**

* Allowlisted fields survive; title/body/payload/object/evidence/provider/user correlators do not.
* Scheduled expiry/redaction is idempotent.
* Metrics remain correct after row reduction or aggregation.
* Replay is refused when required recipient/evidence data has been redacted.

**Provider cleanup**

* Alias/removal request is durable and idempotent.
* Failure does not restore the local user.
* Logs redact provider credentials and deleted-user personal data.
* Timeout/ambiguous provider outcomes have an explicit retry/manual-review policy.
* SendGrid tests prove which identifying fields are transmitted and whether an external erasure workflow is invoked.
* PostHog/Umami cleanup tests cover success, retry, provider rejection, timeout, and idempotency without restoring the local account.

## 8. Existing verification and gaps

### Existing verified coverage

`tests/test_account_deletion.py` covers successful deletion, fresh/non-fresh authentication, password/provider failures, rate limiting and rollback, owned trips and children, friendships, participant rows, suggestion/cooldown roles, owned-trip invitations, preservation of unrelated data, RSVP/connection/wishlist erasure and actor anonymization, ski days, confirmation mismatch/empty input, and log/error behavior.

`tests/test_account_deletion_postgres.py` runs the real route against disposable PostgreSQL, verifies selected FK rules, and proves cleanup of invitation/suggestion/cooldown relationships plus nulling of invited-by and surviving-trip creator references.

Outbox tests cover enqueueing, constraints, state transitions, leases, provider-start durability, worker outcomes, dispatch safety, replay, and reversible cutover behavior independently of account deletion.

### Important gaps

The PostgreSQL account-deletion test does not currently create or assert:

* Activity;
* Event / EmailLog;
* PushDeviceToken;
* InviteShareEvent;
* SkiTripPlanningPost;
* MessageEventLog;
* MessageOutbox in each state;
* MessagingReplayEvent;
* outbox/MEL lineage;
* concurrent worker processing.
* SendGrid/mailbox/log cleanup or de-identification.
* PostHog/Umami deletion or de-identification and invite-share log retention.

Therefore, the current retention conclusions are source- and migration-verified, but not end-to-end PostgreSQL-tested as one deletion scenario.

## 9. Exact inspected-file appendix

### Models and routes

* `models.py`
  * `User`
  * `SkiTrip`, `SkiDay`, `SkiTripParticipant`
  * `SkiTripRsvpTransition`, `SkiTripLifecycleEvent`
  * `Invitation`, `FriendCooldown`, `FriendSuggestion`, `SuggestionPushCooldown`
  * `InviteToken`, `TripInviteToken`, `GroupTrip`, `TripGuest`
  * `Event`, `EmailLog`, `Activity`, `PushDeviceToken`
  * `MessageEventLog`, `MessagingDeliveryPolicy`, `MessagingDeliveryPolicyEvent`
  * `MessagingReplayEvent`, `MessagingWorkerHeartbeat`, `MessageOutbox`
  * `InviteShareEvent`, `SkiTripPlanningPost`
* `app.py`
  * `delete_account`
  * password-reset and feedback SendGrid routes
  * direct APNs/FCM provider functions and admin delivery routes
  * notifications and admin messaging/event/outbox/replay routes
  * trip-planning create/render routes
  * invite generation/share routes and PostHog event calls
* `analytics.py`
  * server-side PostHog sanitization, user identity, capture, identify, and alias behavior

### Messaging services

* `services/message_dispatch.py`
* `services/message_events.py`
* `services/message_outbox.py`
* `services/message_outbox_worker.py`
* `services/messaging_staging.py`
* `services/messaging_cutover.py`
* `services/messaging_constants.py`
* `services/push_providers.py`
* `static/analytics.js`
* `static/js/open-to-ski-export.js`

### Migrations

* `migrations/versions/3cb34b17c7dd_add_email_and_lifecycle_hygiene_schema.py`
* `migrations/versions/370403a1d9f9_add_group_trip_and_trip_invite_.py`
* `migrations/versions/44687c74df69_add_activity_model_for_friends_feed.py`
* `migrations/versions/7e24870bab12_add_message_event_log.py`
* `migrations/versions/bl78_rsvp_transition.py`
* `migrations/versions/bl79_friend_history.py`
* `migrations/versions/bl80_trip_lifecycle.py`
* `migrations/versions/bl87_wishlist_history.py`
* `migrations/versions/bl147_send_safety.py`
* `migrations/versions/bl317_startup_schema.py`
* `migrations/versions/bl440_message_outbox.py`
* `migrations/versions/bl443_reversible_cutover.py`

### Templates

* `templates/notifications.html`
* `templates/components/bottom_nav.html`
* `templates/trip_planning.html`
* `templates/trip_detail.html`
* `templates/open_to_ski.html`
* `templates/push_settings.html`
* `templates/components/analytics_head.html`
* `templates/admin_messaging.html`
* `templates/admin_message_events.html`
* `templates/privacy_policy.html`

### Tests

* `tests/test_account_deletion.py`
* `tests/test_account_deletion_postgres.py`
* `tests/test_csrf.py`
* `tests/test_profile_consolidation.py`
* `tests/test_message_outbox.py`
* `tests/test_message_outbox_dispatch.py`
* `tests/test_message_send_safety.py`
* `tests/test_bl440_admin_outbox.py`
* `tests/test_bl440_message_outbox_migration.py`
* `tests/test_bl443_reversible_cutover.py`
* `tests/test_bl443_reversible_cutover_migration.py`
* `tests/test_bl443_cutover_postgres.py`
* `tests/test_admin_push_broadcast.py`
* `tests/test_bl170_rate_limits.py`
* `tests/test_bl116_analytics.py`
* `tests/test_bl116_auth_analytics.py`
* `tests/test_project_analytics_events.py`
* `tests/test_open_to_ski.py`
* `tests/js/test_open_to_ski_export.js`

### Existing documentation

* `docs/messaging-architecture-inventory.md`
* `docs/messaging-audit.md`
* `docs/engineering/continuous-message-worker.md`

## 10. Final conclusion

Current account deletion removes activities where the account is a direct actor or recipient and removes authored planning content, but a grouped activity can remain visible to a surviving participant when the deleted user appears only inside its JSON membership. Deleted-trip-backed activities can remain stored while being filtered from the current UI. Outbound delivery evidence also survives. Direct MEL and outbox user foreign keys are cleared, so those tables should not block deletion under the existing route. However, retained rows can still identify or strongly correlate the deleted user through Activity JSON, rendered copy, payload/evidence IDs, object and occurrence identifiers, provider references, and timestamps. User-identified PostHog events, potentially linked anonymous availability-sharing events, invite-share/analytics logs, SendGrid, recipient/admin mailboxes, push providers, Umami, and other analytics can also retain associated information outside the local deletion transaction.

That mixed behavior is internally consistent enough to permit deletion, but it is not a complete retention policy and may conflict with the public promise to delete “all associated data.” Privacy/legal owners should first interpret that promise. Product owners can then select an aligned policy before engineering changes are made and implement it with state-aware outbox handling, explicit content redaction rules, provider/analytics decisions, and end-to-end PostgreSQL coverage.