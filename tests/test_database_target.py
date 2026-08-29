"""Offline safety coverage for explicit migration database targets."""

from __future__ import annotations

import ast
from contextlib import contextmanager
import logging.config
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from runtime_config import (
    RuntimeConfigurationError,
    database_identity_hash,
    migration_database_diagnostic,
    resolve_application_database_config,
    resolve_migration_database_config,
)
from scripts import database_target


PROJECT_ROOT = Path(__file__).parents[1]
MIGRATION_ENV_PATH = PROJECT_ROOT / "migrations" / "env.py"
REPLIT_URL = (
    "postgresql://replit-user:replit-password@"
    "ep-synthetic-replit.example:5432/baselodge"
)
DEVELOPMENT_REF = "abcdefghijklmnopqrst"
PRODUCTION_REF = "tsrqponmlkjihgfedcba"
POOLER_HOST = "aws-0-us-west-1.pooler.supabase.com"
DEVELOPMENT_URL = (
    f"postgresql://postgres.{DEVELOPMENT_REF}:development-password"
    f"@{POOLER_HOST}:5432/postgres"
)
PRODUCTION_URL = (
    f"postgresql://postgres.{PRODUCTION_REF}:production-password"
    f"@{POOLER_HOST}:5432/postgres"
)
DIRECT_DEVELOPMENT_URL = (
    f"postgresql://postgres:development-password@"
    f"db.{DEVELOPMENT_REF}.supabase.co:5432/postgres"
)


def _migration_environment(target: str, **overrides) -> dict[str, str]:
    environment = {
        "BASELODGE_MIGRATION_MODE": "1",
        "BASELODGE_MIGRATION_TARGET": target,
    }
    if target == "replit":
        environment.update(
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "DATABASE_URL": REPLIT_URL,
                "BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH": (
                    database_identity_hash(REPLIT_URL)
                ),
            }
        )
    elif target == "supabase-development":
        environment.update(
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_DEVELOPMENT_DATABASE_URL": DEVELOPMENT_URL,
                "BASELODGE_MIGRATION_SUPABASE_DEVELOPMENT_IDENTITY_HASH": (
                    database_identity_hash(DEVELOPMENT_URL)
                ),
            }
        )
    elif target == "supabase-production":
        environment.update(
            {
                "BASELODGE_RUNTIME_ENV": "production",
                "BASELODGE_PRODUCTION_DATABASE_URL": PRODUCTION_URL,
                "BASELODGE_MIGRATION_SUPABASE_PRODUCTION_IDENTITY_HASH": (
                    database_identity_hash(PRODUCTION_URL)
                ),
                "BASELODGE_CONFIRM_PRODUCTION_MIGRATION": "1",
            }
        )
    environment.update(overrides)
    return environment


@pytest.mark.parametrize(
    "target,source",
    [
        ("replit", "DATABASE_URL"),
        ("supabase-development", "BASELODGE_DEVELOPMENT_DATABASE_URL"),
        ("supabase-production", "BASELODGE_PRODUCTION_DATABASE_URL"),
    ],
)
def test_explicit_target_with_matching_identity_passes(target, source):
    configuration = resolve_migration_database_config(
        _migration_environment(target)
    )

    assert configuration.migration_target == target
    assert configuration.source == source
    assert configuration.verified_identity_hash == database_identity_hash(
        configuration.database_url
    )


def test_missing_and_unknown_targets_fail_closed():
    with pytest.raises(RuntimeConfigurationError, match="MIGRATION_TARGET is required"):
        resolve_migration_database_config(
            {
                "BASELODGE_MIGRATION_MODE": "1",
                "BASELODGE_RUNTIME_ENV": "development",
                "DATABASE_URL": REPLIT_URL,
            }
        )
    with pytest.raises(RuntimeConfigurationError, match="must be exactly"):
        resolve_migration_database_config(
            {
                "BASELODGE_MIGRATION_MODE": "1",
                "BASELODGE_MIGRATION_TARGET": "development",
            }
        )


