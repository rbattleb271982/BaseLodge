"""BL-53 — compact Trip Detail My setup coverage."""

from pathlib import Path
import re

import pytest

from app import app
from models import (
    db,
    EquipmentStatus,
    GuestStatus,
    LessonChoice,
    ParticipantEquipment,
    SkiTrip,
    SkiTripParticipant,
    User,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


TRIP_DETAIL_TEMPLATE = Path("templates/trip_detail.html").read_text()


def _trip_html(client, user_id, trip_id):
    _login(client, user_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _setup_trip(owner_equipment=None, participant_status=None):
    resort = _make_resort()
    owner = _make_user("trip-detail-owner", equipment_status=owner_equipment)
    trip = _make_trip(owner, resort=resort)
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip.id, user_id=owner.id
    ).one()
    participant.equipment_status = participant_status
    owner_id = owner.id
    trip_id = trip.id
    participant_id = participant.id
    db.session.commit()
    return owner_id, trip_id, participant_id


def test_compact_setup_chips_preserve_editable_controls(client):
    with app.app_context():
        owner_id, trip_id, _participant_id = _setup_trip(
            owner_equipment=EquipmentStatus.HAVE_OWN_EQUIPMENT.value
        )

    html = _trip_html(client, owner_id, trip_id)

    assert '<h2 class="td-setup-heading">My setup</h2>' in html
    assert 'class="td-setup-rows"' in html
    assert 'class="td-setup-row td-setup-row--readonly" aria-label="Riding"' in html
    assert 'class="td-setup-row-label">Riding</span>' in html
    assert re.search(r'class="td-setup-row-value">\s*Skier\s*</span>', html)
    assert 'id="td-pass-display-text"' in html
    assert 'id="equipmentSummaryText"' in html
    assert 'id="lesson-summary-text"' in html
    assert 'onclick="openPassSheet()"' in html
    assert 'id="equipmentHeader"' in html
    assert 'id="lessonHeader"' in html
    assert 'aria-controls="equipmentOverrideOptions"' in html
    assert 'aria-controls="lesson-options-inline"' in html
    assert html.index('>Riding</span>') < html.index('>Pass</span>')
    assert html.index('>Pass</span>') < html.index('>Equipment</span>')
    assert html.index('>Equipment</span>') < html.index('>Lessons</span>')
    assert 'td-setup-chips' not in html
    assert 'td-setup-chip' not in html

    # Source context is available in the editor, not permanently in the chip.
    assert 'id="equipmentSourceText"' in html
    assert 'id="equipmentSourceText">\n                    From profile' in html
    assert 'td-setup-row-label">Equipment</span>' in html
    assert 'Equipment</span>\n                        <span style="font-size: 11px' not in html


def test_active_participant_gets_editable_setup_chips(client):
    with app.app_context():
        _owner_id, trip_id, _owner_participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        guest = _make_user("trip-detail-guest")
        guest_participant = _add_participant(trip, guest, GuestStatus.INTERESTED)
        guest_participant.equipment_status = ParticipantEquipment.OWN
        guest_id = guest.id
        db.session.commit()

    html = _trip_html(client, guest_id, trip_id)

    assert 'id="equipmentHeader"' in html
    assert 'onclick="toggleEquipmentOverride()"' in html
    assert 'id="lessonHeader"' in html
    assert 'onclick="toggleLessonEditor()"' in html
    assert "Bringing own" in html
    assert 'id="equipmentOverrideOptions"' in html
    assert "From profile" in html
    assert "Have own equipment" in html
    assert "Renting equipment" in html
    assert 'id="td-pass-sheet"' in html

    pass_response = json_post(
        client,
        f"/api/trip/{trip_id}/update-pass",
        {"pass_type": "ikon"},
    )
    assert pass_response.status_code == 200
    assert pass_response.get_json()["pass_display"] == "Ikon"


@pytest.mark.parametrize(
    ("status", "label", "alternative", "alternative_value"),
    [
        (GuestStatus.INTERESTED, "Interested", "Going", "going"),
        (GuestStatus.GOING, "Going", "Interested", "interested"),
    ],
)
def test_active_guest_sees_explicit_rsvp_and_only_valid_alternative(
    client, status, label, alternative, alternative_value
):
    with app.app_context():
        _owner_id, trip_id, _owner_participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        guest = _make_user(f"trip-detail-{status.value}")
        _add_participant(trip, guest, status)
        guest_id = guest.id
        db.session.commit()

    html = _trip_html(client, guest_id, trip_id)
    self_rsvp = html.split('id="td-self-rsvp"', 1)[1].split("</details>", 1)[0]

    assert 'class="td-self-rsvp-label">Your RSVP</span>' in self_rsvp
    assert f'class="td-self-rsvp-status">{label}</span>' in self_rsvp
    assert f'aria-label="Your RSVP: {label}"' in self_rsvp
    assert f'name="response" value="{alternative_value}"' in self_rsvp
    assert f">{alternative}</button>" in self_rsvp
    assert 'class="td-self-rsvp-option td-self-rsvp-option--leave"' in self_rsvp
    assert "Not going" in self_rsvp

    invalid_value = "interested" if alternative_value == "going" else "going"
    assert f'name="response" value="{invalid_value}"' not in self_rsvp
    if status == GuestStatus.GOING:
        assert 'id="td-participant-date-sheet"' in html
    else:
        assert 'id="td-participant-date-sheet"' not in html


def test_pending_invitee_gets_view_only_setup_chips(client):
    with app.app_context():
        _owner_id, trip_id, _owner_participant_id = _setup_trip()
        invited = _make_user("trip-detail-pending")
        trip = SkiTrip.query.get(trip_id)
        _add_participant(trip, invited, GuestStatus.PENDING)
        invited_id = invited.id
        db.session.commit()

    html = _trip_html(client, invited_id, trip_id)

    assert html.count('td-setup-row td-setup-row--readonly') == 4
    assert 'onclick="openPassSheet()"' not in html
    assert 'onclick="toggleEquipmentOverride()"' not in html
    assert 'onclick="toggleLessonEditor()"' not in html
    assert 'id="td-pass-sheet"' not in html
    assert 'id="equipmentOverrideOptions"' not in html
    assert 'id="lesson-options-inline"' not in html


def test_equipment_display_precedence_and_clear_restores_profile(client):
    with app.app_context():
        owner_id, trip_id, participant_id = _setup_trip(
            owner_equipment=EquipmentStatus.NEEDS_RENTALS.value,
            participant_status=ParticipantEquipment.OWN,
        )

    html = _trip_html(client, owner_id, trip_id)
    assert "Bringing own" in html

    response = json_post(
        client,
        f"/api/trips/{trip_id}/participant/signals",
        {"equipment_status": "renting"},
    )
    assert response.status_code == 200
    assert response.get_json()["equipment_display"] == "Renting"

    response = json_post(
        client,
        f"/api/trips/{trip_id}/participant/signals",
        {"equipment_status": ""},
    )
    assert response.status_code == 200
    assert response.get_json()["equipment_display"] == "Renting"

    with app.app_context():
        assert SkiTripParticipant.query.get(participant_id).equipment_status is None


def test_equipment_profile_fallback_and_no_status_display(client):
    with app.app_context():
        own_user_id, own_trip_id, _ = _setup_trip(
            owner_equipment=EquipmentStatus.HAVE_OWN_EQUIPMENT.value
        )
        rental_user_id, rental_trip_id, _ = _setup_trip(
            owner_equipment=EquipmentStatus.NEEDS_RENTALS.value
        )
        unset_user_id, unset_trip_id, _ = _setup_trip(owner_equipment=None)

    assert "Bringing own" in _trip_html(client, own_user_id, own_trip_id)
    assert "Renting" in _trip_html(client, rental_user_id, rental_trip_id)
    assert "Not set" in _trip_html(client, unset_user_id, unset_trip_id)


@pytest.mark.parametrize(
    ("rider_types", "display_value"),
    [
        (["Skier"], "Skier"),
        (["Snowboarder"], "Snowboarder"),
        (["Skier", "Snowboarder"], "Skier + Snowboarder"),
    ],
)
def test_my_setup_riding_row_supports_rider_type_variants(
    client, rider_types, display_value
):
    with app.app_context():
        resort = _make_resort()
        owner = _make_user(f"trip-detail-{display_value}")
        owner.rider_types = rider_types
        trip = _make_trip(owner, resort=resort)
        owner_id = owner.id
        trip_id = trip.id
        db.session.commit()

    html = _trip_html(client, owner_id, trip_id)

    assert re.search(
        rf'class="td-setup-row-value">\s*{re.escape(display_value)}\s*</span>',
        html,
    )


def test_my_setup_distinguishes_missing_values_from_explicit_no_pass(
    client, monkeypatch
):
    monkeypatch.setattr(
        User,
        "is_core_profile_complete",
        property(lambda _user: True),
    )
    with app.app_context():
        resort = _make_resort()
        missing_owner = _make_user("trip-detail-missing-setup")
        missing_owner.pass_type = ""
        missing_owner.equipment_status = None
        missing_trip = _make_trip(missing_owner, resort=resort)

        explicit_owner = _make_user("trip-detail-explicit-no-pass")
        explicit_owner.pass_type = "no_pass"
        explicit_owner.equipment_status = None
        explicit_trip = _make_trip(explicit_owner, resort=resort)
        db.session.commit()

        missing_owner_id = missing_owner.id
        missing_trip_id = missing_trip.id
        explicit_owner_id = explicit_owner.id
        explicit_trip_id = explicit_trip.id

    missing_html = _trip_html(client, missing_owner_id, missing_trip_id)
    explicit_html = _trip_html(client, explicit_owner_id, explicit_trip_id)

    assert "Add pass" in missing_html
    assert "Set equipment" in missing_html
    assert "No pass" in explicit_html
    assert "Add pass" not in explicit_html
    assert "No lesson" in missing_html


def test_my_setup_edit_affordances_are_absent_for_pending_invitee(client):
    with app.app_context():
        owner_id, trip_id, _owner_participant_id = _setup_trip()
        invited = _make_user("trip-detail-pending-affordance")
        trip = SkiTrip.query.get(trip_id)
        _add_participant(trip, invited, GuestStatus.PENDING)
        invited_id = invited.id
        db.session.commit()

    html = _trip_html(client, invited_id, trip_id)

    setup_html = html.split('id="td-setup-card"', 1)[1].split(
        "</div><!-- /td-setup-card -->", 1
    )[0]
    assert 'class="td-setup-row td-setup-row--readonly"' in setup_html
    assert 'onclick="openPassSheet()"' not in setup_html
    assert 'onclick="toggleEquipmentOverride()"' not in setup_html
    assert 'onclick="toggleLessonEditor()"' not in setup_html


def test_lessons_and_equipment_use_existing_signal_endpoint(client):
    with app.app_context():
        owner_id, trip_id, _participant_id = _setup_trip()

    _login(client, owner_id)
    equipment_response = json_post(
        client,
        f"/api/trips/{trip_id}/participant/signals",
        {"equipment_status": "own"},
    )
    assert equipment_response.status_code == 200
    assert equipment_response.get_json()["equipment_display"] == "Bringing own"

    lesson_response = json_post(
        client,
        f"/api/trips/{trip_id}/participant/signals",
        {"taking_lesson": "yes"},
    )
    assert lesson_response.status_code == 200
    assert lesson_response.get_json()["lesson_display"] == "Yes"

    with app.app_context():
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).one()
        assert participant.equipment_status == ParticipantEquipment.OWN
        assert participant.taking_lesson == LessonChoice.YES


