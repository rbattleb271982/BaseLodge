"""Focused BL-173 Stage 2 Group Trip contracts."""

from datetime import date, timedelta
from pathlib import Path

from app import app
from conftest import _TEST_CSRF, _login, _make_user, form_post, json_post
from models import (
    AccommodationStatus,
    Friend,
    GroupTrip,
    GuestStatus,
    TripGuest,
    db,
)


SOURCE = Path("templates/group_trip_detail.html").read_text()
UTILITY = Path("static/js/bl-targeted-refresh.js").read_text()


def _trip(host):
    trip = GroupTrip(
        host_id=host.id,
        title="Stage 2",
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=12),
    )
    db.session.add(trip)
    db.session.flush()
    return trip


def test_group_trip_regions_and_shared_engine_contract():
    for region in ("accommodation", "transportation", "guests", "invite-controls"):
        assert SOURCE.count(f'data-gtd-region="{region}"') >= 1
    assert SOURCE.count('data-gtd-targeted-form="guests,invite-controls"') == 2
    assert "window.BLTargetedRefresh.create" in SOURCE
    assert "window.gtdRefreshRegions = _gtdRefreshController.refresh" in SOURCE
    assert "location.reload" not in SOURCE
    assert "Capacitor" not in SOURCE
    assert "setTimeout" not in UTILITY
    assert "retry" not in UTILITY.lower()


def test_status_failures_restore_only_canonical_status_regions():
    assert "await window.gtdRefreshRegions([region])" in SOURCE
    assert "'accommodation'" in SOURCE
    assert "'transportation'" in SOURCE
    assert "'X-CSRF-Token': _gtdCsrf" in SOURCE


def test_accommodation_requires_csrf_and_host(client):
    with app.app_context():
        host, guest = _make_user("gtd-host"), _make_user("gtd-guest")
        trip = _trip(host)
        db.session.commit()
        host_id, guest_id, trip_id = host.id, guest.id, trip.id

    _login(client, host_id)
    assert client.post(
        f"/group-trip/{trip_id}/accommodation",
        json={"accommodation_status": "booked"},
    ).status_code == 403

    _login(client, guest_id)
    assert json_post(
        client,
        f"/group-trip/{trip_id}/accommodation",
        {"accommodation_status": "booked"},
    ).status_code == 403


def test_accommodation_success_and_validation(client):
    with app.app_context():
        host = _make_user("gtd-accommodation")
        trip = _trip(host)
        db.session.commit()
        host_id, trip_id = host.id, trip.id

    _login(client, host_id)
    response = json_post(
        client,
        f"/group-trip/{trip_id}/accommodation",
        {"accommodation_status": "booked"},
    )
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(GroupTrip, trip_id).accommodation_status == AccommodationStatus.BOOKED

    response = json_post(
        client,
        f"/group-trip/{trip_id}/accommodation",
        {"accommodation_status": "invalid"},
    )
    assert response.status_code == 400


def test_targeted_host_invite_and_guest_removal_keep_current_page(client):
    with app.app_context():
        host, friend = _make_user("gtd-inviter"), _make_user("gtd-friend")
        trip = _trip(host)
        db.session.add_all([
            Friend(user_id=host.id, friend_id=friend.id),
            Friend(user_id=friend.id, friend_id=host.id),
        ])
        db.session.commit()
        host_id, friend_id, trip_id = host.id, friend.id, trip.id

    _login(client, host_id)
    response = client.post(
        f"/group-trip/{trip_id}/invite",
        data={"friend_id": friend_id, "csrf_token": _TEST_CSRF},
        headers={"X-Group-Trip-Refresh": "regions"},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.get_json()["message"].startswith("Invited ")

    with app.app_context():
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=friend_id
        ).one()
        assert guest.status == GuestStatus.INVITED
        guest_id = guest.id

    response = client.post(
        f"/group-trip/{trip_id}/remove-guest/{guest_id}",
        data={"csrf_token": _TEST_CSRF},
        headers={"X-Group-Trip-Refresh": "regions"},
    )
    assert response.status_code == 200
    assert response.get_json()["message"].startswith("Removed ")


def test_targeted_invite_validation_is_non_success_without_redirect(client):
    with app.app_context():
        host = _make_user("gtd-invalid-invite")
        trip = _trip(host)
        db.session.commit()
        host_id, trip_id = host.id, trip.id

    _login(client, host_id)
    response = client.post(
        f"/group-trip/{trip_id}/invite",
        data={"friend_id": "", "csrf_token": _TEST_CSRF},
        headers={"X-Group-Trip-Refresh": "regions"},
    )
    assert response.status_code == 400
    assert response.get_json()["success"] is False