"""Regression protection for mutation-free application startup."""

import ast
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
MAINTENANCE_PATH = PROJECT_ROOT / "scripts" / "run_legacy_maintenance.py"

LEGACY_MUTATOR_NAMES = {
    "run_equipment_migration",
    "run_push_token_migration",
    "run_batch_trip_migration",
    "run_push_notif_pref_migration",
    "run_message_event_log_migration",
    "run_mel_dedupe_index_migration",
    "run_deploy_b_schema_migration",
    "run_ghost_user_cleanup_migration",
    "run_ski_trip_updated_at_migration",
    "run_trip_invite_token_migration",
    "run_pass_system_expansion_migration",
    "run_trip_rsvp_migration",
    "run_mountain_page_view_migration",
    "run_rider_type_normalization_migration",
    "_run_app_store_metric_migration",
    "_run_invite_share_event_migration",
    "run_perf_index_migration",
    "run_ski_trip_notes_migration",
    "run_ski_trip_planning_post_migration",
    "run_friend_discovery_migration",
    "run_participant_pass_migration",
    "_run_pass_mapping_correction_migration",
    "_run_connection_toast_backfill_migration",
}


def _module_level_calls(tree):
    calls = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            return

        def visit_AsyncFunctionDef(self, node):
            return

        def visit_Lambda(self, node):
            return

        def visit_Call(self, node):
            calls.append(node)
            self.generic_visit(node)

    visitor = Visitor()
    for statement in tree.body:
        visitor.visit(statement)
    return calls


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_app_module_has_no_legacy_startup_mutator_invocations():
    tree = ast.parse(APP_PATH.read_text())
    calls = _module_level_calls(tree)
    call_names = {_call_name(call) for call in calls}

    assert not (call_names & LEGACY_MUTATOR_NAMES)
    assert "create_all" not in call_names


def test_application_import_emits_no_persistent_mutation_sql(tmp_path):
    database_path = tmp_path / "startup.db"
    environment = os.environ.copy()
    environment.update(
        {
            "BASELODGE_RUNTIME_ENV": "test",
            "BASELODGE_TEST_DATABASE_URL": f"sqlite:///{database_path}",
            "BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH": "0" * 64,
            "SESSION_SECRET": "test-only",
        }
    )
    environment.pop("BASELODGE_SKIP_STARTUP_MIGRATIONS", None)

    capture_script = r"""
import json
import re
from sqlalchemy import event
from sqlalchemy.engine import Engine

statements = []

def capture(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)

event.listen(Engine, "before_cursor_execute", capture)
import app

forbidden = []
for statement in statements:
    cleaned = re.sub(r"^\s*(?:/\*.*?\*/\s*)*", "", statement, flags=re.S)
    keyword = cleaned.split(None, 1)[0].upper() if cleaned else ""
    if keyword in {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"}:
        forbidden.append(statement)

print(json.dumps({"captured": statements, "forbidden": forbidden}))
"""
    result = subprocess.run(
        [sys.executable, "-c", capture_script],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = result.stdout.strip().splitlines()[-1]
    assert '"forbidden": []' in payload


def test_push_token_maintenance_is_not_reachable_from_startup():
    source = APP_PATH.read_text()
    tree = ast.parse(source)
    calls = _module_level_calls(tree)
    maintenance_source = MAINTENANCE_PATH.read_text()

    assert "run_push_token_migration" not in {
        _call_name(call) for call in calls
    }
    assert "ONESIGNAL_" not in maintenance_source
    assert "import onesignal" not in maintenance_source.lower()
    assert "requests." not in maintenance_source


def test_maintenance_cli_is_dry_run_by_default_and_guards_writes(monkeypatch):
    from scripts import run_legacy_maintenance as maintenance

    dry_run = maintenance._parse_args(["ghost-user-cleanup"])
    assert dry_run.apply is False

    apply_args = maintenance._parse_args(
        ["ghost-user-cleanup", "--apply", "--confirm", "ghost-user-cleanup"]
    )
    monkeypatch.delenv("BASELODGE_MAINTENANCE_WRITE_MODE", raising=False)
    with pytest.raises(
        maintenance.RuntimeConfigurationError,
        match="MAINTENANCE_WRITE_MODE",
    ):
        maintenance._validate_write_authorization(apply_args)

    monkeypatch.setenv("BASELODGE_MAINTENANCE_WRITE_MODE", "1")
    wrong_confirmation = maintenance._parse_args(
        ["ghost-user-cleanup", "--apply", "--confirm", "wrong"]
    )
    with pytest.raises(
        maintenance.RuntimeConfigurationError,
        match="--confirm ghost-user-cleanup",
    ):
        maintenance._validate_write_authorization(wrong_confirmation)