@pytest.mark.parametrize(
    "target,url_key",
    [
        ("replit", "DATABASE_URL"),
        ("supabase-development", "BASELODGE_DEVELOPMENT_DATABASE_URL"),
        ("supabase-production", "BASELODGE_PRODUCTION_DATABASE_URL"),
    ],
)
def test_missing_target_specific_url_fails(target, url_key):
    environment = _migration_environment(target)
    environment.pop(url_key)

    with pytest.raises(RuntimeConfigurationError, match=url_key):
        resolve_migration_database_config(environment)


def test_malformed_database_url_fails_without_echoing_value():
    malformed = "postgresql://user:top-secret@host.example:not-a-port/database"
    environment = _migration_environment(
        "replit",
        DATABASE_URL=malformed,
    )

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        resolve_migration_database_config(environment)

    assert "top-secret" not in str(exc_info.value)
    assert malformed not in str(exc_info.value)


def test_development_target_rejects_production_identity():
    environment = _migration_environment(
        "supabase-development",
        BASELODGE_DEVELOPMENT_DATABASE_URL=PRODUCTION_URL,
    )

    with pytest.raises(RuntimeConfigurationError, match="does not match"):
        resolve_migration_database_config(environment)


def test_production_target_rejects_development_identity():
    environment = _migration_environment(
        "supabase-production",
        BASELODGE_PRODUCTION_DATABASE_URL=DEVELOPMENT_URL,
    )

    with pytest.raises(RuntimeConfigurationError, match="does not match"):
        resolve_migration_database_config(environment)


def test_replit_target_rejects_supabase_url_before_identity_comparison():
    environment = _migration_environment(
        "replit",
        DATABASE_URL=DEVELOPMENT_URL,
        BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH=database_identity_hash(
            DEVELOPMENT_URL
        ),
    )

    with pytest.raises(RuntimeConfigurationError, match="cannot use a Supabase"):
        resolve_migration_database_config(environment)


def test_supabase_target_cannot_fall_back_to_database_url():
    environment = _migration_environment("supabase-development")
    environment.pop("BASELODGE_DEVELOPMENT_DATABASE_URL")
    environment["DATABASE_URL"] = DEVELOPMENT_URL

    with pytest.raises(
        RuntimeConfigurationError,
        match="BASELODGE_DEVELOPMENT_DATABASE_URL",
    ):
        resolve_migration_database_config(environment)


def test_legacy_supabase_and_generic_migration_urls_cannot_authorize():
    environment = {
        "BASELODGE_RUNTIME_ENV": "development",
        "BASELODGE_MIGRATION_MODE": "1",
        "BASELODGE_MIGRATION_TARGET": "supabase-development",
        "SUPABASE_DATABASE_URL": DEVELOPMENT_URL,
        "BASELODGE_MIGRATION_DATABASE_URL": DEVELOPMENT_URL,
        "BASELODGE_MIGRATION_SUPABASE_DEVELOPMENT_IDENTITY_HASH": (
            database_identity_hash(DEVELOPMENT_URL)
        ),
    }

    with pytest.raises(
        RuntimeConfigurationError,
        match="BASELODGE_DEVELOPMENT_DATABASE_URL",
    ):
        resolve_migration_database_config(environment)


def test_production_requires_separate_confirmation_after_identity_match():
    environment = _migration_environment("supabase-production")
    environment.pop("BASELODGE_CONFIRM_PRODUCTION_MIGRATION")

    with pytest.raises(
        RuntimeConfigurationError,
        match="CONFIRM_PRODUCTION_MIGRATION",
    ):
        resolve_migration_database_config(environment)


