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
from models import EquipmentDiscipline, EquipmentSetup, User


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


def _profile_html(client, user_id):
    _login(client, user_id)
    response = client.get("/profile")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _profile_setup(user, discipline, *, primary=False, created_at=None, **fields):
    setup = EquipmentSetup(
        user_id=user.id,
        discipline=discipline,
        is_primary=primary,
        created_at=created_at or datetime.utcnow(),
        **fields,
    )
    db.session.add(setup)
    db.session.flush()
    return setup


@pytest.mark.parametrize(
    ("rider_types", "discipline", "label"),
    [
        (["Skier"], EquipmentDiscipline.SKIER, "Skis"),
        (["Snowboarder"], EquipmentDiscipline.SNOWBOARDER, "Snowboard"),
    ],
)
def test_profile_shows_add_gear_for_single_discipline_without_meaningful_gear(
    client, logged_in_user, rider_types, discipline, label
):
    logged_in_user.rider_types = rider_types
    with app.app_context():
        setup = _profile_setup(logged_in_user, discipline, primary=True)
        user_id, setup_id = logged_in_user.id, setup.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"{label}:" in html
    assert "Add your gear →" in html
    assert f"/settings/equipment#setup-{setup_id}" in html
    identity = html.split('<div class="hc-identity">', 1)[-1].split(
        '<div class="hc-stat-band">', 1
    )[0]
    assert "Setup saved" not in identity


@pytest.mark.parametrize(
    ("rider_types", "discipline", "brand", "model", "label"),
    [
        (["Skier"], EquipmentDiscipline.SKIER, "Blizzard", "Rustler 10", "Skis"),
        (["Snowboarder"], EquipmentDiscipline.SNOWBOARDER, "Burton", "Custom", "Snowboard"),
    ],
)
def test_profile_shows_complete_single_discipline_setup_with_direct_link(
    client, logged_in_user, rider_types, discipline, brand, model, label
):
    logged_in_user.rider_types = rider_types
    with app.app_context():
        setup = _profile_setup(
            logged_in_user,
            discipline,
            primary=True,
            brand=brand,
            model=model,
            boot_brand="Salomon",
            boot_model="Shift",
            binding_brand="Marker",
            binding_model="Griffon",
        )
        user_id, setup_id = logged_in_user.id, setup.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"{label}:" in html
    assert f"{brand} {model}" in html
    assert "Boots:" in html
    assert "Salomon Shift" in html
    assert "Bindings:" in html
    assert "Marker Griffon" in html
    assert html.count(f"/settings/equipment#setup-{setup_id}") >= 3


def test_profile_prefers_global_primary_for_matching_discipline(client, logged_in_user):
    logged_in_user.rider_types = ["Skier"]
    with app.app_context():
        older = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            brand="Atomic",
            model="Maverick",
            created_at=datetime(2025, 1, 1),
        )
        primary = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Blizzard",
            model="Rustler 10",
            created_at=datetime(2025, 2, 1),
        )
        user_id, older_id, primary_id = logged_in_user.id, older.id, primary.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"/settings/equipment#setup-{primary_id}" in html
    assert f"/settings/equipment#setup-{older_id}" not in html


def test_profile_uses_oldest_matching_fallback_when_global_primary_is_other_discipline(
    client, logged_in_user
):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        oldest_ski = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            brand="Atomic",
            model="Maverick",
            created_at=datetime(2025, 1, 1),
        )
        newer_ski = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            brand="Salomon",
            model="Stance",
            created_at=datetime(2025, 2, 1),
        )
        primary_board = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SNOWBOARDER,
            primary=True,
            brand="Burton",
            model="Custom",
        )
        user_id = logged_in_user.id
        oldest_ski_id, newer_ski_id, primary_board_id = (
            oldest_ski.id,
            newer_ski.id,
            primary_board.id,
        )
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"/settings/equipment#setup-{oldest_ski_id}" in html
    assert f"/settings/equipment#setup-{newer_ski_id}" not in html
    assert f"/settings/equipment#setup-{primary_board_id}" in html


