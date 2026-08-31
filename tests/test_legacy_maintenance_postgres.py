"""Disposable PostgreSQL coverage for guarded legacy maintenance."""

from datetime import date, datetime
import json

import psycopg2

from runtime_config import database_identity_hash
from scripts import run_legacy_maintenance as maintenance
from services.ski_seasons import get_ski_season_start_year
from test_import_reference_data_postgres import (
    _initialized_database,
    disposable_postgres,
)


PRODUCTION_HASH = database_identity_hash(
    "postgresql://prod:secret@production.example:5432/baselodge"
)


def _maintenance_environment(monkeypatch, database_url, *, writes=False):
    monkeypatch.setenv("BASELODGE_RUNTIME_ENV", "test")
    monkeypatch.setenv("BASELODGE_MAINTENANCE_MODE", "1")
    monkeypatch.setenv("BASELODGE_MAINTENANCE_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH", PRODUCTION_HASH
    )
    if writes:
        monkeypatch.setenv("BASELODGE_MAINTENANCE_WRITE_MODE", "1")
    else:
        monkeypatch.delenv("BASELODGE_MAINTENANCE_WRITE_MODE", raising=False)


def _apply(operation, *extra):
    return maintenance.main(
        [operation, "--apply", "--confirm", operation, *extra]
    )


def _seed_maintenance_candidates(database_url):
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO resort "
                    "(name,state,slug,pass_brands_json,is_active) "
                    "VALUES ('Reviewed Mountain','CO','reviewed-mountain',"
                    "%s,TRUE) RETURNING id",
                    (json.dumps(["Other"]),),
                )
                resort_id = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO "user" '
                    "(first_name,last_name,email,search_first_name,"
                    "search_last_name) VALUES "
                    "('José','García','jose@example.test',NULL,NULL) "
                    "RETURNING id"
                )
                user_id = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO "user" (first_name,email) '
                    "VALUES ('Actor','actor@example.test') RETURNING id"
                )
                actor_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO equipment_setup "
                    "(user_id,slot,is_primary,created_at) "
                    "VALUES (%s,'primary',FALSE,NULL)",
                    (user_id,),
                )
                cursor.execute(
                    "INSERT INTO push_device_token "
                    "(user_id,token,platform,active,apns_environment,"
                    "created_at,updated_at) "
                    "VALUES (%s,'never-print-this-token','ios',TRUE,"
                    "'unknown',NOW(),NOW()) RETURNING id",
                    (user_id,),
                )
                token_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO activity "
                    "(actor_user_id,recipient_user_id,type,object_type,"
                    "object_id,created_at) "
                    "VALUES (%s,%s,'connection_accepted','user',%s,%s) "
                    "RETURNING id",
                    (
                        actor_id,
                        user_id,
                        actor_id,
                        datetime(2026, 8, 14),
                    ),
                )
                activity_id = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO resort_pass "
                    "(resort_id,pass_name,is_primary,created_at) "
                    "VALUES (%s,'Other',FALSE,NOW())",
                    (resort_id,),
                )
        return {
            "resort_id": resort_id,
            "user_id": user_id,
            "token_id": token_id,
            "activity_id": activity_id,
        }
    finally:
        connection.close()


def test_dry_runs_do_not_write_and_push_reports_no_token_values(
    disposable_postgres, monkeypatch, capsys
):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "maintenance-dry-run"
    )
    seeded = _seed_maintenance_candidates(database_url)
    _maintenance_environment(monkeypatch, database_url)

    assert maintenance.main(["equipment-backfill"]) == 0
    assert maintenance.main(["push-sandbox-tokens"]) == 0
    output = capsys.readouterr().out
    assert str(seeded["token_id"]) in output
    assert "never-print-this-token" not in output

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_primary,created_at FROM equipment_setup"
            )
            assert cursor.fetchone() == (False, None)
            cursor.execute(
                "SELECT active,apns_environment FROM push_device_token "
                "WHERE id=%s",
                (seeded["token_id"],),
            )
            assert cursor.fetchone() == (True, "unknown")
    finally:
        connection.close()


