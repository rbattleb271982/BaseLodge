# BaseLodge History Event Conventions

**Status:** Repository architecture standard
**Scope:** Private, append-only historical records for user and social domains
**Applies before:** BL-80 trip history, BL-87 wishlist history, and future history streams

## 1. Purpose and non-goals

BaseLodge history tables preserve meaningful domain transitions for internal history,
debugging, and future analysis. They complement the current-state tables; they do not
replace them.

This document standardizes the invariants that future history work must preserve while
allowing each domain to keep its own subjects, state machine, source vocabulary, and
transition service.

This is **not** a proposal for:

- A generalized event store or polymorphic event table
- An event bus or event-sourcing framework
- Public history APIs, history UI, or a “former friends” product concept
- Replaying history as the default source of current product state
- Refactoring working history implementations for naming consistency

The preferred architecture is several small, private, domain-specific history tables
with explicit contracts.

## 2. Governing principles

1. **Current state remains authoritative.** Each domain must name the current table or
   field that controls product behavior. History alone never grants authorization,
   visibility, eligibility, messaging access, or social proof.
2. **Record real transitions only.** A history row represents a transition that was
   observed and committed, not a state inferred from dates, surviving rows, analytics,
   notifications, or a later retry.
3. **Write state and history atomically.** The current-state mutation and its history
   insert commit or roll back together.
4. **Prefer domain-specific clarity.** A shared contract is valuable; a shared event
   storage abstraction is not justified when domains have different subjects,
   locking, state semantics, and deletion rules.
5. **Privacy applies to history.** A history table must define what happens when every
   subject is deleted and must not preserve an identifiable deleted subject by accident.
6. **Forward-only is the default.** The period before a stream began recording is
   unknown unless reliable event-level evidence exists.

## 3. History event contract

### 3.1 Event identity and idempotency

- Every event has an immutable, database-generated primary key.
- Event IDs are never reused.
- The semantic subject key identifies a history stream, not an individual event.
  Examples are a trip/participant pair or a canonical user pair.
- Do not add a client or external idempotency key by default. A locked comparison of
  authoritative current state is normally the correct retry strategy.
- Add an external idempotency key only when a domain receives a stable operation
  identifier and state comparison cannot distinguish a cross-transaction retry.
- A retry that requests the already-recorded state emits no event.
- A later legitimate transition back to a previous state receives a new event ID and
  begins a new lifecycle interval.

### 3.2 Subjects

Every stream must explicitly document:

- The entities whose history is being recorded
- Which subjects are required for the event to be meaningful
- Which subjects are privacy/deletion subjects
- Whether the subject is a single entity, ordered relationship, or unordered pair
- What happens when each subject is deleted

Use required foreign keys for subjects where the retention policy allows it. For an
unordered pair, canonicalize the subject IDs before insertion and enforce the
canonical order in the database. A pair event must not represent a self-relationship
or a second ordering of the same pair.

Subjects and actors are separate concepts. A subject identifies the history stream;
an actor identifies who or what performed the transition.

### 3.3 Actors

- User-driven transitions pass the authenticated actor explicitly.
- `actor_user_id` may be nullable for defined system actions and after actor-only
  privacy anonymization.
- Actor storage must use a foreign key with the stream's documented deletion action,
  normally `SET NULL`.
- An actor reference never implies ownership, authorization, relationship access, or
  event visibility.
- Do not copy actor names, emails, or other personal data into the event row when a
  stable user foreign key is sufficient.

### 3.4 Sources

- Each domain defines a finite, database-constrained source vocabulary.
- A source identifies the trusted product path that produced the transition, such as
  an invitation acceptance, profile action, or settings change.
- A source is not a free-form explanation of why the user acted.
- Do not store arbitrary reasons, request payloads, or unbounded metadata unless a
  separately approved requirement demonstrates that they are necessary and safe.
- New source values require the normal code, migration, and test review for the
  affected domain.

### 3.5 Timestamps and ordering

- Operational events use a server- or database-generated timezone-aware timestamp.
- Callers do not provide ordinary transition timestamps.
- Queries order by the event timestamp and then the immutable event ID as a
  deterministic tie-breaker.
- A caller-supplied historical timestamp is allowed only for a separately approved
  import/backfill with explicit provenance and validation.

The timestamp describes when the trusted transition was recorded, not an inferred
date from another product field.

