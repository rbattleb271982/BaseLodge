from capture_harness.manifest import (
    DISCOVERED_ISSUES,
    MANIFEST,
    PERSONAS,
    VIEWPORTS,
    FORBIDDEN,
    validate_manifest,
)


def test_manifest_shape_and_count():
    validate_manifest()
    assert len(MANIFEST) == 106
    assert len({r["capture_id"] for r in MANIFEST}) == 106
    required = {"capture_id", "product_area", "screen", "route_template", "persona",
                "state", "viewport", "segment", "logical_route_bindings", "preconditions",
                "interaction", "deterministic_wait_condition", "output_path", "rationale"}
    assert all(required <= set(row) for row in MANIFEST)


def test_mobile_only_and_exclusions():
    assert {tuple(r["viewport"].values()) for r in MANIFEST} <= {(390, 844), (360, 800)}
    assert all(not any(r["route_template"].startswith(x) for x in FORBIDDEN) for r in MANIFEST)
    assert not any("admin" in r["route_template"].lower() for r in MANIFEST)


def test_personas_and_bindings():
    assert {r["persona"] for r in MANIFEST} == set(PERSONAS)
    for row in MANIFEST:
        for key in ("capture_id", "output_path"):
            assert row[key]
        for key in __import__("re").findall(r"{([^}]+)}", row["route_template"]):
            assert key in row["logical_route_bindings"]


def test_required_phase_three_additions_and_split_states():
    ids = {r["capture_id"] for r in MANIFEST}
    assert any("season-snapshot" in x for x in ids)
    assert not any("buddy-pass-modal" in x for x in ids)
    assert DISCOVERED_ISSUES[0]["requested_state"] == "profile buddy-pass modal"
    assert any("friend-read-only" in x for x in ids)
    for stem in ("mountain-detail__edge__social-loading", "mountain-detail__edge__social-error",
                 "friends__edge__suggestions-loading", "friends__edge__suggestions-error",
                 "trips__edge__progressive-loading", "trips__edge__error-retry"):
        assert any(x.startswith(stem) for x in ids)


def test_route_templates_are_supported_or_intentional_system_outcomes():
    supported = (
        "/auth", "/setup-profile", "/home", "/my-trips", "/season-snapshot",
        "/add_trip", "/trips/", "/friends", "/mountains", "/mountain/",
        "/more", "/settings/wish-list", "/wishlist/", "/mountains-visited",
        "/add-open-dates", "/open-to-ski", "/settings/equipment",
        "/profile", "/profile/ski-days", "/notifications", "/invite/",
    )
    intentional = {
        "/capture-global-flash",
        "/capture-intentional-404",
        "/capture-intentional-500",
    }
    for row in MANIFEST:
        path = row["route_template"].split("?", 1)[0]
        assert path in intentional or path.startswith(supported), (row["capture_id"], path)