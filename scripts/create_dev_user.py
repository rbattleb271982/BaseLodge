"""Create exactly one isolated BaseLodge development account.

This module intentionally does not import Flask, app.py, or models.py.  It is
an explicit, one-user tool for a reserved development email address.
"""

from __future__ import annotations

from dataclasses import dataclass
import argparse
from datetime import datetime
import getpass
import re
import sys
from typing import Any, Callable, Mapping, Sequence

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
from werkzeug.security import generate_password_hash

from runtime_config import (
    DatabaseConfiguration,
    RuntimeConfigurationError,
    resolve_development_user_database_config,
)


DEVELOPMENT_EMAIL_SUFFIX = "@example.test"
ADVISORY_LOCK_KEY = 315001
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@example\.test$")


class DevelopmentUserError(RuntimeError):
    """Raised when a guarded development-user operation cannot proceed."""


@dataclass(frozen=True)
class DevelopmentUserInput:
    first_name: str
    last_name: str
    email: str
    rider_type: str
    pass_type: str
    skill_level: str
    home_state: str


@dataclass(frozen=True)
class DevelopmentUserResult:
    created: bool
    user_id: int | None
    email: str
    verified: bool
    message: str


def _clean(value: str, field: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise DevelopmentUserError(f"{field} is required.")
    if len(cleaned) > maximum:
        raise DevelopmentUserError(f"{field} must be {maximum} characters or fewer.")
    return cleaned


def validate_user_input(user: DevelopmentUserInput) -> DevelopmentUserInput:
    first_name = _clean(user.first_name, "First name", 80)
    last_name = _clean(user.last_name, "Last name", 80)
    email = _clean(user.email, "Development email", 120).lower()
    if not _EMAIL_PATTERN.fullmatch(email):
        raise DevelopmentUserError(
            f"Development email must use the reserved {DEVELOPMENT_EMAIL_SUFFIX} domain."
        )
    rider_type = _clean(user.rider_type, "Rider type", 50)
    pass_type = _clean(user.pass_type, "Pass type", 100)
    skill_level = _clean(user.skill_level, "Skill level", 50)
    home_state = _clean(user.home_state, "Home state", 50)
    return DevelopmentUserInput(
        first_name,
        last_name,
        email,
        rider_type,
        pass_type,
        skill_level,
        home_state,
    )


def _public_table_names(cursor: Any) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return tuple(row[0] for row in cursor.fetchall())


def _table_counts(cursor: Any, table_names: Sequence[str]) -> dict[str, int]:
    return {
        table_name: cursor.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))
        )
        or cursor.fetchone()[0]
        for table_name in table_names
    }


