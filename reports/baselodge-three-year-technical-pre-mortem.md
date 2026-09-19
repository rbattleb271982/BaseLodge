# BaseLodge Three-Year Technical Pre-Mortem

**Investigation date:** September 2026
**Evidence boundary:** Repository, tests, migrations, configuration, documentation, and safe local Git inspection only. No Production system, live user data, or deployed runtime was accessed.
**Interpretation rule:** Population-level consequences below are scenario analysis, not observations of Production traffic or capacity.

## 1. The 2029 Pre-Mortem

It is September 2029. BaseLodge found real demand, but the system did not become technically durable. The likely failure was not that PostgreSQL suddenly stopped working at 50,000 registered users, nor that Flask was intrinsically incapable of serving the product. The more plausible chain was narrower and more operational:

First, the product’s most valuable surface—Home and its social intelligence—continued to assemble many user-specific facts synchronously. The cost was driven by reciprocal-friend degree, availability dates, active trips, participants, activity history, and simultaneous seasonal opens, not by the average account count. The application had useful caps, pagination, indexes, timing logs, and extracted services, but no repository evidence established representative query plans, worker capacity, connection budgets, or p95/p99 behavior at the high-degree and seasonal tails. A growth shock therefore exposed the tail before average metrics made the problem obvious.

Second, the remote-server Capacitor design made a web deployment a de facto mobile release. Native binaries loaded `https://app.baselodgeapp.com` rather than carrying an independently deployable frontend (`capacitor.config.json:2-23`). As native adoption grew, an HTML, session, JavaScript, push, or deep-link regression could affect browser and mobile users together, while old binaries remained in the field. The repository does contain push-tap replay and deep-link handlers (`static/js/bl-native.js:1367-1610`) and Android intent filters (`android/app/src/main/AndroidManifest.xml:20-45`); what it does not prove is end-to-end behavior across cold/warm/resume, authentication, stale payloads, and binary/version combinations. The product could therefore deliver notifications that did not reliably take users to the authorized thing they meant to see.

Third, social privacy and lifecycle semantics became harder to reason about as history accumulated. The repository shows strong reciprocal visibility predicates, signed viewer-bound Availability capabilities, CSRF enforcement, database uniqueness, and explicit deletion cleanup. It also shows legacy and normalized Availability representations, two trip-creator concepts, parallel trip models, JSON payloads without foreign keys, session-scoped notification acknowledgement, and mixed retention after account deletion. `/api/mountains-data` is a protection, not an established stale-cache defect: stable resort reference data may be process-cached, but viewer-derived values are computed dynamically and the endpoint returns `Cache-Control: private, no-store` (`app.py:6584-6700`). The remaining privacy question is whether every other consumer and lifecycle path has equivalent current-state and revocation coverage. None of these facts proves a current catastrophic breach. Together they create a growing surface where an unverified reader, deletion/worker race, or unclear retention policy could turn a local defect into a privacy incident or an expensive support and compliance problem.

Finally, the organization learned about these failures too late because operational evidence lagged behind architectural intent. CI is substantial and intentionally isolated from live environments. Release identity and database-target checks are real controls. The message outbox has leases, uniqueness, provider-phase boundaries, `delivery_unknown`, bounded batches, and worker fencing. But the repository does not prove the live worker deployment, database pool budget, queue SLO, restore RPO/RTO, aggregate alert activation, production schema parity, or native release compatibility. When a provider outage, migration lock, seasonal burst, or bad hosted script occurred, the team had logs and components but not a sufficiently rehearsed measurement-and-recovery loop.

This is a causal hypothesis, not a claim that these incidents have happened.

**[F-01]** Query/runtime pressure is the first scale concern.

**[F-03]** Native/web compatibility is the mobile availability concern.

**[F-04]** Private-projection revocation is the authorization concern.

**[F-06]** Deletion capacity is the transaction concern.

**[F-07]** Mixed local retention is the policy-alignment concern.

**[F-08]** Attention/delivery is the projection concern.

**[F-09]** Security assurance is the privilege/abuse concern.

**[F-10]** Recovery evidence is the operational concern.

**[F-11]** External-provider data custody and retention are the external-deletion evidence concern.

**[F-12]** Mature-scale provider/platform exit and portability are the business-continuity concern.

**[F-13]** Concentrated orchestration and change coupling are the maintainability concern.

The report therefore focuses on measured pressure variables and explicit high-leverage boundaries before scale makes them expensive. A Flask MPA does not imply a rewrite; the relevant question is whether current boundaries remain safe under the intended traffic, data, and lifecycle distributions.

## 2. Executive Findings

The following register is canonical. Each finding has one evidence, severity, and timing classification. Later claims and recommendations identify their supporting finding explicitly; no section heading supplies a classification.

### F-01 — Home/social reads have the highest unmeasured scale exposure

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Before ~10K users

`app.py:12939-13435` assembles connection activity, next-trip candidates, reciprocal friends, friend passes and attendance, Needs You, Availability, Home Ideas, and Happening in one request. `services/ideas_retrieval.py`, `services/ideas_engine.py`, and `services/happening.py` perform social and date-sensitive work. The relevant variable is reciprocal friends × availability dates × active trips/participants × concurrent Home opens. Result caps do not prove that joins and authorization work are bounded before the final result. The repository has component timing logs and deliberate reuse of Availability (`app.py:13111-13117`), but no representative 1K/10K/50K query-plan or concurrency evidence.


### F-02 — Runtime capacity is not inferable from the repository

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Structural
- **Timing classification:** Trigger-based

`.replit:46-49` runs Autoscale with exactly two Gunicorn workers. `gunicorn.conf.py` only contains analytics fork/exit hooks; it does not establish worker, thread, timeout, or database-pool sizing. `runtime_config.py:58-68` sets recycle/pre-ping/connect timeout but not the deployed connection budget. Whether two workers and the effective database limit are adequate is unknown, not a demonstrated defect. The trigger for capacity action is representative peak traffic exceeding p99, pool-wait, queue-time, or timeout/error thresholds.


### F-03 — The remote native shell turns hosted web compatibility into mobile availability

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

`capacitor.config.json:2-23` points the app at `https://app.baselodgeapp.com`; `static/js/bl-native.js` supplies startup, push, diagnostics, bridge behavior, push-tap replay (`:1367-1487`), and `appUrlOpen` handling (`:1516-1610`). Android intent filters exist in `android/app/src/main/AndroidManifest.xml:20-45`. A hosted template, session, or JS change can affect installed binaries without an app-store release. At 50K users, a modest incompatibility becomes a fleet incident. The repository has bounded bridge waits, retries, startup overlay states, allowlisted navigation, diagnostic beacons, tap handling, and deep-link registration, but not evidence of canarying, version gating, offline fallback, or complete tested behavior across cold/warm/resume, auth, stale payload, and binary/version combinations.


### F-04 — Unverified private-projection consumers need revocation coverage, not broader caching

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

`services/visibility.py:17-138,196-271` provides strong current-state reciprocal and capability checks. `docs/engineering/social-intelligence-cache-foundation.md:53-157` correctly warns that raw Availability and viewer-scoped social facts are not ordinary cache data. `app.py:4301-4311` caches stable active-resort reference data only. `/api/mountains-data` computes viewer-derived friend counts dynamically and returns `Cache-Control: private, no-store` at `app.py:6584-6700`; it is therefore a current protection and **not** a demonstrated stale-cache failure. The unresolved finding is narrower: repository inspection does not prove equivalent current-state/revocation coverage for every other private projection or future consumer.


### F-05 — Data semantics accumulate compatibility debt

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Before ~10K users

`models.py` retains legacy and canonical forms: `User.open_dates` beside normalized `UserAvailability` (`models.py:167,548-565`), legacy and canonical resort/trip columns (`models.py:568-776`), `SkiTrip.user_id` and `created_by_user_id`, and legacy `GroupTrip`/`TripGuest` beside `SkiTrip`. JSON event and message payloads are not foreign-key constrained (`models.py:1781-1786,1831-1848,1928-1983,2102-2185`). This is not proof of runtime corruption. It does mean a future feature, backfill, deletion, or rollback must preserve more semantic versions.