def test_stale_conflicting_variables_do_not_override_selected_target():
    environment = _migration_environment(
        "supabase-development",
        DATABASE_URL=REPLIT_URL,
        SUPABASE_DATABASE_URL=PRODUCTION_URL,
        BASELODGE_MIGRATION_DATABASE_URL=PRODUCTION_URL,
        BASELODGE_PRODUCTION_DATABASE_URL=PRODUCTION_URL,
        BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH=database_identity_hash(
            REPLIT_URL
        ),
        BASELODGE_MIGRATION_SUPABASE_PRODUCTION_IDENTITY_HASH=(
            database_identity_hash(PRODUCTION_URL)
        ),
    )

    configuration = resolve_migration_database_config(environment)

    assert configuration.database_url == DEVELOPMENT_URL
    assert configuration.source == "BASELODGE_DEVELOPMENT_DATABASE_URL"


def test_runtime_environment_must_match_selected_supabase_target():
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_ENV=production"):
        resolve_migration_database_config(
            _migration_environment(
                "supabase-production",
                BASELODGE_RUNTIME_ENV="development",
            )
        )


def test_ordinary_application_resolution_does_not_require_migration_target():
    development_url = (
        "postgresql://app:password@development.example:5432/baselodge"
    )
    configuration = resolve_application_database_config(
        {
            "BASELODGE_RUNTIME_ENV": "development",
            "BASELODGE_DEVELOPMENT_DATABASE_URL": development_url,
            "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": "0" * 64,
        }
    )

    assert configuration.database_url == development_url


def test_offline_diagnostic_is_redacted_and_does_not_check_revision():
    calls = []

    def forbidden_reader(database_url):
        calls.append(database_url)
        raise AssertionError("offline diagnostic opened a database")

    exit_code, report = database_target.diagnose(
        _migration_environment("supabase-development"),
        revision_reader=forbidden_reader,
    )

    assert exit_code == 0
    assert calls == []
    assert "Target verification: PASS" in report
    assert "Alembic revision: NOT CHECKED" in report
    assert "postgres." not in report
    assert "development-password" not in report
    assert DEVELOPMENT_URL not in report
    assert DEVELOPMENT_REF not in report


def test_direct_supabase_hostname_is_redacted_in_diagnostic():
    environment = _migration_environment(
        "supabase-development",
        BASELODGE_DEVELOPMENT_DATABASE_URL=DIRECT_DEVELOPMENT_URL,
        BASELODGE_MIGRATION_SUPABASE_DEVELOPMENT_IDENTITY_HASH=(
            database_identity_hash(DIRECT_DEVELOPMENT_URL)
        ),
    )

    details = migration_database_diagnostic(
        resolve_migration_database_config(environment)
    )

    assert details["hostname"] == "db.[project-ref-redacted].supabase.co"
    assert DEVELOPMENT_REF not in "\n".join(details.values())


def test_invalid_diagnostic_fails_before_revision_reader():
    calls = []

    def forbidden_reader(database_url):
        calls.append(database_url)
        raise AssertionError("invalid diagnostic opened a database")

    exit_code, report = database_target.diagnose(
        {
            "BASELODGE_MIGRATION_MODE": "1",
            "BASELODGE_RUNTIME_ENV": "development",
        },
        check_revision=True,
        revision_reader=forbidden_reader,
    )

    assert exit_code == 2
    assert calls == []
    assert "Target verification: FAIL" in report


def test_revision_check_is_explicit_and_uses_verified_url():
    calls = []

    def revision_reader(database_url):
        calls.append(database_url)
        return ("synthetic_revision",)

    environment = _migration_environment("replit")
    exit_code, report = database_target.diagnose(
        environment,
        check_revision=True,
        revision_reader=revision_reader,
    )

    assert exit_code == 0
    assert calls == [REPLIT_URL]
    assert "Alembic revision: synthetic_revision" in report


class _FakeScalarResult:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = rows

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return iter(self._rows)


class _FakeTransaction:
    def __init__(self, events):
        self.events = events

    def rollback(self):
        self.events.append("rollback")


