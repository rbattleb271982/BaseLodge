"""Safety coverage for side-effect-free BaseLodge database configuration."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from runtime_config import (
    RuntimeConfigurationError,
    database_identity_hash,
    resolve_application_database_config,
    resolve_maintenance_database_config,
    resolve_migration_database_config,
)


PRODUCTION_URL = "postgresql://prod_user:never-log@prod.db.example:6543/baselodge"
PRODUCTION_URL_ALTERNATE_ROLE = (
    "postgresql://alternate_role:never-log@prod.db.example:6543/baselodge"
)
DEVELOPMENT_URL = "postgresql://dev_user:never-log@dev.db.example:6543/baselodge"
TEST_URL = "sqlite:///:memory:"
PRODUCTION_HASH = database_identity_hash(PRODUCTION_URL)


def _environment(**overrides):
    environment = {
        "BASELODGE_RUNTIME_ENV": "development",
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
    }
    environment.update(overrides)
    return environment


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