### F-06 — Account-deletion capacity and worker races remain unmeasured

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

**[F-06]** `app.py:18692-18972` performs fresh-authenticated, CSRF-protected, ordered cleanup and commits deletion. Tests cover important SQLite/PostgreSQL behavior (`tests/test_account_deletion.py`, `tests/test_account_deletion_postgres.py`). The transaction nevertheless spans trips, child rows, histories, messages/events, outbox references, tokens, relationships, and JSON-bearing records. This finding is about transaction capacity and worker races only.
**[F-07]** Retention behavior is classified independently below.

The scaling variable is rows linked to one heavy account plus concurrent worker/provider activity. The repository does not establish heavy-account duration, lock behavior, rollback/WAL cost, or delete-vs-worker outcomes.

### F-07 — Demonstrated mixed retention and residual identity behavior needs policy alignment

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

The account-deletion path demonstrably retains or anonymizes some historical/projection records by design: the retention investigation documents surviving MEL/outbox references and grouped Activity/deleted-trip references (`reports/account-deletion-message-retention-investigation.md`). JSON-bearing `Activity`, `Event`, MEL, and outbox fields are not all foreign-key constrained (`models.py:1781-1786,1831-1848,1928-1983,2102-2185`). The evidence supports a credible privacy, support, and compliance risk because local retention, redaction, and identity semantics are mixed and policy alignment is incomplete. This does not claim a legal/privacy-promise violation.

**[F-11]** External-provider retention remains an unverified data-custody evidence gap.

### F-08 — Notification/attention projections and delivery are not one universal state machine

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Before ~10K users

`Activity` stores recipient/actor/object and JSON but no per-item read/resolved/delivery state (`models.py:1831-1851`). `/notifications` caps Activity at 50 and Home action display at 12 (`app.py:13987-14208`; `reports/bl571-attention-architecture-review.md`). Viewed state is session-scoped, while domain resolution occurs elsewhere. This correctly separates “what happened” from “what needs action,” but creates reconciliation obligations across routes, badges, Activity, outbox messages, and domain state.


`services/message_outbox_worker.py:215-261` commits a provider-start boundary and classifies post-start uncertainty as `delivery_unknown`, avoiding unsafe blind duplicates. `models.py:2102-2199` and `services/message_outbox.py` provide uniqueness, leases, bounded retries, dead letters, and fencing. This is a strength, not a naive inline-send design. The unresolved risk is queue age, provider reconciliation, unknown-row retention, and operator replay at seasonal volume.


### F-09 — Security assurance and abuse budgets are not fully evidenced

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

`app.py:1999-2009` authorizes admin routes through an email allowlist; repository inspection does not establish whether deployment-level MFA, step-up controls, or complete admin audit evidence exists outside the repository. Separately, `app.py:455-463` leaves default rate limits empty and applies selected endpoint limits, while `services/rate_limit_storage.py:17-45` correctly rejects process-local limiter storage in Production and requires TLS Redis. The finding is an assurance gap: adequacy against privileged-account compromise and distributed abuse is not established, not a demonstrated admin defect.

The relevant variables are privileged-account/session exposure, distributed identity/IP cardinality, expensive-read volume, and endpoint-specific budgets—not registered users.

### F-10 — Restore, alert, and environment parity are not operationally proven

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Existential
- **Timing classification:** Now / ~1K users

`.github/workflows/ci.yml` provides meaningful disposable PostgreSQL, migration, concurrency, full pytest, JS, and source-integrity checks. `replit.md:79-93` says CI does not connect to Development/Production and branch protection is not configured by the repository. `docs/production-incident-alert-policy.md:18-24` records uptime/request/duration/CPU/memory views and thresholded diagnostics, but no successful-request denominator, percentile, queue-depth, provider aggregate, or active custom-alert proof. Repository backup artifacts and an attached operator report do not prove RPO/RTO or restore drills.

The trigger for change is not a calendar or user count: it is failure to meet a rehearsed restore objective, inability to detect queue/provider degradation, or schema/runtime parity drift.

### F-11 — External-provider data custody and retention are not proven

- **Evidence classification:** Unknown / unproven assumption
- **Severity classification:** Structural
- **Timing classification:** Now / ~1K users

**[F-11]** Repository/local deletion evidence cannot prove what external messaging, push, analytics, storage, or email providers retain, export, suppress, or delete. Provider contracts, deletion responses, export mappings, and retention controls were not verified within the repository boundary.

### F-12 — Business-critical provider/platform exit paths are not rehearsed

- **Evidence classification:** Plausible risk
- **Severity classification:** Structural
- **Timing classification:** Before ~50K users

**[F-12]** Direct provider paths and provider-specific token, event, suppression, and data semantics can make a mature-scale exit expensive if export and substitution are not rehearsed. This is a portability scenario, not evidence that a provider exit is currently blocked.

### F-13 — Concentrated orchestration creates change-coupling risk

- **Evidence classification:** Evidenced risk
- **Severity classification:** Structural
- **Timing classification:** Before ~50K users

**[F-13]** The concentrated `app.py` orchestration surface gives shared helpers, hooks, template context, visibility predicates, and migration-related changes a broad incident radius. Existing extraction and tests make incremental ownership boundaries viable; this is not a claim that a wholesale rewrite is required.

## 3. Architecture Map

### Request and rendering boundary

BaseLodge is a Flask/SQLAlchemy/Jinja2 server-rendered multi-page application with Vanilla JavaScript and AJAX enhancements (`replit.md:16-29`; `templates/base_app.html`; `static/js/`). `app.py` is approximately 28,000 lines and contains initialization, configuration, auth/session, CSRF, migrations/backfills, query helpers, Home, mountains, friends, profile, trips, messaging administration, health, and release identity. Extracted services include `services/ideas_engine.py`, `services/ideas_retrieval.py`, `services/open_dates.py`, `services/happening.py`, paging services, visibility, messaging, and request observability. The accurate characterization is concentrated orchestration with meaningful service extraction—not “no modularity.”

Typical logged-in pages extend `templates/base_app.html`, with page-specific scripts and styles. Primary surfaces include `templates/home.html`, `my_trips_redesign.html`, `friends.html`, `mountains_tab.html`, `profile.html`, `notifications.html`, `trip_detail.html`, and planning/invite pages.

### Identity and authorization

Flask-Login sessions and remember cookies protect web routes. Credential changes version identity, CSRF is centrally enforced for unsafe methods (`app.py:579-632`), and Production refuses missing session secrets (`app.py:725-743`). `services/visibility.py` requires reciprocal directed friendship for friend visibility and uses signed viewer-bound Availability capabilities and trip capability checks. Route-specific code remains in `app.py`, so shared policy is a control and a review obligation.

### Domain and database boundary

`models.py` contains users, resorts, passes, trips, participants, invites, friendships/history, Availability, Ski Days, activity/events, email logs, push tokens, and durable message outbox/event logs. Alembic migrations under `migrations/versions/` evolve the schema. Foreign-key actions mix CASCADE, SET NULL, RESTRICT, and implicit behavior. PostgreSQL is the intended production data store; SQLite remains useful for local tests.

### Social and planning reads

Home combines multiple social projections. Mountains loads a shell and `/api/mountains-data` rather than embedding a prior approximately 210 KB catalog in HTML; `app.py:6539-6700` documents an approximately 20 KB shell and grouped friend-trip counts. My Trips uses cursor pages of 20 in `services/my_trips_paging.py`; Friends’ Trips has separate paging and eager loading. These are positive controls, though candidate-query cost still requires measurement.

### Native boundary

Capacitor iOS and Android projects exist, but `capacitor.config.json` sets the hosted server URL and a navigation allowlist. `static/js/bl-native.js` handles WebView startup, splash, bridge/plugin discovery, push registration, diagnostics, foreground notification behavior, push-tap replay, and `appUrlOpen` deep links; Android intent filters are present in `android/app/src/main/AndroidManifest.xml:20-45`. The installed binary and hosted web app therefore have separate release cadences but a shared runtime contract. The evidence gap is end-to-end lifecycle/version testing, not absent handlers.

### Messaging and operation