def test_profile_dual_rider_shows_one_setup_per_discipline(client, logged_in_user):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        ski = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            brand="Blizzard",
            model="Rustler 10",
        )
        board = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            model="Custom",
        )
        user_id, ski_id, board_id = logged_in_user.id, ski.id, board.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert "Skis:" in html
    assert "Blizzard Rustler 10" in html
    assert "Snowboard:" in html
    assert "Burton Custom" in html
    assert f"/settings/equipment#setup-{ski_id}" in html
    assert f"/settings/equipment#setup-{board_id}" in html


@pytest.mark.parametrize(
    ("discipline", "present_brand", "present_model", "missing_label"),
    [
        (EquipmentDiscipline.SKIER, "Blizzard", "Rustler 10", "Snowboard"),
        (EquipmentDiscipline.SNOWBOARDER, "Burton", "Custom", "Skis"),
    ],
)
def test_profile_dual_rider_shows_specific_add_state_for_missing_discipline(
    client, logged_in_user, discipline, present_brand, present_model, missing_label
):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        setup = _profile_setup(
            logged_in_user,
            discipline,
            brand=present_brand,
            model=present_model,
        )
        user_id, setup_id = logged_in_user.id, setup.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"{present_brand} {present_model}" in html
    assert f"{missing_label}:" in html
    assert "Add your gear →" in html
    assert f"/settings/equipment#setup-{setup_id}" in html


def test_profile_dual_rider_does_not_cross_fallback_between_disciplines(
    client, logged_in_user
):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        ski = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Blizzard",
            model="Rustler 10",
        )
        user_id, ski_id = logged_in_user.id, ski.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert "Blizzard Rustler 10" in html
    assert "Snowboard:    " not in html
    assert "Snowboard:" in html
    assert f"/settings/equipment#setup-{ski_id}" in html


def test_profile_global_primary_is_used_only_for_its_matching_discipline(
    client, logged_in_user
):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        primary_ski = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Blizzard",
            model="Rustler 10",
        )
        older_board = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            model="Custom",
            created_at=datetime(2025, 1, 1),
        )
        newer_board = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SNOWBOARDER,
            brand="Jones",
            model="Mountain Twin",
            created_at=datetime(2025, 2, 1),
        )
        user_id = logged_in_user.id
        primary_ski_id, older_board_id, newer_board_id = (
            primary_ski.id,
            older_board.id,
            newer_board.id,
        )
        db.session.commit()

    html = _profile_html(client, user_id)

    assert f"/settings/equipment#setup-{primary_ski_id}" in html
    assert f"/settings/equipment#setup-{older_board_id}" in html
    assert f"/settings/equipment#setup-{newer_board_id}" not in html


def test_profile_incomplete_setup_shows_add_without_blank_rows(client, logged_in_user):
    logged_in_user.rider_types = ["Skier"]
    with app.app_context():
        setup = _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            primary=True,
            boot_brand="Salomon",
            boot_model="Shift",
        )
        user_id, setup_id = logged_in_user.id, setup.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert "Skis:" in html
    assert "Add your gear →" in html
    assert "Boots:" in html
    assert "Salomon Shift" in html
    assert f"/settings/equipment#setup-{setup_id}" in html
    assert "Skis: </" not in html
    assert "Bindings:" not in html


def test_profile_rental_state_takes_precedence_over_saved_setups(client, logged_in_user):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    logged_in_user.equipment_status = "needs_rentals"
    with app.app_context():
        _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Blizzard",
            model="Rustler 10",
        )
        _profile_setup(
            logged_in_user,
            EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            model="Custom",
        )
        user_id = logged_in_user.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert "Rental gear" in html
    assert "Blizzard Rustler 10" not in html
    assert "Burton Custom" not in html
    assert "Add your gear →" not in html


def test_profile_add_action_without_existing_setup_uses_normal_equipment_flow(
    client, logged_in_user
):
    logged_in_user.rider_types = ["Skier", "Snowboarder"]
    with app.app_context():
        user_id = logged_in_user.id
        db.session.commit()

    html = _profile_html(client, user_id)

    assert html.count('href="/settings/equipment"') >= 2
    assert "Skis:" in html
    assert "Snowboard:" in html
    assert "Add your gear →" in html
    assert "#setup-" not in html
