"""Focused tests for the safe runtime release identity contract."""

import ast
import subprocess
from pathlib import Path

import release_identity
from release_identity import ReleaseIdentity, resolve_release_identity


GIT_SHA = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"


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
