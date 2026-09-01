"""Regression coverage for strict JSON boolean visibility controls."""

import os
from unittest.mock import patch

import pytest

from app import app
from models import Resort, SkiTrip, User, db
from tests.conftest import (
    _FUTURE_END2,
    _FUTURE_START2,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


INVALID_BOOLEAN_VALUES = [
    pytest.param("true", id="string-true"),
    pytest.param("false", id="string-false"),
    pytest.param(0, id="zero"),
    pytest.param(1, id="one"),
    pytest.param(None, id="null"),
    pytest.param([], id="array"),
    pytest.param({}, id="object"),
]


@pytest.fixture
def privacy_setup(client):
    with app.app_context():
        owner = _make_user("strict-boolean-owner")
        resort = _make_resort("Strict Boolean Peak")
        trip = _make_trip(owner, resort=resort, is_public=True)
        db.session.commit()
        data = {
            "owner_id": owner.id,
            "owner_email": owner.email,
            "resort_id": resort.id,
            "trip_id": trip.id,
        }
    return data


def _admin_put(client, resort_id, payload):
    return client.put(
        f"/api/admin/resorts/{resort_id}",
        json=payload,
        headers={"X-CSRF-Token": "test-csrf-fixed-value-baselodge-regression"},
    )


@pytest.mark.parametrize("value", INVALID_BOOLEAN_VALUES)
def test_create_trip_rejects_non_boolean_visibility(client, value):
    with app.app_context():
        owner = _make_user("strict-create")
        resort = _make_resort("Strict Create Peak")
        owner_id, resort_id = owner.id, resort.id
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        "/api/trip/create",
        {
            "resort_id": resort_id,
            "start_date": _FUTURE_START2.isoformat(),
            "end_date": _FUTURE_END2.isoformat(),
            "is_public": value,
        },
    )

    assert response.status_code == 400
    with app.app_context():
        assert SkiTrip.query.filter_by(user_id=owner_id).count() == 0


@pytest.mark.parametrize("value", [True, False], ids=["public", "private"])
def test_create_trip_accepts_boolean_visibility(client, value):
    with app.app_context():
        owner = _make_user("strict-create-valid")
        resort = _make_resort("Strict Create Valid Peak")
        owner_id, resort_id = owner.id, resort.id
        db.session.commit()

    _login(client, owner_id)
    response = json_post(
        client,
        "/api/trip/create",
        {
            "resort_id": resort_id,
            "start_date": _FUTURE_START2.isoformat(),
            "end_date": _FUTURE_END2.isoformat(),
            "is_public": value,
        },
    )

    assert response.status_code == 200
    with app.app_context():
        created = SkiTrip.query.filter_by(user_id=owner_id).one()
        assert created.is_public is value


@pytest.mark.parametrize("value", INVALID_BOOLEAN_VALUES)
def test_update_trip_visibility_rejects_non_boolean_without_mutation(
    client, privacy_setup, value
):
    _login(client, privacy_setup["owner_id"])
    response = json_post(
        client,
        f"/api/trip/{privacy_setup['trip_id']}/update-visibility",
        {"is_public": value},
    )

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(SkiTrip, privacy_setup["trip_id"]).is_public is True


@pytest.mark.parametrize("value", INVALID_BOOLEAN_VALUES)
def test_profile_discoverability_rejects_non_boolean_without_mutation(
    client, privacy_setup, value
):
    _login(client, privacy_setup["owner_id"])
    response = json_post(
        client,
        "/api/profile/update",
        {"discoverable_in_friend_search": value},
    )

    assert response.status_code == 400
    with app.app_context():
        assert (
            db.session.get(User, privacy_setup["owner_id"])
            .discoverable_in_friend_search
            is True
        )


@pytest.mark.parametrize("value", [True, False], ids=["discoverable", "hidden"])
def test_profile_discoverability_accepts_boolean_values(client, privacy_setup, value):
    _login(client, privacy_setup["owner_id"])
    response = json_post(
        client,
        "/api/profile/update",
        {"discoverable_in_friend_search": value},
    )

    assert response.status_code == 200
    with app.app_context():
        assert (
            db.session.get(User, privacy_setup["owner_id"])
            .discoverable_in_friend_search
            is value
        )


@pytest.mark.parametrize("value", INVALID_BOOLEAN_VALUES)
@pytest.mark.parametrize("route_kind", ["put", "toggle"])
def test_admin_resort_activation_rejects_non_boolean_without_mutation(
    client, privacy_setup, value, route_kind
):
    _login(client, privacy_setup["owner_id"])
    with patch.dict(
        os.environ, {"ALLOWED_ADMIN_EMAILS": privacy_setup["owner_email"]}
    ):
        if route_kind == "put":
            response = _admin_put(
                client,
                privacy_setup["resort_id"],
                {"is_active": value},
            )
        else:
            response = json_post(
                client,
                "/api/admin/resorts/toggle-active",
                {"resort_id": privacy_setup["resort_id"], "is_active": value},
            )

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Resort, privacy_setup["resort_id"]).is_active is True


@pytest.mark.parametrize("route_kind", ["put", "toggle"])
@pytest.mark.parametrize("value", [True, False], ids=["active", "inactive"])
def test_admin_resort_activation_accepts_boolean_values(
    client, privacy_setup, route_kind, value
):
    _login(client, privacy_setup["owner_id"])
    with patch.dict(
        os.environ, {"ALLOWED_ADMIN_EMAILS": privacy_setup["owner_email"]}
    ):
        if route_kind == "put":
            response = _admin_put(
                client,
                privacy_setup["resort_id"],
                {"is_active": value},
            )
        else:
            response = json_post(
                client,
                "/api/admin/resorts/toggle-active",
                {"resort_id": privacy_setup["resort_id"], "is_active": value},
            )

    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Resort, privacy_setup["resort_id"]).is_active is value
