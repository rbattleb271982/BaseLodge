"""Focused presentation and route contracts for BL-198 and BL-207."""

import os
from pathlib import Path
from unittest.mock import patch

from app import app
from models import db
from tests.conftest import _login, _make_resort, _make_user


IDENTITY_TEMPLATE = Path("templates/identity_setup.html").read_text()
ADMIN_RESORT_TEMPLATE = Path("templates/admin_resort_ops.html").read_text()


def _step_source(step_number):
    start = IDENTITY_TEMPLATE.index(f'id="ob-step-{step_number}"')
    if step_number == 3:
        return IDENTITY_TEMPLATE[start:]
    end = IDENTITY_TEMPLATE.index(f'id="ob-step-{step_number + 1}"', start)
    return IDENTITY_TEMPLATE[start:end]


def test_last_question_callout_is_only_on_step_three_and_precedes_counter():
    step_one = _step_source(1)
    step_two = _step_source(2)
    step_three = _step_source(3)

    assert "Last Question!" not in step_one
    assert "Last Question!" not in step_two
    assert step_three.count("Last Question!") == 1
    assert (
        step_three.index('class="ob-progress"')
        < step_three.index('onclick="goBack(3)"')
        < step_three.index("Last Question!")
        < step_three.index("Step 3 of 3")
    )


def test_step_three_keeps_progress_back_location_and_finish_contracts():
    step_three = _step_source(3)

    assert step_three.count('class="ob-seg on"') == 3
    assert 'onclick="goBack(3)"' in step_three
    assert "Which state do you live in?" in step_three
    assert "Pick your state or province." in step_three
    assert 'id="state-select"' in step_three
    assert 'id="cta-3"' in step_three
    assert ">Finish</button>" in step_three


def test_pass_step_has_three_semantic_groups_with_complete_ordered_membership():
    step_two = _step_source(2)
    expected_groups = [
        (
            'id="pass-group-no-pass-yet"',
            ["no_pass_yet"],
        ),
        (
            'id="pass-group-epic-ikon"',
            ["epic", "ikon"],
        ),
        (
            'id="pass-group-other"',
            [
                "no_pass",
                "indy",
                "mountain_collective",
                "powder_alliance",
                "freedom",
                "ski_california",
                "other",
            ],
        ),
    ]

    assert step_two.count('<fieldset class="ob-pass-group"') == 3
    positions = []
    all_values = []
    for index, (group_id, values) in enumerate(expected_groups):
        start = step_two.index(group_id)
        end = (
            step_two.index(expected_groups[index + 1][0], start)
            if index + 1 < len(expected_groups)
            else step_two.index('class="ob-footer"', start)
        )
        group_source = step_two[start:end]
        positions.append(start)
        all_values.extend(values)
        value_positions = [
            group_source.index(f'data-val="{value}"') for value in values
        ]
        assert value_positions == sorted(value_positions)

    assert positions == sorted(positions)
    assert sorted(all_values) == sorted(
        [
            "no_pass_yet",
            "no_pass",
            "epic",
            "ikon",
            "indy",
            "mountain_collective",
            "powder_alliance",
            "freedom",
            "ski_california",
            "other",
        ]
    )


def test_pass_controls_keep_accessible_selection_and_interaction_contracts():
    step_two = _step_source(2)

    assert step_two.count('data-grp="pass"') == 10
    assert step_two.count('aria-pressed="false"') == 10
    assert step_two.count('class="ob-pill ob-pill--exclusive"') == 2
    assert 'id="pass-cap-hint" aria-live="polite"' in step_two
    assert 'id="h-pass"' not in step_two
    assert 'id="cta-2" disabled onclick="goNext(2)"' in step_two
    assert 'onclick="goBack(2)"' in step_two

    assert "var PASS_REAL_MAX = 3;" in IDENTITY_TEMPLATE
    assert "var OB_PASS_EXCLUSIVE = ['no_pass', 'no_pass_yet'];" in IDENTITY_TEMPLATE
    assert "pill.setAttribute('aria-pressed', selected ? 'true' : 'false');" in IDENTITY_TEMPLATE
    assert "passSelected.join(',')" in IDENTITY_TEMPLATE


def test_obsolete_duplicate_route_and_admin_link_are_removed():
    assert "debug_resort_duplicates" not in app.view_functions
    assert "/admin/debug-resort-duplicates" not in {
        rule.rule for rule in app.url_map.iter_rules()
    }
    assert "/admin/debug-resort-duplicates" not in ADMIN_RESORT_TEMPLATE
    assert 'href="/admin/resorts/duplicates"' in ADMIN_RESORT_TEMPLATE


def test_permanent_duplicate_route_remains_login_protected(client):
    response = client.get("/admin/resorts/duplicates")

    assert response.status_code == 302
    assert "/auth" in response.headers["Location"]


def test_permanent_duplicate_route_remains_admin_protected(client):
    with app.app_context():
        user = _make_user("bl207-non-admin")
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": ""}):
        response = client.get("/admin/resorts/duplicates")

    assert response.status_code == 403


def test_permanent_duplicate_route_groups_normalized_resorts(client):
    with app.app_context():
        admin = _make_user("bl207-admin")
        first = _make_resort("Test Peak")
        first.slug = "bl207-test-peak-one"
        first.state_code = "co"
        first.country_code = None
        second = _make_resort(" test peak ")
        second.slug = "bl207-test-peak-two"
        second.state_code = " CO "
        second.country_code = "us"
        db.session.commit()
        admin_id, admin_email = admin.id, admin.email

    _login(client, admin_id)
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": admin_email}):
        response = client.get("/admin/resorts/duplicates")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["duplicate_group_count"] == 1
    assert body["total_duplicate_rows"] == 2
    assert body["groups"][0]["name"] == "test peak"
    assert body["groups"][0]["state_code"] == "CO"
    assert body["groups"][0]["country_code"] == "US"
    assert {resort["slug"] for resort in body["groups"][0]["resorts"]} == {
        "bl207-test-peak-one",
        "bl207-test-peak-two",
    }