### 3.6 Append-only behavior and corrections

Ordinary product code does not update or delete an event's business fields. In
particular, it does not rewrite subjects, event types, sources, or transition
timestamps after insertion.

If a domain supports correction, use a new explicit compensating event defined by
that domain. If it does not, a correction requires separately reviewed maintenance
with an audit trail and rollback plan. Do not introduce a generic correction event
merely to avoid making a domain decision.

Privacy erasure and actor anonymization are narrow exceptions to append-only storage:

- Deleting a privacy subject may delete the identifying history required by policy.
- Deleting a user who appears only as actor may null the actor reference.
- Neither operation is a product transition and neither may fabricate a removal,
  cancellation, or other lifecycle event.

### 3.7 Current state versus history

Every history stream must identify its operational current-state source. Examples:

- Current participant status for RSVP behavior
- Reciprocal live `Friend` rows for friendship and authorization
- A future persisted trip lifecycle state for trip completion/cancellation
- The canonical interpretation of a user's wishlist data for wishlist membership

History must not be consulted as a fallback to authorize a request or expose current
private data. Historical reconstruction is allowed only inside a period where the
stream is known to be complete and only for an explicitly historical question.

Before the stream's recording cutover, state is **unknown**. It must not be treated
as active, inactive, added, removed, completed, or cancelled merely because a current
row or date exists.

### 3.8 Backfill

The default policy is no backfill.

A backfill requires a separate reviewed plan that specifies:

- Reliable event-level evidence for every generated event
- Provenance identifying the evidence and its limitations
- Deterministic duplicate prevention and rerun behavior
- Subject deletion and actor anonymization handling
- A bounded scope and rollback validation
- Explicit treatment of records whose history is unknowable

Current-state rows, dates, invitation records, analytics, notifications, messages,
or the absence of a deleted row are not sufficient evidence to fabricate a past
transition. A current snapshot may be useful for a separate product feature, but it
must not be mislabeled as a historical event.

### 3.9 Duplicate prevention and concurrency

Transition services should:

1. Lock the authoritative current-state rows in deterministic order.
2. Refresh the authoritative state while holding those locks.
3. Compare the requested transition with the refreshed state.
4. Mutate current state and append at most one event for a real change.
5. Flush without committing so the caller retains the transaction boundary.

Database constraints validate shape, canonicalization, event types, and source
vocabularies. They should not prohibit legitimate repeated lifecycle events such as
formed → removed → formed.

Where concurrent requests can race, real PostgreSQL tests are required. SQLite
tests alone do not prove row-lock serialization or deadlock avoidance.

### 3.10 Retention and privacy

Each stream must distinguish ordinary product transitions from privacy erasure:

- Ordinary removal or cancellation may create a history event.
- Account deletion or subject deletion erases or irreversibly anonymizes identifying
  history according to the stream's subject policy.
- Actor-only deletion nulls the actor on otherwise valid surviving events.
- Deleting a subject must not create a synthetic removal or cancellation event.
- Avoid snapshots containing names, emails, or other PII unless stable IDs cannot
  satisfy a documented requirement and privacy review approves the exception.

### 3.11 Indexing and query patterns

Indexes follow demonstrated query patterns rather than speculative future use.

The baseline is a composite subject key plus event timestamp. The immutable event ID
is the application ordering tie-breaker. Add actor, event-type, secondary-subject,
or catalog indexes only when a concrete internal query needs them.

Any “state at time T” query must:

- Bound by the canonical subject key
- Order by timestamp and event ID
- Preserve unknown-before-cutover semantics
- Avoid treating an incomplete event stream as a complete ledger

### 3.12 Auditability

Every stream should make its audit meaning legible from the row itself:

- Bounded event types
- Bounded domain-specific sources
- Explicit actor provenance when known
- Immutable server-generated timestamps
- Stable subject foreign keys
- No copied PII or unbounded payloads

## 4. Mandatory implementation checklist

Before implementing or rolling out a new history stream, answer all of the following:

### Contract and state

- [ ] What exact transition does one event represent?
- [ ] What is the authoritative current-state table or field?
- [ ] What are the privacy/lifecycle subjects?
- [ ] Is the subject ordered, unordered, or multi-entity?
- [ ] What does unknown-before-cutover mean for this stream?
- [ ] Can a legitimate lifecycle repeat, and how is each interval distinguished?

