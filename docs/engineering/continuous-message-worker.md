# Continuous messaging worker

The future Production worker belongs in a separate Replit Reserved VM project.
It starts only the worker process; it must not use the web project's Gunicorn
command and must not run Alembic.

## Commands

The first deployment is observation-only:

```sh
BASELODGE_WORKER_MODE=idle-only python run_continuous_message_worker.py
```

After a separately approved cutover, normal delivery uses:

```sh
BASELODGE_WORKER_MODE=normal python run_continuous_message_worker.py
```

`idle-only` and `normal` are the only accepted modes. Idle-only executes
preflight, reads policy and aggregate queue health, and updates its heartbeat.
Its runtime path has no delivery callbacks and cannot claim or call OneSignal.

SIGTERM and SIGINT stop the next claim cycle immediately. An already-started
bounded batch is allowed to finish using the existing lease and provider-start
boundary, after which sessions are closed, a final heartbeat is attempted, the
database engine is disposed, and the process exits.

## Least privilege

Required secrets:

- `BASELODGE_PRODUCTION_DATABASE_URL`: runtime DML access only; the role must
  not own the database and must not have schema creation, alteration, deletion,
  migration, role-management, or database-management privileges.
- `ONESIGNAL_REST_API_KEY`: notification send access for the configured app.

Required non-secret configuration:

- `BASELODGE_RUNTIME_ENV=production`
- `ONESIGNAL_APP_ID`
- `BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH`
- `BASELODGE_PRODUCTION_SUPABASE_PROJECT_REF_HASH` when using the session pooler
- `BASELODGE_APPROVED_WORKER_RELEASE_SHA`, exactly matching `build/release.sha`
- `BASELODGE_WORKER_IDENTITY`, stable and unique per Reserved VM
- `BASELODGE_WORKER_MODE`
- optional bounded tuning: `BASELODGE_WORKER_IDLE_SECONDS`,
  `BASELODGE_WORKER_BATCH_SIZE`, `BASELODGE_WORKER_LEASE_SECONDS`,
  `BASELODGE_WORKER_BACKOFF_INITIAL_SECONDS`,
  `BASELODGE_WORKER_BACKOFF_MAX_SECONDS`,
  `BASELODGE_WORKER_STALE_SECONDS`, `BASELODGE_WORKER_POOL_SIZE`, and
  `BASELODGE_WORKER_MAX_OVERFLOW`

The database URL must explicitly select exactly one `sslmode=verify-full`
(with a valid CA/root certificate where the platform does not provide one).
The worker additionally verifies the live PostgreSQL connection through
`pg_stat_ssl`. OneSignal application ID and REST-key shape are intentionally
validated even in idle-only mode: this proves future delivery readiness without
making a provider network call. The worker needs SELECT/INSERT/UPDATE on messaging runtime,
audit, policy, replay, and heartbeat tables and sequence usage where applicable.
It does not need migration authorization.

Do not configure APNs or Firebase credentials, SendGrid, a web session secret,
Google OAuth, PostHog, Redis rate-limit storage, or administrator email
configuration. The worker command starts no server, web routes, web background
threads, or migration process.

The default stale threshold is at least four idle intervals. Monitoring reads
the current row in `messaging_worker_heartbeat`; an age above the configured
threshold is stale. Heartbeats contain only release/process state, bounded
counters, aggregate queue status, and an allowlisted error category. A stable
worker identity has an ownership generation token: a second fresh process with
the same identity fails closed, while a stale predecessor may be replaced.
Fenced heartbeat updates prevent a predecessor's final `stopped` update from
overwriting its replacement. Loss of heartbeat ownership is fatal: the old
process exits before another claim cycle and does not publish a final heartbeat
over the replacement. Normal delivery also verifies and locks that ownership
in the same transaction immediately before each claim and again immediately
before provider-start. A fenced pre-provider lease is safely released without
calling OneSignal; ownership changes after provider-start retain the existing
`delivery_unknown`/finalization contract.