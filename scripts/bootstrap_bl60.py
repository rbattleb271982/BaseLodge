#!/usr/bin/env python3
"""Safely create the reviewed BL-60 schema on an empty PostgreSQL database.

This tool deliberately has no Flask, SQLAlchemy model, or app.py dependency.
It is not a migration runner and never stamps Alembic.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import psycopg2
from psycopg2.extensions import connection as PgConnection

from runtime_config import (
    DatabaseConfiguration,
    RuntimeConfigurationError,
    resolve_bootstrap_database_config,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = ROOT / "bootstrap" / "bl60_schema.sql"
DEFAULT_CONTRACT_PATH = ROOT / "bootstrap" / "bl60_schema_contract.json"
ADVISORY_LOCK_KEY = 6_031_160


class BootstrapError(RuntimeError):
    """Raised when a bootstrap target or resulting schema is unsafe."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError("Bootstrap schema contract is unreadable.") from exc


def _read_schema(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BootstrapError("Bootstrap schema SQL is unreadable.") from exc


def _rows(cursor, statement: str) -> list[dict[str, Any]]:
    cursor.execute(statement)
    columns = [column.name for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _empty_target_error(connection: PgConnection) -> str | None:
    """Return a safe reason when public contains user-created objects."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        if cursor.fetchone()[0]:
            return "alembic_version already exists"

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_class relation
                JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
            )
            """
        )
        if cursor.fetchone()[0]:
            return "target schema contains relations"

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_type type
                JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
                WHERE namespace.nspname = 'public'
                  AND type.typtype IN ('b', 'c', 'd', 'e', 'r')
            )
            """
        )
        if cursor.fetchone()[0]:
            return "target schema contains user-defined types"

        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_proc procedure
                JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'public'
            )
            """
        )
        if cursor.fetchone()[0]:
            return "target schema contains functions"
    return None


def _normalise_default(value: str | None) -> str | None:
    return " ".join(value.split()) if value else None


