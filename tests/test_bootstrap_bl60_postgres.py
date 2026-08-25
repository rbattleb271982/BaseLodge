"""Disposable PostgreSQL validation for the reviewed BL-60 bootstrap."""

from __future__ import annotations

import ast
import getpass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from urllib.parse import quote
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg2
from psycopg2 import sql
import pytest

from runtime_config import (
    RuntimeConfigurationError,
    database_identity_hash,
    resolve_bootstrap_database_config,
)
from scripts.bootstrap_bl60 import (
    BootstrapError,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_SCHEMA_PATH,
    assert_catalog_matches,
    bootstrap,
)


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
        pytest.skip("PostgreSQL server tools are required for bootstrap validation")

    root = tmp_path_factory.mktemp("bl60-postgres")
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

    def create_database(prefix="bl60"):
        name = f"{prefix}_{uuid4().hex}"
        connection = psycopg2.connect(admin_url)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
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


def _bootstrap_environment(monkeypatch, database_url, runtime_env="test"):
    monkeypatch.setenv("BASELODGE_RUNTIME_ENV", runtime_env)
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


def _public_tables(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _foreign_key_actions(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT target.relname,
                   CASE constraint_row.confdeltype
                       WHEN 'a' THEN 'NO ACTION'
                       WHEN 'r' THEN 'RESTRICT'
                       WHEN 'c' THEN 'CASCADE'
                       WHEN 'n' THEN 'SET NULL'
                       WHEN 'd' THEN 'SET DEFAULT'
                   END
            FROM pg_constraint constraint_row
            JOIN pg_class source ON source.oid = constraint_row.conrelid
            JOIN pg_class target ON target.oid = constraint_row.confrelid
            JOIN pg_namespace namespace ON namespace.oid = source.relnamespace
            WHERE namespace.nspname = 'public'
              AND source.relname = %s
              AND constraint_row.contype = 'f'
            """,
            (table_name,),
        )
        return set(cursor.fetchall())


def _direct_bl60_schema(database_url):
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        connection.close()


def test_bootstrap_path_has_no_application_or_flask_imports():
    tree = ast.parse((ROOT / "scripts" / "bootstrap_bl60.py").read_text())
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert "app" not in imported_roots
    assert "flask" not in imported_roots
    assert "models" not in imported_roots


@pytest.mark.parametrize(
    "environment,match",
    [
        ({}, "RUNTIME_ENV"),
        ({"BASELODGE_RUNTIME_ENV": "invalid"}, "RUNTIME_ENV"),
        ({"BASELODGE_RUNTIME_ENV": "production"}, "only allowed"),
        ({"BASELODGE_RUNTIME_ENV": "test"}, "BOOTSTRAP_MODE"),
        (
            {"BASELODGE_RUNTIME_ENV": "test", "BASELODGE_BOOTSTRAP_MODE": "1"},
            "BOOTSTRAP_DATABASE_URL",
        ),
        (
            {
                "BASELODGE_RUNTIME_ENV": "test",
                "BASELODGE_BOOTSTRAP_MODE": "1",
                "BASELODGE_BOOTSTRAP_DATABASE_URL": "sqlite:///:memory:",
            },
            "PostgreSQL",
        ),
    ],
)
def test_bootstrap_configuration_refuses_invalid_authorization(environment, match):
    environment.setdefault(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )
    with pytest.raises(RuntimeConfigurationError, match=match):
        resolve_bootstrap_database_config(environment)


def test_bootstrap_configuration_rejects_production_identity():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_bootstrap_database_config(
            {
                "BASELODGE_RUNTIME_ENV": "test",
                "BASELODGE_BOOTSTRAP_MODE": "1",
                "BASELODGE_BOOTSTRAP_DATABASE_URL": PRODUCTION_URL,
                "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
            }
        )


def test_development_bootstrap_requires_matching_development_identity():
    with pytest.raises(RuntimeConfigurationError, match="must match"):
        resolve_bootstrap_database_config(
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_BOOTSTRAP_MODE": "1",
                "BASELODGE_BOOTSTRAP_DATABASE_URL": (
                    "postgresql://dev@other.example:5432/baselodge"
                ),
                "BASELODGE_DEVELOPMENT_DATABASE_URL": (
                    "postgresql://dev@expected.example:5432/baselodge"
                ),
                "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
            }
        )


def test_fresh_bootstrap_stamps_and_upgrades_to_head(
    disposable_postgres, monkeypatch
):
    database_url = disposable_postgres("fresh")
    _bootstrap_environment(monkeypatch, database_url)
    bootstrap()

    connection = psycopg2.connect(database_url)
    try:
        assert_catalog_matches(connection, DEFAULT_CONTRACT_PATH)
        assert len(_public_tables(connection)) == 28
        assert "alembic_version" not in _public_tables(connection)
        assert "ski_day" not in _public_tables(connection)
        assert _foreign_key_actions(connection, "mountain_page_view") == set()
        assert _foreign_key_actions(connection, "friend_cooldown") == {
            ("user", "CASCADE")
        }
    finally:
        connection.close()

    _migration_environment(monkeypatch, database_url)
    configuration = _alembic_config()
    command.stamp(configuration, "bl60_mtn_filter_edu")
    command.upgrade(configuration, "head")

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone()[0] == "bl52_trip_stay"
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'ski_trip'
                  AND column_name IN ('stay_name', 'stay_description')
                """
            )
            assert {row[0] for row in cursor.fetchall()} == {
                "stay_name",
                "stay_description",
            }
        assert _foreign_key_actions(connection, "ski_day") == {
            ("user", "CASCADE"),
            ("resort", "RESTRICT"),
            ("ski_trip", "SET NULL"),
        }
        assert _foreign_key_actions(connection, "mountain_page_view") == {
            ("resort", "CASCADE"),
            ("user", "SET NULL"),
        }
    finally:
        connection.close()


def test_existing_bl60_path_upgrades_without_bootstrap(
    disposable_postgres, monkeypatch
):
    database_url = disposable_postgres("existing_path")
    _direct_bl60_schema(database_url)
    _migration_environment(monkeypatch, database_url)
    configuration = _alembic_config()
    command.stamp(configuration, "bl60_mtn_filter_edu")
    command.upgrade(configuration, "head")

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM alembic_version")
            assert cursor.fetchone()[0] == "bl52_trip_stay"
        assert _foreign_key_actions(connection, "ski_day") == {
            ("user", "CASCADE"),
            ("resort", "RESTRICT"),
            ("ski_trip", "SET NULL"),
        }
        assert _foreign_key_actions(connection, "mountain_page_view") == {
            ("resort", "CASCADE"),
            ("user", "SET NULL"),
        }
    finally:
        connection.close()


def test_bl306_orphans_fail_closed_then_resolved_rows_upgrade(
    disposable_postgres, monkeypatch
):
    database_url = disposable_postgres("orphans")
    _direct_bl60_schema(database_url)
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO resort (id, name, state, slug) "
                    "VALUES (1, 'Valid', 'CO', 'valid')"
                )
                cursor.execute(
                    'INSERT INTO "user" (id, first_name, email) '
                    "VALUES (1, 'Valid', 'valid@example.test')"
                )
                cursor.execute(
                    "INSERT INTO mountain_page_view "
                    "(id, resort_id, user_id, session_key) VALUES "
                    "(1, 1, 1, 'valid'), (2, 999, 1, 'bad-resort'), "
                    "(3, 1, 888, 'bad-user')"
                )
    finally:
        connection.close()

    _migration_environment(monkeypatch, database_url)
    configuration = _alembic_config()
    command.stamp(configuration, "bl60_mtn_filter_edu")
    command.upgrade(configuration, "bl305_ski_day_foundation")
    with pytest.raises(RuntimeError, match="orphan references"):
        command.upgrade(configuration, "head")

    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, resort_id, user_id FROM mountain_page_view ORDER BY id"
                )
                assert cursor.fetchall() == [(1, 1, 1), (2, 999, 1), (3, 1, 888)]
                assert _foreign_key_actions(connection, "mountain_page_view") == set()
                cursor.execute("DELETE FROM mountain_page_view WHERE id IN (2, 3)")
    finally:
        connection.close()

    command.upgrade(configuration, "head")
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, resort_id, user_id FROM mountain_page_view ORDER BY id"
            )
            assert cursor.fetchall() == [(1, 1, 1)]
        assert _foreign_key_actions(connection, "mountain_page_view") == {
            ("resort", "CASCADE"),
            ("user", "SET NULL"),
        }
    finally:
        connection.close()


