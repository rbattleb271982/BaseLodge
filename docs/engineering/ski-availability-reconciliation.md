# Ski Availability Reconciliation Runbook

This runbook documents a future audit and guarded reconciliation of legacy
`User.open_dates` values with normalized `UserAvailability` rows. It does not
authorize Production access, mutation, deployment, or backfill execution.

## Canonical resolution contract

Availability resolves independently for each calendar date:

- A strict `YYYY-MM-DD` legacy value on or after the server's current date is
  available when no normalized row exists for that date.
- An active normalized row makes its date available.
- An inactive normalized row makes its date unavailable and tombstones the
  same legacy value.
- Past normalized rows are historical and do not represent current
  availability.
- Historical normalized rows do not suppress unrelated future legacy dates.
- Malformed and past legacy values are ignored; duplicates collapse.

During the rollback window, `UserAvailability` is the canonical write target
and `User.open_dates` remains a compatibility mirror and per-date fallback.

## Separately approved read-only Production audit

Before deployment or reconciliation, obtain separate approval for read-only
Production access. Report counts without exposing user-identifying data for:

- legacy-only users;
- normalized-only users;
- mixed users;
- users with only inactive normalized rows;
- users with only historical normalized rows;
- malformed legacy values;
- past legacy values; and
- same-date conflicts between legacy values and normalized decisions.

The audit must also verify that the normalized uniqueness and active/inactive
behavior match the assumptions in the canonical resolver.

## Guarded backfill contract

A future backfill requires a separate reviewed plan and approval. It must:

- support a read-only dry run and emit category/count summaries before writes;
- parse only strict ISO `YYYY-MM-DD` values;
- ignore past legacy availability when normalizing current state;
- insert only dates whose resolved state is deterministic;
- preserve inactive normalized tombstones;
- never silently overwrite mixed-state conflicts;
- be idempotent and safe to rerun;
- stop on any unexpected state; and
- keep `User.open_dates` intact throughout the rollback window.

No migration or executable backfill is part of this runbook.

## STOP conditions

Stop before mutation or activation when:

- mixed states cannot be resolved deterministically;
- malformed legacy values are materially common;
- normalized-row behavior differs from the resolver assumptions;
- unexpected duplicate or conflicting states exist;
- user intent cannot be preserved; or
- rollback compatibility cannot be maintained.

Escalate the observed counts and examples through the separately approved
review process. Do not choose a lossy default.

## Activation sequence

1. Complete Development verification.
2. Obtain approval and perform the read-only Production audit.
3. Evaluate every STOP condition.
4. Deploy the backward-compatible resolver and dual-write code first.
5. Verify editing, replacement, clearing, privacy, and authorized live surfaces.
6. Separately approve any guarded backfill.
7. Run the backfill in dry-run/read-only mode.
8. If approved and no STOP condition is met, run guarded reconciliation.
9. Verify counts, canonical reads, writes, clearing, and privacy again.
10. Retain the legacy fallback and compatibility mirror for the defined
    rollback window.

Production activation is not complete until the read-only audit, deployment
verification, and any separately approved reconciliation have all passed.