def test_setup_chips_keep_single_open_editor_contract():
    assert "{ content: 'equipmentOverrideOptions'" in TRIP_DETAIL_TEMPLATE
    assert "{ content: 'lesson-options-inline'" in TRIP_DETAIL_TEMPLATE
    assert "_TD_PANELS.forEach(p => _tdClosePanel(p));" in TRIP_DETAIL_TEMPLATE
    assert "function toggleEquipmentOverride()" in TRIP_DETAIL_TEMPLATE
    assert "function toggleLessonEditor()" in TRIP_DETAIL_TEMPLATE
    assert "sourceEl.textContent = value ? 'For this trip' : 'From profile';" in TRIP_DETAIL_TEMPLATE


def test_trip_detail_hub_has_summary_attention_and_progressive_rsvp_sections(client):
    with app.app_context():
        owner_id, trip_id, _participant_id = _setup_trip()

    html = _trip_html(client, owner_id, trip_id)

    assert 'class="page-container td-hub-page' in html
    assert 'id="td-attention-heading"' in html
    assert "Start planning together" in html
    assert 'id="td-setup-card"' in html
    assert 'id="td-rsvp-section"' in html
    assert 'class="td-rsvp-summary"' in html
    assert "Trip participants" in html
    assert html.index('<section class="td-hub-attention') < html.index(
        '<div class="td-setup-card" id="td-setup-card"'
    )
    assert html.index('<div class="td-setup-card" id="td-setup-card"') < html.index(
        '<details class="td-swg-card" id="td-rsvp-section"'
    )
    assert html.index('<details class="td-swg-card" id="td-rsvp-section"') < html.index(
        'id="td-planning-heading"'
    )


