"""Read-only and fail-closed coverage for the release preflight."""

from types import SimpleNamespace

import pytest
import sqlalchemy as sa

import release_preflight
from github_ci_evidence import CheckRun, GitHubCiEvidence
from release_identity import ReleaseIdentity
from runtime_config import DatabaseConfiguration, database_identity_hash


GIT_SHA = "0123456789abcdef0123456789abcdef01234567"
PRODUCTION_URL = "postgresql://prod:secret@prod.example:5432/baselodge"
DEVELOPMENT_URL = "postgresql://dev:secret@dev.example:5432/baselodge"
PRODUCTION_HASH = database_identity_hash(PRODUCTION_URL)
_DEFAULT = object()


def _environment(runtime_env="development", **overrides):
    environment = {
        "BASELODGE_RUNTIME_ENV": runtime_env,
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
        "BASELODGE_DEVELOPMENT_DATABASE_URL": DEVELOPMENT_URL,
        "BASELODGE_PRODUCTION_DATABASE_URL": PRODUCTION_URL,
    }
    environment.update(overrides)
    return environment


def _snapshot(
    revision="bl70_user_season_pass",
    *,
    stay_name=_DEFAULT,
    stay_description=_DEFAULT,
):
    columns = {}
    if stay_name is not None and stay_name is not _DEFAULT:
        columns["stay_name"] = stay_name
    elif stay_name is _DEFAULT:
        columns["stay_name"] = release_preflight.ColumnSnapshot(
            data_type="character varying",
            max_length=200,
            nullable=True,
        )
    if stay_description is not None and stay_description is not _DEFAULT:
        columns["stay_description"] = stay_description
    elif stay_description is _DEFAULT:
        columns["stay_description"] = release_preflight.ColumnSnapshot(
            data_type="character varying",
            max_length=500,
            nullable=True,
        )
    return release_preflight.LiveDatabaseSnapshot(
        revisions=(revision,),
        columns=columns,
    )


def _run(environment=None, **overrides):
    arguments = {
        "identity": ReleaseIdentity(GIT_SHA, "VERIFIED"),
        "source_heads": ("bl70_user_season_pass",),
        "live_database": _snapshot(),
    }
    arguments.update(overrides)
    return release_preflight.run_preflight(
        _environment() if environment is None else environment,
        **arguments,
    )


def test_successful_development_preflight():
    report = _run()

    assert report.passed is True
    assert "PREFLIGHT: PASS" in release_preflight.format_report(report)


def test_successful_production_preflight():
    report = _run(_environment("production"))

    assert report.passed is True


def test_production_preflight_uses_candidate_checkout_identity(monkeypatch):
    monkeypatch.setattr(
        release_preflight,
        "resolve_candidate_release_identity",
        lambda: ReleaseIdentity(GIT_SHA, "VERIFIED"),
    )

    report = release_preflight.run_preflight(
        _environment("production"),
        source_heads=("bl70_user_season_pass",),
        live_database=_snapshot(),
    )

    assert report.passed is True


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"BASELODGE_RUNTIME_ENV": "staging"},
    ],
)
def test_missing_or_invalid_environment_fails_closed(environment):
    report = _run(environment)

    assert report.passed is False
    assert any(
        check.label == "ENVIRONMENT" and not check.passed
        for check in report.checks
    )


def test_production_target_identity_mismatch_fails():
    report = _run(
        _environment(
            "production",
            BASELODGE_PRODUCTION_DATABASE_URL=DEVELOPMENT_URL,
        )
    )

    assert report.passed is False
    assert any(
        check.label == "DATABASE TARGET" and not check.passed
        for check in report.checks
    )


def test_development_targeting_production_fails():
    report = _run(
        _environment(
            BASELODGE_DEVELOPMENT_DATABASE_URL=PRODUCTION_URL,
        )
    )

    assert report.passed is False


def test_generic_database_url_match_fails():
    report = _run(
        _environment(BASELODGE_DEVELOPMENT_DATABASE_URL=DEVELOPMENT_URL,
                     DATABASE_URL=DEVELOPMENT_URL)
    )

    assert report.passed is False
    assert any(
        check.label == "GENERIC REPLIT DB ISOLATION" and not check.passed
        for check in report.checks
    )


