"""Safety coverage for side-effect-free BaseLodge database configuration."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from runtime_config import (
    RuntimeConfigurationError,
    database_identity,
    database_identity_hash,
    resolve_application_database_config,
    resolve_bootstrap_database_config,
    resolve_development_user_database_config,
    resolve_maintenance_database_config,
    resolve_migration_database_config,
    resolve_reference_import_database_config,
    supabase_pooler_project_ref_hash,
)


PRODUCTION_URL = "postgresql://prod_user:never-log@prod.db.example:6543/baselodge"
PRODUCTION_URL_ALTERNATE_ROLE = (
    "postgresql://alternate_role:never-log@prod.db.example:6543/baselodge"
)
DEVELOPMENT_URL = "postgresql://dev_user:never-log@dev.db.example:6543/baselodge"
TEST_URL = "sqlite:///:memory:"
PRODUCTION_HASH = database_identity_hash(PRODUCTION_URL)
SUPABASE_POOLER_HOST = "aws-0-us-east-2.pooler.supabase.com"
PRODUCTION_PROJECT_REF = "abcdefghijklmnopqrst"
DEVELOPMENT_PROJECT_REF = "tsrqponmlkjihgfedcba"
PRODUCTION_POOLER_URL = (
    f"postgresql://postgres.{PRODUCTION_PROJECT_REF}:first-password"
    f"@{SUPABASE_POOLER_HOST}:5432/postgres"
)
PRODUCTION_POOLER_ALTERNATE_ROLE_URL = (
    f"postgresql://readonly.{PRODUCTION_PROJECT_REF}:second-password"
    f"@{SUPABASE_POOLER_HOST}:5432/postgres"
)
DEVELOPMENT_POOLER_URL = (
    f"postgresql://postgres.{DEVELOPMENT_PROJECT_REF}:dev-password"
    f"@{SUPABASE_POOLER_HOST}:5432/postgres"
)
LEGACY_POOLER_ENDPOINT_HASH = hashlib.sha256(
    f"postgresql://{SUPABASE_POOLER_HOST}:5432/postgres".encode()
).hexdigest()
PRODUCTION_PROJECT_REF_HASH = hashlib.sha256(
    PRODUCTION_PROJECT_REF.encode()
).hexdigest()


def _environment(**overrides):
    environment = {
        "BASELODGE_RUNTIME_ENV": "development",
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
    }
    environment.update(overrides)
    return environment


def _pooler_environment(**overrides):
    environment = {
        "BASELODGE_RUNTIME_ENV": "development",
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": (
            LEGACY_POOLER_ENDPOINT_HASH
        ),
        "BASELODGE_PRODUCTION_SUPABASE_PROJECT_REF_HASH": (
            PRODUCTION_PROJECT_REF_HASH
        ),
    }
    environment.update(overrides)
    return environment


def test_supabase_pooler_identity_ignores_password_and_role_for_same_project():
    assert database_identity(PRODUCTION_POOLER_URL) == database_identity(
        PRODUCTION_POOLER_ALTERNATE_ROLE_URL
    )
    identity = database_identity(PRODUCTION_POOLER_URL)
    assert PRODUCTION_PROJECT_REF not in identity
    assert "://postgres." not in identity
    assert "://readonly." not in identity
    assert "password" not in identity
    assert PRODUCTION_PROJECT_REF_HASH in identity


def test_supabase_pooler_identity_distinguishes_projects_on_same_endpoint():
    assert database_identity(PRODUCTION_POOLER_URL) != database_identity(
        DEVELOPMENT_POOLER_URL
    )


def test_supabase_pooler_identity_canonicalizes_terminal_dns_dot():
    trailing_dot_url = PRODUCTION_POOLER_URL.replace(
        f"@{SUPABASE_POOLER_HOST}:",
        f"@{SUPABASE_POOLER_HOST}.:",
    )
    assert database_identity(trailing_dot_url) == database_identity(
        PRODUCTION_POOLER_URL
    )
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_application_database_config(
            _pooler_environment(
                BASELODGE_DEVELOPMENT_DATABASE_URL=trailing_dot_url
            )
        )


@pytest.mark.parametrize(
    "username",
    [
        "postgres",
        "postgres.",
        ".abcdefghijklmnopqrst",
        "postgres.too-short",
        "postgres.ABCDEFGHIJKLMNOPQRST",
    ],
)
def test_supabase_pooler_identity_rejects_malformed_project_reference(username):
    with pytest.raises(RuntimeConfigurationError, match="project reference"):
        database_identity(
            f"postgresql://{username}:secret@{SUPABASE_POOLER_HOST}:5432/postgres"
        )


def test_supabase_pooler_project_hash_exposes_no_project_reference():
    assert (
        supabase_pooler_project_ref_hash(PRODUCTION_POOLER_URL)
        == PRODUCTION_PROJECT_REF_HASH
    )


def test_direct_supabase_hostname_retains_existing_identity_behavior():
    direct_url = (
        f"postgresql://postgres:secret@db.{DEVELOPMENT_PROJECT_REF}"
        ".supabase.co:5432/postgres"
    )
    assert database_identity(direct_url) == (
        f"postgresql://db.{DEVELOPMENT_PROJECT_REF}.supabase.co:5432/postgres"
    )
    assert supabase_pooler_project_ref_hash(direct_url) is None


def test_pooler_guard_requires_explicit_production_project_hash():
    with pytest.raises(
        RuntimeConfigurationError,
        match="PRODUCTION_SUPABASE_PROJECT_REF_HASH",
    ):
        resolve_application_database_config(
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_DEVELOPMENT_DATABASE_URL": DEVELOPMENT_POOLER_URL,
                "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": (
                    LEGACY_POOLER_ENDPOINT_HASH
                ),
            }
        )


def test_development_rejects_production_pooler_with_alternate_role():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_application_database_config(
            _pooler_environment(
                BASELODGE_DEVELOPMENT_DATABASE_URL=(
                    PRODUCTION_POOLER_ALTERNATE_ROLE_URL
                )
            )
        )


def test_migration_rejects_production_pooler_with_alternate_role():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_migration_database_config(
            _pooler_environment(
                BASELODGE_MIGRATION_MODE="1",
                BASELODGE_MIGRATION_DATABASE_URL=(
                    PRODUCTION_POOLER_ALTERNATE_ROLE_URL
                ),
            )
        )


def test_development_maintenance_rejects_production_pooler():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_maintenance_database_config(
            _pooler_environment(
                BASELODGE_MAINTENANCE_MODE="1",
                BASELODGE_MAINTENANCE_DATABASE_URL=(
                    PRODUCTION_POOLER_ALTERNATE_ROLE_URL
                ),
                BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_POOLER_URL,
            )
        )


def test_production_maintenance_accepts_protected_pooler_across_roles():
    configuration = resolve_maintenance_database_config(
        _pooler_environment(
            BASELODGE_RUNTIME_ENV="production",
            BASELODGE_MAINTENANCE_MODE="1",
            BASELODGE_MAINTENANCE_DATABASE_URL=(
                PRODUCTION_POOLER_ALTERNATE_ROLE_URL
            ),
        )
    )
    assert configuration.database_url == PRODUCTION_POOLER_ALTERNATE_ROLE_URL


def test_development_accepts_different_project_on_same_pooler():
    configuration = resolve_application_database_config(
        _pooler_environment(
            BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_POOLER_URL
        )
    )
    assert configuration.database_url == DEVELOPMENT_POOLER_URL


@pytest.mark.parametrize(
    "resolver,mode_key,target_key",
    [
        (
            resolve_bootstrap_database_config,
            "BASELODGE_BOOTSTRAP_MODE",
            "BASELODGE_BOOTSTRAP_DATABASE_URL",
        ),
        (
            resolve_reference_import_database_config,
            "BASELODGE_REFERENCE_IMPORT_MODE",
            "BASELODGE_REFERENCE_IMPORT_DATABASE_URL",
        ),
        (
            resolve_development_user_database_config,
            "BASELODGE_DEVELOPMENT_USER_MODE",
            "BASELODGE_DEVELOPMENT_USER_DATABASE_URL",
        ),
    ],
)
def test_pooler_guards_accept_same_dev_project_across_roles(
    resolver, mode_key, target_key
):
    alternate_dev_role = DEVELOPMENT_POOLER_URL.replace(
        f"postgres.{DEVELOPMENT_PROJECT_REF}:dev-password",
        f"migration.{DEVELOPMENT_PROJECT_REF}:another-password",
    )
    configuration = resolver(
        _pooler_environment(
            **{
                "BASELODGE_DEVELOPMENT_DATABASE_URL": DEVELOPMENT_POOLER_URL,
                mode_key: "1",
                target_key: alternate_dev_role,
            }
        )
    )
    assert configuration.database_url == alternate_dev_role


@pytest.mark.parametrize(
    "resolver,mode_key,target_key",
    [
        (
            resolve_bootstrap_database_config,
            "BASELODGE_BOOTSTRAP_MODE",
            "BASELODGE_BOOTSTRAP_DATABASE_URL",
        ),
        (
            resolve_reference_import_database_config,
            "BASELODGE_REFERENCE_IMPORT_MODE",
            "BASELODGE_REFERENCE_IMPORT_DATABASE_URL",
        ),
        (
            resolve_development_user_database_config,
            "BASELODGE_DEVELOPMENT_USER_MODE",
            "BASELODGE_DEVELOPMENT_USER_DATABASE_URL",
        ),
    ],
)
def test_pooler_guards_reject_production_project(
    resolver, mode_key, target_key
):
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolver(
            _pooler_environment(
                **{
                    "BASELODGE_DEVELOPMENT_DATABASE_URL": DEVELOPMENT_POOLER_URL,
                    mode_key: "1",
                    target_key: PRODUCTION_POOLER_ALTERNATE_ROLE_URL,
                }
            )
        )


def test_development_requires_its_own_database_url():
    with pytest.raises(RuntimeConfigurationError, match="DEVELOPMENT_DATABASE_URL"):
        resolve_application_database_config(_environment())


def test_test_requires_its_own_database_url():
    with pytest.raises(RuntimeConfigurationError, match="TEST_DATABASE_URL"):
        resolve_application_database_config(
            _environment(BASELODGE_RUNTIME_ENV="test")
        )


def test_production_requires_explicit_configuration_when_legacy_url_absent():
    with pytest.raises(RuntimeConfigurationError, match="PRODUCTION_DATABASE_URL"):
        resolve_application_database_config(
            _environment(BASELODGE_RUNTIME_ENV="production")
        )


def test_development_rejects_production_identity_before_engine_creation():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_application_database_config(
            _environment(BASELODGE_DEVELOPMENT_DATABASE_URL=PRODUCTION_URL)
        )


def test_test_rejects_production_identity_before_engine_creation():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_application_database_config(
            _environment(
                BASELODGE_RUNTIME_ENV="test",
                BASELODGE_TEST_DATABASE_URL=PRODUCTION_URL,
            )
        )


@pytest.mark.parametrize("runtime_env,database_key", [
    ("development", "BASELODGE_DEVELOPMENT_DATABASE_URL"),
    ("test", "BASELODGE_TEST_DATABASE_URL"),
])
def test_nonproduction_rejects_production_endpoint_with_alternate_role(
    runtime_env, database_key
):
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_application_database_config(
            _environment(
                BASELODGE_RUNTIME_ENV=runtime_env,
                **{database_key: PRODUCTION_URL_ALTERNATE_ROLE},
            )
        )


def test_development_and_test_ignore_shared_supabase_url():
    development = resolve_application_database_config(
        _environment(
            BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL,
            SUPABASE_DATABASE_URL=PRODUCTION_URL,
        )
    )
    test = resolve_application_database_config(
        _environment(
            BASELODGE_RUNTIME_ENV="test",
            BASELODGE_TEST_DATABASE_URL=TEST_URL,
            SUPABASE_DATABASE_URL=PRODUCTION_URL,
        )
    )

    assert development.database_url == DEVELOPMENT_URL
    assert development.source == "development"
    assert test.database_url == TEST_URL
    assert test.source == "test"


def test_shared_supabase_url_alone_never_selects_development_or_test_database():
    with pytest.raises(RuntimeConfigurationError, match="DEVELOPMENT_DATABASE_URL"):
        resolve_application_database_config(
            _environment(SUPABASE_DATABASE_URL=PRODUCTION_URL)
        )
    with pytest.raises(RuntimeConfigurationError, match="TEST_DATABASE_URL"):
        resolve_application_database_config(
            _environment(
                BASELODGE_RUNTIME_ENV="test",
                SUPABASE_DATABASE_URL=PRODUCTION_URL,
            )
        )


def test_production_legacy_supabase_compatibility_is_narrowly_bounded():
    configuration = resolve_application_database_config(
        _environment(
            BASELODGE_RUNTIME_ENV="production",
            SUPABASE_DATABASE_URL=PRODUCTION_URL,
        )
    )

    assert configuration.database_url == PRODUCTION_URL
    assert configuration.source == "legacy_supabase_production"
    assert configuration.legacy_production_compatibility is True


def test_only_development_enables_debug_behavior():
    assert resolve_application_database_config(
        _environment(BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL)
    ).debug_enabled
    assert not resolve_application_database_config(
        _environment(
            BASELODGE_RUNTIME_ENV="test",
            BASELODGE_TEST_DATABASE_URL=TEST_URL,
        )
    ).debug_enabled
    assert not resolve_application_database_config(
        _environment(
            BASELODGE_RUNTIME_ENV="production",
            BASELODGE_PRODUCTION_DATABASE_URL=PRODUCTION_URL,
        )
    ).debug_enabled


def test_migration_configuration_requires_explicit_mode_and_url():
    with pytest.raises(RuntimeConfigurationError, match="MIGRATION_MODE"):
        resolve_migration_database_config(
            _environment(BASELODGE_MIGRATION_DATABASE_URL=DEVELOPMENT_URL)
        )
    with pytest.raises(RuntimeConfigurationError, match="MIGRATION_DATABASE_URL"):
        resolve_migration_database_config(
            _environment(BASELODGE_MIGRATION_MODE="1")
        )


def test_nonproduction_migration_rejects_production_endpoint_with_alternate_role():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_migration_database_config(
            _environment(
                BASELODGE_MIGRATION_MODE="1",
                BASELODGE_MIGRATION_DATABASE_URL=PRODUCTION_URL_ALTERNATE_ROLE,
            )
        )


def test_maintenance_configuration_requires_explicit_mode_and_target():
    with pytest.raises(RuntimeConfigurationError, match="MAINTENANCE_MODE"):
        resolve_maintenance_database_config(
            _environment(BASELODGE_MAINTENANCE_DATABASE_URL=DEVELOPMENT_URL)
        )
    with pytest.raises(RuntimeConfigurationError, match="MAINTENANCE_DATABASE_URL"):
        resolve_maintenance_database_config(
            _environment(BASELODGE_MAINTENANCE_MODE="1")
        )


def test_development_maintenance_requires_its_configured_database_identity():
    with pytest.raises(RuntimeConfigurationError, match="must match"):
        resolve_maintenance_database_config(
            _environment(
                BASELODGE_MAINTENANCE_MODE="1",
                BASELODGE_MAINTENANCE_DATABASE_URL=(
                    "postgresql://other:never-log@other.db.example:5432/baselodge"
                ),
                BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL,
            )
        )

    configuration = resolve_maintenance_database_config(
        _environment(
            BASELODGE_MAINTENANCE_MODE="1",
            BASELODGE_MAINTENANCE_DATABASE_URL=DEVELOPMENT_URL,
            BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL,
        )
    )
    assert configuration.source == "maintenance"
    assert configuration.runtime_env == "development"


def test_production_maintenance_requires_protected_production_identity():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_maintenance_database_config(
            _environment(
                BASELODGE_RUNTIME_ENV="production",
                BASELODGE_MAINTENANCE_MODE="1",
                BASELODGE_MAINTENANCE_DATABASE_URL=DEVELOPMENT_URL,
            )
        )

    configuration = resolve_maintenance_database_config(
        _environment(
            BASELODGE_RUNTIME_ENV="production",
            BASELODGE_MAINTENANCE_MODE="1",
            BASELODGE_MAINTENANCE_DATABASE_URL=PRODUCTION_URL_ALTERNATE_ROLE,
        )
    )
    assert configuration.safe_identity == (
        "postgresql://prod.db.example:6543/baselodge"
    )


def test_safe_identity_excludes_database_username_and_password():
    configuration = resolve_application_database_config(
        _environment(BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL)
    )

    assert configuration.safe_identity == (
        "postgresql://dev.db.example:6543/baselodge"
    )
    assert "dev_user" not in configuration.safe_identity
    assert "never-log" not in configuration.safe_identity


def test_migration_graph_inspection_does_not_import_app():
    environment = os.environ.copy()
    for key in (
        "BASELODGE_RUNTIME_ENV",
        "BASELODGE_DEVELOPMENT_DATABASE_URL",
        "BASELODGE_TEST_DATABASE_URL",
        "BASELODGE_PRODUCTION_DATABASE_URL",
        "BASELODGE_MIGRATION_DATABASE_URL",
        "BASELODGE_MIGRATION_MODE",
        "SUPABASE_DATABASE_URL",
    ):
        environment.pop(key, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "migrations/alembic.ini",
            "heads",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "bl317_startup_schema" in result.stdout