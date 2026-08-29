"""Read-only, fail-closed release preflight for BaseLodge.

This module intentionally does not import the Flask application.  It reuses
the side-effect-free runtime configuration and release identity contracts,
then performs only metadata SELECTs against the resolved application target.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from release_identity import (
    ReleaseIdentity,
    resolve_candidate_release_identity,
)
from runtime_config import (
    DatabaseConfiguration,
    RuntimeConfigurationError,
    database_identity,
    database_identity_hash,
    resolve_application_database_config,
    resolve_maintenance_database_config,
)


PROJECT_ROOT = Path(__file__).resolve().parent
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "alembic.ini"
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_RUNTIME_ENVS = frozenset({"development", "test", "production"})
_REQUIRED_COLUMNS = {
    "stay_name": ("character varying", 200),
    "stay_description": ("character varying", 500),
}


@dataclass(frozen=True)
class CheckResult:
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ColumnSnapshot:
    data_type: str
    max_length: int | None
    nullable: bool


@dataclass(frozen=True)
class LiveDatabaseSnapshot:
    revisions: tuple[str, ...]
    columns: Mapping[str, ColumnSnapshot]


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def load_source_heads(
    config_path: Path = ALEMBIC_CONFIG_PATH,
) -> tuple[str, ...]:
    """Read migration graph heads without importing the Flask app."""
    alembic_config = Config(str(config_path))
    alembic_config.set_main_option(
        "script_location",
        str(config_path.parent),
    )
    return tuple(ScriptDirectory.from_config(alembic_config).get_heads())


def _runtime_environment(environ: Mapping[str, str]) -> str | None:
    value = environ.get("BASELODGE_RUNTIME_ENV")
    if value is None:
        return None
    value = value.strip()
    return value if value in _SUPPORTED_RUNTIME_ENVS else None


def _value(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _environment_check(environ: Mapping[str, str]) -> CheckResult:
    runtime_env = _runtime_environment(environ)
    if runtime_env is None:
        return CheckResult(
            "ENVIRONMENT",
            False,
            "missing or unsupported runtime environment",
        )

    if runtime_env == "production":
        explicit_url = _value(environ, "BASELODGE_PRODUCTION_DATABASE_URL")
        legacy_url = _value(environ, "SUPABASE_DATABASE_URL")
        if explicit_url and legacy_url:
            try:
                if database_identity(explicit_url) != database_identity(legacy_url):
                    return CheckResult(
                        "ENVIRONMENT",
                        False,
                        "contradictory Production database configuration",
                    )
            except (RuntimeConfigurationError, ValueError):
                return CheckResult(
                    "ENVIRONMENT",
                    False,
                    "ambiguous or invalid Production database configuration",
                )

    return CheckResult("ENVIRONMENT", True, runtime_env)


def _resolve_application_target(
    environ: Mapping[str, str],
) -> tuple[DatabaseConfiguration | None, CheckResult | None]:
    try:
        return resolve_application_database_config(environ), None
    except (RuntimeConfigurationError, ValueError):
        return (
            None,
            CheckResult(
                "DATABASE TARGET",
                False,
                "application target could not be resolved safely",
            ),
        )


def _database_target_checks(
    configuration: DatabaseConfiguration,
    environ: Mapping[str, str],
) -> tuple[CheckResult, CheckResult]:
    issues: list[str] = []
    runtime_env = configuration.runtime_env

    if runtime_env == "production":
        maintenance_environment = dict(environ)
        maintenance_environment.update(
            {
                "BASELODGE_MAINTENANCE_MODE": "1",
                "BASELODGE_MAINTENANCE_DATABASE_URL": (
                    configuration.database_url
                ),
            }
        )
        try:
            resolve_maintenance_database_config(maintenance_environment)
        except (RuntimeConfigurationError, ValueError):
            issues.append("target does not match protected Production identity")

        development_url = _value(
            environ, "BASELODGE_DEVELOPMENT_DATABASE_URL"
        )
        if not development_url:
            issues.append("Development target is unavailable for comparison")
        else:
            try:
                if database_identity(configuration.database_url) == database_identity(
                    development_url
                ):
                    issues.append("target matches Development")
            except (RuntimeConfigurationError, ValueError):
                issues.append("Development target is invalid")

    try:
        target_hash = database_identity_hash(configuration.database_url)
    except (RuntimeConfigurationError, ValueError):
        target_hash = None
        issues.append("target identity is invalid")

    if issues or target_hash is None:
        target_detail = "cannot verify application target"
        if issues:
            target_detail += " (" + "; ".join(issues) + ")"
        target_check = CheckResult("DATABASE TARGET", False, target_detail)
    else:
        target_check = CheckResult(
            "DATABASE TARGET",
            True,
            f"identity_sha256={target_hash}",
        )

    generic_url = _value(environ, "DATABASE_URL")
    if not generic_url:
        isolation_check = CheckResult(
            "GENERIC REPLIT DB ISOLATION",
            True,
            "generic DATABASE_URL is not configured",
        )
    else:
        try:
            matches_generic = database_identity(
                configuration.database_url
            ) == database_identity(generic_url)
        except (RuntimeConfigurationError, ValueError):
            isolation_check = CheckResult(
                "GENERIC REPLIT DB ISOLATION",
                False,
                "generic DATABASE_URL could not be compared safely",
            )
        else:
            isolation_check = CheckResult(
                "GENERIC REPLIT DB ISOLATION",
                not matches_generic,
                (
                    "application target is distinct from generic DATABASE_URL"
                    if not matches_generic
                    else "application target matches generic DATABASE_URL"
                ),
            )

    return target_check, isolation_check


def validate_release_identity(identity: ReleaseIdentity) -> CheckResult:
    if (
        identity.status != "VERIFIED"
        or not isinstance(identity.sha, str)
        or not _GIT_SHA_PATTERN.fullmatch(identity.sha)
        or identity.sha != identity.sha.lower()
    ):
        return CheckResult(
            "RELEASE SHA",
            False,
            "identity is missing, malformed, or UNVERIFIED",
        )
    return CheckResult("RELEASE SHA", True, identity.sha)


def validate_source_heads(heads: Sequence[str]) -> CheckResult:
    if len(heads) != 1:
        return CheckResult(
            "ALEMBIC SOURCE HEAD",
            False,
            f"expected exactly one source head; found {len(heads)}",
        )
    return CheckResult("ALEMBIC SOURCE HEAD", True, heads[0])


def validate_live_revision(
    revisions: Sequence[str],
    expected_head: str | None,
) -> CheckResult:
    if expected_head is None:
        return CheckResult(
            "LIVE ALEMBIC REVISION",
            False,
            "source head is not uniquely determined",
        )
    if tuple(revisions) != (expected_head,):
        return CheckResult(
            "LIVE ALEMBIC REVISION",
            False,
            "live revision does not match the unique source head",
        )
    return CheckResult("LIVE ALEMBIC REVISION", True, expected_head)


def validate_schema(
    snapshot: LiveDatabaseSnapshot | None,
) -> CheckResult:
    if snapshot is None:
        return CheckResult(
            "SCHEMA COMPATIBILITY",
            False,
            "live schema could not be inspected",
        )

    issues: list[str] = []
    for column_name, (expected_type, expected_length) in _REQUIRED_COLUMNS.items():
        column = snapshot.columns.get(column_name)
        if column is None:
            issues.append(f"{column_name} is missing")
            continue
        if column.data_type.lower() not in {
            expected_type,
            "varchar",
        }:
            issues.append(f"{column_name} has an incompatible type")
        if column.max_length != expected_length:
            issues.append(f"{column_name} has an incompatible length")
        if not column.nullable:
            issues.append(f"{column_name} is not nullable")

    if issues:
        return CheckResult(
            "SCHEMA COMPATIBILITY",
            False,
            "; ".join(issues),
        )
    return CheckResult(
        "SCHEMA COMPATIBILITY",
        True,
        "required ski_trip Stay columns are compatible",
    )


def _parse_sqlite_column_type(type_name: str) -> tuple[str, int | None]:
    normalized = type_name.strip().lower()
    match = re.fullmatch(r"(?:character varying|varchar)\s*(?:\((\d+)\))?", normalized)
    if not match:
        return normalized, None
    return "character varying", (
        int(match.group(1)) if match.group(1) else None
    )


def _begin_read_only_transaction(connection) -> None:
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        connection.exec_driver_sql("BEGIN READ ONLY")
        setting = connection.exec_driver_sql(
            "SHOW transaction_read_only"
        ).scalar_one()
        if str(setting).lower() != "on":
            raise RuntimeError("read-only transaction could not be verified")
        return

    if dialect_name == "sqlite":
        connection.exec_driver_sql("PRAGMA query_only = ON")
        setting = connection.exec_driver_sql("PRAGMA query_only").scalar_one()
        if int(setting) != 1:
            raise RuntimeError("SQLite query-only mode could not be verified")
        connection.exec_driver_sql("BEGIN")
        return

    raise RuntimeError("unsupported database dialect")


def read_live_database(
    configuration: DatabaseConfiguration,
) -> LiveDatabaseSnapshot:
    """Read migration/schema metadata using a transaction that cannot write."""
    engine = None
    try:
        engine = create_engine(
            configuration.database_url,
            poolclass=NullPool,
        )
        with engine.connect() as connection:
            try:
                _begin_read_only_transaction(connection)
                if connection.dialect.name == "postgresql":
                    revisions = tuple(
                        row[0]
                        for row in connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).all()
                    )
                    rows = connection.execute(
                        text(
                            """
                            SELECT column_name, data_type,
                                   character_maximum_length, is_nullable
                            FROM information_schema.columns
                            WHERE table_schema = :schema_name
                              AND table_name = :table_name
                              AND column_name IN (
                                  'stay_name', 'stay_description'
                              )
                            ORDER BY column_name
                            """
                        ),
                        {"schema_name": "public", "table_name": "ski_trip"},
                    ).all()
                    columns = {
                        row[0]: ColumnSnapshot(
                            data_type=row[1],
                            max_length=row[2],
                            nullable=row[3] == "YES",
                        )
                        for row in rows
                    }
                elif connection.dialect.name == "sqlite":
                    revisions = tuple(
                        row[0]
                        for row in connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).all()
                    )
                    rows = connection.exec_driver_sql(
                        "PRAGMA table_info(ski_trip)"
                    ).all()
                    columns = {}
                    for row in rows:
                        if row[1] not in _REQUIRED_COLUMNS:
                            continue
                        data_type, max_length = _parse_sqlite_column_type(
                            row[2]
                        )
                        columns[row[1]] = ColumnSnapshot(
                            data_type=data_type,
                            max_length=max_length,
                            nullable=not bool(row[3]),
                        )
                return LiveDatabaseSnapshot(
                    revisions=revisions,
                    columns=columns,
                )
            finally:
                connection.rollback()
    finally:
        if engine is not None:
            engine.dispose()


def run_preflight(
    environ: Mapping[str, str] | None = None,
    *,
    identity: ReleaseIdentity | None = None,
    source_heads: Sequence[str] | None = None,
    live_database: LiveDatabaseSnapshot | None = None,
    database_reader: Callable[
        [DatabaseConfiguration], LiveDatabaseSnapshot
    ] = read_live_database,
) -> PreflightReport:
    environment = dict(os.environ if environ is None else environ)
    checks: list[CheckResult] = []

    environment_check = _environment_check(environment)
    checks.append(environment_check)
    configuration, target_error = _resolve_application_target(environment)
    if target_error is not None:
        checks.append(target_error)
        checks.append(
            CheckResult(
                "GENERIC REPLIT DB ISOLATION",
                False,
                "application target is unavailable for comparison",
            )
        )
    else:
        target_check, isolation_check = _database_target_checks(
            configuration,
            environment,
        )
        checks.extend((target_check, isolation_check))

    runtime_env = _runtime_environment(environment)
    if identity is None:
        try:
            identity = resolve_candidate_release_identity()
        except Exception:
            identity = ReleaseIdentity(sha=None, status="UNVERIFIED")
    checks.append(validate_release_identity(identity))

    if source_heads is None:
        try:
            source_heads = load_source_heads()
        except Exception:
            source_heads = ()
    source_head_check = validate_source_heads(source_heads)
    checks.append(source_head_check)
    expected_head = source_heads[0] if len(source_heads) == 1 else None

    prerequisites_passed = (
        configuration is not None and all(check.passed for check in checks)
    )
    database_error = False
    database_blocked = not prerequisites_passed
    if live_database is None and prerequisites_passed:
        try:
            live_database = database_reader(configuration)
        except Exception:
            database_error = True

    if database_blocked:
        live_database = None
        checks.append(
            CheckResult(
                "LIVE ALEMBIC REVISION",
                False,
                "not inspected because a prerequisite failed",
            )
        )
    elif database_error:
        checks.append(
            CheckResult(
                "LIVE ALEMBIC REVISION",
                False,
                "live database metadata could not be read",
            )
        )
    else:
        revisions = live_database.revisions if live_database else ()
        checks.append(validate_live_revision(revisions, expected_head))
    checks.append(validate_schema(live_database))

    return PreflightReport(tuple(checks))


def format_report(report: PreflightReport) -> str:
    lines = [f"PREFLIGHT: {'PASS' if report.passed else 'FAIL'}"]
    for check in report.checks:
        state = "PASS" if check.passed else "FAIL"
        lines.append(f"{check.label}: {state} — {check.detail}")
    return "\n".join(lines)


def main() -> int:
    try:
        report = run_preflight()
    except Exception:
        report = PreflightReport(
            (
                CheckResult(
                    "PREFLIGHT EXECUTION",
                    False,
                    "preflight could not complete safely",
                ),
            )
        )
    print(format_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())