### Identity and provenance

- [ ] Is the database event ID immutable and database-generated?
- [ ] Is an external idempotency key truly required?
- [ ] Are event types finite and constrained?
- [ ] Are source values finite, trusted, and domain-specific?
- [ ] Is the actor explicit, distinct from subjects, and nullable only for defined reasons?
- [ ] Are timestamps server-generated and deterministically ordered?

### Transaction and concurrency

- [ ] Does the service lock authoritative state in a deterministic order?
- [ ] Does it refresh state while locked?
- [ ] Does a no-op/retry emit no event?
- [ ] Do current-state and history writes commit or roll back together?
- [ ] Does the service avoid owning the caller's commit?
- [ ] Are PostgreSQL race cases covered where concurrency is possible?

### Privacy and retention

- [ ] Does deleting each subject erase the identifying history required by policy?
- [ ] Does actor-only deletion anonymize surviving events?
- [ ] Is account/privacy deletion prevented from creating a product transition?
- [ ] Does the row avoid unnecessary PII copies?
- [ ] Are public APIs, UI, authorization, and visibility explicitly kept separate?

### Migration and historical integrity

- [ ] Is the migration additive, reversible, and free of synthetic backfill?
- [ ] Does upgrade create an empty history table unless a separate backfill is approved?
- [ ] Does downgrade remove only the stream's schema?
- [ ] Are constraints tested for invalid subjects, event types, and sources?
- [ ] Is any proposed backfill supported by event-level evidence and provenance?

### Minimum test invariants

- [ ] A real transition writes exactly one event with correct subjects, actor, source,
      and server timestamp.
- [ ] Duplicate, same-state, rejected, and absent-state no-ops write none.
- [ ] A forced failure rolls back both current state and history.
- [ ] Repeated legitimate lifecycle transitions produce distinct ordered events.
- [ ] Database constraints reject invalid shape and vocabulary values.
- [ ] Subject deletion erases protected history.
- [ ] Actor-only deletion anonymizes the actor.
- [ ] Migration upgrade creates no fabricated historical rows.
- [ ] Migration downgrade removes only the stream table.
- [ ] PostgreSQL concurrency behavior is tested where races are possible.
- [ ] History alone cannot grant authorization, visibility, eligibility, or current
      product state.

## 5. Reference implementations

BL-78 and BL-79 are the current reference implementations. Both substantially conform
to this contract and should not be refactored solely for cosmetic consistency.

### 5.1 BL-78 — RSVP transition history

- **Subject:** A trip and participant user; the current participant row remains
  authoritative.
- **Event shape:** Previous status, new status, server-generated `changed_at`, actor,
  and bounded source.
- **Lifecycle:** A status chain records real changes; same-state submissions do not
  create duplicate history.
- **Locking:** The transition service locks the trip and then the participant in its
  defined order before comparing current status.
- **Privacy:** Subject history is erased when the relevant user or trip is deleted;
  actor-only references are anonymized.
- **Backfill:** Existing participant state is not presented as reconstructed history.
- **Validation:** Transition, no-op, rollback, privacy, migration, and PostgreSQL
  concurrency behavior are covered by focused tests.

### 5.2 BL-79 — Connection lifecycle history

- **Subject:** An unordered pair of users stored in canonical ascending order.
- **Event shape:** `formed` and `removed`, server-generated `occurred_at`, actor, and
  bounded source.
- **Current truth:** The two reciprocal live `Friend` rows remain the sole friendship
  and authorization truth.
- **Lifecycle:** Formation, removal, and legitimate reconnection produce
  formed → removed → formed intervals; retries are event-free.
- **Locking:** Both subject users are locked in canonical order before refreshing and
  mutating the directed friendship rows.
- **Repair:** One-sided live friendship drift is repaired without fabricating a
  second `formed` event.
- **Privacy:** Pair history is erased when either subject user is deleted; actor-only
  references are anonymized.
- **Backfill:** Existing friendship rows are not converted into invented history.
- **Validation:** Lifecycle, repair, no-op, rollback, privacy isolation, migration,
  and PostgreSQL concurrency behavior are covered by focused tests.

### 5.3 Intentional and harmless differences

These differences reflect domain semantics and do not require unification:

