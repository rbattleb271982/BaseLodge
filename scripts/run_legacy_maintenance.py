#!/usr/bin/env python3
"""Explicit, guarded replacements for retired startup data maintenance.

This module intentionally does not import app.py, Flask, application models,
push providers, or OneSignal. Commands are dry-run by default and require both
BASELODGE_MAINTENANCE_WRITE_MODE=1 and an operation-name confirmation to write.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sys

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_config import (  # noqa: E402
    RuntimeConfigurationError,
    resolve_maintenance_database_config,
)
from services.search_utils import normalize_for_search  # noqa: E402


ADVISORY_LOCK_KEY = 31720260821
CONNECTION_TOAST_CUTOFF = datetime(2026, 8, 15)


@dataclass(frozen=True)
class OperationResult:
    operation: str
    details: dict


def _scalar(cursor, query, params=()):
    cursor.execute(query, params)
    return cursor.fetchone()[0]


def _normalize_rider_types(raw):
    canonical = {
        "skier": "Skier",
        "snowboarder": "Snowboarder",
        "telemark": "Telemark",
        "cross-country": "Cross-Country",
        "adaptive": "Adaptive",
        "interested": "Interested",
        "social": "Social",
        "social / après": "Social",
        "social (along for the ride)": "Social",
        "both": "Skier",
    }
    if raw is None:
        return raw
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list):
        return raw
    tokens = [
        token.strip()
        for value in values
        if value
        for token in str(value).split(",")
        if token.strip()
    ]
    if not tokens:
        return raw
    mapped = [canonical.get(token.lower(), token) for token in tokens]
    non_social = [token for token in mapped if token != "Social"]
    return [non_social[0] if non_social else mapped[0]]


def _equipment_backfill(cursor, apply):
    primary = _scalar(
        cursor,
        "SELECT count(*) FROM equipment_setup "
        "WHERE slot = 'primary' AND is_primary = FALSE",
    )
    timestamps = _scalar(
        cursor,
        "SELECT count(*) FROM equipment_setup WHERE created_at IS NULL",
    )
    if apply:
        cursor.execute(
            "UPDATE equipment_setup SET is_primary = TRUE "
            "WHERE slot = 'primary' AND is_primary = FALSE"
        )
        cursor.execute(
            "UPDATE equipment_setup SET created_at = NOW() WHERE created_at IS NULL"
        )
    return OperationResult(
        "equipment-backfill",
        {"primary_rows": primary, "created_at_rows": timestamps},
    )


def _push_sandbox_tokens(cursor, apply, token_ids):
    requested_ids = sorted(set(token_ids or []))
    if apply and not requested_ids:
        raise RuntimeConfigurationError(
            "push-sandbox-tokens requires at least one reviewed --token-id "
            "when used with --apply."
        )

    where_clause = "WHERE id = ANY(%s)" if requested_ids else ""
    parameters = (requested_ids,) if requested_ids else ()
    cursor.execute(
        "SELECT id, user_id, platform, active, apns_environment, "
        "created_at, updated_at FROM push_device_token "
        f"{where_clause} ORDER BY id",
        parameters,
    )
    candidates = [
        {
            "id": row[0],
            "user_id": row[1],
            "platform": row[2],
            "active": row[3],
            "apns_environment": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }
        for row in cursor.fetchall()
    ]
    found_ids = {candidate["id"] for candidate in candidates}
    missing_ids = sorted(set(requested_ids) - found_ids)
    if apply and missing_ids:
        raise RuntimeConfigurationError(
            "Reviewed push token IDs no longer exist: "
            + ", ".join(str(token_id) for token_id in missing_ids)
        )
    if apply:
        cursor.execute(
            "UPDATE push_device_token "
            "SET active = FALSE, apns_environment = 'sandbox' "
            "WHERE id = ANY(%s) "
            "AND (active IS DISTINCT FROM FALSE "
            "OR apns_environment IS DISTINCT FROM 'sandbox')",
            (requested_ids,),
        )
    return OperationResult(
        "push-sandbox-tokens",
        {
            "review_scope": "selected" if requested_ids else "all",
            "requested_ids": requested_ids,
            "missing_ids": missing_ids,
            "candidate_count": len(candidates),
            "candidates": candidates,
        },
    )


def _ghost_user_cleanup(cursor, apply):
    queries = {
        "friend_missing_user": (
            'SELECT count(*) FROM friend f LEFT JOIN "user" u ON u.id=f.user_id '
            "WHERE u.id IS NULL"
        ),
        "friend_missing_friend": (
            'SELECT count(*) FROM friend f LEFT JOIN "user" u ON u.id=f.friend_id '
            "WHERE u.id IS NULL"
        ),
        "invitation_missing_sender": (
            'SELECT count(*) FROM invitation i LEFT JOIN "user" u '
            "ON u.id=i.sender_id WHERE u.id IS NULL"
        ),
        "invitation_missing_receiver": (
            'SELECT count(*) FROM invitation i LEFT JOIN "user" u '
            "ON u.id=i.receiver_id WHERE u.id IS NULL"
        ),
    }
    details = {name: _scalar(cursor, query) for name, query in queries.items()}
    if apply:
        cursor.execute(
            'DELETE FROM friend WHERE user_id NOT IN (SELECT id FROM "user")'
        )
        cursor.execute(
            'DELETE FROM friend WHERE friend_id NOT IN (SELECT id FROM "user")'
        )
        cursor.execute(
            'DELETE FROM invitation WHERE sender_id NOT IN (SELECT id FROM "user")'
        )
        cursor.execute(
            'DELETE FROM invitation WHERE receiver_id NOT IN (SELECT id FROM "user")'
        )
    return OperationResult("ghost-user-cleanup", details)


def _rider_type_normalization(cursor, apply):
    cursor.execute(
        'SELECT id, rider_types FROM "user" '
        "WHERE rider_types IS NOT NULL ORDER BY id"
    )
    changes = []
    for user_id, current in cursor.fetchall():
        normalized = _normalize_rider_types(current)
        if normalized != current:
            changes.append((user_id, normalized))
    if apply:
        for user_id, normalized in changes:
            cursor.execute(
                'UPDATE "user" SET rider_types = %s WHERE id = %s',
                (Json(normalized), user_id),
            )
    return OperationResult(
        "rider-type-normalization",
        {"candidate_count": len(changes), "user_ids": [row[0] for row in changes]},
    )


def _friend_search_backfill(cursor, apply):
    cursor.execute(
        'SELECT id, first_name, last_name FROM "user" '
        "WHERE search_first_name IS NULL OR search_last_name IS NULL "
        "ORDER BY id"
    )
    changes = [
        (
            user_id,
            normalize_for_search(first_name or ""),
            normalize_for_search(last_name or ""),
        )
        for user_id, first_name, last_name in cursor.fetchall()
    ]
    if apply:
        for user_id, first_name, last_name in changes:
            cursor.execute(
                'UPDATE "user" SET search_first_name=%s, search_last_name=%s '
                "WHERE id=%s",
                (first_name, last_name, user_id),
            )
    return OperationResult(
        "friend-search-backfill",
        {"candidate_count": len(changes), "user_ids": [row[0] for row in changes]},
    )


def _pass_system_backfill(cursor, apply):
    details = {
        "legacy_epic_users": _scalar(
            cursor, 'SELECT count(*) FROM "user" WHERE pass_type = %s', ("Epic",)
        ),
        "legacy_not_sure_users": _scalar(
            cursor, 'SELECT count(*) FROM "user" WHERE pass_type = %s', ("Not Sure",)
        ),
        "missing_indy_rows": _scalar(
            cursor,
            "SELECT count(*) FROM resort r WHERE r.pass_brands LIKE '%Indy%' "
            "AND NOT EXISTS (SELECT 1 FROM resort_pass rp "
            "WHERE rp.resort_id=r.id AND rp.pass_name='Indy')",
        ),
        "missing_mountain_collective_rows": _scalar(
            cursor,
            "SELECT count(*) FROM resort r "
            "WHERE r.pass_brands LIKE '%MountainCollective%' "
            "AND NOT EXISTS (SELECT 1 FROM resort_pass rp "
            "WHERE rp.resort_id=r.id AND rp.pass_name='MountainCollective')",
        ),
    }
    if apply:
        cursor.execute(
            'UPDATE "user" SET pass_type=%s WHERE pass_type=%s', ("epic", "Epic")
        )
        cursor.execute(
            'UPDATE "user" SET pass_type=%s WHERE pass_type=%s',
            ("no_pass_yet", "Not Sure"),
        )
        for label, pattern in (
            ("Indy", "%Indy%"),
            ("MountainCollective", "%MountainCollective%"),
        ):
            cursor.execute(
                "INSERT INTO resort_pass "
                "(resort_id, pass_name, is_primary, created_at) "
                "SELECT r.id, %s, FALSE, NOW() FROM resort r "
                "WHERE r.pass_brands LIKE %s "
                "AND NOT EXISTS (SELECT 1 FROM resort_pass rp "
                "WHERE rp.resort_id=r.id AND rp.pass_name=%s)",
                (label, pattern, label),
            )
    return OperationResult("pass-system-backfill", details)


def _trip_rsvp_repair(cursor, apply):
    details = {
        "accepted_rows": _scalar(
            cursor,
            "SELECT count(*) FROM ski_trip_participant WHERE status='accepted'",
        ),
        "invited_rows": _scalar(
            cursor,
            "SELECT count(*) FROM ski_trip_participant WHERE status='invited'",
        ),
        "owner_rows_to_repair": _scalar(
            cursor,
            "SELECT count(*) FROM ski_trip_participant stp "
            "JOIN ski_trip st ON st.id=stp.trip_id AND st.user_id=stp.user_id "
            "WHERE stp.role <> 'owner' "
            "OR stp.status NOT IN ('interested','going')",
        ),
        "owner_rows_to_insert": _scalar(
            cursor,
            "SELECT count(*) FROM ski_trip st WHERE NOT EXISTS "
            "(SELECT 1 FROM ski_trip_participant stp "
            "WHERE stp.trip_id=st.id AND stp.user_id=st.user_id)",
        ),
    }
    if apply:
        cursor.execute(
            "UPDATE ski_trip_participant SET status='interested' "
            "WHERE status='accepted'"
        )
        cursor.execute(
            "UPDATE ski_trip_participant SET status='pending' "
            "WHERE status='invited'"
        )
        cursor.execute(
            "UPDATE ski_trip_participant stp SET role='owner', "
            "status=CASE WHEN stp.status IN ('interested','going') "
            "THEN stp.status ELSE 'interested' END "
            "FROM ski_trip st WHERE st.id=stp.trip_id "
            "AND st.user_id=stp.user_id "
            "AND (stp.role <> 'owner' "
            "OR stp.status NOT IN ('interested','going'))"
        )
        cursor.execute(
            "INSERT INTO ski_trip_participant "
            "(trip_id,user_id,status,role,created_at) "
            "SELECT st.id,st.user_id,'interested','owner',CURRENT_TIMESTAMP "
            "FROM ski_trip st WHERE NOT EXISTS "
            "(SELECT 1 FROM ski_trip_participant stp "
            "WHERE stp.trip_id=st.id AND stp.user_id=st.user_id)"
        )
    return OperationResult("trip-rsvp-repair", details)


def _participant_pass_backfill(cursor, apply):
    query = (
        "SELECT count(*) FROM ski_trip_participant stp "
        "JOIN ski_trip st ON st.id=stp.trip_id "
        "WHERE stp.role='owner' AND st.pass_type IS NOT NULL "
        "AND st.pass_type NOT IN ('','No Pass') AND stp.pass_type IS NULL"
    )
    candidates = _scalar(cursor, query)
    if apply:
        cursor.execute(
            "UPDATE ski_trip_participant stp SET pass_type=st.pass_type "
            "FROM ski_trip st WHERE stp.trip_id=st.id AND stp.role='owner' "
            "AND st.pass_type IS NOT NULL AND st.pass_type NOT IN ('','No Pass') "
            "AND stp.pass_type IS NULL"
        )
    return OperationResult(
        "participant-pass-backfill", {"candidate_count": candidates}
    )


def _connection_toast_backfill(cursor, apply):
    params = (CONNECTION_TOAST_CUTOFF,)
    query = (
        "SELECT count(*) FROM activity a "
        "WHERE a.type='connection_accepted' AND a.created_at < %s "
        "AND NOT EXISTS (SELECT 1 FROM dismissed_insight_card d "
        "WHERE d.user_id=a.recipient_user_id "
        "AND d.card_type='connection_accepted' "
        "AND d.card_key=CAST(a.id AS VARCHAR))"
    )
    candidates = _scalar(cursor, query, params)
    if apply:
        cursor.execute(
            "INSERT INTO dismissed_insight_card "
            "(user_id,card_type,card_key,dismissed_at) "
            "SELECT a.recipient_user_id,'connection_accepted',"
            "CAST(a.id AS VARCHAR),NOW() FROM activity a "
            "WHERE a.type='connection_accepted' AND a.created_at < %s "
            "AND NOT EXISTS (SELECT 1 FROM dismissed_insight_card d "
            "WHERE d.user_id=a.recipient_user_id "
            "AND d.card_type='connection_accepted' "
            "AND d.card_key=CAST(a.id AS VARCHAR))",
            params,
        )
    return OperationResult(
        "connection-toast-backfill", {"candidate_count": candidates}
    )


def _load_pass_mapping_spec(path):
    if path is None:
        raise RuntimeConfigurationError(
            "--spec-file is required for pass-mapping-correction"
        )
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, list) or not raw:
        raise RuntimeConfigurationError(
            "Pass-mapping specification must be a non-empty JSON list."
        )
    allowed_keys = {"slug", "remove", "add", "remove_other"}
    slugs = set()
    for item in raw:
        if not isinstance(item, dict) or not item.get("slug"):
            raise RuntimeConfigurationError(
                "Every pass-mapping item requires a resort slug."
            )
        if set(item) - allowed_keys:
            raise RuntimeConfigurationError(
                "Pass-mapping item contains an unsupported field."
            )
        if not item.get("remove") and not item.get("add"):
            raise RuntimeConfigurationError(
                "Every pass-mapping item requires remove or add."
            )
        if item["slug"] in slugs:
            raise RuntimeConfigurationError(
                f"Duplicate pass-mapping slug: {item['slug']}"
            )
        if any(
            value is not None and not isinstance(value, str)
            for value in (item.get("remove"), item.get("add"))
        ):
            raise RuntimeConfigurationError(
                "Pass-mapping remove and add values must be strings."
            )
        if "remove_other" in item and not isinstance(item["remove_other"], bool):
            raise RuntimeConfigurationError(
                "Pass-mapping remove_other value must be a boolean."
            )
        slugs.add(item["slug"])
    return raw


def _pass_mapping_correction(cursor, apply, spec_file):
    spec = _load_pass_mapping_spec(spec_file)
    details = {
        "specified_resorts": len(spec),
        "missing_slugs": [],
        "pass_rows_to_add": 0,
        "pass_rows_to_remove": 0,
        "json_rows_to_sync": 0,
    }
    resolved = []
    for item in spec:
        cursor.execute(
            "SELECT id, pass_brands_json FROM resort WHERE slug=%s",
            (item["slug"],),
        )
        row = cursor.fetchone()
        if row is None:
            details["missing_slugs"].append(item["slug"])
            continue
        resolved.append((item, row[0], row[1] or []))

    if apply and details["missing_slugs"]:
        raise RuntimeConfigurationError(
            "Pass-mapping apply refused because reviewed resort slugs are "
            "missing: " + ", ".join(details["missing_slugs"])
        )

    for item, resort_id, current_json in resolved:
        cursor.execute(
            "SELECT pass_name FROM resort_pass WHERE resort_id=%s",
            (resort_id,),
        )
        existing = {row[0] for row in cursor.fetchall()}
        remove = item.get("remove")
        add = item.get("add")
        removals = {
            pass_name
            for pass_name in (
                remove,
                "Other" if item.get("remove_other") else None,
            )
            if pass_name and pass_name in existing
        }
        after_removals = existing - removals
        should_add = bool(add and add not in after_removals)
        final_names = set(after_removals)
        if add:
            final_names.add(add)
        final_json = sorted(name for name in final_names if name != "Other")

        details["pass_rows_to_remove"] += len(removals)
        details["pass_rows_to_add"] += int(should_add)
        details["json_rows_to_sync"] += int(
            set(current_json) != set(final_json)
        )

        if not apply:
            continue
        for pass_name in removals:
            cursor.execute(
                "DELETE FROM resort_pass WHERE resort_id=%s AND pass_name=%s",
                (resort_id, pass_name),
            )
        if should_add:
            is_primary = not any(name != "Other" for name in after_removals)
            cursor.execute(
                "INSERT INTO resort_pass "
                "(resort_id,pass_name,is_primary,created_at) "
                "VALUES (%s,%s,%s,NOW())",
                (resort_id, add, is_primary),
            )
        if set(current_json) != set(final_json):
            cursor.execute(
                "UPDATE resort SET pass_brands_json=%s WHERE id=%s",
                (Json(final_json), resort_id),
            )
    return OperationResult("pass-mapping-correction", details)


OPERATIONS = {
    "equipment-backfill": _equipment_backfill,
    "push-sandbox-tokens": _push_sandbox_tokens,
    "ghost-user-cleanup": _ghost_user_cleanup,
    "rider-type-normalization": _rider_type_normalization,
    "friend-search-backfill": _friend_search_backfill,
    "pass-system-backfill": _pass_system_backfill,
    "trip-rsvp-repair": _trip_rsvp_repair,
    "participant-pass-backfill": _participant_pass_backfill,
    "connection-toast-backfill": _connection_toast_backfill,
}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Preview or explicitly run retired startup maintenance."
    )
    parser.add_argument(
        "operation",
        choices=sorted([*OPERATIONS, "pass-mapping-correction"]),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        help="Required with --apply; must exactly match the operation name.",
    )
    parser.add_argument(
        "--spec-file",
        help="Reviewed JSON specification for pass-mapping-correction.",
    )
    parser.add_argument(
        "--token-id",
        action="append",
        type=int,
        dest="token_ids",
        help=(
            "Reviewed push token database ID. Repeat for multiple IDs. "
            "Omit during dry-run to report all token metadata without token values."
        ),
    )
    return parser.parse_args(argv)


def _validate_write_authorization(args):
    if not args.apply:
        return
    if os.environ.get("BASELODGE_MAINTENANCE_WRITE_MODE") != "1":
        raise RuntimeConfigurationError(
            "BASELODGE_MAINTENANCE_WRITE_MODE=1 is required with --apply."
        )
    if args.confirm != args.operation:
        raise RuntimeConfigurationError(
            f"--confirm {args.operation} is required with --apply."
        )


def _validate_operation_arguments(args):
    if args.operation == "push-sandbox-tokens":
        if args.apply and not args.token_ids:
            raise RuntimeConfigurationError(
                "push-sandbox-tokens requires at least one reviewed --token-id "
                "when used with --apply."
            )
        if any(token_id <= 0 for token_id in (args.token_ids or [])):
            raise RuntimeConfigurationError("--token-id values must be positive.")
    elif args.token_ids:
        raise RuntimeConfigurationError(
            "--token-id is only valid for push-sandbox-tokens."
        )

    if args.operation == "pass-mapping-correction":
        _load_pass_mapping_spec(args.spec_file)
    elif args.spec_file:
        raise RuntimeConfigurationError(
            "--spec-file is only valid for pass-mapping-correction."
        )


def main(argv=None):
    args = _parse_args(argv)
    try:
        _validate_write_authorization(args)
        _validate_operation_arguments(args)
        configuration = resolve_maintenance_database_config()
    except RuntimeConfigurationError as error:
        print(f"Maintenance configuration error: {error}", file=sys.stderr)
        return 2

    connection = psycopg2.connect(configuration.database_url)
    try:
        connection.autocommit = False
        connection.set_session(readonly=not args.apply)
        with connection.cursor() as cursor:
            if not _scalar(
                cursor,
                "SELECT pg_try_advisory_xact_lock(%s)",
                (ADVISORY_LOCK_KEY,),
            ):
                raise RuntimeError(
                    "Another BaseLodge maintenance operation holds the singleton lock."
                )
            if args.operation == "pass-mapping-correction":
                result = _pass_mapping_correction(
                    cursor, args.apply, args.spec_file
                )
            elif args.operation == "push-sandbox-tokens":
                result = _push_sandbox_tokens(
                    cursor, args.apply, args.token_ids
                )
            else:
                result = OPERATIONS[args.operation](cursor, args.apply)
            payload = {
                "mode": "apply" if args.apply else "dry-run",
                "runtime": configuration.runtime_env,
                "target": configuration.safe_identity,
                "result": result.details,
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        if args.apply:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())