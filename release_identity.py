"""Resolve the immutable source identity for the running BaseLodge process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable


_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
RELEASE_METADATA_PATH = Path(__file__).with_name("build") / "release.sha"


@dataclass(frozen=True)
class ReleaseIdentity:
    sha: str | None
    status: str

    def as_health_fields(self) -> dict[str, str | None]:
        """Return only the minimal fields safe for the read-only health response."""
        return {
            "release_sha": self.sha,
            "release_identity_status": self.status,
        }


def _validated_identity(candidate: str | None) -> ReleaseIdentity:
    value = candidate.strip() if isinstance(candidate, str) else ""
    if _GIT_SHA_PATTERN.fullmatch(value):
        return ReleaseIdentity(sha=value.lower(), status="VERIFIED")
    return ReleaseIdentity(sha=None, status="UNVERIFIED")


def _read_metadata(path: Path) -> str | None:
    """Return file contents, preserving an invalid file as an invalid identity."""
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _read_git_sha() -> str | None:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if status.returncode != 0 or status.stdout.strip():
            return None

        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def resolve_release_identity(
    *,
    runtime_env: str,
    metadata_path: Path = RELEASE_METADATA_PATH,
    git_lookup: Callable[[], str | None] = _read_git_sha,
) -> ReleaseIdentity:
    """Resolve a build SHA without ever treating an unknown value as verified."""
    metadata_value = _read_metadata(metadata_path)
    if metadata_value is not None:
        return _validated_identity(metadata_value)

    if runtime_env == "production":
        return _validated_identity(None)

    return _validated_identity(git_lookup())