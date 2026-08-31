"""BL-63 — effective attendance dates on individual-presence surfaces."""

from datetime import date, timedelta

import app as app_module
import pytest

from app import (
    app,
    build_friend_at_mountain_card,
    build_trip_overlap_today_card,
    check_trip_invite_eligibility,
    format_trip_dates,
)
from models import Friend, GuestStatus, SkiTripParticipant, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _capture_template(monkeypatch):
    captured = {}

    def fake_render(template_name, **context):
        captured["template_name"] = template_name
        captured["context"] = context
        return "ok"

    monkeypatch.setattr(app_module, "render_template", fake_render)
    return captured


def _link_friends(user, friend):
    db.session.add_all([
        Friend(user_id=user.id, friend_id=friend.id),
        Friend(user_id=friend.id, friend_id=user.id),
    ])


def test_home_overlap_today_uses_effective_window_for_going_friend(client):
    today = date.today()
    with app.app_context():
        resort = _make_resort()
        user = _make_user("overlap-user")
        host = _make_user("overlap-host")
        friend = _make_user("overlap-friend")
        _link_friends(user, friend)
        _make_trip(
            user,
            resort=resort,
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
        )
        shared_trip = _make_trip(
            host,
            resort=resort,
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=3),
        )
        participant = _add_participant(shared_trip, friend, GuestStatus.GOING)
        participant.start_date = today + timedelta(days=1)
        participant.end_date = today + timedelta(days=2)
        db.session.commit()

        # Before a Going guest's personal start, the shared core range alone
        # must not make them physically present.
        assert build_trip_overlap_today_card(user, today, [friend.id]) is None

        participant.start_date = today
        participant.end_date = today
        db.session.commit()
        card = build_trip_overlap_today_card(user, today, [friend.id])
        assert card is not None
        assert card["friend_id"] == friend.id

        # After the personal end, the still-active shared trip must not keep
        # the friend in tomorrow's overlap result.
        assert build_trip_overlap_today_card(
            user, today + timedelta(days=1), [friend.id]
        ) is None

        # Private trip participation is not a visible friend-presence signal.
        shared_trip.is_public = False
        db.session.commit()
        assert build_trip_overlap_today_card(user, today, [friend.id]) is None