def test_trip_detail_hub_keeps_pending_invitee_view_only_and_sticky_rsvp(client):
    with app.app_context():
        _owner_id, trip_id, _owner_participant_id = _setup_trip()
        invited = _make_user("trip-detail-hub-pending")
        trip = SkiTrip.query.get(trip_id)
        _add_participant(trip, invited, GuestStatus.PENDING)
        invited_id = invited.id
        db.session.commit()

    html = _trip_html(client, invited_id, trip_id)

    assert 'class="page-container td-hub-page page-container-with-sticky' in html
    assert 'class="sticky-action-container visible"' in html
    assert 'id="td-attention-heading"' not in html
    assert 'id="td-planning-heading"' not in html
    assert 'id="td-edit-toggle-btn"' not in html
    assert 'onclick="openParticipantDateSheet()"' not in html
    assert 'id="td-self-rsvp"' not in html
    assert 'class="sticky-action-container visible"' in html
    assert 'name="response" value="going"' in html
    assert 'name="response" value="interested"' in html
    assert 'name="response" value="decline"' in html


def test_hub_attention_uses_profile_equipment_fallback(client):
    with app.app_context():
        owner_id, trip_id, _participant_id = _setup_trip(
            owner_equipment=EquipmentStatus.HAVE_OWN_EQUIPMENT.value
        )

    html = _trip_html(client, owner_id, trip_id)

    assert "Bringing own" in html
    assert "Set equipment" not in html
    assert '<section class="td-hub-people td-hub-section" aria-label="Trip participants"' in html


