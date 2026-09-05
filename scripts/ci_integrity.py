"""Repository-owned fast integrity checks for BaseLodge CI.

This module is intentionally independent of Development and Production
configuration. It inspects source control state and source files only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tomllib
from typing import Iterable, Mapping, Sequence

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from release_identity import resolve_candidate_release_identity


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = frozenset(
    {
        ".css",
        ".gradle",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".properties",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".xml",
        ".yaml",
        ".yml",
    }
)
EXCLUDED_CONFLICT_PREFIXES = (
    "attached_assets/",
    "docs/",
    "node_modules/",
)
PROTECTED_SECRET_FILENAMES = frozenset(
    {
        ".env",
        "baselodge-release-key.jks",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)
PROTECTED_SECRET_SUFFIXES = frozenset(
    {
        ".jks",
        ".key",
        ".keystore",
        ".p8",
        ".p12",
        ".pem",
        ".pfx",
    }
)
SAFE_ENV_FILENAMES = frozenset({".env.example", ".env.sample", ".env.template"})
CONFLICT_START = re.compile(r"^<{7,}(?: |$)")
CONFLICT_SEPARATOR = re.compile(r"^={7,}$")
CONFLICT_END = re.compile(r"^>{7,}(?: |$)")
SECRET_PATTERNS = (
    (
        "private-key-material",
        re.compile(r"-{5}BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-{5}"),
    ),
    (
        "credential-bearing-url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
    ),
    (
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "github-token",
        re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "slack-token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    ),
    (
        "stripe-live-secret",
        re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    ),
    (
        "google-api-key",
        re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    ),
    (
        "generic-secret-assignment",
        re.compile(
            r"""(?ix)
            \b(?:api[_-]?key|client[_-]?secret|database[_-]?url|db[_-]?password|
            password|private[_-]?key|secret|token)\b
            \s*[:=]\s*
            ["']?
            (?!\$\{|<|example|placeholder|redacted|changeme|test(?:ing)?[-_])
            [A-Za-z0-9_./+@:$=-]{16,}
            """
        ),
    ),
)
COMPILE_TARGETS = (
    "app.py",
    "models.py",
    "migrations",
    "release_identity.py",
    "release_preflight.py",
    "run_continuous_message_worker.py",
    "runtime_config.py",
    "scripts",
    "services",
    "tests",
)


class IntegrityError(RuntimeError):
    """A concise, expected integrity-gate failure."""


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        env=None if env is None else dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        command = " ".join(arguments[:3])
        raise IntegrityError(f"command failed ({command})")
    return result


def _normalized_requirement(value: str) -> tuple:
    requirement = Requirement(value)
    return (
        canonicalize_name(requirement.name),
        tuple(sorted(requirement.extras)),
        str(requirement.specifier),
        str(requirement.marker or ""),
    )


def validate_dependency_manifests(repository: Path = REPOSITORY_ROOT) -> None:
    _run(["uv", "lock", "--check"], cwd=repository)
    try:
        project = tomllib.loads((repository / "pyproject.toml").read_text("utf-8"))
        project_requirements = project["project"]["dependencies"]
        requirements_lines = [
            line.strip()
            for line in (repository / "requirements.txt").read_text("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        project_normalized = [
            _normalized_requirement(item) for item in project_requirements
        ]
        file_normalized = [
            _normalized_requirement(item) for item in requirements_lines
        ]
    except (
        InvalidRequirement,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        tomllib.TOMLDecodeError,
    ):
        raise IntegrityError("dependency manifests could not be validated") from None
    if len(file_normalized) != len(set(file_normalized)):
        raise IntegrityError("requirements.txt contains duplicate dependencies")
    if set(project_normalized) != set(file_normalized):
        raise IntegrityError("runtime dependency manifests differ")


def _candidate_base(
    repository: Path = REPOSITORY_ROOT,
    explicit_base: str | None = None,
) -> str | None:
    if explicit_base:
        return explicit_base
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    base_sha = os.environ.get("BASE_SHA", "")
    before_sha = os.environ.get("BEFORE_SHA", "")
    zero_sha = "0" * 40
    if event_name == "pull_request" and base_sha:
        return base_sha
    if before_sha and before_sha != zero_sha:
        return before_sha
    parent = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    return "HEAD^" if parent.returncode == 0 else None


def validate_candidate_patch(
    repository: Path = REPOSITORY_ROOT,
    *,
    base: str | None,
    head: str = "HEAD",
) -> None:
    if base is None:
        _run(["git", "show", "--check", "--format=", head], cwd=repository)
        return
    _run(["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=repository)
    _run(["git", "diff", "--check", base, head], cwd=repository)


def _tracked_source_paths(
    repository: Path = REPOSITORY_ROOT,
) -> list[str]:
    output = _run(["git", "ls-files", "-z"], cwd=repository).stdout
    paths = []
    for path in output.split("\0"):
        if not path or path.startswith(EXCLUDED_CONFLICT_PREFIXES):
            continue
        if PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES:
            paths.append(path)
    return paths


def scan_conflict_markers(
    files: Mapping[str, Iterable[str]],
) -> list[Finding]:
    findings = set()
    for path, lines in files.items():
        if path.startswith(EXCLUDED_CONFLICT_PREFIXES):
            continue
        if PurePosixPath(path).suffix.lower() not in SOURCE_SUFFIXES:
            continue
        state = "outside"
        for line in lines:
            if CONFLICT_START.match(line):
                state = "ours"
            elif state == "ours" and CONFLICT_SEPARATOR.match(line):
                state = "theirs"
            elif state == "theirs" and CONFLICT_END.match(line):
                findings.add(Finding(path=path, rule="unresolved-conflict-marker"))
                break
    return sorted(findings)


def validate_conflict_markers(repository: Path = REPOSITORY_ROOT) -> None:
    files: dict[str, list[str]] = {}
    for path in _tracked_source_paths(repository):
        candidate = repository / path
        try:
            files[path] = candidate.read_text("utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
    findings = scan_conflict_markers(files)
    if findings:
        raise IntegrityError(format_findings(findings))


def _is_protected_secret_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    lower_name = candidate.name.lower()
    if lower_name in SAFE_ENV_FILENAMES:
        return False
    return (
        lower_name in PROTECTED_SECRET_FILENAMES
        or lower_name.startswith(".env.")
        or candidate.suffix.lower() in PROTECTED_SECRET_SUFFIXES
    )


def scan_changed_content(
    additions: Mapping[str, Iterable[str] | None],
) -> list[Finding]:
    """Scan added lines; a None value represents a binary or unreadable change."""
    findings = set()
    for path, lines in additions.items():
        if _is_protected_secret_path(path):
            findings.add(Finding(path=path, rule="prohibited-secret-path"))
            continue
        if lines is None:
            continue
        for line in lines:
            for rule, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.add(Finding(path=path, rule=rule))
    return sorted(findings)


def _changed_additions(
    repository: Path = REPOSITORY_ROOT,
    *,
    base: str | None,
    head: str = "HEAD",
) -> dict[str, list[str] | None]:
    path_arguments = [
        "git",
        "show",
        "--format=",
        "--name-only",
        "-z",
        head,
    ]
    arguments = ["git", "show", "--format=", "--no-ext-diff", "--no-color", head]
    if base is not None:
        path_arguments = [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            base,
            head,
            "--",
        ]
        arguments = [
            "git",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--no-renames",
            base,
            head,
            "--",
        ]
    changed_paths = _run(path_arguments, cwd=repository).stdout.split("\0")
    output = _run(arguments, cwd=repository).stdout
    additions: dict[str, list[str] | None] = {
        path: [] for path in changed_paths if path
    }
    current_path: str | None = None
    for line in output.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            additions.setdefault(current_path, [])
            continue
        if line.startswith("Binary files ") and current_path is not None:
            additions[current_path] = None
            continue
        if current_path is not None and line.startswith("+") and not line.startswith("+++"):
            current = additions[current_path]
            if current is not None:
                current.append(line[1:])
    return additions


def format_findings(findings: Iterable[Finding]) -> str:
    """Format path and category only. Never include matched source content."""
    rendered = [
        f"{finding.path}: {finding.rule}"
        for finding in sorted(set(findings))
    ]
    return "integrity findings:\n" + "\n".join(rendered)


def validate_changed_secrets(
    repository: Path = REPOSITORY_ROOT,
    *,
    base: str | None,
    head: str = "HEAD",
) -> None:
    findings = scan_changed_content(
        _changed_additions(repository, base=base, head=head)
    )
    if findings:
        raise IntegrityError(format_findings(findings))


def parse_alembic_heads(output: str) -> list[str]:
    return [
        line.rsplit(" ", 1)[0].strip()
        for line in output.splitlines()
        if line.rstrip().endswith("(head)")
    ]


def validate_alembic_heads(repository: Path = REPOSITORY_ROOT) -> None:
    result = _run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "heads"],
        cwd=repository,
    )
    heads = parse_alembic_heads(result.stdout)
    if len(heads) != 1:
        raise IntegrityError(f"expected exactly one Alembic head; found {len(heads)}")


def validate_python_compilation(repository: Path = REPOSITORY_ROOT) -> None:
    with tempfile.TemporaryDirectory(prefix="baselodge-ci-pycache-") as cache:
        env = os.environ.copy()
        env["PYTHONPYCACHEPREFIX"] = cache
        _run(
            [sys.executable, "-m", "compileall", "-q", *COMPILE_TARGETS],
            cwd=repository,
            env=env,
        )


def validate_candidate_identity() -> None:
    identity = resolve_candidate_release_identity()
    if identity.status != "VERIFIED" or not identity.sha:
        raise IntegrityError("candidate source identity is not verified")


def validate_repository_cleanliness(repository: Path = REPOSITORY_ROOT) -> None:
    result = _run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        ],
        cwd=repository,
    )
    for record in result.stdout.split("\0"):
        if not record:
            continue
        if len(record) < 4 or record[:3] != "?? ":
            raise IntegrityError("repository contains tracked changes")
        path = PurePosixPath(record[3:])
        candidate = repository / path
        if (
            path.parent != PurePosixPath("attached_assets")
            or path.suffix not in {".txt", ".md"}
            or not candidate.is_file()
            or candidate.is_symlink()
        ):
            raise IntegrityError("repository contains unexpected untracked files")


def run_fast_integrity(
    *,
    repository: Path = REPOSITORY_ROOT,
    base: str | None = None,
    head: str = "HEAD",
) -> None:
    candidate_base = _candidate_base(repository, base)
    checks = (
        (
            "changed-content secrets",
            lambda: validate_changed_secrets(
                repository,
                base=candidate_base,
                head=head,
            ),
        ),
        ("conflict markers", lambda: validate_conflict_markers(repository)),
        (
            "candidate patch",
            lambda: validate_candidate_patch(
                repository,
                base=candidate_base,
                head=head,
            ),
        ),
        ("dependency manifests", lambda: validate_dependency_manifests(repository)),
        ("Python compilation", lambda: validate_python_compilation(repository)),
        ("candidate identity", validate_candidate_identity),
        ("Alembic source graph", lambda: validate_alembic_heads(repository)),
        ("repository cleanliness", lambda: validate_repository_cleanliness(repository)),
    )
    for label, check in checks:
        check()
        print(f"PASS: {label}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fast",))
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        run_fast_integrity(base=args.base, head=args.head)
    except IntegrityError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("FAIL: integrity gate infrastructure error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())