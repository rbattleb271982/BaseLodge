"""BL-122 route-level validation for equipment measurements."""

import pytest
from sqlalchemy import event

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


INVALID_SETUP_IDS = (
    "abc",
    "12abc",
    "-1",
    "+1",
    "1.0",
    "0",
    "000",
    "2147483648",
    "9" * 5000,
)


@pytest.mark.parametrize("setup_id", INVALID_SETUP_IDS)
@pytest.mark.parametrize(
    ("route", "payload"),
    (
        ("/settings/equipment/save", _settings_payload()),
        ("/settings/equipment/make-primary", {}),
        ("/settings/equipment/delete", {}),
    ),
)
def test_settings_mutations_reject_invalid_setup_id_before_query_or_change(
    client, setup_id, route, payload
):
    with app.app_context():
        user_id, first_id = _user_and_setup()
        second = EquipmentSetup(
            user_id=user_id,
            discipline=EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            is_primary=True,
        )
        db.session.add(second)
        first = db.session.get(EquipmentSetup, first_id)
        first.is_primary = False
        db.session.commit()
        second_id = second.id

    _login(client, user_id)
    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = form_post(
            client, route, {**payload, "setup_id": setup_id}
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid setup_id"}
    assert not any("equipment_setup" in sql.lower() for sql in statements)
    with app.app_context():
        first = db.session.get(EquipmentSetup, first_id)
        second = db.session.get(EquipmentSetup, second_id)
        assert (first.brand, first.is_primary) == ("Salomon", False)
        assert (second.brand, second.is_primary) == ("Burton", True)


@pytest.mark.parametrize("setup_id", INVALID_SETUP_IDS)
def test_settings_get_rejects_invalid_setup_id_before_equipment_query(
    client, setup_id
):
    with app.app_context():
        user_id, setup_id_existing = _user_and_setup()

    _login(client, user_id)
    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        response = client.get(f"/settings/equipment/get/{setup_id}")
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid setup_id"}
    assert not any("equipment_setup" in sql.lower() for sql in statements)
    with app.app_context():
        assert db.session.get(EquipmentSetup, setup_id_existing).brand == "Salomon"


def test_settings_equipment_id_valid_missing_foreign_and_empty_contracts(client):
    with app.app_context():
        owner_id, owner_setup_id = _user_and_setup()
        other = _make_user("equipment-id-contract")
        other_id = other.id
        db.session.commit()

    _login(client, other_id)
    assert client.get(
        f"/settings/equipment/get/{owner_setup_id}"
    ).status_code == 404
    foreign_save = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(owner_setup_id), brand="Changed"),
    )
    assert foreign_save.status_code == 404
    assert form_post(
        client,
        "/settings/equipment/make-primary",
        {"setup_id": str(owner_setup_id)},
    ).status_code == 404
    assert form_post(
        client,
        "/settings/equipment/delete",
        {"setup_id": str(owner_setup_id)},
    ).get_json() == {"success": True}

    missing_id = 2_147_483_647
    assert client.get(f"/settings/equipment/get/{missing_id}").status_code == 404
    assert form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(missing_id)),
    ).status_code == 404
    assert form_post(
        client,
        "/settings/equipment/make-primary",
        {"setup_id": str(missing_id)},
    ).status_code == 404
    assert form_post(
        client,
        "/settings/equipment/delete",
        {"setup_id": str(missing_id)},
    ).get_json() == {"success": True}

    assert form_post(
        client, "/settings/equipment/make-primary", {}
    ).get_json() == {"error": "setup_id required"}
    created = form_post(
        client, "/settings/equipment/save", _settings_payload(setup_id="")
    )
    assert created.status_code == 200
    assert form_post(
        client, "/settings/equipment/delete", {"setup_id": "", "slot": "secondary"}
    ).get_json() == {"success": True}

    with app.app_context():
        owner_setup = db.session.get(EquipmentSetup, owner_setup_id)
        assert owner_setup.user_id == owner_id
        assert owner_setup.brand == "Salomon"


def test_settings_valid_setup_ids_support_get_edit_primary_and_delete(client):
    with app.app_context():
        user_id, first_id = _user_and_setup()
        second = EquipmentSetup(
            user_id=user_id,
            discipline=EquipmentDiscipline.SNOWBOARDER,
            brand="Burton",
            is_primary=False,
        )
        db.session.add(second)
        first = db.session.get(EquipmentSetup, first_id)
        first.is_primary = True
        db.session.commit()
        second_id = second.id

    _login(client, user_id)
    loaded = client.get(f"/settings/equipment/get/{second_id}")
    assert loaded.status_code == 200
    assert loaded.get_json()["id"] == second_id

    edited = form_post(
        client,
        "/settings/equipment/save",
        _settings_payload(setup_id=str(second_id), brand="Jones"),
    )
    assert edited.status_code == 200
    assert edited.get_json()["setup_id"] == second_id

    made_primary = form_post(
        client,
        "/settings/equipment/make-primary",
        {"setup_id": str(second_id)},
    )
    assert made_primary.get_json() == {"success": True}
    with app.app_context():
        assert db.session.get(EquipmentSetup, first_id).is_primary is False
        assert db.session.get(EquipmentSetup, second_id).is_primary is True
        assert db.session.get(EquipmentSetup, second_id).brand == "Jones"

    deleted = form_post(
        client,
        "/settings/equipment/delete",
        {"setup_id": str(second_id)},
    )
    assert deleted.get_json() == {"success": True}
    with app.app_context():
        assert db.session.get(EquipmentSetup, second_id) is None
        assert db.session.get(EquipmentSetup, first_id).is_primary is True