@pytest.mark.parametrize(
    "setup_sql,match",
    [
        ("CREATE TABLE already_populated (id integer)", "contains relations"),
        (
            "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL)",
            "alembic_version",
        ),
        ("CREATE TYPE guest_status_enum AS ENUM ('invited')", "user-defined types"),
    ],
)
def test_bootstrap_refuses_nonempty_targets(
    disposable_postgres, monkeypatch, setup_sql, match
):
    database_url = disposable_postgres("refuse")
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(setup_sql)
    finally:
        connection.close()
    _bootstrap_environment(monkeypatch, database_url)
    with pytest.raises(BootstrapError, match=match):
        bootstrap()


def test_second_bootstrap_attempt_is_refused(disposable_postgres, monkeypatch):
    database_url = disposable_postgres("second")
    _bootstrap_environment(monkeypatch, database_url)
    bootstrap()
    with pytest.raises(BootstrapError, match="contains relations"):
        bootstrap()


def test_sql_failure_rolls_back_completely(
    disposable_postgres, monkeypatch, tmp_path
):
    database_url = disposable_postgres("sql_rollback")
    broken_schema = tmp_path / "broken.sql"
    broken_schema.write_text(
        DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8")
        + "\nCREATE TABLE should_rollback (id integer);\n"
        + "SELECT deliberately_missing_function();\n",
        encoding="utf-8",
    )
    _bootstrap_environment(monkeypatch, database_url)
    with pytest.raises(BootstrapError, match="rolled back"):
        bootstrap(schema_path=broken_schema)

    connection = psycopg2.connect(database_url)
    try:
        assert _public_tables(connection) == []
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM pg_type type
                JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
                WHERE namespace.nspname = 'public' AND type.typtype = 'e'
                """
            )
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()


def test_catalog_mismatch_rolls_back_completely(
    disposable_postgres, monkeypatch, tmp_path
):
    database_url = disposable_postgres("contract_rollback")
    contract = json.loads(DEFAULT_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["tables"] = contract["tables"][:-1]
    broken_contract = tmp_path / "wrong-contract.json"
    broken_contract.write_text(json.dumps(contract), encoding="utf-8")
    _bootstrap_environment(monkeypatch, database_url)
    with pytest.raises(BootstrapError, match="does not match"):
        bootstrap(contract_path=broken_contract)

    connection = psycopg2.connect(database_url)
    try:
        assert _public_tables(connection) == []
    finally:
        connection.close()