Message intent is represented by `MessageOutbox`; worker modules claim bounded batches, lease rows, fence ownership, record provider phase, and quarantine ambiguous provider outcomes. Push paths include direct APNs/FCM code and OneSignal code; Capacitor and OneSignal native paths coexist. `.replit` publishes Autoscale with two Gunicorn workers. CI runs disposable PostgreSQL and source-integrity checks. `/health`, release identity, request diagnostics, Replit monitoring, and incident-policy documentation exist, but live activation and historical baselines are unknown.

## 4. Deep Analysis

### 4.1 Application architecture and maintainability

**[F-13] Finding — shared orchestration has a large incident radius.**

**[F-13]** The concentration in `app.py` means a shared helper, request hook, template context, visibility predicate, or migration-related change can affect many surfaces. The scaling variable is feature count, lifecycle combinations, and number of engineers changing shared code—not users alone. At ~1K users, manual and focused test feedback may be enough. Around ~10K, more concurrent feature work and more long-lived data combinations increase regression probability. Around ~50K, the same regression has a larger blast radius and longer diagnosis path.

- **Supporting finding:** F-13
- **Timing classification:** Before ~50K users
- **Recommendation:** Map ownership and extract targeted boundaries where measured coupling justifies it; do not pursue a wholesale rewrite.

**[F-01] Partial-failure behavior deserves observability.** Home has multiple `try/except Exception` sections (`app.py:12957-13173`) that roll back and continue with empty or reduced sections. Graceful degradation is valuable, but a hidden empty friend or Needs You section can become a product correctness issue.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Log and count fallback reasons distinctly; do not treat an empty result as equivalent to a successful empty result.

### 4.2 Performance and speed

**[F-01] Home and social intelligence.** `app.py:12939-13435` performs the synchronous reads described above. `docs/engineering/social-intelligence-cache-foundation.md:29-51` correctly identifies Home Ideas as likely social-read cost. At 1K, low-degree users may stay within budget. At 10K, high-degree tails and seasonal trip density matter. At 50K, concurrent tail users can dominate database CPU even if average latency is acceptable.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure rows examined versus returned and `EXPLAIN (ANALYZE, BUFFERS)` on representative synthetic distributions.

**[F-01] Activity history.** Home connection activity uses `.all()` (`app.py:12957-12976`) before building dismissed-ID lists. The scaling variable is per-account activity history, not population. It may be harmless for ordinary accounts and pathological for a long-lived/high-activity account.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish retention or bounded query behavior if measurements show activity history is material.

**[F-01] Trip pages.** Cursor paging, 20-row pages, and deferred Friends’ Trips are appropriate (`services/my_trips_paging.py`, `services/friends_trips_paging.py`, `app.py:6131-6325`). Pagination is not evidence of a defect. It does not prove candidate joins are bounded before limiting.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Monitor query plans for high-degree users.

**[F-01] Mountains and assets.** Shell-only Mountains HTML, grouped friend counts, process-local stable resort cache, content-derived asset versioning, immutable one-year static caching, and Flask-Compress (`app.py:3948-3960,1889,432-436,6539-6700`) are good controls. Remaining variables are resort catalog size, friend-trip aggregation, JSON serialization, and mobile parse/memory. Client-side full-catalog filtering can become a download cost if the catalog grows materially.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure bytes and device timing before changing client-side catalog filtering.

**[F-01] Prefetch.** `static/js/bl-intent-prefetch.js` restricts prefetch to five paths and deduplicates per page. It is not an unbounded loop. It can multiply load by intent × abandonment.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure prefetch-to-navigation conversion and separate prefetch traffic in request metrics before changing prefetch.

**[F-04] Caching.** Stable resort facts and immutable assets are appropriate cache candidates. Authorization, raw Availability, private trip detail, and friend-derived mutable facts are not ordinary shared-cache data.
- **Supporting finding:** F-04
- **Timing classification:** Now / ~1K users
- **Recommendation:** Obtain invalidation/revocation evidence before adding broader caching.

### 4.3 Replit/platform suitability

