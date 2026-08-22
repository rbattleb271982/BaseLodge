"""Disposable PostgreSQL validation for the guarded development-user creator."""

from __future__ import annotations

import ast
from pathlib import Path

import psycopg2
import pytest
from werkzeug.security import check_password_hash

from runtime_config import (
    RuntimeConfigurationError,
    database_identity_hash,
    resolve_development_user_database_config,
)
from scripts.create_dev_user import (
    DevelopmentUserError,
    DevelopmentUserInput,
    create_development_user,
    validate_user_input,
)
from test_import_reference_data_postgres import (
    _initialized_database,
    disposable_postgres,
)


ROOT = Path(__file__).parents[1]
PRODUCTION_URL = "postgresql://prod:secret@production.example:5432/baselodge"
PRODUCTION_HASH = database_identity_hash(PRODUCTION_URL)


def _environment(database_url, *, mode="1", runtime="development"):
    return {
        "BASELODGE_RUNTIME_ENV": runtime,
        "BASELODGE_DEVELOPMENT_USER_MODE": mode,
        "BASELODGE_DEVELOPMENT_DATABASE_URL": database_url,
        "BASELODGE_DEVELOPMENT_USER_DATABASE_URL": database_url,
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": PRODUCTION_HASH,
    }


def _user(email="base-lodge-dev@example.test"):
    return DevelopmentUserInput(
        first_name="Dev",
        last_name="Tester",
        email=email,
        rider_type="Skier",
        pass_type="Ikon",
        skill_level="Intermediate",
        home_state="CO",
    )


def test_creator_has_no_application_or_flask_imports():
    tree = ast.parse((ROOT / "scripts" / "create_dev_user.py").read_text())
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert {"app", "flask", "models"}.isdisjoint(imported_roots)


@pytest.mark.parametrize(
    "environment,match",
    [
        ({}, "RUNTIME_ENV"),
        ({"BASELODGE_RUNTIME_ENV": "test"}, "only allowed"),
        (
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_DEVELOPMENT_DATABASE_URL": "postgresql://dev@safe.example/db",
            },
            "DEVELOPMENT_USER_MODE",
        ),
        (
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_DEVELOPMENT_USER_MODE": "1",
            },
                "DEVELOPMENT_USER_DATABASE_URL",
        ),
        (
            {
                "BASELODGE_RUNTIME_ENV": "development",
                "BASELODGE_DEVELOPMENT_USER_MODE": "1",
                "BASELODGE_DEVELOPMENT_DATABASE_URL": "postgresql://dev@safe.example/db",
                "BASELODGE_DEVELOPMENT_USER_DATABASE_URL": "sqlite:///:memory:",
            },
            "PostgreSQL",
        ),
    ],
)
def test_user_configuration_refuses_invalid_authorization(environment, match):
    environment.setdefault(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )
    with pytest.raises(RuntimeConfigurationError, match=match):
        resolve_development_user_database_config(environment)


def test_user_configuration_rejects_production_identity():
    with pytest.raises(RuntimeConfigurationError, match="protected production"):
        resolve_development_user_database_config(
            _environment(PRODUCTION_URL)
        )


def test_user_configuration_rejects_mismatched_creator_target():
    environment = _environment("postgresql://dev@target.example:5432/baselodge")
    environment["BASELODGE_DEVELOPMENT_DATABASE_URL"] = (
        "postgresql://dev@expected.example:5432/baselodge"
    )
    with pytest.raises(RuntimeConfigurationError, match="must match"):
        resolve_development_user_database_config(environment)


def test_email_must_be_reserved_development_address():
    with pytest.raises(DevelopmentUserError, match="reserved"):
        validate_user_input(_user("someone@real.example"))


def test_guard_refuses_before_connection():
    def should_not_connect(_):
        raise AssertionError("invalid guard opened a connection")

    with pytest.raises(DevelopmentUserError, match="DEVELOPMENT_USER_MODE"):
        create_development_user(
            _user(),
            "DevPassword1!",
            environ=_environment(
                "postgresql://dev@safe.example/db",
                mode="0",
            ),
            connection_factory=should_not_connect,
        )


def test_create_verifies_local_user_and_changes_no_other_tables(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "dev-user")
    result = create_development_user(
        _user(),
        "DevPassword1!",
        environ=_environment(database_url),
    )

    assert result.created is True
    assert result.verified is True
    assert result.email == "base-lodge-dev@example.test"

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT first_name, last_name, email, password_hash,
                       auth_provider, rider_types, pass_type, skill_level,
                       home_state, lifecycle_stage, is_seeded, is_verified,
                       push_notifications_enabled, email_opt_in,
                       email_transactional, email_social, email_digest,
                       discoverable_in_friend_search
                FROM "user"
                WHERE email = %s
                """,
                (result.email,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0:3] == ("Dev", "Tester", result.email)
            assert row[3] and row[3] != "DevPassword1!"
            assert check_password_hash(row[3], "DevPassword1!")
            assert row[4:10] == (
                "email",
                ["Skier"],
                "Ikon",
                "Intermediate",
                "CO",
                "active",
            )
            assert row[10:] == (True, True, False, False, False, False, False, False)
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'user'
                  AND column_name = 'password'
                """
            )
            assert cursor.fetchone() is None
            for table in (
                "friend",
                "ski_trip",
                "invitation",
                "user_availability",
                "ski_day",
                "push_device_token",
                "message_event_log",
                "mountain_page_view",
                "activity",
            ):
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                assert cursor.fetchone()[0] == 0, table
    finally:
        connection.close()


def test_duplicate_email_does_not_reset_password(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "duplicate")
    environment = _environment(database_url)
    first = create_development_user(_user(), "FirstPassword1!", environ=environment)
    second = create_development_user(_user(), "SecondPassword1!", environ=environment)

    assert first.created is True
    assert second.created is False
    assert second.user_id == first.user_id
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT password_hash FROM "user" WHERE id = %s',
                (first.user_id,),
            )
            password_hash = cursor.fetchone()[0]
            assert check_password_hash(password_hash, "FirstPassword1!")
            assert not check_password_hash(password_hash, "SecondPassword1!")
    finally:
        connection.close()


def test_second_distinct_email_is_refused_by_one_time_creator(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "one-time")
    environment = _environment(database_url)
    create_development_user(_user(), "FirstPassword1!", environ=environment)

    with pytest.raises(DevelopmentUserError, match="already exists"):
        create_development_user(
            _user("second-dev-user@example.test"),
            "SecondPassword1!",
            environ=environment,
        )

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM "user"')
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_unexpected_trigger_write_rolls_back_user_creation(
    disposable_postgres, monkeypatch
):
    database_url = _initialized_database(disposable_postgres, monkeypatch, "trigger")
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE creator_audit (id serial PRIMARY KEY)")
            cursor.execute(
                """
                CREATE FUNCTION audit_development_user_creation()
                RETURNS trigger AS $$
                BEGIN
                    INSERT INTO creator_audit DEFAULT VALUES;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER development_user_audit
                AFTER INSERT ON "user"
                FOR EACH ROW EXECUTE FUNCTION audit_development_user_creation()
                """
            )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(DevelopmentUserError, match="Unexpected table changes"):
        create_development_user(
            _user(),
            "DevPassword1!",
            environ=_environment(database_url),
        )

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM "user"')
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM creator_audit")
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()