"""Disposable PostgreSQL validation for the guarded reference-data importer."""

from __future__ import annotations

import ast
from dataclasses import replace
import getpass
from pathlib import Path
import shutil
import socket
import subprocess
from urllib.parse import quote
from uuid import uuid4

from alembic import command
from alembic.config import Config
import openpyxl
import psycopg2
from psycopg2 import sql
import pytest

from runtime_config import (
    RuntimeConfigurationError,
    database_identity_hash,
    resolve_reference_import_database_config,
)
from scripts.bootstrap_bl60 import bootstrap
from scripts.import_reference_data import (
    ALLOWED_PASS_NAMES,
    DEFAULT_WORKBOOK_PATH,
    EXPECTED_MAPPING_COUNT,
    EXPECTED_MAPPED_RESORT_COUNT,
    EXPECTED_RESORT_COUNT,
    EXPECTED_UNMAPPED_RESORT_COUNT,
    ReferenceImportError,
    apply_reference_data,
    load_reference_data,
    main,
    run_import,
    validation_report,
)
from utils.countries import COUNTRIES


ROOT = Path(__file__).parents[1]
PRODUCTION_URL = "postgresql://prod:secret@production.example:5432/baselodge"
PRODUCTION_HASH = database_identity_hash(PRODUCTION_URL)


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


@pytest.fixture(scope="session")
def disposable_postgres(tmp_path_factory):
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("PostgreSQL server tools are required for reference-import validation")

    root = tmp_path_factory.mktemp("reference-import-postgres")
    data = root / "data"
    socket_dir = root / "socket"
    socket_dir.mkdir()
    log = root / "postgres.log"
    port = _free_port()
    role = getpass.getuser()
    subprocess.run(
        [
            initdb,
            "-D",
            str(data),
            "-A",
            "trust",
            "--no-locale",
            "--encoding=UTF8",
            "-U",
            role,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-o",
            f"-F -h 127.0.0.1 -k {socket_dir} -p {port}",
            "-l",
            str(log),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    admin_url = f"postgresql://{quote(role, safe='')}@127.0.0.1:{port}/postgres"

    def create_database(prefix="reference"):
        name = f"{prefix}_{uuid4().hex}"
        connection = psycopg2.connect(admin_url)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
        finally:
            connection.close()
        return f"postgresql://{quote(role, safe='')}@127.0.0.1:{port}/{name}"

    try:
        yield create_database
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True,
            capture_output=True,
            text=True,
        )


def _reference_environment(database_url, runtime_env="test"):
    environment = {
        "BASELODGE_RUNTIME_ENV": runtime_env,
        "BASELODGE_REFERENCE_IMPORT_MODE": "1",
        "BASELODGE_REFERENCE_IMPORT_DATABASE_URL": database_url,
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
    }
    if runtime_env == "development":
        environment["BASELODGE_DEVELOPMENT_DATABASE_URL"] = database_url
    return environment


def _bootstrap_environment(monkeypatch, database_url):
    monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "test")
    monkeypatch.setenv("BASELODGE_BOOTSTRAP_MODE", "1")
    monkeypatch.setenv("BASELODGE_BOOTSTRAP_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )


def _migration_environment(monkeypatch, database_url):
    monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "test")
    monkeypatch.setenv("BASELODGE_MIGRATION_MODE", "1")
    monkeypatch.setenv("BASELODGE_MIGRATION_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )


def _alembic_config():
    configuration = Config(str(ROOT / "migrations" / "alembic.ini"))
    configuration.set_main_option("script_location", str(ROOT / "migrations"))
    return configuration


def _initialized_database(disposable_postgres, monkeypatch, prefix):
    database_url = disposable_postgres(prefix)
    _bootstrap_environment(monkeypatch, database_url)
    bootstrap()
    _migration_environment(monkeypatch, database_url)
    configuration = _alembic_config()
    command.stamp(configuration, "bl60_mtn_filter_edu")
    command.upgrade(configuration, "head")
    return database_url


def _counts(database_url):
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            tables = (
                "resort",
                "resort_pass",
                "country",
                "user",
                "ski_trip",
                "ski_day",
                "push_device_token",
                "mountain_page_view",
            )
            counts = {}
            for table in tables:
                cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
                counts[table] = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*)
                FROM resort_pass mapping
                LEFT JOIN resort resort ON resort.id = mapping.resort_id
                WHERE resort.id IS NULL
                """
            )
            counts["orphan_passes"] = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM (SELECT slug FROM resort GROUP BY slug HAVING count(*) > 1) duplicates"
            )
            counts["duplicate_slugs"] = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT count(*)
                FROM (
                    SELECT resort_id, pass_name
                    FROM resort_pass
                    GROUP BY resort_id, pass_name
                    HAVING count(*) > 1
                ) duplicates
                """
            )
            counts["duplicate_mappings"] = cursor.fetchone()[0]
        return counts
    finally:
        connection.close()