**[F-02]** The current repository config uses Replit Autoscale with two Gunicorn workers (`.replit:46-49`). Current official documentation describes Autoscale as adding servers with traffic and scaling to zero when idle; machine power and maximum instances are configurable: [Deployment types](https://docs.replit.com/features/publishing/deployment-types), [Machine configuration](https://docs.replit.com/features/publishing/machine-configuration). Replit describes Reserved VM as suitable for always-on background workers and persistent APIs: [Deployment types](https://docs.replit.com/features/publishing/deployment-types).

**[F-02]** Keeping the Flask web app on Autoscale is reasonable if health, p95, DB pool, and cold-start measurements meet targets. The message worker is architecturally intended for a separate Reserved VM (`docs/engineering/continuous-message-worker.md`), but whether that VM exists and is supervised is unknown.
- **Supporting finding:** F-02
- **Timing classification:** Now / ~1K users
- **Recommendation:** Keep the web app on Autoscale conditionally and verify supervised always-on worker capacity.

- **Supporting finding:** F-02
- **Timing classification:** Before ~10K users
- **Recommendation:** Keep the web app on Replit provisionally while measuring concurrency and seasonal burst capacity; revisit the worker configuration when predeclared queue, pool-wait, or p99 thresholds are breached.
- **Supporting finding:** F-08
- **Timing classification:** Trigger-based
- **Recommendation:** Move or isolate the outbox worker when its current deployment cannot meet queue-age SLOs.

- **Supporting finding:** F-12
- **Timing classification:** Before ~50K users
- **Recommendation:** Reassess provider/platform exit after representative load and failure-isolation tests; do not migrate solely because the account count reaches 50K.

**[F-10]** Replit documents monitoring for uptime, request metrics, response durations, and resource usage and supports custom domains/geography: [Published App Monitoring](https://docs.replit.com/features/publishing/monitoring-a-deployment), [Project geography](https://docs.replit.com/features/publishing/project-geography). It also documents point-in-time database restoration with a 7-day Core or up to 28-day Pro/Enterprise retention window, and warns that restoring data does not roll back application code: [Data recovery](https://docs.replit.com/features/data-and-storage/data-recovery). Those capabilities are not proof that BaseLodge has configured, tested, or meets its own RPO/RTO.

### 4.4 Database and long-term data integrity

**[F-05] Canonical/legacy duplication.** Availability has normalized `UserAvailability` with unique `(user_id,date)` and legacy `User.open_dates`; resort and trip data also retain legacy fields. This creates a compatibility burden. Availability and Trips are intentionally independent—Availability is possibility, not commitment—so a conflicting date is not itself corruption. The risk is a future reader that silently treats one as authoritative.

**[F-05] Trip ownership semantics.** `SkiTrip.user_id` and `created_by_user_id` can differ. Account deletion nulls creator references for surviving trips (`app.py:18935-18941`). Authorization, analytics, notification, and deletion code therefore depend on documented organizer-versus-creator semantics.

**[F-05] Histories and JSON.** Friend, RSVP, lifecycle, Activity, Event, MEL, and outbox records have different delete/anonymization behavior. JSON fields can retain IDs, names, URLs, or evidence without FK cleanup. At 50K and three years, JSON retention and redaction become a batch/data-governance problem.
- **Supporting finding:** F-05
- **Timing classification:** Before ~10K users
- **Recommendation:** Run disposable-DB deletion scans and inventory JSON schemas.

**[F-05] Constraints are a strength.** Participant/invite uniqueness, canonical friend pairs, Availability uniqueness, push-token uniqueness, and outbox logical uniqueness are database-backed (`models.py:499-529,548-565,1252-1298,1479-1494,1864-1884,2170-2199`).
- **Supporting finding:** F-05
- **Timing classification:** Before ~10K users
- **Recommendation:** Keep these database-backed constraints rather than replacing them with UI-only validation.

**[F-05] Migrations.** Long Alembic history, startup schema/FK reconciliation (`bl306_mpv_fk_reconcile.py`, `bl317_startup_schema.py`), and target checks are mature controls. The risk is lock duration, backfill time, forward/rollback compatibility, and drift between PostgreSQL versions/environments. CI uses PostgreSQL 17 while `.replit` documents PostgreSQL 16; compatibility impact is unknown.

### 4.5 Security and privacy

**[F-09] Current protections.** Password hashing, credential-versioned Flask-Login identity, Secure/HttpOnly/SameSite production cookies, signed remember tokens, fresh-auth deletion, global unsafe-method CSRF, reciprocal visibility, viewer-bound one-hour Availability capabilities, terminal trip mutation guards, Redis-only production rate limiting, and target identity checks are demonstrated in `app.py`, `services/visibility.py`, `runtime_config.py`, and tests. These are not hypothetical controls.

**[F-09] Admin boundary.** `admin_required` is email allowlist-based (`app.py:1999-2009`). Repository inspection cannot establish whether deployment-level MFA/step-up or complete audit controls exist outside the repository. An allowlisted-session compromise would have a broad blast radius, so authorized admin-assurance evidence is needed; this is not a demonstrated admin defect.

**[F-09] Abuse controls.** `default_limits=[]` with selected sensitive route limits means a distributed authenticated scraper may still create expensive social-read load.
- **Supporting finding:** F-09
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure request cardinality, search/invite enumeration, and expensive-route budgets; do not infer that Redis alone solves abuse.

**[F-09] Analytics/logs.** `analytics.py:77-116,203-205` applies denylist sanitization and logs some diagnostics. Denylists can miss new sensitive fields such as dates, IDs, or location combinations. `services/log_privacy.py` is positive evidence but not proof of future-path coverage.
- **Supporting finding:** F-09
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish an event-schema allowlist and redaction tests before adding richer social payloads.

**[F-04] Stale authorization/cache.** The shared visibility service is strong; a stale-friendship defect is not demonstrated. `/api/mountains-data` is explicitly protected with dynamic viewer-derived values and `private, no-store` (`app.py:6584-6700`), while `get_all_active_resorts_map()` caches stable reference data only (`app.py:4301-4311`). The remaining scope is unverified coverage in other consumers or future projections.
- **Supporting finding:** F-04
- **Timing classification:** Now / ~1K users
- **Recommendation:** Test every consumer after unfriend, trip terminalization, deletion, and Availability changes.

**[F-09] Remember and native sessions.** Signed 30-day remember tokens are bearer credentials, though credential changes revoke identity. Logout deactivates all active push tokens because there is no per-session device ID (`app.py:18430-18441`). This is an intentional tradeoff with multi-device consequences, not proof of account takeover.

**[F-09] Authentication/session/authorization lifecycle coverage.** The lifecycle is best evaluated as a sequence rather than isolated route checks: signup/login or OAuth callback establishes Flask-Login identity; remember restoration applies a signed, versioned credential; unsafe requests require the CSRF token; social reads apply current reciprocal visibility; deletion requires fresh authentication and then removes or anonymizes relationships. Existing tests such as `tests/test_auth_session_lifecycle.py`, `tests/test_remember_token_age.py`, `tests/test_state_changing_route_csrf.py`, and visibility tests cover important edges. The remaining measurement/test gap is a matrix across password change, logout on multiple devices, remember restoration, session expiry, unfriend, terminal trip, deleted user, native WebView cookie persistence, and push/invite auth continuation. The relevant variables are active sessions/devices × route predicates × lifecycle transitions × hosted/native versions, not total users. Any failure should be classified under the canonical finding that it exercises; this report does not assert that the shared predicates currently fail.

### 4.6 Product/domain-model complexity

**[F-05]** BaseLodge’s domain boundaries are technically meaningful: Home is current coordination; Notifications are history; Needs You is unresolved attention; Availability is private and canonical; Open to Ski is a presentation; Trips are separate; Favorites are private/direct; Wishlist is future interest. These separations should remain.
- **Supporting finding:** F-05
- **Timing classification:** Leave alone
- **Recommendation:** Keep these domain separations.

**[F-05]** The engineering risks are duplicated state and ambiguous lifecycle ownership: legacy/canonical Availability; `SkiTrip` beside legacy `GroupTrip`; trip organizer versus creator IDs; Activity/messages as projections of domain actions; SkiDay additive synchronization into visited-resort IDs; reusable invitation tokens; and append-only histories with asymmetric deletion.

**[F-13]** The meaningful scale variables are records per account, history rows per relationship/trip, number of legacy readers and writers, number of feature surfaces consuming a concept, and frequency of semantic change. At 1K records and feature combinations may be understood manually. At 10K, larger histories and more readers make backfills and support reconciliation costly. At 50K, changing a semantic definition requires historical backfill, compatibility windows, and cross-surface reconciliation.
- **Supporting finding:** F-13
- **Timing classification:** Before ~50K users
- **Recommendation:** Measure change coupling before consolidation; do not merge boundaries without measured evidence.

### 4.7 Social graph scaling

**[F-01]** Friendship is directed with reciprocal visibility; connection history canonicalizes pairs. The relevant distribution is degree, not total users. Suggestion and social-trip queries can be inexpensive for ordinary users and expensive for a small high-degree tail. Fan-out work also scales with recipients × event types.

**[F-01]** Suggested Friends has its own paging/request/cooldown paths (`services/friend_suggestions_paging.py`, `services/outgoing_friend_requests.py`, `models.py:1479-1578`) and account-deletion cleanup (`app.py:18839-18859`). Its lifecycle is suggestion → request → withdrawal/acceptance/rejection → cooldown/cleanup; it should not be treated as a simple friend list. At 1K, adjacency, candidate, and cooldown records may be manageable. Near 10K and 50K, history rows, feature changes, and recipient/event fan-out—not account count alone—determine tail capacity and cleanup cost.
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Inspect high-degree and seasonal distributions using synthetic degree distributions rather than a uniform graph.

### 4.8 Notifications / Needs You / activity

**[F-08]** The architecture correctly distinguishes seen from resolved and recent activity from unresolved action. The risk is projection drift: multiple routes can mutate canonical state without emitting the same Activity/outbox/attention consequence. Session-scoped viewed state can also differ across devices. Latest-50 Activity and filtered terminal-trip events are product/retention choices, not automatically defects.

**[F-08]** Relevant metrics include action-to-badge reconciliation, stale counts after inline actions, missing event-emitter coverage, Activity omission percentage, and filtered terminal-history rates.
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure action-to-badge reconciliation, stale counts after inline actions, missing event-emitter coverage, Activity omission percentage, and filtered terminal-history rates.
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Use explicit retention for durable audit history rather than overloading Notifications.

### 4.9 Availability / Trips / Ski Days lifecycle

**[F-05]** Availability is destination-neutral and independent from trip attendance. Joining an overlapping trip may offer to remove Availability without silently mutating it. That separation is sound. The risk is legacy mirror drift and future code that assumes availability equals commitment.

**[F-05]** `SkiTrip.lifecycle_state` is constrained to active/completed/cancelled and terminal mutations are rejected. Participants and RSVP/history constraints are positive controls. SkiDay is historical and deleting a trip nulls provenance; deleting a user cascades it. The additive visited-resort update can leave stale IDs after corrections or deletes (`models.py:995-1125`).
- **Supporting finding:** F-05
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure provenance mismatch before altering historical semantics.

### 4.10 Native/Capacitor architecture

**[F-03]** The remote-origin model is viable at small scale and avoids shipping every web change through stores. Its failure modes are availability, compatibility, cookie/session persistence, native binary skew, and lifecycle testing. `bl-native.js` has bounded bridge waits, retries, startup overlay, diagnostics, permission handling, push-tap replay and cold-launch handling (`:1367-1487`), and `appUrlOpen` registration (`:1516-1610`). Android intent filters exist (`android/app/src/main/AndroidManifest.xml:20-45`). Those controls reduce risk but do not create offline capability or prove every lifecycle/version combination.

**[F-03]** The remaining gap is end-to-end tested behavior: cold and warm taps, logged-out invite flows, app resume, OS termination, token rotation, stale payload authorization, and older binaries against current hosted HTML. The existence of handlers means this is not an “implementation absent” finding. It is the compatibility/lifecycle evidence gap.

### 4.11 Push

**[F-03]** Direct APNs/FCM code and OneSignal/Capacitor paths coexist (`app.py:8801-8989`, `services/push_providers.py`, `static/js/bl-native.js`, `package.json`). This is flexibility but also provider identity and token reconciliation complexity. Push tokens are unique per user/token and lifecycle tests exist.

**[F-08]** OneSignal sets iOS badge to `1` (`services/push_providers.py:177-185`); no inspected authoritative unread-count reconciliation on resume/tap was found. This can be a current correctness issue for multiple notifications and devices, but scope it to OS badge semantics rather than declaring Notifications fundamentally broken.

**[F-08]** Outbox `delivery_unknown` is a sound safety boundary. Its operational cost is unknown-row accumulation, provider reconciliation, and replay policy. Provider migration cannot safely resend all unknown rows without an idempotency contract.

### 4.12 Messaging/email infrastructure

**[F-08]** The outbox is transactional, logically unique, leased, fenced, bounded, and provider-phase-aware. Worker defaults (batch 25, lease 60 seconds) are tunable, not proof of capacity. Queue age and provider latency are the real variables.
- **Supporting finding:** F-08
- **Timing classification:** Leave alone
- **Recommendation:** Keep the transactional outbox boundary.

**[F-08]** Email evidence is thinner: `EmailLog` includes type, source event, sent time, count, and environment (`models.py:1792`), but the inspected repository does not establish equivalent provider IDs, retry classes, bounce/complaint handling, idempotency, and retention for every email path.
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Measure account-recovery and invite-completion behavior before expanding email programs.

### 4.13 Caching, prefetching, and state preservation

**[F-04]** Immutable fingerprinted assets, compression, Home request-local Availability reuse, restricted intent prefetch, and server-authorized raw private/social state are appropriate controls.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Keep these caching, prefetch, and authorization boundaries.

**[F-04]** `get_all_active_resorts_map()` (`app.py:4301-4311`) caches stable reference data only. `/api/mountains-data` computes viewer-derived values dynamically and sends `Cache-Control: private, no-store` (`app.py:6584-6700`), so this endpoint is a current protection and not a cache finding. The scope is limited to unverified private-projection consumers beyond this protected path and to future changes that might introduce caching.
- **Supporting finding:** F-04
- **Timing classification:** Now / ~1K users
- **Recommendation:** Test authorization mutation/revocation across all private-projection consumers before changing cache policy.

### 4.14 Testing and CI

**[F-10]** `.github/workflows/ci.yml` runs Python compilation/dependency setup, PostgreSQL 17 tests including concurrency/cutover/account deletion, full pytest, JS tests, and source integrity. Tests cover CSRF, auth lifecycle, remember-token age, deletion, visibility, paging, query budgets, push lifecycle, rate limits, migrations, and outbox behavior.

**[F-10]** The gap is not “no tests.” CI intentionally avoids Development/Production, so it cannot prove live schema, deployment configuration, queue topology, provider behavior, native store binaries, load, or restore.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Add representative synthetic-scale and native-lifecycle tests in disposable environments before relying on population thresholds.

### 4.15 Deployment and rollback

**[F-10]** `.replit` uses a clean-checkout release SHA guard and two-worker Gunicorn Autoscale. `replit.md:73-92` documents `/health`, migration target gates, release identity, and environment separation. These are strong safety properties.

**[F-10]** Rollback is asymmetric when a migration has changed data or schema. Replit’s documented database restoration does not revert application code; code/checkpoint alignment is a separate action.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Treat nontrivial migrations as forward-compatible operations with rehearsed recovery rather than assuming code rollback restores the prior data contract.

### 4.16 Observability and diagnostics

**[F-10]** `/health`, request IDs, `[ROUTE_PERF]`, `[HOME_PERF]`, `[IDEAS_PERF]`, `services/request_observability.py`, analytics, worker heartbeat, and Replit monitoring exist. The incident policy explicitly notes absent aggregate denominators, percentiles, queue-depth/provider aggregate alerts, and active custom alerts (`docs/production-incident-alert-policy.md:18-24`).

**[F-10]** The most important observability work is not more logs. It is service-level indicators: successful request denominator and p95/p99, DB pool wait, Home component failures, cache revocation delay, outbox oldest-ready age, delivery-unknown age, native startup funnel, and restore verification.

### 4.17 Backup / restore / disaster recovery

**[F-10]** Repository backup artifacts and a dated operator note show backup activity, but do not prove retention, encryption ownership, offsite immutability, restore isolation, RPO/RTO, or checksum/row-count verification. Replit’s documented 7–28-day recovery windows may be shorter than a three-year product’s policy requirements.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Run a disposable restore drill and record code/schema alignment, not merely backup existence.

### 4.18 Third-party dependencies and portability

**[F-12]** Dependencies include PostgreSQL/Supabase-related infrastructure, Redis, SendGrid, Firebase Admin, APNs, FCM, OneSignal, PostHog, Capacitor plugins, Replit hosting/object storage, and build tooling (`pyproject.toml`, `package.json`, `replit.nix`). Direct provider paths and provider-specific semantics create migration work.
- **Supporting finding:** F-12
- **Timing classification:** Before ~50K users
- **Recommendation:** Keep abstractions that encode provider status, identity, suppression, retry, and deletion contracts.

**[F-12]** The relevant trigger for a provider move is an outage, deprecation, quota, policy, data-export, or delivery-SLO failure that cannot be mitigated within the current provider.
- **Supporting finding:** F-12
- **Timing classification:** Before ~50K users
- **Recommendation:** Run an export and substitution drill before 50K for each business-critical provider.

The repository pins or constrains Python/Node dependencies through `requirements.txt`, `pyproject.toml`, `uv.lock`, `package.json`, and `package-lock.json`, and CI installs/test-checks them (`.github/workflows/ci.yml`). The repository inspection did not establish an automated dependency vulnerability/license scan, update cadence, SBOM, or reproducible iOS/Android signing/build provenance. This is an evidence gap, not proof of a vulnerable dependency. The relevant variables are dependency age, transitive dependency count, native SDK/API compatibility, upgrade frequency, and time between security release and production adoption.
- **Supporting finding:** F-09
- **Timing classification:** Before ~50K users
- **Recommendation:** Establish dependency vulnerability/license scanning, update cadence, and SBOM coverage; review lockfile updates before unsupported dependencies become a security concern.
- **Supporting finding:** F-10
- **Timing classification:** Before ~50K users
- **Recommendation:** Establish reproducible native signing/build provenance and release verification; do not upgrade native dependencies wholesale without release evidence.

### 4.19 Maintainability / development velocity

**[F-13]** The dominant risk is change coupling, not language choice. A large `app.py`, broad client `bl-native.js`, multiple legacy models, and many product surfaces increase review and regression cost. Existing extraction and tests mean an incremental boundary strategy is viable.
- **Supporting finding:** F-13
- **Timing classification:** Before ~50K users
- **Recommendation:** Track changes by symbol, ownership, regression source, and time-to-diagnosis; do not split into microservices without a measured deployment or failure-isolation need.

### 4.20 Bus factor / documentation / operational knowledge

**[F-10]** `replit.md`, engineering docs, incident policy, migration safety, and worker runbooks are meaningful documentation. They are not proof that a second engineer can execute restore, release, worker cutover, provider reconciliation, or native rollback unaided. The signal is a failed game-day, stale runbook, unknown owner, or inability to reproduce a release—not documentation length.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Conduct a read-only takeover/recovery exercise before operational complexity grows.

### 4.21 Product philosophy as a technical constraint

**[F-08]** The product explicitly avoids manufactured urgency, FOMO, and social pressure. That supports keeping Notifications informational and Needs You resolution-oriented, along with avoiding aggressive speculative loading of private data. Technical metrics are intended to optimize reliable coordination and privacy, not notification volume or screen time. A system that achieves engagement by increasing stale badges or push pressure would be a product-system failure, not a success.

## 5. Growth-Shock Analysis

Assume demand moves from ~1K toward ~10K much faster than expected. The first failure is most likely a burst/capacity mismatch rather than raw storage. Each item below names the single finding it analyzes; recommendation timing is stated separately wherever a recommendation appears.

1. **[F-01] Concurrent Home and full-page opens.** Native resumes, browsers, and seasonal trip planning create simultaneous authenticated HTML requests. Home’s synchronous social reads consume workers and connections. Earliest signals: queue time, p95/p99, pool wait, Home component timings, 5xx/timeouts.
2. **[F-01] Database cardinality tail.** High-degree users and broad date/trip distributions make rows examined diverge from rows returned. Signal: EXPLAIN plan changes, temp files, CPU/IO, high-degree p99.
3. **[F-08] Outbox enqueue and worker lag.** Activity fan-out can exceed a batch-25 worker’s provider throughput. Signal: oldest ready age, enqueued versus claimed rate, lease expiry, provider 429/5xx, `delivery_unknown`.
4. **[F-03] Native/web coupling.** A single hosted release can fail mobile startup or push registration while the binary population is heterogeneous. Signal: startup beacon funnel, WebView render, 401/403/CSRF errors by native version.
5. **[F-09] Abuse and expensive reads.** Distributed identities can avoid simple per-user/IP limits and consume social/read capacity. Signal: unique-user/IP cardinality, low conversion, search/invite enumeration, DB saturation.
6. **[F-10] Operational detection.** Without denominators and queue/provider alerts, a degraded service can look like a few isolated errors. Signal: discrepancy between user reports and available aggregate metrics.

- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish synthetic-load baselines, connection/worker budgets, and Home budgets.
- **Supporting finding:** F-06
- **Timing classification:** Now / ~1K users
- **Recommendation:** Establish a deletion budget.
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish outbox SLOs.
- **Supporting finding:** F-03
- **Timing classification:** Now / ~1K users
- **Recommendation:** Establish native compatibility tests.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Establish restore and alert drills.
- **Supporting finding:** F-02
- **Timing classification:** Trigger-based
- **Recommendation:** Tune Autoscale machine/instance settings, worker batch/concurrency, or query indexes only when measured plans justify them; do not introduce distributed architecture during an incident.

## 6. Evidence Gaps

The table below is an inventory of missing evidence, not a recommendation list; actionable work is stated in the local recommendation blocks in Sections 5, 8, 9, and 10.

| Canonical ID | Unknown | Why it matters | Evidence needed | Timing classification |
|---|---|---|---|---|
| F-01 | Production route p50/p95/p99 | Determines whether Home and synchronous reads are adequate | Authorized Replit monitoring plus request/DB metrics, segmented by route | Before ~10K users |
| F-02 | Runtime concurrency | Determines whether two workers are adequate | Authorized Replit monitoring plus queue and DB metrics | Now / ~1K users |
| F-02 | DB pool/max connections/locks/plans | Worker increases can worsen connection contention | Runtime config inspection and synthetic PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` at graph/data distributions | Now / ~1K users |
| F-01 | Home tail behavior | Average users hide high-degree failures | Low/medium/high-degree fixtures with trips, participants, Availability and activity | Before ~10K |
| F-04 | Private-projection revocation | Unverified consumers may mishandle relationship changes | Multi-worker/browser unfriend/trip/Availability mutation tests; Mountains endpoint is already `private, no-store` | Now / ~1K users |
| F-03 | Native version distribution and lifecycle | Hosted web is a mobile release surface despite implemented handlers | iOS/Android device matrix for cold/warm/resume, auth, push, stale payloads, and older binaries | Now / ~1K users |
| F-03 | Push tap/auth continuation | Delivery without useful navigation erodes trust | Cold logged-out push/invite tests, route persistence and one-time consumption evidence | Now / ~1K users |
| F-08 | Badge/unread reconciliation | OS state may diverge from server state | App-open/tap/resume comparison of badge and authoritative unseen count | Before ~10K |
| F-08 | Worker topology and queue | Outbox correctness does not prove throughput | Deployment identity, heartbeat, queue age, provider latency and synthetic burst | Now / ~1K users |
| F-07 | Local retention/residual identity | Mixed historical retention needs explicit policy alignment | Deletion verification, residual-ID scan, redaction contract, support review | Now / ~1K users |
| F-11 | Provider retention/deletion | Local cleanup cannot prove external erasure | Authorized provider contracts, deletion/export evidence, mailbox/log policy | Now / ~1K users |
| F-06 | Account deletion tail | Large synchronous transaction may time out or race workers | Heavy disposable PostgreSQL fixture, locks/WAL/rollback/residual JSON scan | Now / ~1K users |
| F-05 | Schema parity | PostgreSQL differences may alter plans and legacy semantics | Schema fingerprint and migration timings in disposable PostgreSQL | Before each migration |
| F-10 | Runtime parity | Deployment differences may alter recovery behavior | Lock tests and restore checks in a deployment-equivalent disposable DB | Trigger-based |
| F-10 | Backup RPO/RTO | Backup existence is not recovery capability | Isolated restore drill, checksums, row counts, code/schema alignment, timed runbook | Now / ~1K users |
| F-10 | Aggregate alert activation | Logs alone delay detection | Denominator-based success/p95, queue/provider alerts and game-day | Now / ~1K users |
| F-09 | Admin/branch ownership | Privilege errors have broad blast radius | Authorized admin assurance/MFA review and route-budget evidence | Now / ~1K users |
| F-10 | Release ownership | Release/recovery errors have broad blast radius | CODEOWNERS/branch settings and recovery exercise | Now / ~1K users |
| F-11 | External custody/export | Local deletion cannot prove provider deletion or export | Provider contracts, deletion responses, export mappings, retention controls | Now / ~1K users |
| F-12 | Vendor exit path | Provider outage/deprecation can force unsafe replay | Export contract, token/event mapping, provider substitution rehearsal | Before ~50K |

## 7. What We Should Not Change

Each item below is a deliberate “not a problem/change now” conclusion. It cites one finding and uses the explicit timing label **Leave alone**.

- **Supporting finding:** F-13
- **Timing classification:** Leave alone
- **Recommendation:** Keep Flask/Jinja rather than rewriting to an SPA solely for scale.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Keep Redis from becoming a universal social cache; `/api/mountains-data` remains dynamic and `private, no-store`.
- **Supporting finding:** F-01
- **Timing classification:** Leave alone
- **Recommendation:** Keep cursor pagination and deferment.
- **Supporting finding:** F-08
- **Timing classification:** Leave alone
- **Recommendation:** Keep messaging out of request threads.
- **Supporting finding:** F-05
- **Timing classification:** Leave alone
- **Recommendation:** Keep Availability separate from Trips.
- **Supporting finding:** F-08
- **Timing classification:** Leave alone
- **Recommendation:** Keep Notifications separate from Needs You.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Keep speculative private-data prefetch restricted.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Keep reciprocal visibility and capability binding intact.
- **Supporting finding:** F-09
- **Timing classification:** Leave alone
- **Recommendation:** Keep CSRF, fresh deletion authentication, and database uniqueness intact.
- **Supporting finding:** F-10
- **Timing classification:** Leave alone
- **Recommendation:** Keep CI’s lack of Production access as an intentional boundary.
- **Supporting finding:** F-02
- **Timing classification:** Leave alone
- **Recommendation:** Keep Replit migration trigger-based rather than calendar- or user-count-based.
- **Supporting finding:** F-10
- **Timing classification:** Leave alone
- **Recommendation:** Keep recovery and observability triggers.
- **Supporting finding:** F-08
- **Timing classification:** Leave alone
- **Recommendation:** Keep the outbox rather than replacing it with a generic event bus or microservices.

## 8. Replit Decision Framework

### ~1K users

- **Supporting finding:** F-02
- **Timing classification:** Now / ~1K users
- **Recommendation:** Keep the web application on Replit Autoscale conditionally and confirm the two-worker deployment’s queue and DB behavior.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Run restore and worker game-days.
- **Supporting finding:** F-08
- **Timing classification:** Now / ~1K users
- **Recommendation:** Keep the messaging worker separate and always-on where required by `docs/engineering/continuous-message-worker.md`.

### ~10K users

- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Re-test seasonal concurrency and high-degree Home.
- **Supporting finding:** F-03
- **Timing classification:** Before ~10K users
- **Recommendation:** Re-test native startup and hosted compatibility.
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Re-test outbox bursts and adjust worker capacity if queue triggers fire.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Do not add a shared social cache without a demonstrated bottleneck.

### ~50K users

- **Supporting finding:** F-12
- **Timing classification:** Before ~50K users
- **Recommendation:** Rehearse provider export, token/event mapping, and substitution before mature scale.
- **Supporting finding:** F-02
- **Timing classification:** Before ~50K users
- **Recommendation:** Make component-by-component capacity decisions using measured platform constraints.
- **Supporting finding:** F-10
- **Timing classification:** Before ~50K users
- **Recommendation:** Move a component only if required recovery or observability controls cannot be obtained.

### Migration triggers

  - **Supporting finding:** F-02
  - **Timing classification:** Trigger-based
  - **Recommendation:** Treat sustained p99/queue time above the declared SLO during representative peaks despite available Autoscale configuration as a migration trigger.
  - **Supporting finding:** F-02
  - **Timing classification:** Trigger-based
  - **Recommendation:** Migrate when DB connection/lock saturation cannot be solved by query, index, or pool tuning.
  - **Supporting finding:** F-08
  - **Timing classification:** Trigger-based
  - **Recommendation:** Isolate or move the worker when oldest-ready age exceeds notification SLO despite measured worker/provider capacity.
  - **Supporting finding:** F-02
  - **Timing classification:** Trigger-based
  - **Recommendation:** Migrate when regional latency or availability exceeds the user-facing target despite supported geography.
  - **Supporting finding:** F-10
  - **Timing classification:** Trigger-based
  - **Recommendation:** Migrate when code/schema rollback and restore cannot be rehearsed within RTO.
  - **Supporting finding:** F-09
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Obtain required audit, secret, network, and failure-isolation controls.
  - **Supporting finding:** F-12
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Establish a supported exit path before provider or platform deprecation/contract change.

Replit’s official deployment types and monitoring documentation support this staged posture; they do not prove BaseLodge’s live configuration. Database restore alignment includes application code because documented data recovery does not roll back code.

## 9. Preventative Roadmap

### NOW / ~1K

- **Supporting finding:** F-01
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish route and Home-component baselines.
- **Supporting finding:** F-02
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish DB and queue baselines.
- **Supporting finding:** F-03
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish native-startup baselines.
- **Supporting finding:** F-08
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish badge baselines.
- **Supporting finding:** F-06
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish deletion baselines.
- **Supporting finding:** F-10
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Establish restore/alert baselines.
- **Supporting finding:** F-06
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Run disposable heavy-account deletion and delete-vs-worker race tests.
- **Supporting finding:** F-04
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Test authorization/revocation after unfriend, trip privacy, and Availability mutation across every private consumer.
- **Supporting finding:** F-03
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Verify native cold/warm/resume, push registration, push tap, logged-out auth continuation, and older hosted/native combinations.
- **Supporting finding:** F-09
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Review admin allowlist, deployment step-up/MFA/audit evidence, analytics allowlisting, and abuse budgets.
- **Supporting finding:** F-07
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Define local retention/redaction contracts.
- **Supporting finding:** F-11
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Obtain external-provider retention, deletion, and export evidence.
- **Supporting finding:** F-10
  - **Timing classification:** Now / ~1K users
  - **Recommendation:** Perform a timed isolated restore drill with recorded RPO/RTO.

### BEFORE ~10K

- **Supporting finding:** F-01
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Run synthetic low/medium/high-degree and seasonal Home data matrices with query plans and p95/p99.
- **Supporting finding:** F-05
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Run semantic data matrices.
- **Supporting finding:** F-01
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Set Home fallback/error metrics.
- **Supporting finding:** F-08
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Set outbox queue-age/provider SLOs.
- **Supporting finding:** F-03
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Establish a native/web compatibility release gate and hosted-script rollback/canary procedure.
- **Supporting finding:** F-05
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Inventory canonical readers/writers and legacy field drift; make migration compatibility explicit.
- **Supporting finding:** F-08
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Reconcile badge/unread and Notifications/Needs You lifecycle behavior.
- **Supporting finding:** F-08
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Confirm the separately deployed worker’s identity, restart policy, and heartbeat.
- **Supporting finding:** F-10
  - **Timing classification:** Before ~10K users
  - **Recommendation:** Confirm least privilege and alerting evidence.

### BEFORE ~50K

- **Supporting finding:** F-05
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reassess relational cardinality and JSON payload growth using representative records and histories.
- **Supporting finding:** F-07
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reassess historical retention.
- **Supporting finding:** F-10
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reassess table/index bloat, migration duration, and restore duration.
- **Supporting finding:** F-12
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Rehearse provider export/substitution and token/event portability.
- **Supporting finding:** F-02
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reassess Replit component boundaries using measured capacity constraints, not population alone.
- **Supporting finding:** F-10
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reassess recovery controls.
- **Supporting finding:** F-13
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Reduce change coupling at measured feature boundaries.
- **Supporting finding:** F-10
  - **Timing classification:** Before ~50K users
  - **Recommendation:** Document ownership and recovery procedures.

### TRIGGER-BASED

- **Supporting finding:** F-02
  - **Timing classification:** Trigger-based
  - **Recommendation:** Run connection-budget tests when representative peak traffic shows queue, pool, or timeout pressure.
- **Supporting finding:** F-01
  - **Timing classification:** Trigger-based
  - **Recommendation:** Tune web capacity on sustained p99/timeout evidence.
- **Supporting finding:** F-02
  - **Timing classification:** Trigger-based
  - **Recommendation:** Move web capacity on sustained queue/pool evidence.
- **Supporting finding:** F-08
  - **Timing classification:** Trigger-based
  - **Recommendation:** Move or multiply workers on oldest-ready-age and provider-throughput evidence.
- **Supporting finding:** F-04
  - **Timing classification:** Trigger-based
  - **Recommendation:** Change caching only after measured hit/waste benefit plus revocation tests.
- **Supporting finding:** F-03
  - **Timing classification:** Trigger-based
  - **Recommendation:** Change native provider/platform after compatibility or quota evidence.
- **Supporting finding:** F-08
  - **Timing classification:** Trigger-based
  - **Recommendation:** Change messaging provider after delivery-SLO or outage evidence.
- **Supporting finding:** F-10
  - **Timing classification:** Trigger-based
  - **Recommendation:** Change platform after recovery-control evidence.

### LEAVE ALONE

- **Supporting finding:** F-13
- **Timing classification:** Leave alone
- **Recommendation:** Keep the Flask MPA and current ownership boundaries unless new coupling evidence contradicts this conclusion.
- **Supporting finding:** F-01
- **Timing classification:** Leave alone
- **Recommendation:** Keep current pagination and immutable asset caching unless scale evidence contradicts these conclusions.
- **Supporting finding:** F-04
- **Timing classification:** Leave alone
- **Recommendation:** Keep server-authorized private projections.
- **Supporting finding:** F-05
- **Timing classification:** Leave alone
- **Recommendation:** Keep canonical Availability/Trip separation.
- **Supporting finding:** F-08
- **Timing classification:** Leave alone
- **Recommendation:** Keep the durable outbox boundary.
- **Supporting finding:** F-10
- **Timing classification:** Leave alone
- **Recommendation:** Keep CI’s disposable-environment isolation.

## 10. Top 10 “If We Ignore This” Risks

Each risk names one canonical finding ID. The list is deliberately ten or fewer; F-08 covers both attention projection and outbound delivery.

### 1. [F-01] Home tail latency and silent partial failure

- **Evidence:** `app.py:12939-13435`; `services/ideas_retrieval.py`; Home fallbacks
- **Plausible failure path:** graph/date/trip cardinality consumes workers; exceptions render empty sections; users lose coordination context without a clear error
- **Earliest warning:** high-degree p99, rows examined, fallback counters, DB pool wait
- **Supporting finding:** F-01
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish synthetic tail benchmarks and explicit component SLOs.

### 2. [F-03] Remote hosted web breaks installed native clients

- **Evidence:** `capacitor.config.json`; `static/js/bl-native.js:1367-1610`; `android/app/src/main/AndroidManifest.xml:20-45`
- **Plausible failure path:** hosted HTML/JS/session change is incompatible with an old binary despite existing tap/deep-link handlers; native startup/push/auth fails
- **Earliest warning:** startup beacon funnel, version-segmented 401/403/JS errors, failed cold/warm/resume tap completion
- **Supporting finding:** F-03
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish a compatibility matrix, canary/rollback process, and version gate.

### 3. [F-04] Unverified private-projection consumer lacks revocation proof

- **Evidence:** `services/visibility.py`; cache foundation; protected `/api/mountains-data` at `app.py:6584-6700`
- **Plausible failure path:** a future or unverified consumer mishandles current authorization after unfriend/trip privacy mutation; the Mountains endpoint itself is not this failure because it is dynamic and `private, no-store`
- **Earliest warning:** failed mutation-to-revocation tests or cross-consumer authorization divergence
- **Supporting finding:** F-04
- **Timing classification:** Now / ~1K users
- **Recommendation:** Maintain server-authorized reads and revocation tests rather than broader caching.

### 4. [F-06] Heavy account deletion exceeds transaction or worker-race limits

- **Evidence:** `app.py:18740-18972`; deletion tests; outbox SET NULL behavior
- **Plausible failure path:** a heavy account’s transaction collides with worker/provider activity or exceeds timeout/lock budgets
- **Earliest warning:** deletion duration, locks/WAL, rollback, and delete-vs-worker race outcomes
- **Supporting finding:** F-06
- **Timing classification:** Now / ~1K users
- **Recommendation:** Run heavy disposable PostgreSQL and race tests and define explicit policy.

### 5. [F-07] Retained identity and mixed redaction create policy-alignment risk

- **Evidence:** `reports/account-deletion-message-retention-investigation.md`; JSON-bearing models
- **Plausible failure path:** local historical projections retain identifiers/content in mixed forms while policy alignment remains incomplete
- **Earliest warning:** residual-ID scans and deletion-verification discrepancies
- **Supporting finding:** F-07
- **Timing classification:** Now / ~1K users
- **Recommendation:** Define and test local retention/redaction separately from transaction capacity.

### 6. [F-08] Attention projections or outbound delivery diverge

- **Evidence:** Activity/attention models and review; `services/message_outbox_worker.py`; `delivery_unknown`
- **Plausible failure path:** action/badge/history projections drift, or seasonal/provider bursts create unresolved delivery backlog
- **Earliest warning:** stale badge/action reports, oldest-ready age, lease expiry, unknown age, provider p95
- **Supporting finding:** F-08
- **Timing classification:** Before ~10K users
- **Recommendation:** Establish lifecycle reconciliation and queue/provider SLOs.

### 7. [F-09] Admin assurance or distributed-abuse adequacy remains unproven

- **Evidence:** `app.py:1999-2009,455-463`; `services/rate_limit_storage.py`
- **Plausible failure path:** an allowlisted-session compromise or distributed identity set reaches high-impact or expensive-read paths; this is a scenario, not an observed defect
- **Earliest warning:** unusual admin actions, unique identity/IP patterns, DB load without conversion
- **Supporting finding:** F-09
- **Timing classification:** Now / ~1K users
- **Recommendation:** Obtain authorized deployment/admin evidence, review step-up/audit controls, and set route budgets.

### 8. [F-05] Legacy/canonical data semantics drift

- **Evidence:** Availability mirrors, trip IDs/models, JSON payloads, migrations
- **Plausible failure path:** a new feature reads a legacy field or rollback leaves contradictory state; long-lived histories behave differently
- **Earliest warning:** mismatch scans, backfill errors, old-account-only defects
- **Supporting finding:** F-05
- **Timing classification:** Before ~10K users
- **Recommendation:** Inventory ownership and run migration compatibility tests.

### 9. [F-10] Migration or restore cannot safely recover the service

- **Evidence:** migration chain, startup reconciliation, Replit data/code restore asymmetry
- **Plausible failure path:** lock/backfill or schema mismatch blocks release; restoring DB without matching code creates a second failure
- **Earliest warning:** lock/duration drift, schema fingerprint mismatch, untested RTO
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Use forward-compatible migrations and run timed restore drills.

### 10. [F-02] Runtime capacity is exceeded before its trigger is measured

- **Evidence:** `.replit:46-49`; `gunicorn.conf.py`; `runtime_config.py:58-68`
- **Plausible failure path:** burst concurrency queues behind two workers or DB connections before average traffic appears high
- **Earliest warning:** queue time, pool wait, p99, timeout/5xx
- **Supporting finding:** F-02
- **Timing classification:** Trigger-based
- **Recommendation:** Establish a synthetic capacity baseline and conditionally tune or migrate Replit capacity.

## 11. Final Answers

### 1. If BaseLodge fails technologically by September 2029 despite genuine user demand, what are the three most plausible reasons?

1. F-01 Home/social tail pressure: synchronous work, high-degree users, and seasonal concurrency combine into unreliable coordination.
2. F-03 Native/web compatibility contract failure: the hosted web app becomes the mobile app’s release surface while lifecycle, authentication, push, deep-link, and binary-version behavior remain incompletely evidenced.
3. F-10 Unproven detection, recovery, and environment parity: incidents can outpace alerting, restore, or deployment-equivalence evidence.
Other findings are contributing factors to these three primary failure reasons, not additional reasons in this answer.

### 2. What is the single most important technical thing BaseLodge should address now?

- **Supporting finding:** F-01
- **Timing classification:** Now / ~1K users
- **Recommendation:** Establish a representative Home/social tail benchmark and operational SLO baseline covering route/DB p95/p99, rows/plans, and worker/connection pressure under high-degree seasonal fixtures.

### 3. What is the most important thing we should deliberately NOT change yet?

- **Supporting finding:** F-13
- **Timing classification:** Leave alone
- **Recommendation:** Keep the Flask/Jinja MPA and avoid distributed infrastructure solely because the product is growing.

### 4. What should we measure now so that we are not guessing later?

- **Supporting finding:** F-01
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure Home and key-route p50/p95/p99, SQL statements/rows/plans, and high-degree/date-tail behavior.
- **Supporting finding:** F-02
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure request queue and DB pool wait.
- **Supporting finding:** F-08
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure worker/outbox oldest-ready age and `delivery_unknown`.
- **Supporting finding:** F-06
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure deletion locks/duration/race outcomes.
- **Supporting finding:** F-04
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure projection revocation.
- **Supporting finding:** F-03
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure native cold/warm/resume and push-tap funnels by binary version.
- **Supporting finding:** F-10
- **Timing classification:** Now / ~1K users
- **Recommendation:** Measure restore RPO/RTO and alert denominators.

### 5. At what point, if any, should BaseLodge move part or all of its architecture away from Replit?

- **Supporting finding:** F-02
- **Timing classification:** Trigger-based
- **Recommendation:** Move a component only when measured Replit capacity, connection, network, or geographic constraints cannot be solved with supported configuration.
- **Supporting finding:** F-08
- **Timing classification:** Trigger-based
- **Recommendation:** Move or isolate the worker when measured queue SLOs fail.
- **Supporting finding:** F-10
- **Timing classification:** Trigger-based
- **Recommendation:** Move a component when required recovery or observability controls cannot be obtained.
- **Supporting finding:** F-12
- **Timing classification:** Before ~50K users
- **Recommendation:** Reassess provider/platform portability component by component rather than migrating by calendar.

### 6. Is there anything in the current architecture that could become substantially harder to fix if we wait until 10K or 50K users?

Legacy/canonical data ownership, retention policy, account deletion, projection revocation, native/web compatibility, provider/token migration, and restore/migration procedures become harder as records, histories, consumers, binary cohorts, and operational dependencies multiply.
These become harder because records and histories per account, installed binary/version cohorts, active providers, and feature consumers multiply—not because the code suddenly becomes impossible to change.

### 7. What technical decision being made today has the greatest chance of looking like an obvious mistake in hindsight in September 2029?

- **Supporting finding:** F-03
- **Timing classification:** Before ~10K users
- **Recommendation:** Maintain a continuously tested native compatibility, lifecycle, push-tap/auth, and rollback contract for the remote shell; the remote-shell decision itself can remain appropriate.