@pytest.mark.parametrize(
    "environment",
    [
        _environment(
            BASELODGE_DEVELOPMENT_DATABASE_URL=(
                "postgresql://dev:secret@host:not-a-port/baselodge"
            )
        ),
        _environment(
            DATABASE_URL="postgresql://replit:secret@host:not-a-port/replit"
        ),
    ],
)
def test_malformed_database_url_fails_without_exception_or_leak(environment):
    report = _run(environment)
    output = release_preflight.format_report(report)

    assert report.passed is False
    assert "secret" not in output
    assert "not-a-port" not in output


@pytest.mark.parametrize(
    "identity",
    [
        ReleaseIdentity(None, "UNVERIFIED"),
        ReleaseIdentity("not-a-sha", "VERIFIED"),
        ReleaseIdentity(GIT_SHA.upper(), "VERIFIED"),
    ],
)
def test_unverified_or_malformed_release_identity_fails(identity):
    report = _run(identity=identity)

    assert report.passed is False
    assert any(
        check.label == "RELEASE SHA" and not check.passed
        for check in report.checks
    )


def test_multiple_alembic_heads_fail_closed():
    report = _run(source_heads=("head_a", "head_b"))

    assert report.passed is False
    assert any(
        check.label == "ALEMBIC SOURCE HEAD" and not check.passed
        for check in report.checks
    )


def test_live_revision_mismatch_fails():
    report = _run(live_database=_snapshot(revision="older_revision"))

    assert report.passed is False
    assert any(
        check.label == "LIVE ALEMBIC REVISION" and not check.passed
        for check in report.checks
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(
            stay_name=None,
            stay_description=release_preflight.ColumnSnapshot(
                "character varying", 500, True
            ),
        ),
        _snapshot(
            stay_name=release_preflight.ColumnSnapshot("integer", None, True),
        ),
        _snapshot(
            stay_name=release_preflight.ColumnSnapshot(
                "character varying", 201, True
            ),
        ),
        _snapshot(
            stay_name=release_preflight.ColumnSnapshot(
                "character varying", 200, False
            ),
        ),
    ],
)
def test_schema_incompatibility_fails(snapshot):
    report = _run(live_database=snapshot)

    assert report.passed is False
    assert any(
        check.label == "SCHEMA COMPATIBILITY" and not check.passed
        for check in report.checks
    )


@pytest.mark.parametrize(
    "column",
    [
        "stay_description",
    ],
)
@pytest.mark.parametrize(
    "column_snapshot",
    [
        release_preflight.ColumnSnapshot("integer", None, True),
        release_preflight.ColumnSnapshot("character varying", 501, True),
        release_preflight.ColumnSnapshot("character varying", 500, False),
    ],
)
def test_each_stay_description_schema_mismatch_fails(
    column,
    column_snapshot,
):
    report = _run(
        live_database=_snapshot(
            stay_description=column_snapshot,
        )
    )

    assert report.passed is False
    assert any(
        check.label == "SCHEMA COMPATIBILITY" and not check.passed
        for check in report.checks
    )


def test_missing_stay_description_fails():
    snapshot = release_preflight.LiveDatabaseSnapshot(
        revisions=("bl70_user_season_pass",),
        columns={
            "stay_name": release_preflight.ColumnSnapshot(
                "character varying", 200, True
            )
        },
    )

    report = _run(live_database=snapshot)

    assert report.passed is False


def test_database_query_failure_fails_closed():
    def fail_reader(_configuration):
        raise RuntimeError("database unavailable")

    report = release_preflight.run_preflight(
        _environment(),
        identity=ReleaseIdentity(GIT_SHA, "VERIFIED"),
        source_heads=("bl70_user_season_pass",),
        database_reader=fail_reader,
    )

    assert report.passed is False
    assert any(
        check.label == "LIVE ALEMBIC REVISION" and not check.passed
        for check in report.checks
    )


def test_failed_prerequisite_does_not_open_database():
    def unexpected_reader(_configuration):
        raise AssertionError("database reader must not be called")

    report = release_preflight.run_preflight(
        _environment(),
        identity=ReleaseIdentity(None, "UNVERIFIED"),
        source_heads=("bl70_user_season_pass",),
        database_reader=unexpected_reader,
    )

    assert report.passed is False
    assert any(
        check.label == "LIVE ALEMBIC REVISION"
        and check.detail == "not inspected because a prerequisite failed"
        for check in report.checks
    )


def test_cli_returns_nonzero_for_failed_required_check(monkeypatch, capsys):
    failed = release_preflight.PreflightReport(
        (
            release_preflight.CheckResult(
                "ENVIRONMENT", False, "invalid configuration"
            ),
        )
    )
    monkeypatch.setattr(
        release_preflight,
        "run_release_ready",
        lambda *_args, **_kwargs: failed,
    )

    assert release_preflight.main(["--approved-sha", GIT_SHA]) == 1
    output = capsys.readouterr().out
    assert "RELEASE READY: NO" in output
    assert "PREFLIGHT: FAIL" in output