class _FakeConnection:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("connect")
        return self

    def __exit__(self, *_args):
        self.events.append("connection-close")

    def begin(self):
        self.events.append("begin")
        return _FakeTransaction(self.events)

    def execute(self, statement):
        sql = str(statement)
        self.events.append(sql)
        if sql == "SHOW transaction_read_only":
            return _FakeScalarResult(scalar="on")
        if sql.startswith("SELECT version_num"):
            return _FakeScalarResult(rows=("revision_a",))
        return _FakeScalarResult()


class _FakeEngine:
    def __init__(self, events):
        self.events = events

    def connect(self):
        return _FakeConnection(self.events)

    def dispose(self):
        self.events.append("dispose")


def test_revision_reader_enforces_read_only_transaction_with_mocked_connection():
    events = []

    def engine_factory(database_url, **kwargs):
        assert database_url == REPLIT_URL
        assert kwargs
        events.append("engine")
        return _FakeEngine(events)

    revisions = database_target._read_current_revision(
        REPLIT_URL,
        engine_factory=engine_factory,
    )

    assert revisions == ("revision_a",)
    assert events.index("SET TRANSACTION READ ONLY") < events.index(
        "SELECT version_num FROM alembic_version ORDER BY version_num"
    )
    assert "rollback" in events
    assert events[-1] == "dispose"


def test_revision_reader_fails_if_database_does_not_confirm_read_only():
    events = []

    class UnsafeConnection(_FakeConnection):
        def execute(self, statement):
            sql = str(statement)
            self.events.append(sql)
            if sql == "SHOW transaction_read_only":
                return _FakeScalarResult(scalar="off")
            return _FakeScalarResult()

    class UnsafeEngine(_FakeEngine):
        def connect(self):
            return UnsafeConnection(self.events)

    with pytest.raises(RuntimeConfigurationError, match="read-only"):
        database_target._read_current_revision(
            REPLIT_URL,
            engine_factory=lambda *_args, **_kwargs: UnsafeEngine(events),
        )

    assert not any(event.startswith("SELECT version_num") for event in events)
    assert "rollback" in events


def test_alembic_environment_guards_before_models_and_engine_initialization():
    source = MIGRATION_ENV_PATH.read_text()
    tree = ast.parse(source)
    top_level = tree.body

    guard_assignment = next(
        index
        for index, node in enumerate(top_level)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "migration_configuration"
            for target in node.targets
        )
    )
    models_import = next(
        index
        for index, node in enumerate(top_level)
        if isinstance(node, ast.ImportFrom) and node.module == "models"
    )
    sqlalchemy_import = next(
        index
        for index, node in enumerate(top_level)
        if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy"
    )

    assert guard_assignment < models_import
    assert guard_assignment < sqlalchemy_import
    assert "resolve_migration_database_config" in source
    assert source.count("migration_configuration.database_url") == 1
    assert "BASELODGE_MIGRATION_DATABASE_URL" not in source


def test_alembic_offline_and_online_paths_share_verified_url():
    source = MIGRATION_ENV_PATH.read_text()

    assert "url=get_migration_url()" in source
    assert 'configuration["sqlalchemy.url"] = get_migration_url()' in source
    assert source.index("get_migration_url()") < source.index(
        "engine_from_config("
    )
    assert "if context.is_offline_mode()" in source


