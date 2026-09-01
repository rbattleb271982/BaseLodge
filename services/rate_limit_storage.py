"""Runtime-safe Flask-Limiter storage configuration."""

from urllib.parse import urlsplit


_MEMORY_STORAGE_URI = "memory://"
_PRODUCTION_SHARED_SCHEME = "rediss"
_PRODUCTION_CONFIGURATION_ERROR = (
    "Production rate limiting requires shared Redis-compatible storage "
    "configured through RATELIMIT_STORAGE_URI."
)


def resolve_rate_limit_storage_uri(
    configured_uri: str | None,
    *,
    runtime_env: str,
) -> str:
    """Resolve limiter storage while preventing process-local Production use."""
    storage_uri = (configured_uri or "").strip()

    if runtime_env == "production":
        scheme = urlsplit(storage_uri).scheme.lower()
        if scheme != _PRODUCTION_SHARED_SCHEME:
            raise RuntimeError(_PRODUCTION_CONFIGURATION_ERROR)

    return storage_uri or _MEMORY_STORAGE_URI


def rate_limit_storage_is_shared(storage_uri: str) -> bool:
    """Return whether the configured backend is not process-local memory."""
    return urlsplit(storage_uri).scheme.lower() != "memory"