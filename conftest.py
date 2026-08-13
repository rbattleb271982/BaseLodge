"""
conftest.py — project root

Loaded by pytest BEFORE tests/conftest.py is parsed.

WHY MODULE LEVEL:
  Module-level code here executes the instant Python imports this file.
  pytest imports rootdir/conftest.py before tests/conftest.py, so these
  assignments are guaranteed to complete before tests/conftest.py line 30
  (`from app import app, limiter`) runs — and therefore before app.py
  reads SUPABASE_DATABASE_URL to set SQLALCHEMY_DATABASE_URI.

  With SUPABASE_DATABASE_URL="", app.py evaluates:
    is_production = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///baselodge.db"
  All 20 module-level startup migrations then target SQLite, never Supabase.

  These assignments are NOT inside pytest_configure, a fixture, a helper,
  a function, or a class — because any such wrapper executes too late to
  protect application import and startup migrations.
"""

import os

# ── PRIMARY PRE-IMPORT SAFETY GUARD ──────────────────────────────────────────
# MUST remain at module level. Executes before any application code is imported.
os.environ["SUPABASE_DATABASE_URL"] = ""
os.environ["RECOVERED_SUPABASE_DATABASE_URL"] = ""
# ─────────────────────────────────────────────────────────────────────────────

import pytest


@pytest.fixture(scope="session", autouse=True)
def _assert_test_process_is_sqlite():
    """
    Second fail-closed layer: abort the test session if the active
    database engine is not SQLite.

    This fixture fires after application import but before any test
    function executes. It cannot protect the 20 startup migrations
    that run during app.py import — that is the responsibility of the
    module-level os.environ assignments above. This fixture catches any
    scenario where those assignments did not prevent a PostgreSQL engine
    from being cached (e.g. a future code change imports app earlier,
    or another plugin restores the URL before app import).

    db.engine.dialect.name is a Python-side attribute on the already-
    constructed engine object. It does not open a database connection,
    inspect a URL, print credentials, or query any database.
    """
    from app import app, db

    with app.app_context():
        dialect = db.engine.dialect.name
        assert dialect == "sqlite", (
            "SAFETY ABORT [session]: database isolation failed. "
            f"Expected SQLite engine but active dialect is '{dialect}'. "
            "Test session aborted to prevent access to an external database."
        )