| Difference | Reason |
|---|---|
| Trip/user subject versus unordered user pair | The domains have different history identities |
| Previous/new status versus formed/removed event type | RSVP is a status state machine; connection history is interval lifecycle |
| Trip-then-participant locks versus canonical user-pair locks | Each service locks its authoritative current state |
| `changed_at` versus `occurred_at` | Both provide the same server-generated timestamp semantics |
| Transition-oriented versus event-oriented model names | Naming follows domain vocabulary |
| Domain-specific constraint/index prefixes and result objects | Local clarity is preferable to cosmetic abstraction |

## 6. BL-80 starting guidance: trip completion and cancellation

BL-80 is not implemented by this document.

### Likely contract

- **Subjects:** The trip and its organizer/owner, with the privacy policy explicitly
  defined for both.
- **Event types:** Explicit `completed` and `cancelled`; do not infer completion from
  dates or overload the existing planning/going state.
- **Actor:** The organizer for user-driven actions; nullable only for approved system
  actions or actor anonymization.
- **Sources:** A bounded trip-specific vocabulary distinguishing explicit organizer
  actions from any approved system lifecycle process.
- **Current truth:** A persisted trip lifecycle or terminal state, not the event table.
- **Concurrency:** Lock the trip, refresh its lifecycle state, compare the requested
  transition, and append one event in the same transaction.
- **Backfill:** Do not infer completion or cancellation from dates, current status,
  message logs, notifications, analytics, or the absence of a deleted trip.
- **Likely indexes:** Trip/time and organizer/time, after concrete query needs are
  established.

### Decisions required before BL-80

The current application hard-deletes trips for cancellation. BL-80 must separately
decide:

- Whether cancellation keeps a soft-deleted trip, a non-identifying tombstone, or a
  narrowly bounded retained event
- What exact action or trusted process constitutes completion
- What participants may see after completion or cancellation
- Which non-PII trip attributes, if any, may survive deletion
- How retained terminal history interacts with account deletion
- How existing RSVP cleanup and messaging/audit behavior should be preserved

Until those decisions are made, no trip history schema or migration should be created.

## 7. BL-87 starting guidance: wishlist add and remove

BL-87 is not implemented by this document.

### Likely contract

- **Subject:** A user/resort pair.
- **Event types:** `added` and `removed`.
- **Actor:** The authenticated user for current product routes; nullable only for
  approved system operations or actor anonymization.
- **Sources:** A bounded vocabulary distinguishing mountain-page changes, settings
  bulk replacement, and any future approved import/admin path.
- **Current truth:** The canonical, eligible interpretation of
  `User.wish_list_resorts`, not event replay.
- **Concurrency:** Lock and refresh the User row, normalize the current list, compute
  a stable before/after diff, and append per-resort events atomically.
- **No-ops:** Duplicate add and absent remove remain successful event-free no-ops.
- **Privacy:** Erase a user's wishlist history on account deletion; do not copy resort
  names or user PII into history.
- **Backfill:** Do not infer add/remove times from the current JSON list or analytics.
- **Likely indexes:** User/time and user/resort/time, subject to demonstrated queries.

### Decisions required before BL-87

- Whether ordering-only settings changes are history events
- How inactive or deleted resorts are represented
- Whether a bulk replacement emits one event per membership diff
- The exact atomic behavior for a mixed add/remove update
- Whether delegated or system changes will exist
- Whether any future import needs a stable external idempotency key

## 8. Migration implications

BL-140 is a conventions document and requires no database migration. It must not add
an empty migration, alter migration ancestry, backfill existing data, or connect to a
shared database.

The current graph remains:

```text
bl52_trip_stay
  → bl78_rsvp_transition
  → bl79_friend_history
  → bl70_user_season_pass
```

BL-70 remains deferred. Any future material conformance defect in BL-78 or BL-79
must become a separately reviewed cleanup task with its own tests and rollout plan;
it must not be silently folded into a conventions document.

## 9. Explicit out-of-scope items

- BL-80 trip history implementation
- BL-87 wishlist history implementation
- BL-70 rollout
- A generalized event store, event bus, or event-sourcing framework
- Refactoring BL-78 or BL-79 for cosmetic consistency
- Public history APIs, UI, or former-friend concepts
- Changes to current authorization, visibility, recommendations, messaging, counts,
  notifications, or analytics
- Synthetic history backfill
- Persistent Replit, Supabase Development, or Production database access or mutation