def test_explicit_apply_preserves_legacy_data_behavior(
    disposable_postgres, monkeypatch, tmp_path
):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "maintenance-apply"
    )
    seeded = _seed_maintenance_candidates(database_url)
    _maintenance_environment(monkeypatch, database_url, writes=True)

    assert _apply("equipment-backfill") == 0
    assert _apply("friend-search-backfill") == 0
    assert _apply("connection-toast-backfill") == 0
    assert _apply(
        "push-sandbox-tokens",
        "--token-id",
        str(seeded["token_id"]),
    ) == 0

    spec_path = tmp_path / "pass-mapping.json"
    spec_path.write_text(
        json.dumps(
            [
                {
                    "slug": "reviewed-mountain",
                    "add": "Ikon",
                    "remove_other": True,
                }
            ]
        )
    )
    assert _apply(
        "pass-mapping-correction", "--spec-file", str(spec_path)
    ) == 0

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_primary,created_at FROM equipment_setup"
            )
            is_primary, created_at = cursor.fetchone()
            assert is_primary is True
            assert created_at is not None

            cursor.execute(
                'SELECT search_first_name,search_last_name FROM "user" '
                "WHERE id=%s",
                (seeded["user_id"],),
            )
            assert cursor.fetchone() == ("jose", "garcia")

            cursor.execute(
                "SELECT user_id,card_type,card_key,dismissed_at "
                "FROM dismissed_insight_card"
            )
            dismissed = cursor.fetchone()
            assert dismissed[:3] == (
                seeded["user_id"],
                "connection_accepted",
                str(seeded["activity_id"]),
            )
            assert dismissed[3] is not None

            cursor.execute(
                "SELECT active,apns_environment FROM push_device_token "
                "WHERE id=%s",
                (seeded["token_id"],),
            )
            assert cursor.fetchone() == (False, "sandbox")

            cursor.execute(
                "SELECT pass_name,is_primary FROM resort_pass "
                "WHERE resort_id=%s",
                (seeded["resort_id"],),
            )
            assert cursor.fetchall() == [("Ikon", True)]
            cursor.execute(
                "SELECT pass_brands_json FROM resort WHERE id=%s",
                (seeded["resort_id"],),
            )
            assert cursor.fetchone()[0] == ["Ikon"]
    finally:
        connection.close()


def test_user_season_pass_backfill_is_guarded_authoritative_and_idempotent(
    disposable_postgres, monkeypatch, capsys
):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "season-pass-backfill"
    )
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO "user" '
                    "(first_name,email,pass_type,previous_pass) "
                    "VALUES ('Current','current-pass@example.test','Epic',"
                    "'Ikon') RETURNING id"
                )
                current_user_id = cursor.fetchone()[0]
                cursor.execute(
                    'INSERT INTO "user" '
                    "(first_name,email,pass_type,previous_pass) "
                    "VALUES ('Previous Only','previous-only@example.test',"
                    "NULL,'Ikon') RETURNING id"
                )
                previous_only_user_id = cursor.fetchone()[0]
    finally:
        connection.close()

    _maintenance_environment(monkeypatch, database_url)
    assert maintenance.main(["user-season-pass-backfill"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["result"]["candidate_count"] == 1
    assert dry_run["result"]["inserted_count"] == 0
    assert dry_run["result"]["historical_seasons_inferred"] == 0

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM user_season_pass")
            assert cursor.fetchone()[0] == 0
    finally:
        connection.close()

    _maintenance_environment(monkeypatch, database_url, writes=True)
    assert _apply("user-season-pass-backfill") == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["result"]["inserted_count"] == 1

    season_start_year = get_ski_season_start_year(date.today())
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT season_start_year,pass_type "
                    "FROM user_season_pass WHERE user_id=%s",
                    (current_user_id,),
                )
                assert cursor.fetchone() == (season_start_year, "epic")
                cursor.execute(
                    "SELECT count(*) FROM user_season_pass WHERE user_id=%s",
                    (previous_only_user_id,),
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    'UPDATE "user" SET pass_type=%s WHERE id=%s',
                    ("ikon", current_user_id),
                )
    finally:
        connection.close()

    assert _apply("user-season-pass-backfill") == 0
    second_apply = json.loads(capsys.readouterr().out)
    assert second_apply["result"]["candidate_count"] == 0
    assert second_apply["result"]["existing_count"] == 1
    assert second_apply["result"]["inserted_count"] == 0

    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*),min(pass_type) FROM user_season_pass "
                "WHERE user_id=%s",
                (current_user_id,),
            )
            assert cursor.fetchone() == (1, "epic")
    finally:
        connection.close()


def test_apply_requires_reviewed_push_ids_before_connecting(monkeypatch):
    _maintenance_environment(
        monkeypatch,
        "postgresql://test@unreachable.example:5432/baselodge",
        writes=True,
    )
    assert _apply("push-sandbox-tokens") == 2