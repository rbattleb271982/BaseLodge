"""Side-effect-free runtime and database configuration for BaseLodge.

This module must remain safe to import from tooling, tests, and Alembic.  It
does not import Flask, SQLAlchemy, or application models, and it never opens a
database connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
import re
from typing import Mapping
from urllib.parse import unquote, urlsplit


_VALID_RUNTIME_ENVS = frozenset({"development", "test", "production"})
_HASH_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$", re.IGNORECASE)
_SUPABASE_POOLER_HOST_PATTERN = re.compile(
    r"^[a-z0-9-]+\.pooler\.supabase\.com$"
)
_SUPABASE_PROJECT_REF_PATTERN = re.compile(r"^[a-z0-9]{20}$")
_SUPABASE_DIRECT_HOST_PATTERN = re.compile(
    r"^db\.[a-z0-9]+\.supabase\.co$"
)
_VALID_MIGRATION_TARGETS = frozenset(
    {"replit", "supabase-development", "supabase-production"}
)
_MIGRATION_TARGET_URL_KEYS = {
    "replit": "DATABASE_URL",
    "supabase-development": "BASELODGE_DEVELOPMENT_DATABASE_URL",
    "supabase-production": "BASELODGE_PRODUCTION_DATABASE_URL",
}
_MIGRATION_TARGET_IDENTITY_HASH_KEYS = {
    "replit": "BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH",
    "supabase-development": (
        "BASELODGE_MIGRATION_SUPABASE_DEVELOPMENT_IDENTITY_HASH"
    ),
    "supabase-production": (
        "BASELODGE_MIGRATION_SUPABASE_PRODUCTION_IDENTITY_HASH"
    ),
}
_MIGRATION_TARGET_RUNTIME_ENVS = {
    "replit": frozenset({"development", "test"}),
    "supabase-development": frozenset({"development"}),
    "supabase-production": frozenset({"production"}),
}


class RuntimeConfigurationError(RuntimeError):
    """Raised before database engine construction for unsafe configuration."""


@dataclass(frozen=True)
class DatabaseConfiguration:
    runtime_env: str
    database_url: str
    source: str
    legacy_production_compatibility: bool = False
    migration_target: str | None = None
    verified_identity_hash: str | None = None

    @property
    def debug_enabled(self) -> bool:
        return self.runtime_env == "development"

    @property
    def safe_identity(self) -> str:
        return database_identity(self.database_url)


def _value(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _runtime_env(environ: Mapping[str, str]) -> str:
    runtime_env = _value(environ, "BASELODGE_RUNTIME_ENV")
    if runtime_env not in _VALID_RUNTIME_ENVS:
        raise RuntimeConfigurationError(
            "BASELODGE_RUNTIME_ENV must be explicitly set to development, test, or production."
        )
    return runtime_env


def _normalize_url(database_url: str) -> str:
    normalized = database_url.strip().strip('"').strip("'")
    if normalized.startswith("postgres://"):
        return "postgresql://" + normalized[len("postgres://") :]
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+asyncpg://",
        "postgresql+aiopg://",
    ):
        if normalized.startswith(prefix):
            return "postgresql://" + normalized[len(prefix) :]
    return normalized


def _canonical_hostname(hostname: str) -> str:
    """Normalize a DNS hostname without changing its endpoint semantics."""
    return hostname.lower().removesuffix(".")


def database_identity(database_url: str) -> str:
    """Return a credential-free canonical connection identity."""
    identity, parsed = _database_endpoint_identity(database_url)
    if parsed.scheme.lower().startswith("sqlite"):
        return identity

    project_ref_hash = _supabase_pooler_project_ref_hash(parsed)
    if project_ref_hash:
        return f"{identity}?supabase_project_ref_sha256={project_ref_hash}"
    return identity


def _database_endpoint_identity(database_url: str):
    """Return the historical credential-free endpoint identity and parsed URL."""
    try:
        parsed = urlsplit(_normalize_url(database_url))
        parsed_port = parsed.port
    except ValueError as exc:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid."
        ) from exc
    scheme = parsed.scheme.lower()
    if scheme.startswith("sqlite"):
        path = parsed.path or ":memory:"
        return f"sqlite:{path}", parsed

    if not scheme or not parsed.hostname or not parsed.path:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid; a host and database name are required."
        )
    host = _canonical_hostname(parsed.hostname)
    port = parsed_port or (5432 if scheme.startswith("postgres") else 0)
    database_name = parsed.path.lstrip("/").split("/")[0]
    if not database_name:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid; a host and database name are required."
        )
    return f"{scheme}://{host}:{port}/{database_name}", parsed


def _supabase_pooler_project_ref_hash(parsed) -> str | None:
    host = _canonical_hostname(parsed.hostname or "")
    if not _SUPABASE_POOLER_HOST_PATTERN.fullmatch(host):
        return None

    username = unquote(parsed.username or "")
    if "." not in username:
        raise RuntimeConfigurationError(
            "Supabase pooler database username must include a valid project reference."
        )
    role, project_ref = username.rsplit(".", 1)
    if not role or not _SUPABASE_PROJECT_REF_PATTERN.fullmatch(project_ref):
        raise RuntimeConfigurationError(
            "Supabase pooler database username must include a valid project reference."
        )
    return hashlib.sha256(project_ref.encode("utf-8")).hexdigest()


def supabase_pooler_project_ref_hash(database_url: str) -> str | None:
    """Return only the non-reversible project-reference hash for a pooler URL."""
    return _supabase_pooler_project_ref_hash(urlsplit(_normalize_url(database_url)))


def database_identity_hash(database_url: str) -> str:
    identity = database_identity(database_url)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _database_endpoint_identity_hash(database_url: str) -> str:
    identity, _ = _database_endpoint_identity(database_url)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _expected_identity_hash(environ: Mapping[str, str], key: str) -> str:
    configured_hash = _value(environ, key)
    if not configured_hash or not _HASH_PATTERN.fullmatch(configured_hash):
        raise RuntimeConfigurationError(
            f"{key} must be configured as a SHA-256 database identity hash."
        )
    return configured_hash.split(":", 1)[-1].lower()


def _database_hostname(database_url: str) -> str:
    try:
        parsed = urlsplit(_normalize_url(database_url))
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid."
        ) from exc
    if not hostname:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid; a host and database name are required."
        )
    return _canonical_hostname(hostname)


def _is_supabase_database_url(database_url: str) -> bool:
    hostname = _database_hostname(database_url)
    return hostname.endswith(".supabase.com") or hostname.endswith(".supabase.co")


def _validate_migration_database_class(
    migration_target: str, database_url: str
) -> None:
    parsed = urlsplit(_normalize_url(database_url))
    if not parsed.scheme.lower().startswith("postgresql"):
        raise RuntimeConfigurationError(
            "Migration target database URL must use a PostgreSQL dialect."
        )

    is_supabase = _is_supabase_database_url(database_url)
    if migration_target == "replit" and is_supabase:
        raise RuntimeConfigurationError(
            "Migration target replit cannot use a Supabase database URL."
        )
    if migration_target.startswith("supabase-") and not is_supabase:
        raise RuntimeConfigurationError(
            f"Migration target {migration_target} requires a Supabase database URL."
        )


def migration_database_diagnostic(
    configuration: DatabaseConfiguration,
) -> Mapping[str, str]:
    """Return credential-free fields for the offline migration diagnostic."""
    if not configuration.migration_target or not configuration.verified_identity_hash:
        raise RuntimeConfigurationError(
            "Migration diagnostic requires a verified migration configuration."
        )

    parsed = urlsplit(_normalize_url(configuration.database_url))
    hostname = _database_hostname(configuration.database_url)
    if _SUPABASE_DIRECT_HOST_PATTERN.fullmatch(hostname):
        hostname = "db.[project-ref-redacted].supabase.co"
    elif _SUPABASE_POOLER_HOST_PATTERN.fullmatch(hostname):
        hostname = "[supabase-session-pooler]"
    database_name = parsed.path.lstrip("/").split("/")[0]
    dialect = parsed.scheme.lower().split("+", 1)[0]

    return {
        "migration_target": configuration.migration_target,
        "source": configuration.source,
        "dialect": dialect,
        "hostname": hostname,
        "database_name": database_name,
        "identity_hash": "sha256:[verified]",
        "verification": "PASS",
    }


def _expected_production_hash(environ: Mapping[str, str]) -> str:
    configured_hash = _value(environ, "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH")
    if not configured_hash or not _HASH_PATTERN.fullmatch(configured_hash):
        raise RuntimeConfigurationError(
            "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH must be configured for development and test safety."
        )
    return configured_hash.split(":", 1)[-1].lower()


def _expected_production_supabase_project_ref_hash(
    environ: Mapping[str, str],
) -> str:
    configured_hash = _value(
        environ, "BASELODGE_PRODUCTION_SUPABASE_PROJECT_REF_HASH"
    )
    if not configured_hash or not _HASH_PATTERN.fullmatch(configured_hash):
        raise RuntimeConfigurationError(
            "BASELODGE_PRODUCTION_SUPABASE_PROJECT_REF_HASH must be configured "
            "for shared Supabase pooler safety."
        )
    return configured_hash.split(":", 1)[-1].lower()


def _matches_protected_production_identity(
    database_url: str, environ: Mapping[str, str]
) -> bool:
    expected_database_hash = _expected_production_hash(environ)
    project_ref_hash = supabase_pooler_project_ref_hash(database_url)
    if project_ref_hash is not None:
        return (
            project_ref_hash
            == _expected_production_supabase_project_ref_hash(environ)
        )
    return database_identity_hash(database_url) == expected_database_hash


def _validate_protected_live_production_target(
    database_url: str,
    environ: Mapping[str, str],
) -> None:
    """Require both historical endpoint and Supabase project ownership."""
    _, parsed = _database_endpoint_identity(database_url)
    host = _canonical_hostname(parsed.hostname or "")
    port = parsed.port or 5432
    project_ref_hash = _supabase_pooler_project_ref_hash(parsed)
    if (
        not _SUPABASE_POOLER_HOST_PATTERN.fullmatch(host)
        or port != 5432
        or project_ref_hash is None
    ):
        raise RuntimeConfigurationError(
            "Protected live Production target must be a Supabase Session Pooler."
        )

    if not hmac.compare_digest(
        _database_endpoint_identity_hash(database_url),
        _expected_production_hash(environ),
    ):
        raise RuntimeConfigurationError(
            "Protected live Production endpoint identity does not match."
        )
    if not hmac.compare_digest(
        project_ref_hash,
        _expected_production_supabase_project_ref_hash(environ),
    ):
        raise RuntimeConfigurationError(
            "Protected live Production project identity does not match."
        )


def _production_targets_agree(
    live_database_url: str,
    explicit_database_url: str,
) -> bool:
    """Compare credential-free endpoint, connection class, and project identity."""
    try:
        live_identity, live_parsed = _database_endpoint_identity(live_database_url)
        explicit_identity, explicit_parsed = _database_endpoint_identity(
            explicit_database_url
        )
        live_project = _supabase_pooler_project_ref_hash(live_parsed)
        explicit_project = _supabase_pooler_project_ref_hash(explicit_parsed)
    except (RuntimeConfigurationError, ValueError):
        return False

    return (
        live_project is not None
        and explicit_project is not None
        and hmac.compare_digest(live_identity, explicit_identity)
        and hmac.compare_digest(live_project, explicit_project)
    )


def _reject_production_identity(database_url: str, environ: Mapping[str, str]) -> None:
    if _matches_protected_production_identity(database_url, environ):
        raise RuntimeConfigurationError(
            "Configured database matches the protected production database identity and is not allowed here."
        )


def _require_url(environ: Mapping[str, str], key: str, runtime_env: str) -> str:
    database_url = _value(environ, key)
    if not database_url:
        raise RuntimeConfigurationError(
            f"{key} is required when BASELODGE_RUNTIME_ENV={runtime_env}."
        )
    return _normalize_url(database_url)


def resolve_application_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Select the normal application database without cross-environment fallback."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)

    if runtime_env == "development":
        database_url = _require_url(
            environment, "BASELODGE_DEVELOPMENT_DATABASE_URL", runtime_env
        )
        _reject_production_identity(database_url, environment)
        return DatabaseConfiguration(runtime_env, database_url, "development")

    if runtime_env == "test":
        database_url = _require_url(
            environment, "BASELODGE_TEST_DATABASE_URL", runtime_env
        )
        _reject_production_identity(database_url, environment)
        return DatabaseConfiguration(runtime_env, database_url, "test")

    database_url = _value(environment, "BASELODGE_PRODUCTION_DATABASE_URL")
    if database_url:
        return DatabaseConfiguration(
            runtime_env, _normalize_url(database_url), "production"
        )

    # Temporary compatibility for the existing published deployment only.
    legacy_url = _value(environment, "SUPABASE_DATABASE_URL")
    if legacy_url:
        return DatabaseConfiguration(
            runtime_env,
            _normalize_url(legacy_url),
            "legacy_supabase_production",
            legacy_production_compatibility=True,
        )

    raise RuntimeConfigurationError(
        "BASELODGE_PRODUCTION_DATABASE_URL is required when BASELODGE_RUNTIME_ENV=production."
    )


def resolve_migration_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Resolve and verify an explicitly selected migration database target."""
    environment = os.environ if environ is None else environ
    if _value(environment, "BASELODGE_MIGRATION_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_MIGRATION_MODE=1 is required for migration database access."
        )

    migration_target = _value(environment, "BASELODGE_MIGRATION_TARGET")
    if migration_target is None:
        raise RuntimeConfigurationError(
            "BASELODGE_MIGRATION_TARGET is required for migration database access."
        )
    if migration_target not in _VALID_MIGRATION_TARGETS:
        raise RuntimeConfigurationError(
            "BASELODGE_MIGRATION_TARGET must be exactly replit, "
            "supabase-development, or supabase-production."
        )

    runtime_env = _runtime_env(environment)
    allowed_runtime_envs = _MIGRATION_TARGET_RUNTIME_ENVS[migration_target]
    if runtime_env not in allowed_runtime_envs:
        expected_runtime_env = " or ".join(sorted(allowed_runtime_envs))
        raise RuntimeConfigurationError(
            f"Migration target {migration_target} requires "
            f"BASELODGE_RUNTIME_ENV={expected_runtime_env}."
        )

    if migration_target == "supabase-production":
        url_key = "SUPABASE_DATABASE_URL"
        database_url = _require_url(environment, url_key, runtime_env)
        _validate_migration_database_class(migration_target, database_url)
        _validate_protected_live_production_target(database_url, environment)

        explicit_database_url = _value(
            environment, "BASELODGE_PRODUCTION_DATABASE_URL"
        )
        if explicit_database_url and not _production_targets_agree(
            database_url, explicit_database_url
        ):
            raise RuntimeConfigurationError(
                "Contradictory explicit and live Production database targets."
            )
        identity_hash = database_identity_hash(database_url)
    else:
        url_key = _MIGRATION_TARGET_URL_KEYS[migration_target]
        database_url = _require_url(environment, url_key, runtime_env)
        _validate_migration_database_class(migration_target, database_url)

        identity_hash = database_identity_hash(database_url)
        identity_hash_key = _MIGRATION_TARGET_IDENTITY_HASH_KEYS[migration_target]
        expected_identity_hash = _expected_identity_hash(
            environment, identity_hash_key
        )
        if not hmac.compare_digest(identity_hash, expected_identity_hash):
            raise RuntimeConfigurationError(
                f"Migration target {migration_target} does not match its configured "
                "database identity."
            )

    if (
        migration_target == "supabase-production"
        and _value(environment, "BASELODGE_CONFIRM_PRODUCTION_MIGRATION") != "1"
    ):
        raise RuntimeConfigurationError(
            "BASELODGE_CONFIRM_PRODUCTION_MIGRATION=1 is required for "
            "Supabase Production migration access."
        )

    return DatabaseConfiguration(
        runtime_env=runtime_env,
        database_url=database_url,
        source=url_key,
        migration_target=migration_target,
        verified_identity_hash=identity_hash,
    )


def resolve_maintenance_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Resolve an explicitly authorized standalone maintenance target."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)
    if _value(environment, "BASELODGE_MAINTENANCE_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_MAINTENANCE_MODE=1 is required for maintenance access."
        )

    database_url = _require_url(
        environment, "BASELODGE_MAINTENANCE_DATABASE_URL", runtime_env
    )
    if not urlsplit(database_url).scheme.lower().startswith("postgresql"):
        raise RuntimeConfigurationError(
            "BASELODGE_MAINTENANCE_DATABASE_URL must use a PostgreSQL dialect."
        )

    if runtime_env == "production":
        if not _matches_protected_production_identity(database_url, environment):
            raise RuntimeConfigurationError(
                "Production maintenance target must match the protected production "
                "database identity."
            )
    else:
        _reject_production_identity(database_url, environment)
        if runtime_env == "development":
            development_url = _require_url(
                environment, "BASELODGE_DEVELOPMENT_DATABASE_URL", runtime_env
            )
            _reject_production_identity(development_url, environment)
            if database_identity(database_url) != database_identity(development_url):
                raise RuntimeConfigurationError(
                    "Development maintenance target must match the configured "
                    "development database identity."
                )

    return DatabaseConfiguration(runtime_env, database_url, "maintenance")


def resolve_bootstrap_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Resolve a guarded, empty-database bootstrap target without opening it."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)
    if runtime_env not in {"development", "test"}:
        raise RuntimeConfigurationError(
            "Bootstrap database access is only allowed for development or test."
        )
    if _value(environment, "BASELODGE_BOOTSTRAP_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_BOOTSTRAP_MODE=1 is required for bootstrap database access."
        )

    database_url = _require_url(
        environment, "BASELODGE_BOOTSTRAP_DATABASE_URL", runtime_env
    )
    if not urlsplit(database_url).scheme.lower().startswith("postgresql"):
        raise RuntimeConfigurationError(
            "BASELODGE_BOOTSTRAP_DATABASE_URL must use a PostgreSQL dialect."
        )
    _reject_production_identity(database_url, environment)

    if runtime_env == "development":
        development_url = _require_url(
            environment, "BASELODGE_DEVELOPMENT_DATABASE_URL", runtime_env
        )
        _reject_production_identity(development_url, environment)
        if database_identity(database_url) != database_identity(development_url):
            raise RuntimeConfigurationError(
                "Development bootstrap target must match the configured development "
                "database identity."
            )

    return DatabaseConfiguration(runtime_env, database_url, "bootstrap")


def resolve_reference_import_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Resolve a guarded development/test reference-data import target."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)
    if runtime_env not in {"development", "test"}:
        raise RuntimeConfigurationError(
            "Reference-data import is only allowed for development or test."
        )
    if _value(environment, "BASELODGE_REFERENCE_IMPORT_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_REFERENCE_IMPORT_MODE=1 is required for reference-data import."
        )

    database_url = _require_url(
        environment, "BASELODGE_REFERENCE_IMPORT_DATABASE_URL", runtime_env
    )
    if not urlsplit(database_url).scheme.lower().startswith("postgresql"):
        raise RuntimeConfigurationError(
            "BASELODGE_REFERENCE_IMPORT_DATABASE_URL must use a PostgreSQL dialect."
        )
    _reject_production_identity(database_url, environment)

    if runtime_env == "development":
        development_url = _require_url(
            environment, "BASELODGE_DEVELOPMENT_DATABASE_URL", runtime_env
        )
        _reject_production_identity(development_url, environment)
        if database_identity(database_url) != database_identity(development_url):
            raise RuntimeConfigurationError(
                "Development reference-import target must match the configured "
                "development database identity."
            )

    return DatabaseConfiguration(runtime_env, database_url, "reference_import")


def resolve_development_user_database_config(
    environ: Mapping[str, str] | None = None,
) -> DatabaseConfiguration:
    """Resolve the explicitly authorized isolated development-user target."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)
    if runtime_env != "development":
        raise RuntimeConfigurationError(
            "Development-user creation is only allowed in development."
        )
    if _value(environment, "BASELODGE_DEVELOPMENT_USER_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_DEVELOPMENT_USER_MODE=1 is required for development-user creation."
        )

    database_url = _require_url(
        environment, "BASELODGE_DEVELOPMENT_USER_DATABASE_URL", runtime_env
    )
    if not urlsplit(database_url).scheme.lower().startswith("postgresql"):
        raise RuntimeConfigurationError(
            "BASELODGE_DEVELOPMENT_USER_DATABASE_URL must use a PostgreSQL dialect."
        )
    _reject_production_identity(database_url, environment)

    configured_development_url = _require_url(
        environment, "BASELODGE_DEVELOPMENT_DATABASE_URL", runtime_env
    )
    if database_identity(database_url) != database_identity(configured_development_url):
        raise RuntimeConfigurationError(
            "Development-user target must match the configured development "
            "database identity."
        )

    return DatabaseConfiguration(runtime_env, database_url, "development_user")