def test_cli_converts_unexpected_failure_to_safe_nonzero_result(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        release_preflight,
        "run_release_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "postgresql://user:top-secret@private.example/baselodge"
            )
        ),
    )

    assert release_preflight.main(["--approved-sha", GIT_SHA]) == 1
    output = capsys.readouterr().out
    assert "PREFLIGHT: FAIL" in output
    assert "top-secret" not in output
    assert "private.example" not in output


def test_output_never_contains_urls_or_credentials():
    output = release_preflight.format_report(_run())

    assert PRODUCTION_URL not in output
    assert DEVELOPMENT_URL not in output
    assert "secret" not in output
    assert GIT_SHA in output


def test_database_reader_uses_read_only_sql(monkeypatch):
    statements = []

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def scalar_one(self):
            return self._rows[0][0]

    class FakeConnection:
        dialect = SimpleNamespace(name="postgresql")

        def exec_driver_sql(self, statement):
            statements.append(statement)
            if statement == "SHOW transaction_read_only":
                return FakeResult([("on",)])
            return FakeResult([])

        def execute(self, statement, params=None):
            statements.append(str(statement))
            if "version_num" in str(statement):
                return FakeResult([("bl70_user_season_pass",)])
            return FakeResult(
                [
                    ("stay_description", "character varying", 500, "YES"),
                    ("stay_name", "character varying", 200, "YES"),
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def rollback(self):
            statements.append("ROLLBACK")

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            pass

    monkeypatch.setattr(
        release_preflight,
        "create_engine",
        lambda *_args, **_kwargs: FakeEngine(),
    )

    configuration = DatabaseConfiguration(
        "production", PRODUCTION_URL, "production"
    )
    snapshot = release_preflight.read_live_database(configuration)

    assert snapshot.revisions == ("bl70_user_season_pass",)
    assert "BEGIN READ ONLY" in statements
    assert "ROLLBACK" in statements
    assert not any(
        statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE")
        )
        for statement in statements
    )


def test_sqlite_read_only_mode_rejects_writes(tmp_path):
    database_path = tmp_path / "preflight.db"
    engine = sa.create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE safety_probe (id INTEGER PRIMARY KEY)"
        )

    with engine.connect() as connection:
        release_preflight._begin_read_only_transaction(connection)
        with pytest.raises(sa.exc.OperationalError):
            connection.exec_driver_sql(
                "INSERT INTO safety_probe (id) VALUES (1)"
            )
        connection.rollback()

    with engine.connect() as connection:
        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM safety_probe"
        ).scalar_one()
    engine.dispose()

    assert count == 0


def _passing_evidence(sha=GIT_SHA):
    return GitHubCiEvidence(
        sha=sha,
        checks=(
            CheckRun(
                "Tests", sha, "completed", "success", 1, "github-actions"
            ),
            CheckRun(
                "Source integrity",
                sha,
                "completed",
                "success",
                2,
                "github-actions",
            ),
        ),
        verified=True,
        detail="Tests and Source integrity passed for the exact SHA",
    )


def test_clean_matching_workspace_sha_passes_identity_portion():
    identity = ReleaseIdentity(GIT_SHA, "VERIFIED")

    assert release_preflight.validate_approved_sha(GIT_SHA).passed
    assert release_preflight.validate_workspace_sha(identity, GIT_SHA).passed


def test_dirty_or_unverified_workspace_fails_release_identity():
    check = release_preflight.validate_workspace_sha(
        ReleaseIdentity(None, "UNVERIFIED"),
        GIT_SHA,
    )

    assert check.passed is False


def test_mismatched_workspace_head_fails_release_identity():
    check = release_preflight.validate_workspace_sha(
        ReleaseIdentity("f" * 40, "VERIFIED"),
        GIT_SHA,
    )

    assert check.passed is False


