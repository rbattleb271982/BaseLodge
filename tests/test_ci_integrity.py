"""Self-tests for the repository-owned CI integrity command."""

from pathlib import Path
import os
import subprocess
import sys

import pytest

from scripts import ci_integrity


def _git(repository, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )


def _temporary_git_repository(tmp_path):
    repository = tmp_path / "candidate"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "Integrity Test")
    (repository / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(repository, "add", "app.py")
    _git(repository, "commit", "--quiet", "-m", "initial")
    return repository


def test_clean_scanner_input_passes():
    additions = {
        "app.py": ["value = get_runtime_setting()"],
        ".env.example": ["SESSION_SECRET=placeholder"],
    }

    assert ci_integrity.scan_changed_content(additions) == []
    assert ci_integrity.scan_conflict_markers(additions) == []


def test_unresolved_conflict_marker_fails():
    lines = [
        "<" * 7 + " current",
        "first version",
        "=" * 7,
        "second version",
        ">" * 7 + " incoming",
    ]

    findings = ci_integrity.scan_conflict_markers({"app.py": lines})

    assert findings == [
        ci_integrity.Finding(
            path="app.py",
            rule="unresolved-conflict-marker",
        )
    ]


def test_nondefault_wide_conflict_marker_fails():
    lines = [
        "<" * 12 + " current",
        "first version",
        "=" * 12,
        "second version",
        ">" * 12 + " incoming",
    ]

    findings = ci_integrity.scan_conflict_markers({"service.py": lines})

    assert findings == [
        ci_integrity.Finding(
            path="service.py",
            rule="unresolved-conflict-marker",
        )
    ]


def test_documentation_conflict_marker_is_narrowly_excluded():
    lines = [
        "<" * 7 + " current",
        "=" * 7,
        ">" * 7 + " proposed",
    ]

    assert ci_integrity.scan_conflict_markers({"docs/example.md": lines}) == []


def test_standalone_source_separator_is_not_a_conflict():
    lines = ["=" * 40, "BaseLodge Application", "=" * 40]

    assert ci_integrity.scan_conflict_markers({"app.py": lines}) == []


def test_synthetic_secret_fails_without_echoing_value():
    synthetic = "sk_live_" + "syntheticvalue123456789"

    findings = ci_integrity.scan_changed_content(
        {"config.py": [f'PAYMENT_TOKEN = "{synthetic}"']}
    )
    output = ci_integrity.format_findings(findings)

    assert findings
    assert "config.py: stripe-live-secret" in output
    assert synthetic not in output


def test_protected_signing_path_fails_without_reading_contents():
    findings = ci_integrity.scan_changed_content({
        "android/baselodge-release-key.jks": None,
        "ios/AuthKey_synthetic.p8": None,
    })

    assert findings == [
        ci_integrity.Finding(
            path="android/baselodge-release-key.jks",
            rule="prohibited-secret-path",
        ),
        ci_integrity.Finding(
            path="ios/AuthKey_synthetic.p8",
            rule="prohibited-secret-path",
        )
    ]


def test_binary_protected_signing_path_is_found_from_git_metadata(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    protected = repository / "android" / "baselodge-release-key.jks"
    protected.parent.mkdir(parents=True)
    protected.write_bytes(b"\x00synthetic-binary\x00")
    _git(repository, "add", "android/baselodge-release-key.jks")
    _git(repository, "commit", "--quiet", "-m", "unsafe signing file")

    additions = ci_integrity._changed_additions(
        repository,
        base="HEAD^",
        head="HEAD",
    )
    findings = ci_integrity.scan_changed_content(additions)

    assert findings == [
        ci_integrity.Finding(
            path="android/baselodge-release-key.jks",
            rule="prohibited-secret-path",
        )
    ]


def test_candidate_base_prefers_pull_request_base(monkeypatch, tmp_path):
    repository = _temporary_git_repository(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("BASE_SHA", "a" * 40)
    monkeypatch.setenv("BEFORE_SHA", "b" * 40)

    assert ci_integrity._candidate_base(repository) == "a" * 40


def test_candidate_base_uses_push_before_sha(monkeypatch, tmp_path):
    repository = _temporary_git_repository(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.setenv("BEFORE_SHA", "b" * 40)

    assert ci_integrity._candidate_base(repository) == "b" * 40


def test_zero_push_sha_falls_back_to_parent(monkeypatch, tmp_path):
    repository = _temporary_git_repository(tmp_path)
    (repository / "app.py").write_text("value = 2\n", encoding="utf-8")
    _git(repository, "add", "app.py")
    _git(repository, "commit", "--quiet", "-m", "second")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.delenv("BASE_SHA", raising=False)
    monkeypatch.setenv("BEFORE_SHA", "0" * 40)

    assert ci_integrity._candidate_base(repository) == "HEAD^"


def test_unresolvable_candidate_base_fails_closed(tmp_path):
    repository = _temporary_git_repository(tmp_path)

    with pytest.raises(ci_integrity.IntegrityError):
        ci_integrity.validate_candidate_patch(
            repository,
            base="f" * 40,
            head="HEAD",
        )


def test_repository_cleanliness_passes_clean_and_fails_dirty(tmp_path):
    repository = _temporary_git_repository(tmp_path)

    ci_integrity.validate_repository_cleanliness(repository)
    (repository / "app.py").write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(
        ci_integrity.IntegrityError,
        match="repository contains tracked changes",
    ):
        ci_integrity.validate_repository_cleanliness(repository)


def test_credential_bearing_database_url_is_redacted():
    password = "-".join(("synthetic", "password", "for", "ci"))
    scheme = "postgresql" + "://"
    line = f'DATABASE_URL="{scheme}ci_user:{password}@db.invalid/test"'

    output = ci_integrity.format_findings(
        ci_integrity.scan_changed_content({"settings.py": [line]})
    )

    assert "credential-bearing-url" in output
    assert password not in output


def test_alembic_head_parser_requires_exactly_one_head():
    assert ci_integrity.parse_alembic_heads("bl442_worker_heartbeat (head)\n") == [
        "bl442_worker_heartbeat"
    ]
    assert len(
        ci_integrity.parse_alembic_heads(
            "first (head)\nbranchpoint\nsecond (head)\n"
        )
    ) == 2


def test_current_alembic_graph_has_exactly_one_head():
    ci_integrity.validate_alembic_heads()


def test_javascript_test_command_executes_successfully():
    result = subprocess.run(
        ["npm", "test"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "fail 0" in result.stdout


def test_integrity_error_returns_nonzero_without_traceback(monkeypatch, capsys):
    def fail(**_kwargs):
        raise ci_integrity.IntegrityError("synthetic failure")

    monkeypatch.setattr(ci_integrity, "run_fast_integrity", fail)

    assert ci_integrity.main(["fast"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "FAIL: synthetic failure"


def test_unexpected_subprocess_error_never_echoes_secret_or_traceback():
    synthetic = "-".join(("synthetic", "dependency", "credential", "value"))
    program = """
import os
from scripts import ci_integrity

def fail(**_kwargs):
    raise RuntimeError(os.environ["SYNTHETIC_CREDENTIAL"])

ci_integrity.run_fast_integrity = fail
raise SystemExit(ci_integrity.main(["fast"]))
"""
    env = os.environ.copy()
    env["SYNTHETIC_CREDENTIAL"] = synthetic
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "FAIL: integrity gate infrastructure error"
    assert synthetic not in result.stderr
    assert "Traceback" not in result.stderr