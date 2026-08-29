"""Resolve the immutable source identity for the running BaseLodge process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable


_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
RELEASE_METADATA_PATH = Path(__file__).with_name("build") / "release.sha"
_ALLOWED_PROMPT_SUFFIXES = frozenset({".txt", ".md"})


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


def _is_allowed_prompt_artifact(
    status_path: str,
    repository_path: Path,
) -> bool:
    relative_path = Path(status_path)
    try:
        relative_path.relative_to(Path("attached_assets"))
    except ValueError:
        return False
    if relative_path.parent != Path("attached_assets"):
        return False

    candidate_path = repository_path / relative_path
    return (
        candidate_path.is_file()
        and not candidate_path.is_symlink()
        and candidate_path.suffix in _ALLOWED_PROMPT_SUFFIXES
    )


def _status_only_contains_allowed_prompt_artifacts(
    status_output: str,
    repository_path: Path,
) -> bool:
    """Allow only untracked regular prompt artifacts under attached_assets."""
    for record in status_output.split("\0"):
        if not record:
            continue
        if len(record) < 4 or record[:2] != "??" or record[2] != " ":
            return False
        if not _is_allowed_prompt_artifact(record[3:], repository_path):
            return False
    return True


def _read_git_sha(repository_path: Path | None = None) -> str | None:
    repository_path = (
        Path(__file__).parent
        if repository_path is None
        else Path(repository_path)
    )
    try:
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "-z",
            ],
            cwd=repository_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if status.returncode != 0 or not _status_only_contains_allowed_prompt_artifacts(
            status.stdout,
            repository_path,
        ):
            return None

        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD^{commit}"],
            cwd=repository_path,
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


def resolve_candidate_release_identity(
    *,
    git_lookup: Callable[[], str | None] | None = None,
) -> ReleaseIdentity:
    """Resolve the clean checkout SHA for a pre-release candidate."""
    lookup = _read_git_sha if git_lookup is None else git_lookup
    return _validated_identity(lookup())