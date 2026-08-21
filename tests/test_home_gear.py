from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

import pytest

from app import app
from conftest import _login, _make_trip, _make_user
from models import EquipmentDiscipline, EquipmentSetup, db


EQUIPMENT_TEMPLATE = Path("templates/settings_equipment.html").read_text()


def _home_html(client, user_id):
    _login(client, user_id)
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=[],
    ), patch(
        "services.ideas_engine.build_destination_feed",
        return_value=([], {}, []),
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


def _setup(user, discipline, *, primary=False, created_at=None, label=None, brand=None, model=None):
    setup = EquipmentSetup(
        user_id=user.id,
        discipline=discipline,
        is_primary=primary,
        created_at=created_at or datetime.utcnow(),
        label=label,
        brand=brand,
        model=model,
    )
    db.session.add(setup)
    db.session.flush()
    return setup


@pytest.mark.parametrize(
    ("rider_types", "discipline", "label", "brand", "model", "expected_label"),
    [
        (["Skier"], EquipmentDiscipline.SKIER, None, "Salomon", "QST 92", "Skis"),
        (["Snowboarder"], EquipmentDiscipline.SNOWBOARDER, None, "Burton", "Custom", "Snowboard"),
    ],
)
def test_home_shows_matching_single_discipline_setup(
    client, rider_types, discipline, label, brand, model, expected_label
):
    with app.app_context():
        user = _make_home_user("gear", rider_types=rider_types)
        setup = _setup(user, discipline, primary=True, label=label, brand=brand, model=model)
        user_id, setup_id = user.id, setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert f"{expected_label}</span>" in html
    assert f"{brand} {model}" in html
    assert f'/settings/equipment#setup-{setup_id}' in html


def test_home_shows_both_disciplines_and_missing_specific_add_state(client):
    with app.app_context():
        user = _make_home_user("both", rider_types=["Skier", "Snowboarder"])
        ski_setup = _setup(
            user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Salomon",
            model="QST 92",
        )
        user_id, ski_setup_id = user.id, ski_setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert f'/settings/equipment#setup-{ski_setup_id}' in html
    assert "Skis</span>" in html
    assert "Add your snowboard gear" in html


def test_home_shows_single_snowboarder_add_state_when_no_setup_exists(client):
    with app.app_context():
        user = _make_home_user("empty-board", rider_types=["Snowboarder"])
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Add your gear" in html
    assert "Add your snowboard gear" not in html
    assert "Snowboard</span>" not in html


def test_home_shows_snowboard_setup_and_ski_add_state_for_dual_profile(client):
    with app.app_context():
        user = _make_home_user("board-only", rider_types=["Skier", "Snowboarder"])
        setup = _setup(
            user,
            EquipmentDiscipline.SNOWBOARDER,
            primary=True,
            brand="Jones",
            model="Mountain Twin",
        )
        user_id, setup_id = user.id, setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Add your ski gear" in html
    assert "Jones Mountain Twin" in html
    assert f'/settings/equipment#setup-{setup_id}' in html


def test_home_excludes_mismatched_setup_and_uses_add_state(client):
    with app.app_context():
        user = _make_home_user("mismatch", rider_types=["Skier"])
        _setup(
            user,
            EquipmentDiscipline.SNOWBOARDER,
            primary=True,
            brand="Burton",
            model="Custom",
        )
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Add your gear" in html
    assert "Burton Custom" not in html
    assert "Snowboard</span>" not in html


def test_home_prefers_matching_global_primary_and_keeps_primary_flags_unchanged(client):
    with app.app_context():
        user = _make_home_user("primary", rider_types=["Skier", "Snowboarder"])
        old_ski = _setup(
            user,
            EquipmentDiscipline.SKIER,
            brand="Rossignol",
            model="Experience",
            created_at=datetime.utcnow() - timedelta(days=2),
        )
        primary_ski = _setup(
            user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Salomon",
            model="QST 92",
            created_at=datetime.utcnow() - timedelta(days=1),
        )
        board = _setup(
            user,
            EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            model="Custom",
        )
        user_id = user.id
        old_ski_id, primary_ski_id, board_id = old_ski.id, primary_ski.id, board.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert f'/settings/equipment#setup-{primary_ski_id}' in html
    assert f'/settings/equipment#setup-{board_id}' in html
    assert f'/settings/equipment#setup-{old_ski_id}' not in html
    with app.app_context():
        assert EquipmentSetup.query.get(primary_ski_id).is_primary is True
        assert EquipmentSetup.query.get(old_ski_id).is_primary is False
        assert EquipmentSetup.query.get(board_id).is_primary is False


def test_home_uses_oldest_matching_setup_when_global_primary_is_other_discipline(client):
    with app.app_context():
        user = _make_home_user("fallback", rider_types=["Skier", "Snowboarder"])
        oldest_ski = _setup(
            user,
            EquipmentDiscipline.SKIER,
            brand="Atomic",
            model="Maverick",
            created_at=datetime.utcnow() - timedelta(days=3),
        )
        _setup(
            user,
            EquipmentDiscipline.SKIER,
            brand="Salomon",
            model="Stance",
            created_at=datetime.utcnow() - timedelta(days=2),
        )
        primary_board = _setup(
            user,
            EquipmentDiscipline.SNOWBOARDER,
            primary=True,
            brand="Jones",
            model="Mountain Twin",
        )
        user_id = user.id
        oldest_ski_id, primary_board_id = oldest_ski.id, primary_board.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert f'/settings/equipment#setup-{oldest_ski_id}' in html
    assert f'/settings/equipment#setup-{primary_board_id}' in html


def test_home_treats_blank_detail_setup_as_saved_gear(client):
    with app.app_context():
        user = _make_home_user("blank", rider_types=["Skier"])
        setup = _setup(user, EquipmentDiscipline.SKIER, primary=True)
        user_id, setup_id = user.id, setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Skis setup" in html
    assert f'/settings/equipment#setup-{setup_id}' in html
    assert "Add your gear" not in html


def test_home_preserves_rental_state_over_saved_setup(client):
    with app.app_context():
        user = _make_home_user(
            "rental",
            rider_types=["Skier"],
            equipment_status="needs_rentals",
        )
        _setup(
            user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="Salomon",
            model="QST 92",
        )
        user_id = user.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Rental gear" in html
    assert "Salomon QST 92" not in html
    assert "Add your gear" not in html


def test_home_uses_legacy_rider_profile_for_matching_gear(client):
    with app.app_context():
        user = _make_home_user(
            "legacy",
            rider_types=[],
            primary_rider_type="Snowboarder",
        )
        setup = _setup(
            user,
            EquipmentDiscipline.SNOWBOARDER,
            primary=True,
            label="Pow board",
        )
        user_id, setup_id = user.id, setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "Pow board" in html
    assert f'/settings/equipment#setup-{setup_id}' in html


def test_home_gear_summary_renders_in_populated_header(client):
    with app.app_context():
        user = _make_home_user("trip", rider_types=["Skier"])
        setup = _setup(
            user,
            EquipmentDiscipline.SKIER,
            primary=True,
            brand="K2",
            model="Mindbender",
        )
        _make_trip(user)
        user_id, setup_id = user.id, setup.id
        db.session.commit()

    html = _home_html(client, user_id)

    assert "K2 Mindbender" in html
    assert f'/settings/equipment#setup-{setup_id}' in html


def test_gear_page_hash_contract_reuses_existing_edit_form_safely():
    function_match = re.search(
        r"function openSetupFromHash\(\) \{.*?\n\}",
        EQUIPMENT_TEMPLATE,
        flags=re.DOTALL,
    )
    assert function_match
    function_source = function_match.group(0)

    cases = [
        ("#setup-42", 42, True),
        ("", None, False),
        ("#setup-invalid", None, False),
        ("#setup-99", None, False),
    ]
    for hash_value, expected_id, card_exists in cases:
        script = f"""
const calls = [];
const renderedCardId = {json.dumps('eq-card-42' if card_exists else '')};
const window = {{ location: {{ hash: {json.dumps(hash_value)} }} }};
const document = {{
  getElementById: (id) => id === renderedCardId ? {{}} : null
}};
const openEditForm = (id) => calls.push(id);
{function_source}
openSetupFromHash();
const expected = {json.dumps([] if expected_id is None else [expected_id])};
if (JSON.stringify(calls) !== JSON.stringify(expected)) {{
  throw new Error(JSON.stringify({{ hash: window.location.hash, calls, expected }}));
}}
"""
        result = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout