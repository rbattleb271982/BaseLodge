"""Side-effect-free runtime and database configuration for BaseLodge.

This module must remain safe to import from tooling, tests, and Alembic.  It
does not import Flask, SQLAlchemy, or application models, and it never opens a
database connection.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
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


class RuntimeConfigurationError(RuntimeError):
    """Raised before database engine construction for unsafe configuration."""


@dataclass(frozen=True)
class DatabaseConfiguration:
    runtime_env: str
    database_url: str
    source: str
    legacy_production_compatibility: bool = False

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
    parsed = urlsplit(_normalize_url(database_url))
    scheme = parsed.scheme.lower()
    if scheme.startswith("sqlite"):
        path = parsed.path or ":memory:"
        return f"sqlite:{path}"

    if not parsed.hostname or not parsed.path:
        raise RuntimeConfigurationError(
            "Configured database URL is invalid; a host and database name are required."
        )
    host = _canonical_hostname(parsed.hostname)
    port = parsed.port or (5432 if scheme.startswith("postgres") else 0)
    database_name = parsed.path.lstrip("/").split("/")[0]
    identity = f"{scheme}://{host}:{port}/{database_name}"
    project_ref_hash = _supabase_pooler_project_ref_hash(parsed)
    if project_ref_hash:
        return f"{identity}?supabase_project_ref_sha256={project_ref_hash}"
    return identity


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
    """Select the migration-only database without importing the Flask app."""
    environment = os.environ if environ is None else environ
    runtime_env = _runtime_env(environment)
    if _value(environment, "BASELODGE_MIGRATION_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_MIGRATION_MODE=1 is required for migration database access."
        )

    database_url = _require_url(
        environment, "BASELODGE_MIGRATION_DATABASE_URL", runtime_env
    )
    if runtime_env in {"development", "test"}:
        _reject_production_identity(database_url, environment)
    return DatabaseConfiguration(runtime_env, database_url, "migration")


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