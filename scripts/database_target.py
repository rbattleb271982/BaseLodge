#!/usr/bin/env python3
"""Credential-free migration target diagnostics.

The default diagnostic is entirely offline.  A live Alembic revision read is
available only through the explicit ``--check-revision`` option and uses a
verified migration target in a read-only transaction.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from runtime_config import (
    RuntimeConfigurationError,
    migration_database_diagnostic,
    resolve_migration_database_config,
)


def _read_current_revision(
    database_url: str,
    *,
    engine_factory: Callable = create_engine,
) -> tuple[str, ...]:
    """Read Alembic revisions only after PostgreSQL confirms read-only mode."""
    engine = engine_factory(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                read_only = connection.execute(
                    text("SHOW transaction_read_only")
                ).scalar_one()
                if str(read_only).lower() not in {"on", "true", "1"}:
                    raise RuntimeConfigurationError(
                        "Database did not confirm read-only transaction mode."
                    )
                revisions = connection.execute(
                    text(
                        "SELECT version_num FROM alembic_version "
                        "ORDER BY version_num"
                    )
                ).scalars()
                return tuple(str(revision) for revision in revisions)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def diagnose(
    environ: Mapping[str, str] | None = None,
    *,
    check_revision: bool = False,
    revision_reader: Callable[[str], tuple[str, ...]] = _read_current_revision,
) -> tuple[int, str]:
    """Return an exit code and safe human-readable diagnostic report."""
    environment = os.environ if environ is None else environ
    try:
        configuration = resolve_migration_database_config(environment)
        details = migration_database_diagnostic(configuration)
    except RuntimeConfigurationError as exc:
        return 2, "\n".join(
            (
                "Migration target: UNVERIFIED",
                "Target verification: FAIL",
                f"Reason: {exc}",
            )
        )

    lines = [
        f"Migration target: {details['migration_target']}",
        f"URL source: {details['source']}",
        f"Database dialect: {details['dialect']}",
        f"Database host: {details['hostname']}",
        f"Database name: {details['database_name']}",
        f"Environment identity: {details['identity_hash']}",
        f"Target verification: {details['verification']}",
        "Alembic revision: NOT CHECKED (offline diagnostic)",
    ]

    if check_revision:
        try:
            revisions = revision_reader(configuration.database_url)
        except Exception as exc:
            safe_reason = (
                str(exc)
                if isinstance(exc, RuntimeConfigurationError)
                else "read-only revision check failed"
            )
            lines[-1] = f"Alembic revision: FAIL ({safe_reason})"
            return 3, "\n".join(lines)
        lines[-1] = (
            "Alembic revision: "
            + (", ".join(revisions) if revisions else "UNVERSIONED")
        )

    return 0, "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify an explicitly selected BaseLodge migration target."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Verify target identity without running migrations.",
    )
    diagnose_parser.add_argument(
        "--check-revision",
        action="store_true",
        help="Opt in to a live read-only Alembic revision query.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "diagnose":
        exit_code, report = diagnose(check_revision=args.check_revision)
        print(report)
        return exit_code
    return 2


if __name__ == "__main__":
    raise SystemExit(main())