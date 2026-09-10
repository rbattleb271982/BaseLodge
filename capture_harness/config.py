"""Fail-closed configuration and disposable resources for capture runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import tempfile
from typing import Iterator, Mapping
from urllib.parse import urlsplit

from zoneinfo import ZoneInfo


CAPTURE_NOW = datetime(2027, 1, 15, 12, 0, tzinfo=ZoneInfo("America/Denver"))
FROZEN_NOW = CAPTURE_NOW
_CAPTURE_ROOT = Path("/tmp").resolve()


class CaptureConfigurationError(RuntimeError):
    """Raised when a capture could target a non-disposable environment."""


@dataclass(frozen=True)
class CaptureConfig:
    """Validated capture settings.  The URL is always a file-backed SQLite URL."""

    database_url: str
    database_path: Path
    runtime_env: str = "test"
    capture_mode: bool = True

    @property
    def database_uri(self) -> str:
        """SQLAlchemy-compatible spelling used by capture runners."""
        return self.database_url


def frozen_now() -> datetime:
    """Return the deterministic instant used by all capture scenarios."""
    return CAPTURE_NOW


def _value(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    return value.strip() if value and value.strip() else None


def _under_capture_root(path: Path) -> bool:
    try:
        path.relative_to(_CAPTURE_ROOT)
    except ValueError:
        return False
    return path != _CAPTURE_ROOT


def _sqlite_path(url: str) -> Path:
    raw = url.strip().strip('"').strip("'")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise CaptureConfigurationError("Capture database URL is invalid.") from exc
    if parsed.scheme.lower() != "sqlite":
        raise CaptureConfigurationError(
            "Capture database URL must use the SQLite dialect."
        )
    if parsed.query or parsed.fragment or parsed.username or parsed.hostname:
        raise CaptureConfigurationError("Capture SQLite URL must be a local file URL.")
    path = parsed.path
    if not path or path in {":memory:", "/:memory:"}:
        raise CaptureConfigurationError("Capture database must not use SQLite memory mode.")
    candidate = Path(path)
    if not candidate.is_absolute():
        raise CaptureConfigurationError("Capture SQLite database path must be absolute.")
    resolved = candidate.resolve(strict=False)
    if not _under_capture_root(resolved):
        raise CaptureConfigurationError("Capture database must resolve under /tmp.")
    return resolved


def resolve_capture_config(
    environ: Mapping[str, str] | None = None,
) -> CaptureConfig:
    """Validate capture-only environment settings without opening a database."""
    environment = os.environ if environ is None else environ
    if _value(environment, "BASELODGE_RUNTIME_ENV") != "test":
        raise CaptureConfigurationError(
            "BASELODGE_RUNTIME_ENV must be exactly test for capture."
        )
    if _value(environment, "BASELODGE_CAPTURE_MODE") != "1":
        raise CaptureConfigurationError(
            "BASELODGE_CAPTURE_MODE=1 is required for capture."
        )

    # Explicit live-environment URLs are rejected even when a separate capture
    # URL is present. This prevents an accidental fallback in the server.
    for key in (
        "BASELODGE_DEVELOPMENT_DATABASE_URL",
        "BASELODGE_PRODUCTION_DATABASE_URL",
        "SUPABASE_DATABASE_URL",
        "DATABASE_URL",
    ):
        if _value(environment, key):
            raise CaptureConfigurationError(
                f"{key} is not allowed in capture mode."
            )
    url = next(
        (
            _value(environment, key)
            for key in (
                "BASELODGE_CAPTURE_DATABASE_URL",
                "BASELODGE_TEST_DATABASE_URL",
            )
            if _value(environment, key)
        ),
        None,
    )
    if not url:
        raise CaptureConfigurationError(
            "BASELODGE_CAPTURE_DATABASE_URL is required for capture."
        )
    path = _sqlite_path(url)
    return CaptureConfig(
        database_url=f"sqlite:///{path.as_posix()}",
        database_path=path,
    )


validate_capture_environment = resolve_capture_config


@dataclass
class DisposableDatabase:
    """A capture database file which is removed when its context exits."""

    path: Path

    def __enter__(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, exc_type, exc, traceback) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                self.path.with_name(self.path.name + suffix).unlink()
            except FileNotFoundError:
                pass


@contextmanager
def capture_database(
    config: CaptureConfig | None = None,
) -> Iterator[CaptureConfig]:
    """Yield capture settings and remove the configured database afterward."""
    selected = config or resolve_capture_config()
    with DisposableDatabase(selected.database_path):
        yield selected


def disposable_database_path(prefix: str = "baselodge-capture-") -> Path:
    """Create a unique safe database filename under /tmp (without opening it)."""
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".sqlite3", dir="/tmp")
    os.close(fd)
    path = Path(name)
    path.unlink()
    return path