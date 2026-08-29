"""Focused tests for the safe runtime release identity contract."""

import ast
import subprocess
from pathlib import Path

import release_identity
from release_identity import (
    ReleaseIdentity,
    resolve_candidate_release_identity,
    resolve_release_identity,
)


GIT_SHA = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"


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
    _git(repository, "config", "user.name", "Candidate Test")
    tracked_file = repository / "tracked.txt"
    tracked_file.write_text("initial\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "--quiet", "-m", "initial")
    return repository


def _candidate_identity(repository):
    return resolve_candidate_release_identity(
        git_lookup=lambda: release_identity._read_git_sha(repository),
    )


def _add_untracked(repository, relative_path):
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("prompt artifact\n", encoding="utf-8")


def test_valid_build_metadata_is_normalized_and_verified(tmp_path):
    metadata_path = tmp_path / "release.sha"
    metadata_path.write_text(f"  {GIT_SHA}\n", encoding="utf-8")

    identity = resolve_release_identity(
        runtime_env="production",
        metadata_path=metadata_path,
        git_lookup=lambda: (_ for _ in ()).throw(
            AssertionError("Production must not invoke Git fallback")
        ),
    )

    assert identity == ReleaseIdentity(
        sha=GIT_SHA.lower(),
        status="VERIFIED",
    )
    assert identity.as_health_fields() == {
        "release_sha": GIT_SHA.lower(),
        "release_identity_status": "VERIFIED",
    }


def test_missing_metadata_uses_git_revision_when_available(tmp_path):
    identity = resolve_release_identity(
        runtime_env="development",
        metadata_path=tmp_path / "missing",
        git_lookup=lambda: GIT_SHA,
    )

    assert identity.status == "VERIFIED"
    assert identity.sha == GIT_SHA.lower()


def test_candidate_identity_uses_clean_checkout_contract():
    identity = resolve_candidate_release_identity(
        git_lookup=lambda: GIT_SHA,
    )

    assert identity == ReleaseIdentity(
        sha=GIT_SHA.lower(),
        status="VERIFIED",
    )


def test_candidate_identity_fails_closed_when_git_is_unavailable():
    identity = resolve_candidate_release_identity(
        git_lookup=lambda: None,
    )

    assert identity == ReleaseIdentity(sha=None, status="UNVERIFIED")


def test_candidate_clean_checkout_is_verified_from_real_git(tmp_path):
    repository = _temporary_git_repository(tmp_path)

    identity = _candidate_identity(repository)
    head = _git(repository, "rev-parse", "HEAD").stdout.strip()

    assert identity == ReleaseIdentity(sha=head, status="VERIFIED")


def test_candidate_allows_untracked_attached_assets_txt(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/prompt.txt")

    assert _candidate_identity(repository).status == "VERIFIED"


def test_candidate_allows_untracked_attached_assets_md(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/prompt.md")

    assert _candidate_identity(repository).status == "VERIFIED"


def test_candidate_allows_multiple_prompt_artifacts_only(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/first.txt")
    _add_untracked(repository, "attached_assets/second.md")

    assert _candidate_identity(repository).status == "VERIFIED"


def test_candidate_rejects_nested_attached_assets_prompt_artifact(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/nested/prompt.txt")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_untracked_python_outside_attached_assets(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "scripts/untrusted.py")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_untracked_arbitrary_text_outside_attached_assets(
    tmp_path,
):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "notes.txt")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_untracked_code_under_attached_assets(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/prompt.py")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_modified_tracked_file(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_staged_modification(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_staged_new_file(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "new.txt")
    _git(repository, "add", "new.txt")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_deleted_tracked_file(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    (repository / "tracked.txt").unlink()

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_renamed_tracked_file(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _git(repository, "mv", "tracked.txt", "renamed.txt")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_allowed_prompt_plus_disallowed_change(tmp_path):
    repository = _temporary_git_repository(tmp_path)
    _add_untracked(repository, "attached_assets/prompt.txt")
    _add_untracked(repository, "src/runtime.py")

    assert _candidate_identity(repository).status == "UNVERIFIED"


def test_candidate_rejects_git_command_failure(tmp_path):
    assert release_identity._read_git_sha(tmp_path / "not-a-repository") is None


def test_missing_production_metadata_is_unverified_without_git_fallback(tmp_path):
    git_called = False

    def git_lookup():
        nonlocal git_called
        git_called = True
        return GIT_SHA

    identity = resolve_release_identity(
        runtime_env="production",
        metadata_path=tmp_path / "missing",
        git_lookup=git_lookup,
    )

    assert identity == ReleaseIdentity(sha=None, status="UNVERIFIED")
    assert git_called is False


def test_empty_production_metadata_is_unverified(tmp_path):
    metadata_path = tmp_path / "release.sha"
    metadata_path.write_text("", encoding="utf-8")

    identity = resolve_release_identity(
        runtime_env="production",
        metadata_path=metadata_path,
        git_lookup=lambda: (_ for _ in ()).throw(
            AssertionError("Production must not invoke Git fallback")
        ),
    )

    assert identity == ReleaseIdentity(sha=None, status="UNVERIFIED")


def test_malformed_metadata_does_not_fallback_to_a_different_revision(tmp_path):
    metadata_path = tmp_path / "release.sha"
    metadata_path.write_text("not-a-git-sha\n", encoding="utf-8")

    identity = resolve_release_identity(
        runtime_env="production",
        metadata_path=metadata_path,
        git_lookup=lambda: (_ for _ in ()).throw(
            AssertionError("Production must not invoke Git fallback")
        ),
    )

    assert identity == ReleaseIdentity(sha=None, status="UNVERIFIED")


def test_git_lookup_rejects_a_dirty_checkout(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=" M app.py\n",
            stderr="",
        )

    monkeypatch.setattr(release_identity.subprocess, "run", fake_run)

    assert release_identity._read_git_sha() is None


def test_git_lookup_returns_head_for_a_clean_checkout(monkeypatch):
    results = iter(
        [
            subprocess.CompletedProcess(
                ["git", "status"],
                returncode=0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                ["git", "rev-parse"],
                returncode=0,
                stdout=f"{GIT_SHA}\n",
                stderr="",
            ),
        ]
    )

    monkeypatch.setattr(
        release_identity.subprocess,
        "run",
        lambda command, **kwargs: next(results),
    )

    assert release_identity._read_git_sha() == f"{GIT_SHA}\n"


def test_health_fields_contain_no_source_or_environment_details():
    identity = ReleaseIdentity(sha=GIT_SHA.lower(), status="VERIFIED")

    assert set(identity.as_health_fields()) == {
        "release_sha",
        "release_identity_status",
    }
    assert all("environment" not in key for key in identity.as_health_fields())


def test_release_identity_module_has_no_database_dependency():
    source = Path(release_identity.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert "models" not in imported_modules
    assert not any(name.startswith("sqlalchemy") for name in imported_modules)
    assert not any(name.startswith("flask_sqlalchemy") for name in imported_modules)


def test_health_exposes_only_minimal_verified_identity_fields(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(
        app_module,
        "RELEASE_IDENTITY",
        ReleaseIdentity(sha=GIT_SHA.lower(), status="VERIFIED"),
    )

    response = client.get("/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["release_sha"] == GIT_SHA.lower()
    assert payload["release_identity_status"] == "VERIFIED"
    assert set(payload) == {
        "status",
        "database",
        "environment",
        "release_sha",
        "release_identity_status",
        "timestamp",
    }


def test_health_remains_healthy_when_release_identity_is_unverified(
    client, monkeypatch
):
    import app as app_module

    monkeypatch.setattr(
        app_module,
        "RELEASE_IDENTITY",
        ReleaseIdentity(sha=None, status="UNVERIFIED"),
    )

    response = client.get("/health")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["release_sha"] is None
    assert payload["release_identity_status"] == "UNVERIFIED"