def _workbook_copy(tmp_path):
    copy = tmp_path / "reference.xlsx"
    shutil.copy(DEFAULT_WORKBOOK_PATH, copy)
    return copy


def test_importer_source_has_no_application_or_flask_imports():
    tree = ast.parse((ROOT / "scripts" / "import_reference_data.py").read_text())
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert {"app", "flask", "models"}.isdisjoint(imported_roots)


def test_canonical_workbook_matches_reviewed_contract():
    data, summary = load_reference_data()

    assert summary.valid
    assert summary.resort_count == EXPECTED_RESORT_COUNT
    assert summary.mapping_count == EXPECTED_MAPPING_COUNT
    assert summary.mapped_resort_count == EXPECTED_MAPPED_RESORT_COUNT
    assert summary.unmapped_resort_count == EXPECTED_UNMAPPED_RESORT_COUNT
    assert not summary.duplicate_slugs
    assert not summary.duplicate_mapping_pairs
    assert not summary.missing_mapping_slugs
    assert not summary.invalid_pass_names
    assert not summary.invalid_country_codes
    assert {"AD", "AT", "GE"}.issubset(COUNTRIES)
    assert {mapping["pass_name"] for mapping in data.mappings} == ALLOWED_PASS_NAMES
    assert ("alta-us", "Ikon") in {
        (mapping["slug"], mapping["pass_name"]) for mapping in data.mappings
    }
    assert ("alta-us", "Other") in {
        (mapping["slug"], mapping["pass_name"]) for mapping in data.mappings
    }


@pytest.mark.parametrize(
    "mutation,match",
    [
        (
            lambda workbook: workbook.remove(workbook["ResortPassMap_FIXED"]),
            "missing required worksheet",
        ),
        (
            lambda workbook: setattr(workbook["Resorts_Cleaned"]["B2"], "value", None),
            "missing required fields",
        ),
        (
            lambda workbook: workbook["ResortPassMap_FIXED"].append(
                [
                    "49-degrees-north-us",
                    "49 Degrees North",
                    "Other",
                    "duplicate",
                    1,
                    "test",
                    "",
                ]
            ),
            "duplicate mapping pairs",
        ),
        (
            lambda workbook: setattr(workbook["ResortPassMap_FIXED"]["A2"], "value", "missing-resort"),
            "missing mapping slugs",
        ),
        (
            lambda workbook: setattr(workbook["ResortPassMap_FIXED"]["C2"], "value", "InvalidPass"),
            "invalid pass names",
        ),
        (
            lambda workbook: setattr(workbook["Resorts_Cleaned"]["E2"], "value", "ZZ"),
            "invalid country codes",
        ),
    ],
)
def test_workbook_validation_refuses_bad_source(tmp_path, mutation, match):
    workbook_path = _workbook_copy(tmp_path)
    workbook = openpyxl.load_workbook(workbook_path)
    mutation(workbook)
    workbook.save(workbook_path)
    workbook.close()

    with pytest.raises(ReferenceImportError, match=match):
        load_reference_data(workbook_path, enforce_expected_counts=False)


@pytest.mark.parametrize(
    "environment,match",
    [
        ({}, "RUNTIME_ENV"),
        ({"BASELODGE_RUNTIME_ENV": "production"}, "only allowed"),
        ({"BASELODGE_RUNTIME_ENV": "test"}, "REFERENCE_IMPORT_MODE"),
        (
            {
                "BASELODGE_RUNTIME_ENV": "test",
                "BASELODGE_REFERENCE_IMPORT_MODE": "1",
            },
            "REFERENCE_IMPORT_DATABASE_URL",
        ),
        (
            {
                "BASELODGE_RUNTIME_ENV": "test",
                "BASELODGE_REFERENCE_IMPORT_MODE": "1",
                "BASELODGE_REFERENCE_IMPORT_DATABASE_URL": "sqlite:///:memory:",
            },
            "PostgreSQL",
        ),
    ],
)
def test_reference_import_configuration_refuses_invalid_authorization(environment, match):
    environment.setdefault(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )
    with pytest.raises(RuntimeConfigurationError, match=match):
        resolve_reference_import_database_config(environment)


