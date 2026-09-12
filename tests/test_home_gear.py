"""Task 539 regressions for the compact Round 11 G Gear row."""

from datetime import datetime
from unittest.mock import patch

from app import app
from conftest import _login, _make_trip, _make_user
from models import EquipmentDiscipline, EquipmentSetup, db


def _home_html(client, user_id):
    _login(client, user_id)
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=[],
    ), patch(
        "services.ideas_retrieval.get_home_ideas",
        return_value=[],
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ):
        response = client.get("/home")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _make_home_user(label, rider_types=None, **extra):
    user = _make_user(label, **extra)
    if rider_types is not None:
        user.rider_types = rider_types
    return user


def _setup(user, discipline, *, primary=False, label=None):
    setup = EquipmentSetup(
        user_id=user.id,
        discipline=discipline,
        is_primary=primary,
        created_at=datetime.utcnow(),
        label=label,
    )
    db.session.add(setup)
    db.session.flush()
    return setup


def test_home_gear_row_shows_rider_skill_and_single_setup(client):
    with app.app_context():
        user = _make_home_user("gear-one", rider_types=["Skier"])
        user.skill_level = "Advanced"
        _setup(user, EquipmentDiscipline.SKIER, primary=True)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Skier · Advanced" in html
    assert "1 setup" in html
    assert 'href="/settings/equipment"' in html


def test_home_gear_row_counts_all_matching_saved_setups(client):
    with app.app_context():
        user = _make_home_user("gear-multi", rider_types=["Skier"])
        user.skill_level = "Advanced"
        _setup(user, EquipmentDiscipline.SKIER, primary=True)
        _setup(user, EquipmentDiscipline.SKIER)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Skier · Advanced" in html
    assert "2 setups" in html


def test_home_gear_row_ignores_setup_for_unselected_discipline(client):
    with app.app_context():
        user = _make_home_user("gear-mismatch", rider_types=["Skier"])
        user.skill_level = "Intermediate"
        _setup(user, EquipmentDiscipline.SNOWBOARDER, primary=True)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Skier · Intermediate" in html
    assert "No setup saved" in html


def test_home_gear_row_preserves_rental_state(client):
    with app.app_context():
        user = _make_home_user(
            "gear-rental",
            rider_types=["Skier"],
            equipment_status="needs_rentals",
        )
        _setup(user, EquipmentDiscipline.SKIER, primary=True)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Rental gear" in html
    assert "1 setup" not in html


def test_home_gear_row_uses_legacy_rider_profile(client):
    with app.app_context():
        user = _make_home_user(
            "gear-legacy",
            rider_types=[],
            primary_rider_type="Snowboarder",
        )
        user.skill_level = "Beginner"
        _setup(user, EquipmentDiscipline.SNOWBOARDER, primary=True)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Snowboarder · Beginner" in html
    assert "1 setup" in html


def test_home_gear_row_is_identical_when_next_trip_exists(client):
    with app.app_context():
        user = _make_home_user("gear-trip", rider_types=["Skier"])
        user.skill_level = "Advanced"
        _setup(user, EquipmentDiscipline.SKIER, primary=True)
        _make_trip(user)
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Skier · Advanced" in html
    assert "1 setup" in html
    assert 'id="your-next-trip"' in html