def test_release_ready_requires_exact_sha_passing_ci_and_existing_preflight():
    calls = []

    def fetch(repository, sha, *, token=None):
        calls.append((repository, sha, token))
        return _passing_evidence(sha)

    report = release_preflight.run_release_ready(
        GIT_SHA,
        _environment(),
        identity=ReleaseIdentity(GIT_SHA, "VERIFIED"),
        source_heads=("bl70_user_season_pass",),
        live_database=_snapshot(),
        evidence_fetcher=fetch,
        workspace_identity_resolver=lambda: ReleaseIdentity(GIT_SHA, "VERIFIED"),
    )

    assert report.passed is True
    assert calls == [
        ("rbattleb271982/BaseLodge", GIT_SHA, None)
    ]
    assert "RELEASE READY: YES" in (
        release_preflight.format_release_ready_report(report)
    )


def test_github_api_failure_is_not_verified_and_blocks_database():
    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("synthetic-token-must-not-appear")

    def unexpected_reader(_configuration):
        raise AssertionError("database must remain blocked")

    report = release_preflight.run_release_ready(
        GIT_SHA,
        _environment(),
        identity=ReleaseIdentity(GIT_SHA, "VERIFIED"),
        source_heads=("bl70_user_season_pass",),
        evidence_fetcher=fail_fetch,
        database_reader=unexpected_reader,
        workspace_identity_resolver=lambda: ReleaseIdentity(GIT_SHA, "VERIFIED"),
    )
    output = release_preflight.format_release_ready_report(report)

    assert report.passed is False
    assert "exact-SHA GitHub CI evidence is not verified" in output
    assert "synthetic-token" not in output


def test_evidence_from_different_sha_fails_release_ready():
    report = release_preflight.run_release_ready(
        GIT_SHA,
        _environment(),
        identity=ReleaseIdentity(GIT_SHA, "VERIFIED"),
        source_heads=("bl70_user_season_pass",),
        evidence_fetcher=lambda *_args, **_kwargs: _passing_evidence("f" * 40),
        database_reader=lambda _configuration: (_ for _ in ()).throw(
            AssertionError("database must remain blocked")
        ),
        workspace_identity_resolver=lambda: ReleaseIdentity(GIT_SHA, "VERIFIED"),
    )

    assert report.passed is False
    assert any(
        check.label == "GITHUB CI EVIDENCE" and not check.passed
        for check in report.checks
    )


def test_post_publish_exact_sha_and_production_health_pass():
    check = release_preflight.validate_post_publish_health(
        {
            "status": "healthy",
            "environment": "production",
            "release_identity_status": "VERIFIED",
            "release_sha": GIT_SHA,
        },
        GIT_SHA,
    )

    assert check.passed is True


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": "healthy",
            "environment": "production",
            "release_identity_status": "VERIFIED",
            "release_sha": "f" * 40,
        },
        {
            "status": "healthy",
            "environment": "development",
            "release_identity_status": "VERIFIED",
            "release_sha": GIT_SHA,
        },
        {
            "status": "healthy",
            "environment": "production",
            "release_identity_status": "UNVERIFIED",
            "release_sha": None,
        },
    ],
)
def test_post_publish_identity_mismatch_fails(payload):
    check = release_preflight.validate_post_publish_health(payload, GIT_SHA)

    assert check.passed is False


def test_post_publish_health_requires_exact_configured_origin_and_path():
    opened = False

    def unexpected_open(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("unsafe URL must not be opened")

    for candidate in (
        "http://app.example/health",
        "https://app.example/",
        "https://app.example/health?verbose=1",
        "https://other.example/health",
    ):
        with pytest.raises(RuntimeError, match="Production origin"):
            release_preflight._read_post_publish_health(
                candidate,
                expected_base_url="https://app.example",
                opener=unexpected_open,
            )

    assert opened is False


def test_post_publish_health_rejects_redirected_response():
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://other.example/health"

        def read(self, _limit):
            return b"{}"

    with pytest.raises(RuntimeError, match="redirected"):
        release_preflight._read_post_publish_health(
            "https://app.example/health",
            expected_base_url="https://app.example",
            opener=lambda *_args, **_kwargs: Response(),
        )


def test_final_workspace_recheck_blocks_stale_ready_result():
    identities = iter(
        [
            ReleaseIdentity(GIT_SHA, "VERIFIED"),
            ReleaseIdentity(None, "UNVERIFIED"),
        ]
    )
    report = release_preflight.run_release_ready(
        GIT_SHA,
        _environment(),
        source_heads=("bl70_user_season_pass",),
        live_database=_snapshot(),
        evidence_fetcher=lambda *_args, **_kwargs: _passing_evidence(),
        workspace_identity_resolver=lambda: next(identities),
    )

    assert report.passed is False
    assert report.checks[-1].label == "FINAL WORKSPACE SHA"
    assert report.checks[-1].passed is False