def _verify_created_user(
    cursor: Any,
    user: DevelopmentUserInput,
    user_id: int,
    password: str,
    table_names: Sequence[str],
    before_counts: Mapping[str, int],
) -> None:
    cursor.execute(
        """
        SELECT first_name, last_name, email, password_hash, auth_provider,
               rider_types, pass_type, skill_level, home_state,
               lifecycle_stage, onboarding_completed_at, profile_completed_at,
               is_seeded, is_verified, push_notifications_enabled,
               email_opt_in, email_transactional, email_social, email_digest,
               discoverable_in_friend_search
        FROM "user"
        WHERE id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise DevelopmentUserError("Created development user could not be verified.")
    (
        first_name,
        last_name,
        email,
        password_hash,
        auth_provider,
        rider_types,
        pass_type,
        skill_level,
        home_state,
        lifecycle_stage,
        onboarding_completed_at,
        profile_completed_at,
        is_seeded,
        is_verified,
        push_notifications_enabled,
        email_opt_in,
        email_transactional,
        email_social,
        email_digest,
        discoverable_in_friend_search,
    ) = row
    if (
        (first_name, last_name, email) != (user.first_name, user.last_name, user.email)
        or not password_hash
        or password_hash == password
        or auth_provider != "email"
        or rider_types != [user.rider_type]
        or (pass_type, skill_level, home_state) != (
            user.pass_type,
            user.skill_level,
            user.home_state,
        )
        or lifecycle_stage != "active"
        or onboarding_completed_at is None
        or profile_completed_at is None
        or not is_seeded
        or not is_verified
        or push_notifications_enabled
        or email_opt_in
        or email_transactional
        or email_social
        or email_digest
        or discoverable_in_friend_search
    ):
        raise DevelopmentUserError("Created development user failed verification.")

    cursor.execute(
        "SELECT count(*) FROM \"user\" WHERE email = %s",
        (user.email,),
    )
    if cursor.fetchone()[0] != 1:
        raise DevelopmentUserError("Development email does not identify exactly one user.")

    current_counts = _table_counts(cursor, table_names)
    changed_tables = {
        table: (before_counts[table], current_counts[table])
        for table in table_names
        if before_counts[table] != current_counts[table]
    }
    if changed_tables != {"user": (before_counts["user"], before_counts["user"] + 1)}:
        raise DevelopmentUserError(
            "Unexpected table changes detected while creating the development user."
        )


def create_development_user(
    user: DevelopmentUserInput,
    password: str,
    *,
    environ: Mapping[str, str] | None = None,
    connection_factory: Callable[[str], Any] = psycopg2.connect,
) -> DevelopmentUserResult:
    """Create and verify one guarded development user in one transaction."""
    try:
        configuration = resolve_development_user_database_config(environ)
    except RuntimeConfigurationError as exc:
        raise DevelopmentUserError(str(exc)) from exc

    user = validate_user_input(user)
    if not password or len(password) < 8:
        raise DevelopmentUserError("Password must be at least 8 characters.")
    password_hash = generate_password_hash(password)
    connection = None
    try:
        connection = connection_factory(configuration.database_url)
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
            cursor.execute('LOCK TABLE "user" IN SHARE ROW EXCLUSIVE MODE')
            table_names = _public_table_names(cursor)
            before_counts = _table_counts(cursor, table_names)
            cursor.execute(
                'SELECT id, email FROM "user" ORDER BY id FOR UPDATE',
            )
            existing_users = cursor.fetchall()
            existing_for_email = next(
                (row for row in existing_users if row[1] == user.email),
                None,
            )
            if existing_for_email:
                connection.rollback()
                return DevelopmentUserResult(
                    created=False,
                    user_id=existing_for_email[0],
                    email=user.email,
                    verified=True,
                    message="Development email already exists; password was not changed.",
                )
            if existing_users:
                raise DevelopmentUserError(
                    "A development user already exists; this one-time creator "
                    "will not create another account."
                )
            now = datetime.utcnow()
            cursor.execute(
                """
                INSERT INTO "user" (
                    first_name, last_name, email, password_hash, auth_provider,
                    rider_types, pass_type, skill_level, home_state,
                    lifecycle_stage, onboarding_completed_at, profile_completed_at,
                    is_seeded, is_verified, push_notifications_enabled,
                    email_opt_in, email_transactional, email_social, email_digest,
                    discoverable_in_friend_search, search_first_name,
                    search_last_name, buddy_passes_available
                )
                VALUES (
                    %s, %s, %s, %s, 'email',
                    %s, %s, %s, %s,
                    'active', %s, %s,
                    TRUE, TRUE, FALSE,
                    FALSE, FALSE, FALSE, FALSE,
                    FALSE, %s, %s, TRUE
                )
                RETURNING id
                """,
                (
                    user.first_name,
                    user.last_name,
                    user.email,
                    password_hash,
                    Json([user.rider_type]),
                    user.pass_type,
                    user.skill_level,
                    user.home_state,
                    now,
                    now,
                    user.first_name.casefold(),
                    user.last_name.casefold(),
                ),
            )
            user_id = cursor.fetchone()[0]
            _verify_created_user(
                cursor,
                user,
                user_id,
                password,
                table_names,
                before_counts,
            )
        connection.commit()
        return DevelopmentUserResult(
            created=True,
            user_id=user_id,
            email=user.email,
            verified=True,
            message="Development user created and verified successfully.",
        )
    except DevelopmentUserError:
        if connection:
            connection.rollback()
        raise
    except psycopg2.Error as exc:
        if connection:
            connection.rollback()
        raise DevelopmentUserError(
            "Development-user creation failed and was rolled back."
        ) from exc
    except Exception as exc:
        if connection:
            connection.rollback()
        raise DevelopmentUserError(
            "Development-user creation failed and was rolled back."
        ) from exc
    finally:
        if connection:
            connection.close()


def _prompt(input_fn: Callable[[str], str], label: str) -> str:
    return input_fn(f"{label}: ")


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass.getpass,
) -> int:
    parser = argparse.ArgumentParser(
        description="Create exactly one guarded BaseLodge development user."
    )
    parser.parse_args(argv)
    try:
        # Resolve before collecting inputs so failed guards refuse before any
        # connection and do not unnecessarily solicit account data.
        resolve_development_user_database_config()
        user = DevelopmentUserInput(
            first_name=_prompt(input_fn, "First name"),
            last_name=_prompt(input_fn, "Last name"),
            email=_prompt(input_fn, "Development email"),
            rider_type=_prompt(input_fn, "Rider type"),
            pass_type=_prompt(input_fn, "Pass type"),
            skill_level=_prompt(input_fn, "Skill level"),
            home_state=_prompt(input_fn, "Home state or province"),
        )
        password = password_fn("Password (hidden): ")
        confirmation = password_fn("Password again (hidden): ")
        if password != confirmation:
            raise DevelopmentUserError("Passwords do not match.")
        result = create_development_user(user, password)
        print(result.message)
        print(f"Email: {result.email}")
        if result.user_id is not None:
            print(f"User ID: {result.user_id}")
        return 0
    except (DevelopmentUserError, RuntimeConfigurationError) as exc:
        print(f"Development user creation refused or failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())