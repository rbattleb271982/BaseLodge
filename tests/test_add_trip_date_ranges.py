"""Regression guards for the add-trip date-range interaction."""

from datetime import date, timedelta
import json
from pathlib import Path
import re

import pytest

from app import app
from models import SkiTrip, db
from tests.conftest import _login, _make_resort, _make_trip, _make_user, form_post


ADD_TRIP_TEMPLATE = Path("templates/add_trip.html").read_text()


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_batch_creation_can_replace_terminal_retained_range(client, lifecycle_state):
    start = date.today() + timedelta(days=20)
    end = start + timedelta(days=2)
    with app.app_context():
        owner = _make_user(f"batch-terminal-owner-{lifecycle_state}")
        resort = _make_resort()
        retained = _make_trip(
            owner, resort=resort, start_date=start, end_date=end
        )
        retained.lifecycle_state = lifecycle_state
        db.session.commit()
        owner_id, resort_id, retained_id = owner.id, resort.id, retained.id

    _login(client, owner_id)
    response = form_post(client, "/add_trip", {
        "resort_id": str(resort_id),
        "date_ranges_json": json.dumps([{
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }]),
        "trip_status": "planning",
        "is_public": "on",
    })
    assert response.status_code == 302

    with app.app_context():
        matching = SkiTrip.query.filter_by(
            user_id=owner_id, start_date=start, end_date=end
        ).order_by(SkiTrip.id).all()
        assert {trip.id for trip in matching} != {retained_id}
        assert len(matching) == 2
        assert any((trip.lifecycle_state or "active") == "active" for trip in matching)


def test_completed_standard_selection_auto_stages_without_confirmation():
    assert re.search(
        r"// Same day \(day trip\) or after start — stage immediately for standard trips\."
        r".*?if \(!IS_GROUP_FLOW\) \{\s*confirmAddRange\(\);\s*\}",
        ADD_TRIP_TEMPLATE,
        re.DOTALL,
    )
    assert "showRangeConfirm" not in ADD_TRIP_TEMPLATE
    assert "hideRangeConfirm" not in ADD_TRIP_TEMPLATE
    assert "Add this range" not in ADD_TRIP_TEMPLATE
    assert "at-range-confirm" not in ADD_TRIP_TEMPLATE


def test_auto_staging_reuses_existing_range_lifecycle():
    confirm_start = ADD_TRIP_TEMPLATE.index("function confirmAddRange()")
    remove_start = ADD_TRIP_TEMPLATE.index("function removeRange(", confirm_start)
    confirm_body = ADD_TRIP_TEMPLATE[confirm_start:remove_start]

    assert "stagedRanges.push" in confirm_body
    assert "renderStagedList();" in confirm_body
    assert "updateSubmitCTA();" in confirm_body
    assert "startDateInput.value = endDateInput.value = '';" in confirm_body
    assert "updateCalendarClasses();" in confirm_body
    assert "updateRangeSummary();" in confirm_body


def test_standard_cta_requires_staged_range_and_mountain():
    cta_start = ADD_TRIP_TEMPLATE.index("function updateSubmitCTA()")
    cta_end = ADD_TRIP_TEMPLATE.index("function updateRangeSummary()", cta_start)
    cta_body = ADD_TRIP_TEMPLATE[cta_start:cta_end]

    assert "btn.disabled = (n === 0 || !selResortId);" in cta_body

    select_start = ADD_TRIP_TEMPLATE.index("function selectMountain(")
    clear_start = ADD_TRIP_TEMPLATE.index("function clearMountain(", select_start)
    calendar_start = ADD_TRIP_TEMPLATE.index("// ── Calendar helpers", clear_start)
    select_body = ADD_TRIP_TEMPLATE[select_start:clear_start]
    clear_body = ADD_TRIP_TEMPLATE[clear_start:calendar_start]

    assert "updateSubmitCTA();" in select_body
    assert "updateSubmitCTA();" in clear_body


def test_multi_range_remove_validation_and_save_contracts_remain():
    assert "function removeRange(idx)" in ADD_TRIP_TEMPLATE
    assert "removeRange(${i})" in ADD_TRIP_TEMPLATE
    assert "This date range is already added." in ADD_TRIP_TEMPLATE
    assert "This range overlaps with an already-staged date." in ADD_TRIP_TEMPLATE
    assert "date_ranges_json_input" in ADD_TRIP_TEMPLATE
    assert "stagedRanges.map(r => ({ start_date: r.startStr, end_date: r.endStr }))" in ADD_TRIP_TEMPLATE
    assert "if (stagedRanges.length === 0)" in ADD_TRIP_TEMPLATE


def test_group_flow_and_edit_flow_are_not_broadened():
    assert "const IS_GROUP_FLOW" in ADD_TRIP_TEMPLATE
    assert "if (!IS_GROUP_FLOW)" in ADD_TRIP_TEMPLATE
    assert "templates/trip_detail.html" not in ADD_TRIP_TEMPLATE