"""BL-122 route-level validation for equipment measurements."""

import pytest

from app import app
from models import EquipmentDiscipline, EquipmentSetup, EquipmentSlot, User, db
from services.equipment_validation import parse_nullable_measurement
from tests.conftest import _login, _make_user, form_post, json_post


def _settings_payload(**overrides):
    payload = {
        "discipline": "Skier",
        "brand": "Salomon",
        "model": "QST 98",
        "length_cm": "170",
        "width_mm": "98",
        "boot_flex": "",
        "purchase_year": "",
    }
    payload.update(overrides)
    return payload


def _profile_payload(**overrides):
    payload = {
        "slot": "PRIMARY",
        "discipline": "SKIER",
        "brand": "Salomon",
        "length_cm": "170",
        "width_mm": "98",
    }
    payload.update(overrides)
    return payload


def _user_and_setup(*, slot=None, length_cm=170, width_mm=98):
    user = _make_user("bl122")
    setup = EquipmentSetup(
        user_id=user.id,
        slot=slot,
        discipline=EquipmentDiscipline.SKIER,
        brand="Salomon",
        length_cm=length_cm,
        width_mm=width_mm,
    )
    db.session.add(setup)
    db.session.commit()
    return user.id, setup.id


@pytest.mark.parametrize(
    "value",
    ["abc", "170.5", "1e2", "170cm", 49, 251],
)
def test_settings_rejects_invalid_length_without_creating_setup(client, value):
    with app.app_context():
        user = _make_user("bl122-settings-create")
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(length_cm=value),
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"].startswith("Length")
    with app.app_context():
        assert EquipmentSetup.query.filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize(
    "value",
    ["abc", "98.5", "1e2", "98mm", 49, 401],
)
def test_settings_rejects_invalid_width_without_creating_setup(client, value):
    with app.app_context():
        user = _make_user("bl122-settings-width-create")
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(width_mm=value),
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"].startswith("Width")
    with app.app_context():
        assert EquipmentSetup.query.filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("length_cm", "49"),
        ("length_cm", "251"),
        ("width_mm", "49"),
        ("width_mm", "401"),
    ],
)
def test_settings_invalid_update_preserves_existing_values(
    client, field, value
):
    with app.app_context():
        user_id, setup_id = _user_and_setup()

    _login(client, user_id)
    response = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(setup_id), **{field: value}),
    )

    assert response.status_code == 400
    assert response.is_json
    with app.app_context():
        setup = db.session.get(EquipmentSetup, setup_id)
        assert (setup.length_cm, setup.width_mm) == (170, 98)


def test_settings_valid_strings_and_empty_values_preserve_response_contract(client):
    with app.app_context():
        user_id, setup_id = _user_and_setup()

    _login(client, user_id)
    valid = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(setup_id)),
    )
    assert valid.status_code == 200
    assert valid.get_json()["success"] is True
    assert valid.get_json()["setup_id"] == setup_id

    empty = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(
            setup_id=str(setup_id),
            length_cm="",
            width_mm="",
        ),
    )
    assert empty.status_code == 200
    with app.app_context():
        setup = db.session.get(EquipmentSetup, setup_id)
        assert setup.length_cm is None
        assert setup.width_mm is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("length_cm", "abc"),
        ("length_cm", "170.5"),
        ("length_cm", "1e2"),
        ("length_cm", "170cm"),
        ("length_cm", 49),
        ("length_cm", 251),
        ("width_mm", "abc"),
        ("width_mm", "98.5"),
        ("width_mm", "1e2"),
        ("width_mm", "98mm"),
        ("width_mm", 49),
        ("width_mm", 401),
    ],
)
def test_profile_rejects_invalid_measurements_without_creating_setup(
    client, field, value
):
    with app.app_context():
        user = _make_user("bl122-profile-create")
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client,
        "/profile/equipment",
        _profile_payload(**{field: value}),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert field.split("_")[0].capitalize() in body["error"]
    with app.app_context():
        assert EquipmentSetup.query.filter_by(user_id=user_id).count() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("length_cm", "49"),
        ("length_cm", "251"),
        ("width_mm", "49"),
        ("width_mm", "401"),
    ],
)
def test_profile_invalid_update_preserves_existing_values(client, field, value):
    with app.app_context():
        user_id, setup_id = _user_and_setup(slot=EquipmentSlot.PRIMARY)

    _login(client, user_id)
    response = json_post(
        client,
        "/profile/equipment",
        _profile_payload(**{field: value}),
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False
    with app.app_context():
        setup = db.session.get(EquipmentSetup, setup_id)
        assert (setup.length_cm, setup.width_mm) == (170, 98)


def test_profile_valid_strings_and_null_values_preserve_response_contract(client):
    with app.app_context():
        user_id, setup_id = _user_and_setup(slot=EquipmentSlot.PRIMARY)

    _login(client, user_id)
    valid = json_post(client, "/profile/equipment", _profile_payload())
    assert valid.status_code == 200
    assert valid.get_json()["success"] is True
    assert "message" in valid.get_json()

    cleared = json_post(
        client,
        "/profile/equipment",
        _profile_payload(length_cm=None, width_mm=None),
    )
    assert cleared.status_code == 200
    with app.app_context():
        setup = db.session.get(EquipmentSetup, setup_id)
        assert setup.length_cm is None
        assert setup.width_mm is None


def test_settings_setup_ownership_behavior_remains_unchanged(client):
    with app.app_context():
        owner_id, setup_id = _user_and_setup()
        other_user = _make_user("bl122-other")
        other_id = other_user.id
        db.session.commit()

    _login(client, other_id)
    response = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(setup_id), length_cm="180"),
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "Setup not found"
    with app.app_context():
        setup = db.session.get(EquipmentSetup, setup_id)
        assert setup.user_id == owner_id
        assert setup.length_cm == 170


def test_profile_save_remains_owner_scoped(client):
    with app.app_context():
        owner_id, setup_id = _user_and_setup(slot=EquipmentSlot.PRIMARY)
        other_user = _make_user("bl122-profile-other")
        other_id = other_user.id
        db.session.commit()

    _login(client, other_id)
    response = json_post(
        client,
        "/profile/equipment",
        _profile_payload(length_cm="180"),
    )

    assert response.status_code == 200
    with app.app_context():
        owner_setup = db.session.get(EquipmentSetup, setup_id)
        other_setup = EquipmentSetup.query.filter_by(
            user_id=other_id,
            slot=EquipmentSlot.PRIMARY,
        ).one()
        assert owner_setup.length_cm == 170
        assert other_setup.length_cm == 180


@pytest.mark.parametrize(
    ("value", "minimum", "maximum"),
    [("50", 50, 250), ("250", 50, 250), ("", 50, 250), (None, 50, 250)],
)
def test_nullable_measurement_helper_accepts_contract_values(
    value, minimum, maximum
):
    assert parse_nullable_measurement(
        value,
        field_label="Length",
        minimum=minimum,
        maximum=maximum,
    ) == (None if value in ("", None) else int(value))