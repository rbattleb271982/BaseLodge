"""Invariants for the deterministic capture fixture registry."""
from capture_harness.fixtures import (
    FROZEN_TODAY,
    PERSONAS,
    resolve_route_binding,
    seed_all,
    validate_fixtures,
)


def test_capture_registry_is_stable(client, db_fixture, app_fixture):
    with app_fixture.app_context():
        registry = seed_all(db_fixture)
        assert FROZEN_TODAY.isoformat() == "2027-01-15"
        assert tuple(registry["personas"]) == PERSONAS
        assert validate_fixtures(db_fixture, registry)
        assert len(registry["personas"]["HEAVY"]["friends"]) == 25
        assert len(registry["personas"]["HEAVY"]["trips"]) == 15
        assert len(registry["personas"]["HEAVY"]["planning_posts"]) == 3
        assert registry["personas"]["LIGHT"]["trips"]
        assert registry["personas"]["TYPICAL"]["trips"]
        assert len(registry["personas"]["EXTREME"]["trips"]) == 6
        assert registry["personas"]["EDGE"]["user"].wish_list_resorts
        assert registry["personas"]["HEAVY"]["scenarios"]["pagination"]["pages"] == (
            10, 10, 5
        )
        assert resolve_route_binding("home", registry).email == (
            "capture-heavy@fixture.invalid"
        )
