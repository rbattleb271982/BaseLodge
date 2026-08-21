"""BL-91 all-time, per-resort SkiDay totals in the owner's Mountains view."""

from datetime import date
import json
import re

import sqlalchemy as sa

from app import app
from models import Friend, SkiDay, db
from tests.conftest import (
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    form_post,
)


def _log_day(user, resort, ski_date, **kwargs):
    db.session.add(SkiDay(
        user_id=user.id,
        resort_id=resort.id,
        ski_date=ski_date,
        source=kwargs.pop("source", "user_confirmation"),
        **kwargs,
    ))
    db.session.commit()


def _logged_day_map(html):
    match = re.search(r"var RS_LOGGED_DAY_COUNTS = ({.*?});", html)
    assert match, "Mountains Visited should include its logged-day count map"
    return {int(resort_id): count for resort_id, count in json.loads(match.group(1)).items()}


def test_mountains_visited_shows_one_logged_day_for_one_explicit_ski_day(client):
    with app.app_context():
        user = _make_user("one-day")
        resort = _make_resort("One Day Mountain")
        _log_day(user, resort, date(2026, 1, 10))
        user_id, resort_id = user.id, resort.id

    _login(client, user_id)
    html = client.get("/mountains-visited").get_data(as_text=True)

    assert _logged_day_map(html) == {resort_id: 1}
    assert "logged day' + (count === 1 ? '' : 's')" in html


def test_mountains_visited_uses_all_time_counts_across_resorts_and_seasons(client):
    with app.app_context():
        user = _make_user("all-time")
        first = _make_resort("All Time First")
        second = _make_resort("All Time Second")
        _log_day(user, first, date(2024, 1, 15))
        _log_day(user, first, date(2025, 2, 16))
        _log_day(user, first, date(2026, 3, 17))
        _log_day(user, second, date(2026, 1, 18))
        user_id = user.id
        expected = {first.id: 3, second.id: 1}

    _login(client, user_id)
    assert _logged_day_map(client.get("/mountains-visited").get_data(as_text=True)) == expected


def test_logged_day_totals_change_after_bl99_delete_and_move(client):
    with app.app_context():
        user = _make_user("move-delete")
        first = _make_resort("Move Old Mountain")
        second = _make_resort("Move New Mountain")
        _log_day(user, first, date(2026, 1, 10))
        _log_day(user, first, date(2026, 1, 11))
        day_to_move = SkiDay.query.filter_by(
            user_id=user.id,
            resort_id=first.id,
            ski_date=date(2026, 1, 10),
        ).one()
        day_to_delete = SkiDay.query.filter_by(
            user_id=user.id,
            resort_id=first.id,
            ski_date=date(2026, 1, 11),
        ).one()
        user_id, first_id, second_id = user.id, first.id, second.id
        move_id, delete_id = day_to_move.id, day_to_delete.id

    _login(client, user_id)
    assert _logged_day_map(client.get("/mountains-visited").get_data(as_text=True)) == {
        first_id: 2,
    }
    assert form_post(
        client,
        f"/profile/ski-days/{move_id}/edit",
        {"ski_date": "2026-01-10", "resort_id": str(second_id)},
    ).status_code == 302
    assert form_post(client, f"/profile/ski-days/{delete_id}/delete").status_code == 302

    assert _logged_day_map(client.get("/mountains-visited").get_data(as_text=True)) == {
        second_id: 1,
    }


def test_manual_visited_mountain_without_ski_day_stays_visible_without_zero_count(client):
    with app.app_context():
        user = _make_user("manual-no-days")
        resort = _make_resort("Manual Only Mountain")
        user.visited_resort_ids = [resort.id]
        db.session.commit()
        user_id, resort_id = user.id, resort.id

    _login(client, user_id)
    html = client.get("/mountains-visited").get_data(as_text=True)

    assert str(resort_id) in html
    assert _logged_day_map(html) == {}
    assert "0 logged days" not in html


def test_logged_day_totals_are_isolated_from_other_users_and_trip_rsvps(client):
    with app.app_context():
        user = _make_user("isolated")
        other = _make_user("other")
        resort = _make_resort("Isolated Mountain")
        _log_day(user, resort, date(2026, 1, 10))
        _log_day(other, resort, date(2026, 1, 11))
        trip = _make_trip(other, resort=resort)
        user_id, resort_id = user.id, resort.id
        db.session.commit()

    _login(client, user_id)
    assert _logged_day_map(client.get("/mountains-visited").get_data(as_text=True)) == {
        resort_id: 1,
    }


def test_mountains_visited_uses_one_grouped_ski_day_query(client):
    with app.app_context():
        user = _make_user("query-count")
        first = _make_resort("Query First")
        second = _make_resort("Query Second")
        _log_day(user, first, date(2026, 1, 10))
        _log_day(user, second, date(2026, 1, 11))
        user_id = user.id
        engine = db.engine

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "ski_day" in statement.lower():
            statements.append(statement.lower())

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        _login(client, user_id)
        response = client.get("/mountains-visited")
        assert response.status_code == 200
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert "group by" in statements[0]


def test_friend_mountains_view_keeps_logged_day_counts_private(client):
    with app.app_context():
        viewer = _make_user("friend-viewer")
        friend = _make_user("friend-owner")
        resort = _make_resort("Private Count Mountain")
        db.session.add_all([
            Friend(user_id=viewer.id, friend_id=friend.id),
            Friend(user_id=friend.id, friend_id=viewer.id),
        ])
        _log_day(friend, resort, date(2026, 1, 10))
        viewer_id, friend_id = viewer.id, friend.id

    _login(client, viewer_id)
    html = client.get(f"/mountains-visited/{friend_id}").get_data(as_text=True)

    assert "RS_LOGGED_DAY_COUNTS" not in html
    assert "logged day" not in html