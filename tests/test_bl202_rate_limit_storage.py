"""Focused BL-202 shared Production rate-limit storage contracts."""

import pytest

from services.rate_limit_storage import (
    rate_limit_storage_is_shared,
    resolve_rate_limit_storage_uri,
)


@pytest.mark.parametrize(
    "configured_uri",
    [
        None,
        "",
        "   ",
        "memory://",
        "MEMORY://",
        "redis://test-user:dummy-secret@redis.example.test:6379/0",
        'REDIS_URL="rediss://test-user:dummy-secret@redis.example.test:6380/0"',
    ],
)
def test_production_rejects_missing_or_process_local_storage(configured_uri):
    with pytest.raises(RuntimeError, match="requires shared Redis-compatible"):
        resolve_rate_limit_storage_uri(
            configured_uri,
            runtime_env="production",
        )


def test_production_accepts_native_tls_redis_without_emitting_credentials(capsys):
    configured_uri = (
        "rediss://test-user:dummy-secret@redis.example.test:6380/0"
    )

    resolved = resolve_rate_limit_storage_uri(
        configured_uri,
        runtime_env="production",
    )

    assert resolved == configured_uri
    assert rate_limit_storage_is_shared(resolved) is True
    assert capsys.readouterr() == ("", "")


def test_production_configuration_error_does_not_expose_credentials():
    configured_uri = "memory://test-user:dummy-secret@localhost"

    with pytest.raises(RuntimeError) as error:
        resolve_rate_limit_storage_uri(
            configured_uri,
            runtime_env="production",
        )

    assert configured_uri not in str(error.value)
    assert "dummy-secret" not in str(error.value)


@pytest.mark.parametrize("runtime_env", ["development", "test"])
def test_non_production_preserves_in_memory_fallback(runtime_env):
    assert (
        resolve_rate_limit_storage_uri(None, runtime_env=runtime_env)
        == "memory://"
    )
    assert rate_limit_storage_is_shared("memory://") is False