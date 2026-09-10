"""Pure safety checks for the Phase 3 capture runtime."""

from pathlib import Path
import socket

import pytest

from capture_harness.config import (
    CAPTURE_NOW,
    CaptureConfigurationError,
    capture_database,
    resolve_capture_config,
)
from capture_harness.effects import (
    OutboundNetworkBlocked,
    install_capture_effects,
)


def _environment(**overrides):
    environment = {
        "BASELODGE_RUNTIME_ENV": "test",
        "BASELODGE_CAPTURE_MODE": "1",
        "BASELODGE_CAPTURE_DATABASE_URL": "sqlite:////tmp/capture-test.sqlite3",
    }
    environment.update(overrides)
    return environment


def test_capture_config_is_file_sqlite_under_tmp():
    config = resolve_capture_config(_environment())
    assert config.database_path == Path("/tmp/capture-test.sqlite3")
    assert config.database_url == "sqlite:////tmp/capture-test.sqlite3"
    assert CAPTURE_NOW.isoformat() == "2027-01-15T12:00:00-07:00"


@pytest.mark.parametrize(
    "overrides",
    [
        {"BASELODGE_RUNTIME_ENV": "development"},
        {"BASELODGE_CAPTURE_MODE": "0"},
        {"BASELODGE_CAPTURE_DATABASE_URL": "sqlite:///:memory:"},
        {"BASELODGE_CAPTURE_DATABASE_URL": "sqlite:///relative.db"},
        {"BASELODGE_CAPTURE_DATABASE_URL": "postgresql://host/db"},
        {"BASELODGE_CAPTURE_DATABASE_URL": "sqlite:////var/lib/app.db"},
        {"BASELODGE_PRODUCTION_DATABASE_URL": "postgresql://host/db"},
        {"SUPABASE_DATABASE_URL": "postgresql://host.supabase.co/db"},
    ],
)
def test_capture_config_fails_closed(overrides):
    with pytest.raises(CaptureConfigurationError):
        resolve_capture_config(_environment(**overrides))


def test_disposable_capture_database_removes_sidecars(tmp_path):
    path = tmp_path / "capture.sqlite3"
    path = Path("/tmp") / path.name
    config = resolve_capture_config(
        _environment(BASELODGE_CAPTURE_DATABASE_URL=f"sqlite:///{path}")
    )
    with capture_database(config):
        config.database_path.touch()
        Path(f"{config.database_path}-wal").touch()
        assert config.database_path.exists()
    assert not config.database_path.exists()
    assert not Path(f"{config.database_path}-wal").exists()


def test_capture_network_is_recorded_and_blocked():
    with install_capture_effects() as recorder:
        with pytest.raises(OutboundNetworkBlocked):
            socket.create_connection(("example.invalid", 443))
    assert recorder.attempts[0].operation == "create_connection"
    assert recorder.attempts[0].address == ("example.invalid", 443)


def test_capture_auth_is_not_registered_on_normal_application(app_fixture):
    routes = {rule.rule for rule in app_fixture.url_map.iter_rules()}
    assert "/api/capture/auth" not in routes
    assert "/api/capture/health" not in routes