def test_reference_import_configuration_rejects_production_identity():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_reference_import_database_config(
            _reference_environment(PRODUCTION_URL)
        )


def test_development_reference_import_requires_matching_development_identity():
    environment = _reference_environment(
        "postgresql://dev@target.example:5432/baselodge", "development"
    )
    environment["BASELODGE_DEVELOPMENT_DATABASE_URL"] = (
        "postgresql://dev@expected.example:5432/baselodge"
    )
    with pytest.raises(RuntimeConfigurationError, match="must match"):
        resolve_reference_import_database_config(environment)


def test_dry_run_is_non_mutating_and_reports_planned_counts():
    def should_not_connect(_):
        raise AssertionError("dry-run opened a database connection")

    summary = run_import(
        environ=_reference_environment("postgresql://test@safe.example:5432/baselodge"),
        connection_factory=should_not_connect,
    )

    report = validation_report(summary)
    assert "Planned resorts: 695" in report
    assert "Planned resort-pass mappings: 245" in report
    assert summary.resort_count == EXPECTED_RESORT_COUNT
    assert summary.mapping_count == EXPECTED_MAPPING_COUNT


def test_apply_refuses_an_alternate_workbook_before_connecting(tmp_path):
    alternate = _workbook_copy(tmp_path)

    def should_not_connect(_):
        raise AssertionError("alternate workbook attempt opened a database connection")

    with pytest.raises(ReferenceImportError, match="canonical workbook"):
        run_import(
            workbook_path=alternate,
            apply=True,
            environ=_reference_environment(
                "postgresql://test@safe.example:5432/baselodge"
            ),
            connection_factory=should_not_connect,
        )


def test_apply_refuses_a_canonical_path_with_unapproved_content_before_connecting():
    data, _ = load_reference_data()

    def should_not_connect(_):
        raise AssertionError("tampered workbook attempt opened a database connection")

    with pytest.raises(ReferenceImportError, match="canonical workbook"):
        apply_reference_data(
            replace(data, workbook_sha256="0" * 64),
            resolve_reference_import_database_config(
                _reference_environment(
                    "postgresql://test@safe.example:5432/baselodge"
                )
            ),
            connection_factory=should_not_connect,
        )


def test_cli_does_not_allow_an_alternate_workbook_option():
    with pytest.raises(SystemExit):
        main(["--workbook", "alternate.xlsx"])


def test_disposable_apply_writes_only_reviewed_reference_data(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "apply")
    summary = run_import(
        apply=True,
        environ=_reference_environment(database_url),
    )

    assert summary.resort_count == EXPECTED_RESORT_COUNT
    assert summary.mapping_count == EXPECTED_MAPPING_COUNT
    counts = _counts(database_url)
    assert counts == {
        "resort": 695,
        "resort_pass": 245,
        "country": 0,
        "user": 0,
        "ski_trip": 0,
        "ski_day": 0,
        "push_device_token": 0,
        "mountain_page_view": 0,
        "orphan_passes": 0,
        "duplicate_slugs": 0,
        "duplicate_mappings": 0,
    }

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT mapping.pass_name, mapping.is_primary
                FROM resort_pass mapping
                JOIN resort ON resort.id = mapping.resort_id
                WHERE resort.slug = 'alta-us'
                ORDER BY mapping.pass_name
                """
            )
            assert cursor.fetchall() == [("Ikon", True), ("Other", False)]
    finally:
        connection.close()


def test_reference_import_rolls_back_all_reference_writes(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "rollback")
    data, _ = load_reference_data()
    configuration = resolve_reference_import_database_config(
        _reference_environment(database_url)
    )

    with pytest.raises(ReferenceImportError, match="rolled back"):
        apply_reference_data(data, configuration, fail_after_resorts=True)

    counts = _counts(database_url)
    assert counts["resort"] == 0
    assert counts["resort_pass"] == 0
    assert counts["orphan_passes"] == 0


def test_reference_import_is_idempotent(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "idempotent")
    environment = _reference_environment(database_url)
    run_import(apply=True, environ=environment)
    first_counts = _counts(database_url)

    run_import(apply=True, environ=environment)
    second_counts = _counts(database_url)

    assert first_counts == second_counts
    assert second_counts["resort"] == 695
    assert second_counts["resort_pass"] == 245
    assert second_counts["duplicate_slugs"] == 0
    assert second_counts["duplicate_mappings"] == 0