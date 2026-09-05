# Social intelligence cache foundation

## Status and decision

This document defines the BL-145 caching contract. It does **not** authorize or
implement a social cache, a generation store, invalidation hooks, migrations, or
Production rollout.

The V1 decision is:

1. Instrument current social reads before adding a cache.
2. Keep PostgreSQL authoritative for authentication, relationships, privacy,
   lifecycle, participation, availability, wishlist membership, and source
   existence.
3. If measurement justifies caching, pilot only a per-viewer Home Ideas
   candidate cache containing minimal source identifiers.
4. Treat every cache hit as untrusted input. Reauthorize, filter, and hydrate
   all candidates from current PostgreSQL rows before rendering.
5. Do not add Redis merely because Production already uses Redis for rate
   limiting.

The safety invariant is:

> A cache hit never grants visibility.

TTL, cache deletion, and cache generations improve correctness and performance.
They are not authorization controls.

## Current social intelligence read map

| Surface | Authoritative inputs and path | Cost and privacy | Decision |
|---|---|---|---|
| Home Ideas | `get_home_ideas()` expands reciprocal friendships, availability, wishlists, public active trips, active participants, dismissals, and ranking in one bounded SQL statement | Highest likely read cost; exposes friend-derived intent and availability | Instrument first. Only minimal per-viewer candidate caching is a V1 candidate |
| Home Happening | `get_happening_candidates()` unions friend-owned and active friend-participant occurrences, then ranks one result per friend | Bounded and simpler than Ideas; exposes future friend presence | Instrument separately. Do not assume Ideas and Happening need the same cache |
| Friends and friend profiles | Reciprocal `Friend` rows plus paged user/profile reads | Relationship authorization is highly mutable; current queries are bounded | Do not cache authorization or full results in V1 |
| Friend trips and trip summaries | Current relationship, trip privacy, lifecycle, ownership, active participation, and attendance | A stale result can reveal a private or terminal trip | Do not cache full cards or detail authorization in V1 |
| Availability overlap | Normalized availability with legacy fallback, reciprocal friendships, and exact date intersections | Raw dates are private and highly volatile | Never cache raw calendars. Keep only inside an authorized per-viewer computation |
| Wishlist and pass context | User wishlist/pass state and canonical resort/pass metadata | Social intersections are private; public resort/pass facts are not | Keep intersections viewer-scoped. Public reference facts may use a separate shared cache |
| Ski Day and mountain social facts | Confirmed history, reciprocal friendship, public-trip filters, and owner-only day totals | Can disclose presence or historical activity | Do not add a new cache in V1 |
| Public resort/pass reference data | Active resort and canonical pass presentation | Stable and non-social | Short-lived shared caching is acceptable with versioned keys |

Home Ideas already performs source expansion, concept reduction, suppression,
ranking, and its five-row limit inside the database. Only the final rows cross
into Python. A cache is worthwhile only if a bounded revalidation query is
materially cheaper than that authoritative query.

The former `/trip-ideas` route now redirects to Home. Helper and detail routes
remain relevant to the authorization contract: availability detail uses a
viewer-bound signed capability and revalidates current friendships and dates;
wishlist detail treats request identifiers as locators and revalidates current
friendship and wishlist membership.

## Existing cache inventory and required remediation

### Safe existing patterns

- Static assets use startup fingerprints and immutable browser cache headers.
- Public/deterministic responses may use ETags.
- Request-local state and memoization may avoid repeated work within one
  request.
- Stable resort reference data may be held process-locally when the value
  contains no social facts and bounded cross-worker staleness is acceptable.

### Mountains cache is not a model for new social caching

`/api/mountains-data` currently stores a complete per-user serialized response
in `_mountains_cache` for five minutes. The body includes `friend_count`, which
is derived from reciprocal friendships and public active friend-owned trips.
There is no explicit invalidation on friendship removal, trip privatization,
trip lifecycle change, trip deletion, or account deletion.

The mixed response also sends `Cache-Control: private, max-age=300`, and the
Mountains page fetches it with the browser's default HTTP-cache behavior. There
are therefore two independent stale-value layers: the process-local dictionary
and the authenticated browser cache. Fixing only the server dictionary would
still let the browser reuse a fresh five-minute response without contacting the
server.

