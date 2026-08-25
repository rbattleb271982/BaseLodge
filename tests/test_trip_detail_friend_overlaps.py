"""BL-54 — separate public friend-trip overlap heads-up on Trip Detail."""

from datetime import date, timedelta

import app as app_module
import pytest

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
    db.session.add(Friend(user_id=user.id, friend_id=friend.id))


def _name(user, first, last):
    user.first_name = first
    user.last_name = last
    return user


def _context_for_trip(client, monkeypatch, viewer_id, trip_id):
    captured = _capture_template(monkeypatch)
    _login(client, viewer_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    return captured["context"]


def test_organizer_friend_overlap_uses_inclusive_dates_and_safe_link(
    client, monkeypatch
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort(name="Vail")
        viewer = _name(_make_user("viewer"), "Alex", "Rider")
        friend = _name(_make_user("friend"), "Jonathan", "Smith")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        other_trip = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=8),
        )
        db.session.commit()
        viewer_id, trip_id, other_trip_id = viewer.id, trip.id, other_trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    overlaps = context["trip_friend_overlaps"]
    assert len(overlaps) == 1
    assert overlaps[0]["friend_name"] == "Jonathan Smith"
    assert overlaps[0]["friend_trip_id"] == other_trip_id
    assert overlaps[0]["overlap_days"] == 1
    assert overlaps[0]["overlap_dates"] == (today + timedelta(days=5)).strftime("%b %-d")
    assert overlaps[0]["friend_trip_linkable"] is True


def test_template_links_only_to_authorized_friend_owned_trip(client):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _make_user("friend")
        host = _make_user("host")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        friend_owned = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        host_owned = _make_trip(
            host, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        _add_participant(host_owned, friend, GuestStatus.GOING)
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id
        friend_owned_id, host_owned_id = friend_owned.id, host_owned.id

    _login(client, viewer_id)
    html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert f'href="/friend-trip/{friend_owned_id}"' in html
    assert f'href="/friend-trip/{host_owned_id}"' not in html


def test_going_guest_effective_dates_qualify_but_interested_and_private_do_not(
    client, monkeypatch
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        host = _make_user("host")
        going_friend = _name(_make_user("going"), "Going", "Friend")
        interested_friend = _name(_make_user("interested"), "Interested", "Friend")
        private_friend = _name(_make_user("private"), "Private", "Friend")
        for friend in (going_friend, interested_friend, private_friend):
            _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=6),
        )
        shared = _make_trip(
            host, resort=resort, start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=9),
        )
        going = _add_participant(shared, going_friend, GuestStatus.GOING)
        going.start_date = today + timedelta(days=4)
        going.end_date = today + timedelta(days=5)
        _add_participant(shared, interested_friend, GuestStatus.INTERESTED)
        private_trip = _make_trip(
            private_friend, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4), is_public=False,
        )
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    overlaps = context["trip_friend_overlaps"]
    assert [row["friend_name"] for row in overlaps] == ["Going Friend"]
    assert overlaps[0]["friend_trip_dates"] == (
        f"{(today + timedelta(days=4)).strftime('%b %-d')}–"
        f"{(today + timedelta(days=5)).strftime('%-d')}"
    )
    assert overlaps[0]["friend_trip_linkable"] is False