def test_trip_detail_people_uses_product_labels_counts_and_alpha_groups(client):
    with app.app_context():
        resort = _make_resort("Aspen")
        owner = _make_user("trip-detail-people-owner")
        owner.first_name = "Owner"
        owner.last_name = "Organizer"
        trip = _make_trip(owner, resort=resort)

        going_late = _make_user("trip-detail-people-zoe")
        going_late.first_name = "Zoe"
        going_late.last_name = "Zed"
        _add_participant(trip, going_late, GuestStatus.GOING)

        going_early = _make_user("trip-detail-people-anna")
        going_early.first_name = "Anna"
        going_early.last_name = "Alpha"
        _add_participant(trip, going_early, GuestStatus.GOING)

        pending = _make_user("trip-detail-people-pending")
        pending.first_name = "Mia"
        pending.last_name = "Pending"
        _add_participant(trip, pending, GuestStatus.PENDING)

        declined = _make_user("trip-detail-people-declined")
        declined.first_name = "Riley"
        declined.last_name = "Declined"
        _add_participant(trip, declined, GuestStatus.DECLINED)

        owner_id, trip_id = owner.id, trip.id
        db.session.commit()

    html = _trip_html(client, owner_id, trip_id)
    summary = html.split('id="td-rsvp-section"', 1)[1].split("</summary>", 1)[0]

    assert "Friends at this mountain" in html
    assert "See your friends' trips at Aspen." in html
    assert "Trip participants" in summary
    assert "2 Going · 1 Interested · 1 Pending · 1 Declined" in summary
    assert 'aria-controls="td-rsvp-details"' in summary
    assert 'id="td-rsvp-details"' in html

    heading_positions = [
        html.index('class="td-person-status-tag td-person-status-heading">Going'),
        html.index('class="td-person-status-tag td-person-status-heading">Interested'),
        html.index('class="td-person-status-tag td-person-status-heading">Pending'),
        html.index('class="td-person-status-tag td-person-status-heading">Declined'),
    ]
    assert heading_positions == sorted(heading_positions)
    assert html.index("Anna Alpha") < html.index("Zoe Zed")
    assert "Attending full trip" in html


def test_trip_detail_people_hides_zero_declined_count(client):
    with app.app_context():
        owner_id, trip_id, _participant_id = _setup_trip()

    html = _trip_html(client, owner_id, trip_id)
    summary = html.split('id="td-rsvp-section"', 1)[1].split("</summary>", 1)[0]

    assert "1 Interested" in summary
    assert "Declined" not in summary


def test_trip_detail_people_keeps_attendance_dates_owner_only(client):
    with app.app_context():
        owner_id, trip_id, _owner_participant_id = _setup_trip()
        trip = SkiTrip.query.get(trip_id)
        guest = _make_user("trip-detail-people-going")
        guest.first_name = "Going"
        guest.last_name = "Guest"
        _add_participant(trip, guest, GuestStatus.GOING)
        guest_id = guest.id
        db.session.commit()

    owner_html = _trip_html(client, owner_id, trip_id)
    guest_html = _trip_html(client, guest_id, trip_id)

    assert "Attending full trip" in owner_html
    assert 'data-attendance-dates="true"' in owner_html
    assert 'data-attendance-dates="true"' not in guest_html


def test_trip_detail_people_rows_use_mobile_safe_wrapping():
    assert "overflow-wrap: anywhere" in TRIP_DETAIL_TEMPLATE
    assert "flex-wrap: wrap" in TRIP_DETAIL_TEMPLATE
    assert ".td-person-actions" in TRIP_DETAIL_TEMPLATE