These caches are viewer-scoped, but viewer scoping alone is insufficient.
During their TTL, a stale response may preserve a friend-derived count after
its authoritative source becomes ineligible. The current tests clear the
process cache manually between source mutations and therefore do not prove
revocation while either stale layer exists.

The current `friend_count` has precise all-time semantics: it counts distinct
reciprocal friends who **own** at least one public active/legacy trip at the
resort. It does not require an upcoming date and does not derive the count from
participant RSVP state. Cache remediation must preserve those product semantics
unless a separately approved product task changes them.

Before using the Mountains implementation as precedent or expanding it, a later
task must do one of the following:

- split stable public resort/pass presentation from authoritative per-request
  friend counts; or
- place friend-count candidates behind the generation and revalidation
  contract in this document.

The preferred V1 remediation is the split. Public reference data may remain
cached in a public/reference response. Friend counts should be returned through
a separate authenticated response that is non-storable at browser/proxy layers
and recomputed from current reciprocal friendship, public visibility, and
active lifecycle state. A generation-validated client protocol is an acceptable
later alternative only if it proves revocation before display. Retaining
`private, max-age=300` on any response containing `friend_count` is not safe.
TTL alone is not an acceptable privacy-revocation mechanism.

## Cacheability classes

### A. Safe for short-lived shared caching

- Public resort presentation.
- Canonical pass-reference facts.
- Deterministic public payloads with no user, trip, friendship, availability,
  wishlist, or Ski Day facts.

### B. Safe only with explicit invalidation

- Per-viewer Ideas candidate sets.
- A later per-viewer Happening candidate set.
- Any later per-viewer friend-trip or mountain-social candidate set.

These require transactional generation changes plus an emergency TTL.

### C. Safe only with viewer ownership

Any value derived from a friend graph, friend trip, availability overlap,
wishlist overlap, pass context, Ski Day fact, dismissal, or private profile
state. Such entries may never be reused for another viewer, session, household,
or a viewer with a “similar” graph.

Viewer ownership is necessary but does not grant authorization.

### D. Unsafe to cache in V1

- Authentication/session validity.
- Reciprocal friendship or a `may_view` decision.
- Signed capability validation.
- Raw availability calendars or exact friend dates.
- Private trip details or participant rosters.
- Names, emails, avatars, private profile attributes, and rendered social cards.
- Globally shared friend-derived rankings.

The current relationship system has reciprocal `Friend` rows, append-only
connection history, and a reconnect cooldown. It has no block/restriction
authorization model. If such a model is added later, it becomes an
authorization source and an invalidation dependency; historical connection
events must never grant access.

### E. Not worth caching without new evidence

- Paged Friends/search results.
- Friend profile authorization.
- Trip detail authorization.
- Owner-only Ski Day history.
- Inexpensive point lookups.
- Any bounded query without measured latency or database pressure.

## Ownership, namespace, and value contract

Future social keys have this conceptual shape:

```text
baselodge:{runtime}:social:{family}:schema-v{N}:viewer:{viewer_id}:generation:{generation}:input:{input_hash}
```

Candidate families are:

- `ideas_candidates`: eligible for a measured V1 pilot.
- `happening_candidates`: deferred pending separate measurement.
- `friend_trip_candidates`: deferred.
- `mountain_social_candidates`: deferred.

Public reference keys use a separate namespace:

```text
baselodge:{runtime}:public:{family}:schema-v{N}:entity:{id}:generation:{generation}
```

Development, test, and Production namespaces must not overlap. An unknown
runtime, namespace, schema, or semantic version is a cache miss.

A social cache value may contain only:

- candidate kind;
- authoritative source IDs required for revalidation;
- a non-sensitive ranking bucket or opaque score inputs;
- viewer ID, family, schema version, and generation;
- creation and absolute expiry timestamps.

It must not contain names, emails, profile attributes, friend lists,
relationship labels, raw availability, copied trip details, Ski Day history,
signed capabilities, session identifiers, authorization outcomes, or rendered
HTML.

All user-facing details and current dates are hydrated from authoritative rows
after revalidation.

## Authorization sequence

Every future social cache read follows this sequence:

1. Validate the authenticated account and versioned session before constructing
   a viewer key.
