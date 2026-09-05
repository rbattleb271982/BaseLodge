"""Read-only GitHub CI evidence for an immutable BaseLodge commit."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASELODGE_GITHUB_REPOSITORY = "rbattleb271982/BaseLodge"
REQUIRED_CHECKS = ("Tests", "Source integrity")
REQUIRED_CHECK_PROVIDER = "github-actions"
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_PAGES = 10


class GitHubEvidenceError(RuntimeError):
    """A fail-closed error whose message contains no token or response body."""


@dataclass(frozen=True)
class CheckRun:
    name: str
    head_sha: str
    status: str
    conclusion: str | None
    identifier: int
    app_slug: str | None


@dataclass(frozen=True)
class GitHubCiEvidence:
    sha: str
    checks: tuple[CheckRun, ...]
    verified: bool
    detail: str


def validate_full_sha(value: str | None) -> str | None:
    candidate = value if isinstance(value, str) else ""
    return candidate if _GIT_SHA_PATTERN.fullmatch(candidate) else None


def _parse_check_runs(payload: object) -> tuple[CheckRun, ...]:
    if not isinstance(payload, Mapping):
        raise GitHubEvidenceError("GitHub checks response is invalid")
    raw_runs = payload.get("check_runs")
    if not isinstance(raw_runs, list):
        raise GitHubEvidenceError("GitHub checks response is invalid")

    parsed: list[CheckRun] = []
    for raw_run in raw_runs:
        if not isinstance(raw_run, Mapping):
            raise GitHubEvidenceError("GitHub checks response is invalid")
        name = raw_run.get("name")
        head_sha = raw_run.get("head_sha")
        status = raw_run.get("status")
        conclusion = raw_run.get("conclusion")
        identifier = raw_run.get("id")
        app = raw_run.get("app")
        app_slug = app.get("slug") if isinstance(app, Mapping) else None
        if (
            not isinstance(name, str)
            or not isinstance(head_sha, str)
            or not isinstance(status, str)
            or conclusion is not None
            and not isinstance(conclusion, str)
            or not isinstance(identifier, int)
            or app_slug is not None
            and not isinstance(app_slug, str)
        ):
            raise GitHubEvidenceError("GitHub checks response is invalid")
        parsed.append(
            CheckRun(
                name=name,
                head_sha=head_sha,
                status=status,
                conclusion=conclusion,
                identifier=identifier,
                app_slug=app_slug,
            )
        )
    return tuple(parsed)


def evaluate_check_runs(
    sha: str,
    check_runs: Iterable[CheckRun],
) -> GitHubCiEvidence:
    approved_sha = validate_full_sha(sha)
    if approved_sha is None:
        return GitHubCiEvidence(
            sha="",
            checks=(),
            verified=False,
            detail="approved SHA is malformed",
        )

    latest: dict[str, CheckRun] = {}
    for check_run in check_runs:
        if (
            check_run.name not in REQUIRED_CHECKS
            or check_run.app_slug != REQUIRED_CHECK_PROVIDER
        ):
            continue
        current = latest.get(check_run.name)
        if current is None or check_run.identifier > current.identifier:
            latest[check_run.name] = check_run

    missing = [name for name in REQUIRED_CHECKS if name not in latest]
    if missing:
        return GitHubCiEvidence(
            sha=approved_sha,
            checks=tuple(latest.values()),
            verified=False,
            detail="missing required checks: " + ", ".join(missing),
        )

    selected = tuple(latest[name] for name in REQUIRED_CHECKS)
    if any(check.head_sha != approved_sha for check in selected):
        return GitHubCiEvidence(
            sha=approved_sha,
            checks=selected,
            verified=False,
            detail="required check evidence belongs to another SHA",
        )

    failed = [
        check.name
        for check in selected
        if check.status != "completed" or check.conclusion != "success"
    ]
    if failed:
        return GitHubCiEvidence(
            sha=approved_sha,
            checks=selected,
            verified=False,
            detail="required checks are not successful: " + ", ".join(failed),
        )
    return GitHubCiEvidence(
        sha=approved_sha,
        checks=selected,
        verified=True,
        detail="Tests and Source integrity passed for the exact SHA",
    )


def fetch_github_ci_evidence(
    repository: str,
    sha: str,
    *,
    token: str | None = None,
    opener: Callable[..., object] = urlopen,
) -> GitHubCiEvidence:
    """Fetch exact-SHA check runs using only GitHub's read-only API."""
    approved_sha = validate_full_sha(sha)
    if approved_sha is None:
        raise GitHubEvidenceError("approved SHA is malformed")
    if (
        not _REPOSITORY_PATTERN.fullmatch(repository)
        or repository != BASELODGE_GITHUB_REPOSITORY
    ):
        raise GitHubEvidenceError("GitHub repository identity is invalid")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "BaseLodge-release-preflight",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if isinstance(token, str) and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"

    all_runs: list[CheckRun] = []
    total_count: int | None = None
    for page in range(1, _MAX_PAGES + 1):
        query = urlencode(
            {"filter": "latest", "per_page": 100, "page": page}
        )
        url = (
            "https://api.github.com/repos/"
            f"{repository}/commits/{approved_sha}/check-runs?{query}"
        )
        request = Request(url, headers=headers, method="GET")
        try:
            response = opener(request, timeout=10)
            with response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError):
            raise GitHubEvidenceError(
                "GitHub CI evidence could not be retrieved"
            ) from None
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise GitHubEvidenceError("GitHub checks response is too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise GitHubEvidenceError("GitHub checks response is invalid") from None
        if not isinstance(payload, Mapping):
            raise GitHubEvidenceError("GitHub checks response is invalid")
        count = payload.get("total_count")
        if not isinstance(count, int) or count < 0:
            raise GitHubEvidenceError("GitHub checks response is invalid")
        if total_count is None:
            total_count = count
        elif count != total_count:
            raise GitHubEvidenceError("GitHub checks response changed during read")
        page_runs = _parse_check_runs(payload)
        all_runs.extend(page_runs)
        if len(all_runs) >= total_count:
            break
        if not page_runs:
            raise GitHubEvidenceError("GitHub checks response is incomplete")
    else:
        raise GitHubEvidenceError("GitHub checks response exceeds safe limits")

    return evaluate_check_runs(approved_sha, all_runs)