def test_home_friend_at_mountain_uses_effective_past_attendance(client):
    today = date.today()
    with app.app_context():
        resort = _make_resort()
        user = _make_user("history-user", wish_list_resorts=[resort.id])
        host = _make_user("history-host")
        friend = _make_user("history-friend")
        _link_friends(user, friend)
        _make_trip(
            user,
            resort=resort,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=5),
        )
        shared_trip = _make_trip(
            host,
            resort=resort,
            start_date=today - timedelta(days=4),
            end_date=today + timedelta(days=3),
        )
        participant = _add_participant(shared_trip, friend, GuestStatus.GOING)
        participant.start_date = today - timedelta(days=3)
        participant.end_date = today - timedelta(days=1)
        db.session.commit()

        # Before the personal start, this friend has not yet been at the
        # mountain even though the shared trip's core range has started.
        assert build_friend_at_mountain_card(
            user, today - timedelta(days=4), [friend.id]
        ) is None

        card = build_friend_at_mountain_card(user, today, [friend.id])
        assert card is not None
        assert card["friend_id"] == friend.id
        assert card["resort_id"] == resort.id

        # A private guest attendance range is not exposed through the card.
        shared_trip.is_public = False
        db.session.commit()
        assert build_friend_at_mountain_card(user, today, [friend.id]) is None


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_home_intelligence_ignores_terminal_trip_inputs(client, lifecycle_state):
    today = date.today()
    with app.app_context():
        resort = _make_resort()
        user = _make_user(f"terminal-intel-user-{lifecycle_state}",
                          wish_list_resorts=[resort.id])
        friend = _make_user(f"terminal-intel-friend-{lifecycle_state}")
        _link_friends(user, friend)

        user_today = _make_trip(
            user, resort=resort, start_date=today, end_date=today
        )
        friend_today = _make_trip(
            friend, resort=resort, start_date=today, end_date=today
        )
        user_future = _make_trip(
            user, resort=resort,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        friend_past = _make_trip(
            friend, resort=resort,
            start_date=today - timedelta(days=4),
            end_date=today - timedelta(days=2),
        )
        for trip in (user_today, friend_today, user_future, friend_past):
            trip.lifecycle_state = lifecycle_state
        db.session.commit()

        assert build_trip_overlap_today_card(user, today, [friend.id]) is None
        assert build_friend_at_mountain_card(user, today, [friend.id]) is None
        assert not check_trip_invite_eligibility(user.id, friend.id)


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_friend_profile_hides_terminal_future_trip_comparisons(client, lifecycle_state):
    today = date.today()
    with app.app_context():
        viewer = _make_user(f"profile-terminal-viewer-{lifecycle_state}")
        friend = _make_user(f"profile-terminal-friend-{lifecycle_state}")
        resort = _make_resort(f"Profile Terminal {lifecycle_state} Peak")
        trip = _make_trip(
            friend, resort=resort,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        trip.lifecycle_state = lifecycle_state
        _link_friends(viewer, friend)
        db.session.commit()
        viewer_id, friend_id = viewer.id, friend.id

    _login(client, viewer_id)
    html = client.get(f"/friends/{friend_id}").get_data(as_text=True)
    assert f"Profile Terminal {lifecycle_state} Peak" not in html


def test_my_trips_friend_grouping_uses_going_guest_effective_dates(client, monkeypatch):
    today = date.today()
    captured = _capture_template(monkeypatch)
    with app.app_context():
        resort = _make_resort()
        user = _make_user("list-user")
        host = _make_user("list-host")
        guest_friend = _make_user("list-guest")
        _link_friends(user, host)
        _link_friends(user, guest_friend)
        shared_trip = _make_trip(
            host,
            resort=resort,
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=7),
        )
        participant = _add_participant(shared_trip, guest_friend, GuestStatus.GOING)
        participant.start_date = today + timedelta(days=3)
        participant.end_date = today + timedelta(days=4)
        db.session.commit()
        user_id = user.id
        guest_id = guest_friend.id

    _login(client, user_id)
    response = client.get("/my-trips?tab=friends")
    assert response.status_code == 200

    rows = [
        row
        for month in captured["context"]["friends_trips_tab"]
        for destination in month["destinations"]
        for row in destination["rows"]
        if row["friend_id"] == guest_id
    ]
    assert len(rows) == 1
    assert rows[0]["trip_start"] == today + timedelta(days=3)
    assert rows[0]["trip_end"] == today + timedelta(days=4)
    trip_start = today + timedelta(days=3)
    trip_end = today + timedelta(days=4)
    end_format = "%b %-d" if trip_start.month != trip_end.month else "%-d"
    assert rows[0]["formatted_date"] == (
        f"{trip_start.strftime('%b %-d')}–"
        f"{trip_end.strftime(end_format)}"
    )


def test_trip_detail_participant_overlap_uses_each_going_guest_window(
    client, monkeypatch
):
    today = date.today()
    captured = _capture_template(monkeypatch)
    with app.app_context():
        resort = _make_resort()
        owner = _make_user("detail-owner")
        current_guest = _make_user("detail-current")
        other_guest = _make_user("detail-other")
        trip = _make_trip(
            owner,
            resort=resort,
            start_date=today,
            end_date=today + timedelta(days=6),
        )
        current_participant = _add_participant(trip, current_guest, GuestStatus.GOING)
        current_participant.start_date = today
        current_participant.end_date = today + timedelta(days=2)
        other_participant = _add_participant(trip, other_guest, GuestStatus.GOING)
        other_participant.start_date = today + timedelta(days=3)
        other_participant.end_date = today + timedelta(days=5)
        db.session.commit()
        current_guest_id = current_guest.id
        trip_id = trip.id
        other_participant_id = other_participant.id

    _login(client, current_guest_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    assert captured["context"]["participant_overlaps"] == []

    with app.app_context():
        other_participant = db.session.get(SkiTripParticipant, other_participant_id)
        other_participant.start_date = today + timedelta(days=2)
        db.session.commit()

    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    assert captured["context"]["participant_overlaps"] == [
        {"name": "Udetail", "days": 1}
    ]


def test_friend_trip_detail_uses_current_going_guest_effective_overlap(
    client, monkeypatch
):
    today = date.today()
    captured = _capture_template(monkeypatch)
    with app.app_context():
        resort = _make_resort()
        user = _make_user("friend-detail-user")
        friend = _make_user("friend-detail-owner")
        _link_friends(user, friend)
        trip = _make_trip(
            friend,
            resort=resort,
            start_date=today,
            end_date=today + timedelta(days=6),
        )
        participant = _add_participant(trip, user, GuestStatus.GOING)
        participant.start_date = today + timedelta(days=2)
        participant.end_date = today + timedelta(days=4)
        db.session.commit()
        user_id = user.id
        trip_id = trip.id

    _login(client, user_id)
    response = client.get(f"/friend-trip/{trip_id}")
    assert response.status_code == 200

    context = captured["context"]
    assert context["has_overlap"] is True
    assert context["overlap_days"] == 3
    assert format_trip_dates(context["trip"]) == format_trip_dates(
        context["trip"],
        start_date=today,
        end_date=today + timedelta(days=6),
    )