2. Read the viewer's current social-read generation from PostgreSQL.
3. Look up only the exact viewer/family/schema/generation/input key.
4. Treat a decoded hit as untrusted candidate input.
5. Revalidate all candidates in a bounded query against current reciprocal
   friendship, trip privacy, active lifecycle, active participant state,
   attendance, source existence, dates, wishlist/availability eligibility, and
   viewer-specific dismissal rules.
6. Hydrate names, trip/resort details, exact dates, profile/pass presentation,
   and signed capabilities from current authoritative state.
7. Drop an invalid candidate without exposing the reason.
8. If source authorization cannot be checked, return no cached social content
   or perform the bounded authoritative computation.

Authentication before lookup protects key ownership. Authorization after lookup
protects current eligibility. Both are required.

Current reciprocal friendship rows authorize friend-only data. Pending,
declined, former, one-sided, and historical connection states do not authorize.
Public trips are authenticated friend-social, not globally public. Broad
friend-presence surfaces also require public, active, date-eligible trips;
private trips never contribute to Mountains social proof.

## Transactional generations and invalidation

A future generation store should maintain a monotonic
`social_read_generation` per viewer. A source mutation increments every
viewer's generation whose derived results can change.

Generation increments:

- happen in the same PostgreSQL transaction as the authoritative mutation;
- are computed using pre-mutation relationship/trip participants when deletion
  would otherwise remove the dependency information;
- make old keys unreachable without requiring physical deletion;
- roll back with the source mutation;
- never depend on a best-effort external cache delete.

At the current graph size, bounded direct-friend fan-out is simpler and safer
than maintaining a durable cache-dependency graph. Instrument affected-viewer
counts so this decision can be revisited before high-degree fan-out becomes
expensive.

### Invalidation matrix

Families: **I** Ideas, **H** Happening, **F** friend trips, **M** mountain
social, **P** public resort/pass reference.

“Affected viewers” means the source user and reciprocal friends whose output
may use that source. For a trip, it includes the owner, currently active
participants, and eligible direct friends of those principals.

| Mutation | Required generation changes |
|---|---|
| Friendship formed | I/H/F/M for both users |
| Friendship removed | I/H/F/M for both users in the removal transaction |
| Future block/restriction state changed | I/H/F/M for both endpoints |
| Trip created | I/H/F for owner and affected viewers |
| Trip privacy changed | I/H/F for affected viewers; public-to-private is still rejected by current revalidation |
| Trip dates changed | I/H/F for affected viewers |
| Trip resort changed | I/H/F plus affected old/new resort M families |
| Trip cancelled, completed, restored, or deleted | I/H/F for affected viewers |
| Participant invited | F for participant/organizer; I/H only if current eligibility changes |
| Participant becomes Interested/Going | I/H/F for affected viewers |
| Participant declines, is removed, or otherwise becomes inactive | I/H/F for affected viewers |
| Personal attendance dates changed or cleared | I/H/F for affected viewers |
| Availability created, changed, or deleted | I for user and reciprocal friends |
| Wishlist resort added or removed | I for user and reciprocal friends |
| User pass changed | I for user and reciprocal friends when pass context affects a card |
| Ski Day created, corrected, or deleted | M for user and reciprocal friends; I only if Ideas later consumes Ski Days |
| Social/profile privacy changed | Every family whose rules use that setting, for user and reciprocal friends |
| Account deleted | Capture affected viewers before deletion; increment their I/H/F/M generations and remove the deleted viewer's payloads best-effort |
| Resort/pass reference changed | P; social families only if eligibility/ranking, rather than presentation alone, changes |
| Idea/Happening dismissal changed | The matching family for that viewer only |

Current RSVP access is granted only by Interested and Going. Pending, Declined,
and Removed are not active participation. Going-only attendance overrides are
cleared on non-Going transitions. Terminal trips require explicit exclusion;
future dates and public metadata do not make a completed/cancelled trip live.

## TTL contract

- Target social candidate TTL: 60 seconds with jitter.
- Negative-result TTL: at most 30 seconds.
- Performance TTL: may increase only after measurement and privacy tests.
- Emergency absolute upper bound: five minutes for social candidates.
- Public non-social reference upper bound: one hour unless a separately
  reviewed immutable/versioned contract applies.
- Reads do not extend expiry.
- Authenticated browser/proxy caching follows the same privacy boundary. A
  response containing current friend-derived facts is non-storable unless the
  client participates in an approved generation-validation protocol before
  display.

