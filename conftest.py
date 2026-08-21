"""
conftest.py — project root

Loaded by pytest BEFORE tests/conftest.py is parsed.

WHY MODULE LEVEL:
  Module-level code here executes the instant Python imports this file.
  pytest imports rootdir/conftest.py before tests/conftest.py, so these
  assignments are guaranteed to complete before tests/conftest.py imports
  app.py. BaseLodge is put in explicit test mode with an isolated SQLite
  database before application configuration can be evaluated.

  These assignments are NOT inside pytest_configure, a fixture, a helper,
  a function, or a class — because any such wrapper executes too late to
  protect application import and startup migrations.
"""

import os

# ── PRIMARY PRE-IMPORT SAFETY GUARD ──────────────────────────────────────────
# MUST remain at module level. Executes before any application code is imported.
os.environ["BASELODGE_RUNTIME_ENV"] = "test"
os.environ["BASELODGE_TEST_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["BASELODGE_PRODUCTION_DATABASE_IDENTITY_HASH"] = "0" * 64
os.environ.pop("BASELODGE_DEVELOPMENT_DATABASE_URL", None)
os.environ.pop("BASELODGE_PRODUCTION_DATABASE_URL", None)
os.environ.pop("BASELODGE_MIGRATION_DATABASE_URL", None)
os.environ.pop("BASELODGE_MIGRATION_MODE", None)
os.environ["SUPABASE_DATABASE_URL"] = ""
os.environ["RECOVERED_SUPABASE_DATABASE_URL"] = ""
os.environ.pop("DATABASE_URL", None)
# ─────────────────────────────────────────────────────────────────────────────

import pytest


@pytest.fixture(scope="session", autouse=True)
def _assert_test_process_is_sqlite():
    """
    Second fail-closed layer: abort the test session if the active database
    engine is not SQLite or the resolved runtime environment is not test.

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
        assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
        assert dialect == "sqlite", (
            "SAFETY ABORT [session]: database isolation failed. "
            f"Expected SQLite engine but active dialect is '{dialect}'. "
            "Test session aborted to prevent access to an external database."
        )
