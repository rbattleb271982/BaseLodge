"""
Test suite for profile settings — guarantees trip duration display.

Note: Tests that asserted /profile redirects to /more or that profile.html
is absent from app.py were removed when /profile became the canonical
Profile/Account screen. Those refactor-guard tests are no longer valid.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool
from datetime import date, datetime
from werkzeug.security import generate_password_hash

from app import app, db
from conftest import _login
from models import User


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
    engines_map = db._app_engines.get(app, {})
    key_existed = None in engines_map
    engine = engines_map.get(None)
    return key_existed, engine


def _install_engine(new_engine):
    db._app_engines.setdefault(app, {})[None] = new_engine


def _restore_engine_state(key_existed, original_engine):
    engines_map = db._app_engines.get(app)
    if engines_map is None:
        return
    if key_existed:
        engines_map[None] = original_engine
    else:
        engines_map.pop(None, None)


def _assert_sqlite(context=""):
    dialect = db.engine.dialect.name
    assert dialect == "sqlite", (
        f"SAFETY ABORT [{context}]: database isolation failed. "
        f"Expected SQLite engine but active dialect is '{dialect}'. "
        "Destructive schema operation prevented."
    )


@pytest.fixture
def client():
    """Create test client with guaranteed SQLite in-memory isolation."""
    app.config['TESTING'] = True
    key_existed, original_engine = _capture_engine_state()
    sqlite_engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        _install_engine(sqlite_engine)
        with app.app_context():
            _assert_sqlite("setup")
            db.create_all()
        yield app.test_client()
        with app.app_context():
            db.session.remove()
            _assert_sqlite("teardown")
            db.drop_all()
    finally:
        _restore_engine_state(key_existed, original_engine)
        sqlite_engine.dispose()


@pytest.fixture
def logged_in_user(client):
    """Create a test user in the current SQLite database."""
    with app.app_context():
        user = User(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            rider_types=["Skier"],
            pass_type="ikon",
            skill_level="Intermediate",
            home_state="CO",
            onboarding_completed_at=datetime.utcnow(),
        )
        user.password_hash = generate_password_hash("testpassword")
        user.lifecycle_stage = "active"
        db.session.add(user)
        db.session.commit()
        yield user


def test_trip_duration_display(client, logged_in_user):
    """Trip duration calculation: (end - start).days + 1 == number of ski days."""
    from models import SkiTrip, Resort

    with app.app_context():
        resort = Resort(
            name="Test Resort",
            slug="test-resort",
            state="CO",
            state_code="CO",
            country_code="US",
            is_active=True,
            is_region=False,
        )
        db.session.add(resort)
        db.session.commit()

        # Feb 10 – Feb 13 inclusive = 4 ski days
        trip = SkiTrip(
            user_id=logged_in_user.id,
            mountain="Test Resort",
            state="CO",
            start_date=date(2025, 2, 10),
            end_date=date(2025, 2, 13),
            is_public=True,
            resort_id=resort.id,
        )
        db.session.add(trip)
        db.session.commit()

        duration = (trip.end_date - trip.start_date).days + 1
        assert duration == 4, f"Trip should be 4 days, got {duration}"


def test_profile_shows_joined_month_and_year_without_day_or_time(client, logged_in_user):
    """Own Profile renders the canonical account date at month/year precision."""
    logged_in_user.created_at = datetime(2025, 3, 14, 16, 27, 9)
    db.session.commit()
    _login(client, logged_in_user.id)

    response = client.get("/profile")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Joined BaseLodge · March 2025" in html
    assert "March 14" not in html
    assert "16:27" not in html
    assert "2025-03-14" not in html


def test_profile_omits_joined_line_when_created_at_is_null(client, logged_in_user):
    """Legacy accounts without a canonical timestamp get no placeholder."""
    logged_in_user.created_at = None
    db.session.commit()
    _login(client, logged_in_user.id)

    response = client.get("/profile")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Joined BaseLodge" not in html
    assert "Unknown" not in html


def test_friend_profile_template_remains_without_joined_account_metadata():
    """BL-82 is intentionally limited to the signed-in user's Profile."""
    from pathlib import Path

    friend_profile_template = Path("templates/friend_profile.html").read_text()
    assert "Joined BaseLodge" not in friend_profile_template