TTL bounds delayed additions, omissions, ranking changes, and missed
non-privacy invalidations. Friendship/session revocation, trip privatization,
participant removal, terminal transitions, and account deletion must not rely
on TTL.

## Fail-closed behavior

| Failure | Required behavior |
|---|---|
| Generation update fails | Roll back the authoritative mutation once caching is enabled |
| Generation cannot be read | Bypass social cache; never guess |
| Cache unavailable or times out | Use bounded PostgreSQL computation or a defined empty/degraded section |
| Unknown version, malformed payload, wrong viewer, or generation mismatch | Treat as miss and emit an aggregate metric |
| Current authorization/source revalidation fails | Render no cached social candidates |
| Candidate references missing/ineligible data | Drop it without revealing why |
| Cache write fails after authoritative read | Return the authoritative result and record the write failure |
| Metrics/logging fails | Preserve request and authorization semantics |

Fallback must be load-bounded so a cache outage does not create an unbounded
database miss storm. Load shedding may omit a social section; it may not serve
stale private data.

## Versioning and race safety

Every key and payload includes family, cache-schema version, ranking/semantic
version, viewer ownership, generation, and absolute expiry. A payload-shape,
eligibility, ranking, or privacy-dependency change increments the family
version. Namespace rotation is the emergency global disable; mass deletion is
not required for correctness.

For recomputation:

1. Read generation before computing.
2. Compute outside cache locks and without holding a database transaction while
   waiting on network coordination.
3. Read generation again before writing.
4. Discard the write if generation changed.
5. Include generation in the key so a stale writer cannot overwrite a newer
   value.

Use process-local single-flight for an initial pilot, with bounded wait and
authoritative fallback. Jitter expiry. Do not add a distributed lock in V1;
bounded duplicate computation is safer than unnecessary coordination
complexity.

## Recommended architecture

The smallest appropriate architecture is:

1. PostgreSQL remains the authoritative data and future generation store.
2. Add privacy-safe baseline instrumentation with no social cache.
3. If Ideas has a demonstrated bottleneck and cheap bounded revalidation, use a
   bounded per-process memory cache for minimal Ideas candidates.
4. Read the PostgreSQL generation and revalidate on every request so worker-local
   staleness cannot grant access.
5. Continue ETags for deterministic payload transfer and request-local
   memoization for repeated same-request work.
6. Evaluate shared Redis only if a useful process-local pilot has materially
   poor cross-worker hit rates.

Production rate limiting already requires shared TLS Redis. That does not make
the limiter backend automatically appropriate for social caching. Any reuse
requires an isolated namespace, strict connect/read timeouts, bounded payload
and memory limits, and evidence that cache load cannot impair security-critical
rate limiting. A separate logical database or service remains an open
operational decision.

Do not introduce database-backed payload caching or precomputed social tables in
V1.

## Surface-specific strategy

### Ideas

Ideas is the only initial social candidate because its SQL performs the broadest
source expansion and ranking. Cache minimal candidate descriptors only.
Revalidate reciprocal friendship, public active trip state, active
participation, current availability/wishlist intersections, dismissals, and
source existence on every hit. Hydrate all presentation and capabilities after
that check.

If revalidation costs nearly as much as the existing bounded query, do not ship
the cache; optimize the authoritative query instead.

### Happening

Measure separately. A future cache may hold viewer-scoped trip/occurrence IDs
only. Recheck reciprocal friendship, public visibility, active lifecycle,
active RSVP, effective attendance dates, future eligibility, dismissals, and
source existence. Do not share an Ideas payload or semantic version.

### Friends

Keep relationship and profile reads authoritative. A relationship check may be
memoized only within one request. Never store a global “A may see B” fact.

### Trips

Do not cache private or participant-rich cards/details in V1. A future candidate
cache contains trip IDs only and rechecks privacy, lifecycle, dates, owner
relationship, active participation, and attendance. ETags can reduce payload
transfer but do not replace server authorization.

### Mountains

Split public resort/pass presentation from social `friend_count` before further
cache work. Keep the public payload independently cacheable, but make the
authenticated social-count response non-storable in the browser and
intermediaries and recompute it authoritatively. Preserve the current all-time
distinct friend-owner semantics: trip dates and participant status do not
affect this count. Private and terminal trips never contribute to social proof,
even when the viewer can access a private trip through another path.

