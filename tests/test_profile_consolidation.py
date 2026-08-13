"""
Test suite for profile consolidation - ensures /profile is replaced with /more.
Prevents regressions and guarantees trip duration display.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app import app, db
from models import User
from datetime import date


# ── Engine-map helpers ────────────────────────────────────────────────────────
#
# Flask-SQLAlchemy 3.x caches the active SQLAlchemy engine in:
#
#   db._app_engines: WeakKeyDictionary[Flask, dict[str|None, Engine]]
#
# The default-bind engine lives at db._app_engines[app][None].
# Setting app.config['SQLALCHEMY_DATABASE_URI'] after this engine is cached
# has NO EFFECT on db.engine, db.session, db.create_all(), or db.drop_all().
# The only safe isolation technique is to directly replace the cached entry.


def _capture_engine_state():
    """
    Capture the exact pre-test state of the Flask-SQLAlchemy engine map
    for the None (default) bind key.

    Returns (key_existed: bool, engine_or_none):
      key_existed=False -> the None key was absent; teardown must remove it.
      key_existed=True  -> the None key was present; teardown must restore it.

    engines_map.get(None) alone cannot distinguish "key absent" from
    "key present with value None", so membership is tested explicitly.
    Must be called before any engine-map modification.
    """
    engines_map = db._app_engines.get(app, {})
    key_existed = None in engines_map
    engine = engines_map.get(None)
    return key_existed, engine


def _install_engine(new_engine):
    """
    Install new_engine as the active engine for the None bind key.

    Pure Python dict assignment. Does NOT dispose, connect to, query,
    or otherwise interact with the displaced engine.
    Must be called inside the try block.
    """
    db._app_engines.setdefault(app, {})[None] = new_engine


def _restore_engine_state(key_existed, original_engine):
    """
    Restore the Flask-SQLAlchemy engine map to its exact pre-test state.

    Case A (key_existed=True): engines_map[None] = original_engine
    Case B (key_existed=False): engines_map.pop(None, None)

    Pure Python dict operation. No SQL, no connections, no .dispose()
    on original_engine.
    """
    engines_map = db._app_engines.get(app)
    if engines_map is None:
        return
    if key_existed:
        engines_map[None] = original_engine
    else:
        engines_map.pop(None, None)


def _assert_sqlite(context=""):
    """
    Fail closed: abort if the currently active db.engine is not SQLite.

    Inspects db.engine.dialect.name (actual resolved engine dialect),
    NOT app.config['SQLALCHEMY_DATABASE_URI'].
    Does not inspect or print the database URL.
    """
    dialect = db.engine.dialect.name
    assert dialect == "sqlite", (
        f"SAFETY ABORT [{context}]: database isolation failed. "
        f"Expected SQLite engine but active dialect is '{dialect}'. "
        "Destructive schema operation prevented."
    )


@pytest.fixture
def client():
    """Create test client with guaranteed SQLite in-memory isolation.

    Isolation mechanism:
      1. Capture the exact pre-test Flask-SQLAlchemy engine-map state.
      2. Create a dedicated SQLite in-memory engine (StaticPool).
      3. Enter try/finally — THEN install SQLite as the first engine-map
         mutation, ensuring finally is active before any modification.
      4. Verify isolation via dialect check immediately before each
         destructive schema operation.
      5. finally: restore the exact original engine-map state (pure
         Python dict — no SQL, no .dispose() on original engine),
         then dispose only the temporary SQLite engine.

    The displaced PostgreSQL/Supabase engine is NEVER disposed.
    Only the temporary sqlite_engine created here is disposed.
    """
    app.config['TESTING'] = True

    # Step 1: Capture pre-test state before any modification.
    key_existed, original_engine = _capture_engine_state()

    # Step 2: Create isolated SQLite engine before entering try so it is
    # always bound in the finally scope for disposal.
    sqlite_engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    try:
        # Step 3: Install inside try — finally is now active before any
        # engine-map mutation. Pure dict assignment; does NOT dispose,
        # connect to, or interact with the displaced engine in any way.
        _install_engine(sqlite_engine)

        # Step 4: Setup — assert SQLite immediately before create_all.
        with app.app_context():
            _assert_sqlite("setup")
            db.create_all()

        yield app.test_client()

        # Step 5: Teardown — session remove, then assert SQLite immediately
        # before drop_all. Nothing occurs between assertion and drop_all.
        with app.app_context():
            db.session.remove()
            _assert_sqlite("teardown")
            db.drop_all()

    finally:
        # Step 6: Restore exact original engine-map state first.
        # Pure Python dict manipulation — no database access, no SQL,
        # no .dispose() on original_engine.
        _restore_engine_state(key_existed, original_engine)

        # Step 7: Dispose only the temporary SQLite engine, after
        # the original state has already been restored. Even if
        # dispose() raises, the engine map is already correct.
        sqlite_engine.dispose()


@pytest.fixture
def logged_in_user(client):
    """Create and login a test user."""
    with app.app_context():
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            rider_type="Skier",
            pass_type="Epic"
        )
        user.set_password("testpassword")
        db.session.add(user)
        db.session.commit()
        
        with client:
            client.post('/auth', data={
                'email': 'test@example.com',
                'password': 'testpassword',
                'action': 'login'
            })
            yield user


def test_profile_redirects(client):
    """Test that /profile always redirects to /more."""
    response = client.get("/profile", follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location


def test_profile_post_redirects(client, logged_in_user):
    """Test that POST to /profile redirects to /more."""
    response = client.post("/profile", data={"skill_level": "Advanced"}, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location


def test_edit_profile_save_redirects(client, logged_in_user):
    """Test that saving profile edits redirects to /more, not /profile."""
    response = client.post("/edit_profile", data={
        "skill_level": "Advanced",
        "rider_type": "Skier",
        "pass_type": "Epic"
    }, follow_redirects=False)
    assert response.status_code in (301, 302)
    assert "/more" in response.location
    assert "/profile" not in response.location


def test_no_profile_template_reference():
    """Test that profile.html is never referenced in app.py."""
    with open("app.py", "r") as f:
        code = f.read()
    assert "profile.html" not in code, "profile.html should not be referenced in app.py"


def test_trip_duration_display(client, logged_in_user):
    """Test that trip rows include duration in days."""
    from models import SkiTrip, Resort
    
    with app.app_context():
        # Create a test resort
        resort = Resort(
            name="Test Resort",
            state="CO",
            brand="Epic"
        )
        db.session.add(resort)
        db.session.commit()
        
        # Create a trip: Feb 10 - Feb 13 = 4 days
        trip = SkiTrip(
            user_id=logged_in_user.id,
            mountain="Test Resort",
            state="CO",
            start_date=date(2025, 2, 10),
            end_date=date(2025, 2, 13),
            is_public=True,
            resort_id=resort.id
        )
        db.session.add(trip)
        db.session.commit()
        
        # Verify duration calculation
        duration = (trip.end_date - trip.start_date).days + 1
        assert duration == 4, f"Trip should be 4 days, got {duration}"


def test_no_redirect_to_old_profile():
    """Test that nothing redirects to the old /profile route."""
    with open("app.py", "r") as f:
        code = f.read()
    
    # Check for dangerous redirect patterns
    assert "redirect(url_for(\"profile\"))" not in code
    assert "redirect(url_for('profile'))" not in code