def _run_mocked_alembic_environment(monkeypatch, environment, *, offline):
    events = []

    class FakeConnection:
        def __enter__(self):
            events.append("connect")
            return self

        def __exit__(self, *_args):
            events.append("connection-close")

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            events.append("dispose")

    @contextmanager
    def transaction():
        events.append("begin-transaction")
        yield
        events.append("end-transaction")

    fake_context = SimpleNamespace(
        config=SimpleNamespace(
            config_file_name="unused",
            config_ini_section="alembic",
            get_section=lambda *_args: {},
        ),
        is_offline_mode=lambda: offline,
        configure=lambda **kwargs: events.append(("configure", kwargs)),
        begin_transaction=transaction,
        run_migrations=lambda: events.append("run-migrations"),
    )
    fake_alembic = ModuleType("alembic")
    fake_alembic.context = fake_context

    fake_sqlalchemy = ModuleType("sqlalchemy")

    def fake_engine_from_config(*_args, **_kwargs):
        events.append("engine-from-config")
        return FakeEngine()

    fake_sqlalchemy.engine_from_config = fake_engine_from_config
    fake_sqlalchemy.pool = SimpleNamespace(NullPool=object())

    fake_models = ModuleType("models")
    fake_models.db = SimpleNamespace(metadata=object())

    for key in (
        "BASELODGE_RUNTIME_ENV",
        "BASELODGE_MIGRATION_MODE",
        "BASELODGE_MIGRATION_TARGET",
        "BASELODGE_MIGRATION_REPLIT_IDENTITY_HASH",
        "BASELODGE_MIGRATION_SUPABASE_DEVELOPMENT_IDENTITY_HASH",
        "BASELODGE_MIGRATION_SUPABASE_PRODUCTION_IDENTITY_HASH",
        "BASELODGE_CONFIRM_PRODUCTION_MIGRATION",
        "DATABASE_URL",
        "BASELODGE_DEVELOPMENT_DATABASE_URL",
        "BASELODGE_PRODUCTION_DATABASE_URL",
        "BASELODGE_MIGRATION_DATABASE_URL",
        "SUPABASE_DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)
    monkeypatch.setitem(sys.modules, "sqlalchemy", fake_sqlalchemy)
    monkeypatch.setitem(sys.modules, "models", fake_models)
    monkeypatch.setattr(logging.config, "fileConfig", lambda *_args: None)

    runpy.run_path(str(MIGRATION_ENV_PATH), run_name="mocked_migration_env")
    return events


@pytest.mark.parametrize("offline", [True, False])
def test_invalid_alembic_configuration_stops_before_engine_or_connection(
    monkeypatch, offline
):
    with pytest.raises(RuntimeError, match="MIGRATION_TARGET is required"):
        _run_mocked_alembic_environment(
            monkeypatch,
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_MIGRATION_MODE": "1",
                "DATABASE_URL": REPLIT_URL,
            },
            offline=offline,
        )


def test_mocked_offline_alembic_uses_verified_url_without_engine(monkeypatch):
    events = _run_mocked_alembic_environment(
        monkeypatch,
        _migration_environment("replit"),
        offline=True,
    )

    configure_event = next(
        event for event in events if isinstance(event, tuple)
    )
    assert configure_event[1]["url"] == REPLIT_URL
    assert "engine-from-config" not in events
    assert "connect" not in events
    assert "run-migrations" in events


def test_mocked_online_alembic_verifies_before_engine_and_connection(monkeypatch):
    events = _run_mocked_alembic_environment(
        monkeypatch,
        _migration_environment("replit"),
        offline=False,
    )

    assert events.index("engine-from-config") < events.index("connect")
    assert events.index("connect") < events.index("run-migrations")
    assert events[-1] == "dispose"


def test_raw_alembic_and_flask_migrate_use_the_same_environment_module():
    alembic_ini = (PROJECT_ROOT / "migrations" / "alembic.ini").read_text()
    app_source = (PROJECT_ROOT / "app.py").read_text()

    assert "script_location = migrations" in alembic_ini
    assert "Migrate(app, db" in app_source
    assert (PROJECT_ROOT / "migrations" / "env.py").exists()


def test_retired_db_init_cannot_import_app_or_access_database():
    source = (PROJECT_ROOT / "db_init.py").read_text()

    assert "from app import" not in source
    assert "from models import" not in source
    assert "db.session" not in source
    result = subprocess.run(
        [sys.executable, "db_init.py"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "retired and cannot access a database" in result.stderr