## Privacy-safe observability

Record aggregate metrics by cache family:

- hit, miss, negative hit, and expiry;
- decode/version rejection;
- generation mismatch and stale-write rejection;
- recomputation count and duration;
- revalidation input/accepted/rejected counts;
- generation increment count, affected-viewer count bucket, and failure;
- single-flight wait/timeout and duplicate computation;
- backend timeout/error and database fallback;
- payload-size and entry-age buckets.

Reuse request correlation and allowlisted structured logs. Do not log cache
keys, viewer/source/friend/trip IDs, viewer-linked resort IDs, exact dates,
names, tokens, payloads, credentials, or raw fan-out lists.

## Required safety tests

Before enabling any social cache, prove:

- one viewer can never read another viewer's entry;
- friendship removal immediately rejects stale Ideas, Happening, friend-trip,
  Mountains, and mountain-social candidates;
- future block/restriction changes revoke stale results;
- trip public-to-private, terminal transition, and deletion reject stale IDs;
- participant decline/removal and attendance clearing reject stale results;
- availability and wishlist deletion remove stale overlap details;
- pass changes cannot preserve stale personalized copy;
- Ski Day correction/deletion cannot preserve stale friend-derived facts;
- account deletion rejects the account and removes it from friends' cached
  candidates;
- missing source rows, malformed values, unknown versions, expired values, and
  generation mismatches are misses;
- source rollback does not advance generation;
- source mutation and generation update are atomic;
- recomputation racing with mutation cannot write into the new generation;
- two app processes observe generation revocation;
- a slow/unavailable cache falls back without stale disclosure;
- concurrent misses are bounded and do not hold database transactions;
- hit and miss paths return identical authorized output;
- metrics and logs contain no private identifiers or payloads.

The existing Mountains suite must add mutation-without-manual-cache-clear cases.
It must also assert that a response containing `friend_count` is non-storable
and include an integration/browser-cache simulation proving a previously
fetched body cannot be reused after friendship removal, trip public-to-private,
trip terminal transition/deletion, or account deletion. Tests must distinguish
the current owner-trip count from participant-derived or future-only semantics.
PostgreSQL is required for transaction and concurrency tests; retain SQLite
coverage where the application suite requires cross-dialect behavior.

## Staged rollout

1. **Baseline:** measure latency, query count, and result bounds for Ideas,
   Happening, Friends, friend trips, overlaps, and Mountains social counts.
2. **Decision gate:** proceed only for sustained measurable cost with a
   materially cheaper bounded revalidation path.
3. **Generation dark launch:** implement transactional generations and the full
   revocation tests while cache reads remain disabled.
4. **Development pilot:** enable per-viewer Ideas candidates only.
5. **Shadow verification:** compare hit-path output with authoritative output and
   emit aggregate divergence metrics without payloads.
6. **Later limited Production task:** use a kill switch, small cohort, 60-second
   TTL, and immediate bypass.
7. **Selective expansion:** consider Happening only after Ideas proves lower
   latency/database work without privacy or correctness regressions.

No Production rollout is part of BL-145.

## Explicitly do not cache

- authentication, visibility, friendship, or session decisions;
- complete social cards or rendered HTML;
- raw availability, exact friend travel dates, or Ski Day history;
- private trip details or participant rosters;
- signed capabilities, CSRF/session data, or secrets;
- globally shared friend-derived rankings;
- profile data copied merely to avoid a current authoritative join;
- any result without measured cost and a cheaper safe revalidation path.

## Open decisions for later implementation

- The latency/query threshold that justifies an Ideas pilot.
- The acceptable generation fan-out at measured graph size.
- Whether process-local hit rate is sufficient before evaluating Redis.
- Redis operational isolation from rate limiting, if Redis is evaluated.
- The exact empty/degraded Home presentation during authoritative-source
  failure.
- The schema and transaction integration of a future generation store.

## Verdict

BaseLodge may cache selected social candidate retrieval only when values are
minimal, viewer-owned, versioned, generation-fenced, and fully reauthorized
before display. The immediate work is instrumentation and remediation of the
existing TTL-only Mountains friend-count cache, not new cache infrastructure.

Privacy revocation remains authoritative and immediate regardless of cache
state.