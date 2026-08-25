"""BL-52 — shared Trip Detail Stay coverage."""

from datetime import date, timedelta

import pytest

import app as app_module
from app import app
from models import GuestStatus, SkiTrip, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


def _trip_html(client, user_id, trip_id):
    _login(client, user_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _setup_trip(**trip_kwargs):
    resort = _make_resort()
    owner = _make_user("stay-owner")
    trip = _make_trip(owner, resort=resort, **trip_kwargs)
    db.session.commit()
    return owner.id, trip.id


def test_day_trip_has_no_stay_ui_even_when_stay_data_exists(client):
    with app.app_context():
        today = date.today() + timedelta(days=60)
        owner_id, trip_id = _setup_trip(
            start_date=today,
            end_date=today,
            stay_name="Day trip hotel",
            stay_description="Should stay hidden",
            accommodation_link="https://example.com/day-trip",
        )

    html = _trip_html(client, owner_id, trip_id)

    assert 'id="td-stay-heading"' not in html
    assert "Add Stay" not in html
    assert "Day trip hotel" not in html
    assert "View property" not in html


def test_overnight_owner_sees_compact_add_stay_but_no_empty_card(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip()

    html = _trip_html(client, owner_id, trip_id)

    assert 'id="td-stay-heading"' in html
    assert "Add Stay" in html
    assert 'class="td-stay-card"' not in html


def test_overnight_active_participant_sees_no_empty_stay_state(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip()
        trip = db.session.get(SkiTrip, trip_id)
        guest = _make_user("stay-interested")
        _add_participant(trip, guest, GuestStatus.INTERESTED)
        guest_id = guest.id
        db.session.commit()

    html = _trip_html(client, guest_id, trip_id)

    assert 'id="td-stay-heading"' not in html
    assert "Add Stay" not in html


def test_organizer_can_create_name_only_stay(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {"stay_name": "The Hythe"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "stay_name": "The Hythe",
        "stay_description": None,
        "accommodation_link": None,
    }
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.stay_name == "The Hythe"
        assert trip.stay_description is None
        assert trip.accommodation_link is None

    html = _trip_html(client, owner_id, trip_id)
    assert "The Hythe" in html
    assert "View property" not in html


def test_organizer_can_create_stay_with_description_and_url(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip()

    _login(client, owner_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {
            "stay_name": "Marriott Vail",
            "stay_description": "Check-in after 4 PM",
            "accommodation_link": "  https://www.marriott.com/vail  ",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["stay_name"] == "Marriott Vail"
    assert response.get_json()["stay_description"] == "Check-in after 4 PM"
    assert response.get_json()["accommodation_link"] == "https://www.marriott.com/vail"
    html = _trip_html(client, owner_id, trip_id)
    assert "Marriott Vail" in html
    assert "Check-in after 4 PM" in html
    assert 'href="https://www.marriott.com/vail"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert "View property" in html


def test_organizer_can_edit_and_clear_stay(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip(
            stay_name="Old rental",
            stay_description="Old details",
            accommodation_link="https://example.com/old",
        )

    _login(client, owner_id)
    edit_response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {
            "stay_name": "Airbnb on Gore Creek",
            "stay_description": "Use the rear entrance",
            "accommodation_link": "https://example.com/new",
        },
    )
    assert edit_response.status_code == 200

    clear_response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {"clear": True},
    )
    assert clear_response.status_code == 200
    assert clear_response.get_json() == {
        "success": True,
        "stay_name": None,
        "stay_description": None,
        "accommodation_link": None,
    }

    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.stay_name is None
        assert trip.stay_description is None
        assert trip.accommodation_link is None

    html = _trip_html(client, owner_id, trip_id)
    assert "Airbnb on Gore Creek" not in html
    assert "Add Stay" in html


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        ({"stay_name": "   "}, "Stay name is required."),
        ({"stay_name": "x" * 201}, "Stay name cannot exceed 200 characters."),
        (
            {"stay_name": "Valid", "stay_description": "x" * 501},
            "Stay description cannot exceed 500 characters.",
        ),
        (
            {"stay_name": "Valid", "accommodation_link": "example.com/stay"},
            "Link must start with http:// or https://",
        ),
        (
            {"stay_name": "Valid", "accommodation_link": "javascript:alert(1)"},
            "Link must start with http:// or https://",
        ),
    ],
)
def test_invalid_stay_save_rejected_without_partial_persistence(
    client, payload, expected_error
):
    with app.app_context():
        _owner_id, trip_id = _setup_trip(
            stay_name="Existing Stay",
            stay_description="Keep this",
            accommodation_link="https://example.com/existing",
        )

    _login(client, _owner_id)
    response = json_post(client, f"/api/trip/{trip_id}/stay", payload)

    assert response.status_code == 400
    assert response.get_json()["error"] == expected_error
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.stay_name == "Existing Stay"
        assert trip.stay_description == "Keep this"
        assert trip.accommodation_link == "https://example.com/existing"


def test_active_going_and_interested_participants_view_but_cannot_mutate_stay(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip(
            stay_name="Rental house near Lionshead",
            stay_description="Shared front door code separately",
        )
        trip = db.session.get(SkiTrip, trip_id)
        going = _make_user("stay-going")
        interested = _make_user("stay-interested-viewer")
        _add_participant(trip, going, GuestStatus.GOING)
        _add_participant(trip, interested, GuestStatus.INTERESTED)
        going_id = going.id
        interested_id = interested.id
        db.session.commit()

    assert "Rental house near Lionshead" in _trip_html(client, going_id, trip_id)
    assert "Rental house near Lionshead" in _trip_html(client, interested_id, trip_id)

    _login(client, going_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {"stay_name": "Guest overwrite"},
    )
    assert response.status_code == 403
    assert "organizer" in response.get_json()["error"].lower()

    with app.app_context():
        assert db.session.get(SkiTrip, trip_id).stay_name == "Rental house near Lionshead"


def test_pending_invitee_does_not_see_stay_and_keeps_sticky_rsvp(client):
    with app.app_context():
        _owner_id, trip_id = _setup_trip(stay_name="Private condo")
        trip = db.session.get(SkiTrip, trip_id)
        pending = _make_user("stay-pending")
        _add_participant(trip, pending, GuestStatus.PENDING)
        pending_id = pending.id
        db.session.commit()

    html = _trip_html(client, pending_id, trip_id)

    assert 'id="td-stay-heading"' not in html
    assert "Private condo" not in html
    assert "Add Stay" not in html
    assert 'class="sticky-action-container visible"' in html
    assert 'value="going"' in html


@pytest.mark.parametrize("status", [GuestStatus.DECLINED, GuestStatus.REMOVED])
def test_declined_and_removed_viewers_remain_denied(client, status):
    with app.app_context():
        _owner_id, trip_id = _setup_trip(stay_name="Hidden stay")
        trip = db.session.get(SkiTrip, trip_id)
        viewer = _make_user(f"stay-{status.value}")
        _add_participant(trip, viewer, status)
        viewer_id = viewer.id
        db.session.commit()

    _login(client, viewer_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 404


def test_historical_authorized_participant_sees_saved_stay(client):
    with app.app_context():
        start = date.today() - timedelta(days=8)
        owner_id, trip_id = _setup_trip(
            start_date=start,
            end_date=start + timedelta(days=3),
            stay_name="Historical lodge",
        )
        trip = db.session.get(SkiTrip, trip_id)
        guest = _make_user("stay-history")
        _add_participant(trip, guest, GuestStatus.GOING)
        guest_id = guest.id
        db.session.commit()

    assert "Historical lodge" in _trip_html(client, owner_id, trip_id)
    assert "Historical lodge" in _trip_html(client, guest_id, trip_id)


def test_legacy_accommodation_values_do_not_become_named_stay(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip(
            accommodation_status="hotel",
            accommodation_link="https://example.com/legacy",
        )

    html = _trip_html(client, owner_id, trip_id)

    assert 'id="td-stay-heading"' in html
    assert "Add Stay" in html
    assert "View property" not in html
    assert "https://example.com/legacy" not in html


def test_legacy_accommodation_writer_rejects_unsafe_link_without_partial_save(client):
    with app.app_context():
        owner_id, trip_id = _setup_trip(
            accommodation_status="hotel",
            accommodation_link="https://example.com/legacy",
        )

    _login(client, owner_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/accommodation",
        {"status": "hotel", "link": "javascript:alert(1)"},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Link must start with http:// or https://"
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.accommodation_status == "hotel"
        assert trip.accommodation_link == "https://example.com/legacy"


def test_legacy_accommodation_writer_cannot_change_named_stay_or_notify(
    client, monkeypatch
):
    with app.app_context():
        owner_id, trip_id = _setup_trip(
            stay_name="The Hythe",
            accommodation_status="hotel",
            accommodation_link="https://example.com/the-hythe",
        )

    emitted_events = []
    monkeypatch.setattr(
        app_module,
        "emit_messaging_event",
        lambda **kwargs: emitted_events.append(kwargs),
    )
    _login(client, owner_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/accommodation",
        {"status": "airbnb", "link": "https://example.com/changed"},
    )

    assert response.status_code == 409
    assert response.get_json()["message"] == "Manage this trip's Stay from Trip Detail."
    assert emitted_events == []
    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        assert trip.stay_name == "The Hythe"
        assert trip.accommodation_status == "hotel"
        assert trip.accommodation_link == "https://example.com/the-hythe"


def test_stay_save_is_silent(client, monkeypatch):
    with app.app_context():
        owner_id, trip_id = _setup_trip()

    emitted_events = []
    monkeypatch.setattr(
        app_module,
        "emit_messaging_event",
        lambda **kwargs: emitted_events.append(kwargs),
    )
    _login(client, owner_id)
    response = json_post(
        client,
        f"/api/trip/{trip_id}/stay",
        {"stay_name": "Quiet lodge"},
    )

    assert response.status_code == 200
    assert emitted_events == []