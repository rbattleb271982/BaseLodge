"""Focused tests for exact-SHA, read-only GitHub CI evidence."""

import json
from urllib.error import HTTPError

import pytest

import github_ci_evidence


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "89abcdef0123456789abcdef0123456789abcdef"


def _run(
    name,
    *,
    sha=SHA,
    status="completed",
    conclusion="success",
    identifier=1,
    app_slug="github-actions",
):
    return github_ci_evidence.CheckRun(
        name=name,
        head_sha=sha,
        status=status,
        conclusion=conclusion,
        identifier=identifier,
        app_slug=app_slug,
    )


def test_exact_full_lowercase_sha_is_accepted():
    assert github_ci_evidence.validate_full_sha(SHA) == SHA


@pytest.mark.parametrize(
    "candidate",
    [
        SHA[:12],
        SHA.upper(),
        f" {SHA}",
        f"{SHA}\n",
        "not-a-sha",
        "",
        None,
    ],
)
def test_shortened_or_malformed_sha_is_rejected(candidate):
    assert github_ci_evidence.validate_full_sha(candidate) is None


def test_required_successful_checks_for_exact_sha_are_verified():
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [_run("Tests"), _run("Source integrity", identifier=2)],
    )

    assert evidence.verified is True
    assert evidence.sha == SHA


def test_missing_required_check_fails_closed():
    evidence = github_ci_evidence.evaluate_check_runs(SHA, [_run("Tests")])

    assert evidence.verified is False
    assert "Source integrity" in evidence.detail


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("completed", "failure"),
        ("completed", "cancelled"),
        ("completed", "neutral"),
        ("completed", "skipped"),
        ("in_progress", None),
    ],
)
def test_required_check_must_be_completed_success(status, conclusion):
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [
            _run("Tests", status=status, conclusion=conclusion),
            _run("Source integrity", identifier=2),
        ],
    )

    assert evidence.verified is False
    assert "Tests" in evidence.detail


def test_latest_rerun_controls_check_result():
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [
            _run("Tests", identifier=1),
            _run("Tests", conclusion="failure", identifier=3),
            _run("Source integrity", identifier=2),
        ],
    )

    assert evidence.verified is False


def test_different_sha_evidence_fails_closed():
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [_run("Tests", sha=OTHER_SHA), _run("Source integrity", identifier=2)],
    )

    assert evidence.verified is False
    assert "another SHA" in evidence.detail


def test_noncanonical_api_head_sha_is_rejected():
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [
            _run("Tests", sha=SHA.upper()),
            _run("Source integrity", identifier=2),
        ],
    )

    assert evidence.verified is False


@pytest.mark.parametrize("app_slug", [None, "third-party-checks"])
def test_wrong_or_missing_check_provider_fails_closed(app_slug):
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [
            _run("Tests", app_slug=app_slug),
            _run("Source integrity", identifier=2),
        ],
    )

    assert evidence.verified is False
    assert "Tests" in evidence.detail


def test_higher_id_spoof_cannot_replace_github_actions_check():
    evidence = github_ci_evidence.evaluate_check_runs(
        SHA,
        [
            _run("Tests", identifier=1),
            _run(
                "Tests",
                conclusion="failure",
                identifier=100,
                app_slug="third-party-checks",
            ),
            _run("Source integrity", identifier=2),
        ],
    )

    assert evidence.verified is True


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode()


def test_fetch_uses_exact_repository_and_sha_read_only():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return _Response(
            {
                "total_count": 2,
                "check_runs": [
                    {
                        "id": 1,
                        "name": "Tests",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 2,
                        "name": "Source integrity",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ],
            }
        )

    evidence = github_ci_evidence.fetch_github_ci_evidence(
        github_ci_evidence.BASELODGE_GITHUB_REPOSITORY,
        SHA,
        opener=opener,
    )

    assert evidence.verified is True
    request, timeout = requests[0]
    assert request.method == "GET"
    assert f"/commits/{SHA}/check-runs" in request.full_url
    assert timeout == 10


def test_api_failure_is_not_verified_and_never_exposes_token():
    token = "test-token-value-that-must-not-appear"

    def fail(request, timeout):
        raise HTTPError(
            request.full_url,
            503,
            token,
            hdrs=None,
            fp=None,
        )

    with pytest.raises(github_ci_evidence.GitHubEvidenceError) as error:
        github_ci_evidence.fetch_github_ci_evidence(
            github_ci_evidence.BASELODGE_GITHUB_REPOSITORY,
            SHA,
            token=token,
            opener=fail,
        )

    assert token not in str(error.value)
    assert "could not be retrieved" in str(error.value)