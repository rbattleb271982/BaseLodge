"""Focused BL-193 tests for the compact Home Next Trip module."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from flask import render_template
from unittest.mock import patch

from app import _count_home_next_trip_friends_going, app
from models import Friend, GuestStatus, ParticipantRole, SkiTripParticipant, db
from tests.conftest import _add_participant, _login, _make_trip, _make_user


def _connect(viewer, friend):
    db.session.add(Friend(user_id=viewer.id, friend_id=friend.id))


def _home_response(client, user_id):
    _login(client, user_id)
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=[],
    ), patch(
        "services.ideas_retrieval.get_home_ideas",
        return_value=[],
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ):
        return client.get("/home")


def _render_next_trip(start, end, *, today, friends=0):
    trip = SimpleNamespace(
        id=41,
        user_id=7,
        mountain="Test Peak",
        resort=None,
        start_date=start,
        end_date=end,
        attendance_start_date=start,
        attendance_end_date=end,
    )
    summary = {
        "next_trip": {
            "trip": trip,
            "is_owner": True,
            "friends_going_count": friends,
        }
    }
    with app.test_request_context():
        return render_template(
            "partials/home/_next_trip.html",
            home_summary=summary,
            home_today=today,
        )


def test_friend_count_is_one_bounded_going_only_aggregate(client):
    with app.app_context():
        viewer = _make_user("next-count-viewer")
        owner = _make_user("next-count-owner")
        going = _make_user("next-count-going")
        interested = _make_user("next-count-interested")
        pending = _make_user("next-count-pending")
        declined = _make_user("next-count-declined")
        removed = _make_user("next-count-removed")
        nonfriend = _make_user("next-count-nonfriend")
        trip = _make_trip(owner, is_public=False)

        for friend in (owner, going, interested, pending, declined, removed):
            _connect(viewer, friend)
        _add_participant(trip, going, GuestStatus.GOING)
        _add_participant(trip, interested, GuestStatus.INTERESTED)
        _add_participant(trip, pending, GuestStatus.PENDING)
        _add_participant(trip, declined, GuestStatus.DECLINED)
        _add_participant(trip, removed, GuestStatus.REMOVED)
        _add_participant(trip, nonfriend, GuestStatus.GOING)
        db.session.commit()
        trip_ref = SimpleNamespace(id=trip.id, user_id=trip.user_id)
        viewer_id = viewer.id
        friend_ids = [
            owner.id,
            going.id,
            going.id,
            interested.id,
            pending.id,
            declined.id,
            removed.id,
            viewer.id,
        ]

        statements = []

        def capture(_conn, _cursor, statement, parameters, _context, _executemany):
            statements.append((statement, parameters))

        engine = db.engine
        sa.event.listen(engine, "before_cursor_execute", capture)
        try:
            count = _count_home_next_trip_friends_going(
                trip_ref,
                friend_ids,
                viewer_id,
            )
        finally:
            sa.event.remove(engine, "before_cursor_execute", capture)

        assert count == 2
        select_statements = [
            statement for statement, _parameters in statements
            if statement.lstrip().upper().startswith("SELECT")
        ]
        assert len(select_statements) == 1
        assert "count(distinct(ski_trip_participant.user_id))" in (
            select_statements[0].lower()
        )
        assert "ski_trip_participant.trip_id" in select_statements[0].lower()


def test_owner_is_not_counted_when_not_a_direct_friend(client):
    with app.app_context():
        viewer = _make_user("next-nonfriend-viewer")
        owner = _make_user("next-nonfriend-owner")
        trip = _make_trip(owner)
        db.session.commit()

        assert _count_home_next_trip_friends_going(trip, [], viewer.id) == 0


def test_private_guest_trip_uses_effective_attendance_window_and_connected_owner(client):
    today = date.today()
    owner_start = today + timedelta(days=8)
    owner_end = today + timedelta(days=15)
    guest_start = today + timedelta(days=10)
    guest_end = today + timedelta(days=12)

    with app.app_context():
        viewer = _make_user("next-private-guest")
        owner = _make_user("next-private-owner")
        _connect(viewer, owner)
        trip = _make_trip(
            owner,
            mountain="Private Peak",
            start_date=owner_start,
            end_date=owner_end,
            is_public=False,
        )
        participant = _add_participant(trip, viewer, GuestStatus.GOING)
        participant.start_date = guest_start
        participant.end_date = guest_end
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id

    response = _home_response(client, viewer_id)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="your-next-trip"' in html
    assert "Private Peak" in html
    assert f"{guest_start.strftime('%b %-d')}–{guest_end.strftime('%-d')}" in html
    assert "2 nights" in html
    assert "1 friend going" in html
    assert "Trip in 10 days" in html
    assert f'href="/trips/{trip_id}"' in html
    assert "Actions to take" not in html


def test_home_omits_next_trip_card_when_no_trip(client):
    with app.app_context():
        viewer = _make_user("next-empty")
        db.session.commit()
        viewer_id = viewer.id

    response = _home_response(client, viewer_id)

    assert response.status_code == 200
    assert 'id="your-next-trip"' not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2027, 1, 13), date(2027, 1, 17), "Jan 13–17"),
        (date(2027, 1, 30), date(2027, 2, 2), "Jan 30–Feb 2"),
        (date(2027, 12, 30), date(2028, 1, 2), "Dec 30–Jan 2"),
    ],
)
def test_compact_date_ranges(start, end, expected):
    html = _render_next_trip(start, end, today=date(2027, 1, 1))

    assert expected in html


@pytest.mark.parametrize(
    ("days_until", "expected"),
    [
        (12, "Trip in 12 days"),
        (1, "Trip tomorrow"),
        (0, "Trip today"),
        (-2, "Trip today"),
    ],
)
def test_countdown_states(days_until, expected):
    today = date(2027, 1, 10)
    start = today + timedelta(days=days_until)
    end = max(start, today) + timedelta(days=1)

    html = _render_next_trip(start, end, today=today)

    assert expected in html


def test_night_and_friend_count_grammar():
    html = _render_next_trip(
        date(2027, 1, 10),
        date(2027, 1, 11),
        today=date(2027, 1, 1),
        friends=1,
    )
    assert "1 night" in html
    assert "1 friend going" in html

    html = _render_next_trip(
        date(2027, 1, 10),
        date(2027, 1, 14),
        today=date(2027, 1, 1),
        friends=3,
    )
    assert "4 nights" in html
    assert "3 friends going" in html