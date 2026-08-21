"""Web-only SkiDay correction flows and ownership boundaries."""

from datetime import date

import pytest

from app import app
from models import SkiDay, db
from tests.conftest import (
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    form_post,
)


def _setup_user_and_resorts():
    user = _make_user("correction-owner")
    other = _make_user("correction-other")
    first = _make_resort("Correction Mountain")
    second = _make_resort("Second Correction Mountain")
    db.session.commit()
    return user, other, first, second


def _add_day(user, resort, ski_date=date(2026, 1, 10), **kwargs):
    day = SkiDay(
        user_id=user.id,
        resort_id=resort.id,
        ski_date=ski_date,
        source=kwargs.pop("source", "user_confirmation"),
        **kwargs,
    )
    db.session.add(day)
    db.session.commit()
    return day


def test_profile_ski_days_page_lists_only_current_users_history(client):
    with app.app_context():
        user, other, first, _ = _setup_user_and_resorts()
        _add_day(user, first)
        _add_day(other, first, date(2026, 1, 11))
        user_id = user.id
        other_day_id = SkiDay.query.filter_by(user_id=other.id).one().id

    _login(client, user_id)
    response = client.get("/profile/ski-days")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Correction Mountain" in html
    assert f"/profile/ski-days/{other_day_id}/edit" not in html


def test_add_missed_ski_day_validates_and_persists(client):
    with app.app_context():
        user, _, first, _ = _setup_user_and_resorts()
        user_id = user.id
        first_id = first.id

    _login(client, user_id)
    response = form_post(
        client,
        "/profile/ski-days/add",
        {"ski_date": "2026-02-14", "resort_id": str(first_id)},
    )

    assert response.status_code == 302
    with app.app_context():
        day = SkiDay.query.filter_by(user_id=user_id).one()
        assert day.ski_date == date(2026, 2, 14)
        assert day.resort_id == first_id
        assert day.source == "user_confirmation"
        assert db.session.get(type(user), user_id).visited_resort_ids == [first_id]


@pytest.mark.parametrize(
    "form_data,expected_message",
    [
        ({"ski_date": "not-a-date", "resort_id": "1"}, "Enter a valid ski date."),
        ({"ski_date": "2026-02-14", "resort_id": "not-an-id"}, "Choose a valid resort."),
    ],
)
def test_add_ski_day_rejects_invalid_form_values(client, form_data, expected_message):
    with app.app_context():
        user, _, _, _ = _setup_user_and_resorts()
        user_id = user.id

    _login(client, user_id)
    response = form_post(
        client,
        "/profile/ski-days/add",
        form_data,
    )
    assert response.status_code == 302
    follow = client.get(response.headers["Location"])
    assert expected_message in follow.get_data(as_text=True)


def test_duplicate_ski_day_is_rejected_cleanly(client):
    with app.app_context():
        user, _, first, _ = _setup_user_and_resorts()
        _add_day(user, first)
        user_id = user.id
        first_id = first.id

    _login(client, user_id)
    response = form_post(
        client,
        "/profile/ski-days/add",
        {"ski_date": "2026-01-10", "resort_id": str(first_id)},
    )
    assert response.status_code == 302
    follow = client.get(response.headers["Location"])
    assert "That ski day is already logged." in follow.get_data(as_text=True)
    with app.app_context():
        assert SkiDay.query.filter_by(user_id=user_id).count() == 1


def test_edit_ski_day_date_and_resort_successfully(client):
    with app.app_context():
        user, _, first, second = _setup_user_and_resorts()
        day = _add_day(user, first)
        user_id, day_id = user.id, day.id
        first_id, second_id = first.id, second.id

    _login(client, user_id)
    response = form_post(
        client,
        f"/profile/ski-days/{day_id}/edit",
        {"ski_date": "2026-03-01", "resort_id": str(second_id)},
    )
    assert response.status_code == 302

    with app.app_context():
        updated = db.session.get(SkiDay, day_id)
        assert updated.ski_date == date(2026, 3, 1)
        assert updated.resort_id == second_id
        assert updated.source == "user_confirmation"
        assert db.session.get(type(user), user_id).visited_resort_ids == [
            first_id,
            second_id,
        ]


def test_edit_into_existing_duplicate_is_rejected_and_unrelated_day_stays_intact(client):
    with app.app_context():
        user, _, first, second = _setup_user_and_resorts()
        first_day = _add_day(user, first, date(2026, 1, 10))
        second_day = _add_day(user, second, date(2026, 2, 10))
        user_id, first_day_id = user.id, first_day.id
        first_id, second_id = first.id, second.id
        second_day_id = second_day.id

    _login(client, user_id)
    response = form_post(
        client,
        f"/profile/ski-days/{first_day_id}/edit",
        {"ski_date": "2026-02-10", "resort_id": str(second_id)},
    )
    assert response.status_code == 302
    follow = client.get(response.headers["Location"])
    assert "You already have that resort and date logged." in follow.get_data(
        as_text=True
    )

    with app.app_context():
        unchanged = db.session.get(SkiDay, first_day_id)
        other_day = db.session.get(SkiDay, second_day_id)
        assert (unchanged.resort_id, unchanged.ski_date) == (
            first_id,
            date(2026, 1, 10),
        )
        assert (other_day.resort_id, other_day.ski_date) == (
            second_id,
            date(2026, 2, 10),
        )


def test_delete_ski_day_hard_deletes_without_removing_visited_resort(client):
    with app.app_context():
        user, _, first, _ = _setup_user_and_resorts()
        day = _add_day(user, first)
        user_id, day_id, first_id = user.id, day.id, first.id

    _login(client, user_id)
    response = form_post(client, f"/profile/ski-days/{day_id}/delete")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(SkiDay, day_id) is None
        assert db.session.get(type(user), user_id).visited_resort_ids == [first_id]


def test_other_users_ski_day_cannot_be_edited_or_deleted(client):
    with app.app_context():
        user, other, first, second = _setup_user_and_resorts()
        other_day = _add_day(other, first)
        user_id, other_day_id, first_id = user.id, other_day.id, first.id
        other_id = other.id
        second_id = second.id

    _login(client, user_id)
    edit_response = form_post(
        client,
        f"/profile/ski-days/{other_day_id}/edit",
        {"ski_date": "2026-04-01", "resort_id": str(second_id)},
    )
    delete_response = form_post(
        client,
        f"/profile/ski-days/{other_day_id}/delete",
    )
    assert edit_response.status_code == 404
    assert delete_response.status_code == 404

    with app.app_context():
        stored = db.session.get(SkiDay, other_day_id)
        assert (stored.user_id, stored.resort_id, stored.ski_date) == (
            other_id,
            first_id,
            date(2026, 1, 10),
        )


def test_trip_linked_ski_day_remains_editable_and_keeps_provenance(client):
    with app.app_context():
        user, _, first, second = _setup_user_and_resorts()
        trip = _make_trip(user, resort=first)
        day = _add_day(
            user,
            first,
            trip_id=trip.id,
            source="trip_confirmation",
        )
        user_id, day_id, trip_id, second_id = user.id, day.id, trip.id, second.id

    _login(client, user_id)
    response = form_post(
        client,
        f"/profile/ski-days/{day_id}/edit",
        {"ski_date": "2026-04-01", "resort_id": str(second_id)},
    )
    assert response.status_code == 302

    with app.app_context():
        updated = db.session.get(SkiDay, day_id)
        assert updated.trip_id == trip_id
        assert updated.source == "trip_confirmation"
        assert updated.resort_id == second_id