@pytest.mark.parametrize(
    "viewer_status",
    [GuestStatus.PENDING, GuestStatus.DECLINED, GuestStatus.REMOVED],
)
def test_inactive_viewer_records_on_other_trip_do_not_hide_overlap(
    client, monkeypatch, viewer_status
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _make_user("friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        other_trip = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        _add_participant(other_trip, viewer, viewer_status)
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    assert len(context["trip_friend_overlaps"]) == 1


def test_interested_viewer_can_receive_heads_up(client, monkeypatch):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        host = _make_user("host")
        friend = _make_user("friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            host, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        _add_participant(trip, viewer, GuestStatus.INTERESTED)
        _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    assert len(context["trip_friend_overlaps"]) == 1


def test_going_guest_null_dates_fall_back_to_core_and_ended_window_is_excluded(
    client, monkeypatch
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        host = _make_user("host")
        fallback_friend = _name(_make_user("fallback"), "Core", "Dates")
        ended_friend = _name(_make_user("ended"), "Ended", "Dates")
        _link_friends(viewer, fallback_friend)
        _link_friends(viewer, ended_friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=6),
        )
        shared = _make_trip(
            host, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=7),
        )
        _add_participant(shared, fallback_friend, GuestStatus.GOING)
        ended = _add_participant(shared, ended_friend, GuestStatus.GOING)
        ended.start_date = today
        ended.end_date = today + timedelta(days=1)
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    assert [row["friend_name"] for row in context["trip_friend_overlaps"]] == [
        "Core Dates"
    ]


def test_viewer_on_other_trip_and_nonmatching_or_historical_trips_are_suppressed(
    client, monkeypatch
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        other_resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _make_user("friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        shared_other = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=4),
        )
        _add_participant(shared_other, viewer, GuestStatus.GOING)
        _make_trip(
            friend, resort=other_resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
        )
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    assert _context_for_trip(
        client, monkeypatch, viewer_id, trip_id
    )["trip_friend_overlaps"] == []

    with app_module.app.app_context():
        current_trip = db.session.get(app_module.SkiTrip, trip_id)
        current_trip.end_date = today - timedelta(days=1)
        db.session.commit()

    assert _context_for_trip(
        client, monkeypatch, viewer_id, trip_id
    )["trip_friend_overlaps"] == []


def test_one_representative_per_friend_uses_overlap_then_start_then_trip_id(
    client, monkeypatch
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _name(_make_user("friend"), "Taylor", "Friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=8),
        )
        shorter = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
        )
        winner = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=4),
            end_date=today + timedelta(days=7),
        )
        tie_by_id = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=4),
            end_date=today + timedelta(days=7),
        )
        tie_later = _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=8),
        )
        db.session.commit()
        viewer_id, trip_id, winner_id = viewer.id, trip.id, winner.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    overlaps = context["trip_friend_overlaps"]
    assert len(overlaps) == 1
    assert overlaps[0]["friend_trip_id"] == winner_id


@pytest.mark.parametrize(
    ("other_start_offset", "other_end_offset", "expected_days"),
    [
        (2, 2, 1),  # shared first day
        (4, 4, 1),  # same-day trip within the window
        (3, 5, 3),  # multi-day inclusive overlap
    ],
)
def test_overlap_boundaries_are_inclusive(
    client, monkeypatch, other_start_offset, other_end_offset, expected_days
):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _make_user("friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=6),
        )
        _make_trip(
            friend, resort=resort,
            start_date=today + timedelta(days=other_start_offset),
            end_date=today + timedelta(days=other_end_offset),
        )
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    context = _context_for_trip(client, monkeypatch, viewer_id, trip_id)
    assert context["trip_friend_overlaps"][0]["overlap_days"] == expected_days


def test_multiple_friends_are_sorted_and_template_limits_initial_rows(client):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort(name="Vail")
        viewer = _make_user("viewer")
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=8),
        )
        friends = []
        for first, start_offset in (
            ("Zoe", 3), ("Aaron", 3), ("Mia", 4), ("Nina", 5),
        ):
            friend = _name(_make_user(first.lower()), first, "Tester")
            _link_friends(viewer, friend)
            _make_trip(
                friend, resort=resort,
                start_date=today + timedelta(days=start_offset),
                end_date=today + timedelta(days=start_offset + 1),
            )
            friends.append(friend)
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    _login(client, viewer_id)
    response = client.get(f"/trips/{trip_id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="td-friend-trip-overlaps"' in html
    assert "Friends at Vail during your trip" in html
    assert html.index("Aaron Tester") < html.index("Zoe Tester") < html.index("Mia Tester")
    assert "See all overlaps" in html
    assert "Nina Tester" in html
    assert "td-overlap-avatar" not in html


def test_no_overlap_renders_no_heads_up_markup(client):
    today = date.today()
    with app_module.app.app_context():
        resort = _make_resort()
        viewer = _make_user("viewer")
        friend = _make_user("friend")
        _link_friends(viewer, friend)
        trip = _make_trip(
            viewer, resort=resort, start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=3),
        )
        _make_trip(
            friend, resort=resort, start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=6),
        )
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    _login(client, viewer_id)
    html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert 'id="td-friend-trip-overlaps"' not in html