def catalog(connection: PgConnection) -> dict[str, Any]:
    """Return a stable, reviewable public-schema catalog."""
    with connection.cursor() as cursor:
        enums = _rows(
            cursor,
            """
            SELECT type.typname AS name,
                   json_agg(enum.enumlabel ORDER BY enum.enumsortorder) AS values
            FROM pg_type type
            JOIN pg_enum enum ON enum.enumtypid = type.oid
            JOIN pg_namespace namespace ON namespace.oid = type.typnamespace
            WHERE namespace.nspname = 'public'
            GROUP BY type.typname
            ORDER BY type.typname
            """,
        )
        tables = _rows(
            cursor,
            """
            SELECT relation.relname AS name
            FROM pg_class relation
            JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public' AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """,
        )
        columns = _rows(
            cursor,
            """
            SELECT relation.relname AS table_name,
                   attribute.attname AS name,
                   attribute.attnum AS ordinal,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS type,
                   NOT attribute.attnotnull AS nullable,
                   pg_get_expr(default_value.adbin, default_value.adrelid, true) AS default
            FROM pg_attribute attribute
            JOIN pg_class relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_attrdef default_value
                   ON default_value.adrelid = attribute.attrelid
                  AND default_value.adnum = attribute.attnum
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY relation.relname, attribute.attnum
            """,
        )
        constraints = _rows(
            cursor,
            """
            SELECT relation.relname AS table_name,
                   constraint_row.conname AS name,
                   constraint_row.contype AS kind,
                   pg_get_constraintdef(constraint_row.oid, true) AS definition,
                   CASE constraint_row.confdeltype
                       WHEN 'a' THEN 'NO ACTION'
                       WHEN 'r' THEN 'RESTRICT'
                       WHEN 'c' THEN 'CASCADE'
                       WHEN 'n' THEN 'SET NULL'
                       WHEN 'd' THEN 'SET DEFAULT'
                       ELSE NULL
                   END AS on_delete
            FROM pg_constraint constraint_row
            JOIN pg_class relation ON relation.oid = constraint_row.conrelid
            JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND constraint_row.contype IN ('p', 'u', 'c', 'f')
            ORDER BY relation.relname, constraint_row.contype, constraint_row.conname
            """,
        )
        indexes = _rows(
            cursor,
            """
            SELECT table_relation.relname AS table_name,
                   index_relation.relname AS name,
                   index_info.indisunique AS unique,
                   pg_get_indexdef(index_info.indexrelid) AS definition,
                   pg_get_expr(index_info.indpred, index_info.indrelid, true) AS predicate
            FROM pg_index index_info
            JOIN pg_class index_relation ON index_relation.oid = index_info.indexrelid
            JOIN pg_class table_relation ON table_relation.oid = index_info.indrelid
            JOIN pg_namespace namespace ON namespace.oid = table_relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND NOT index_info.indisprimary
              AND NOT EXISTS (
                  SELECT 1
                  FROM pg_constraint constraint_row
                  WHERE constraint_row.conindid = index_info.indexrelid
              )
            ORDER BY table_relation.relname, index_relation.relname
            """,
        )

    tables_by_name = {
        row["name"]: {
            "name": row["name"],
            "columns": [],
            "primary_key": None,
            "unique_constraints": [],
            "check_constraints": [],
            "foreign_keys": [],
            "indexes": [],
        }
        for row in tables
    }
    for row in columns:
        row["default"] = _normalise_default(row["default"])
        tables_by_name[row.pop("table_name")]["columns"].append(
            [
                row["ordinal"],
                row["name"],
                row["type"],
                row["nullable"],
                row["default"],
            ]
        )
    for row in constraints:
        table = tables_by_name[row.pop("table_name")]
        row["definition"] = _normalise_default(row["definition"])
        kind = row.pop("kind")
        if kind == "p":
            table["primary_key"] = [row["name"], row["definition"]]
        elif kind == "u":
            table["unique_constraints"].append([row["name"], row["definition"]])
        elif kind == "c":
            table["check_constraints"].append([row["name"], row["definition"]])
        else:
            table["foreign_keys"].append(
                [row["name"], row["definition"], row["on_delete"]]
            )
    for row in indexes:
        tables_by_name[row.pop("table_name")]["indexes"].append(
            [
                row["name"],
                row["unique"],
                _normalise_default(row["definition"]),
                row["predicate"],
            ]
        )

    return {
        "contract_version": "bl60_mtn_filter_edu",
        "normalization": {
            "defaults": "Whitespace-only differences are normalized.",
            "generated_names": "Names are retained because they are application-visible.",
        },
        "enums": [[row["name"], row["values"]] for row in enums],
        "tables": [tables_by_name[name] for name in sorted(tables_by_name)],
    }


def assert_catalog_matches(connection: PgConnection, contract_path: Path) -> None:
    expected = _read_json(contract_path)
    actual = catalog(connection)
    if actual != expected:
        raise BootstrapError(
            "Bootstrap schema does not match the reviewed BL-60 catalog contract."
        )


def _connect(configuration: DatabaseConfiguration) -> PgConnection:
    try:
        connection = psycopg2.connect(configuration.database_url)
    except psycopg2.Error as exc:
        raise BootstrapError("Unable to connect to the guarded bootstrap target.") from exc
    connection.autocommit = False
    return connection


def bootstrap(
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> None:
    """Apply and verify the schema, committing only after exact catalog parity."""
    try:
        configuration = resolve_bootstrap_database_config()
    except RuntimeConfigurationError as exc:
        raise BootstrapError(str(exc)) from exc

    schema_sql = _read_schema(schema_path)
    _read_json(contract_path)
    connection = _connect(configuration)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
        unsafe_reason = _empty_target_error(connection)
        if unsafe_reason:
            raise BootstrapError(f"Bootstrap refused: {unsafe_reason}.")

        with connection.cursor() as cursor:
            cursor.execute(schema_sql)
        assert_catalog_matches(connection, contract_path)
        connection.commit()
    except BootstrapError:
        connection.rollback()
        raise
    except psycopg2.Error as exc:
        connection.rollback()
        raise BootstrapError(
            "Bootstrap transaction failed and was rolled back."
        ) from exc
    finally:
        connection.close()


def main() -> int:
    try:
        bootstrap()
    except BootstrapError as exc:
        print(f"BL-60 bootstrap refused or failed: {exc}", file=sys.stderr)
        return 1
    print("BL-60 bootstrap completed and matched the reviewed catalog contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())