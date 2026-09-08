from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app import app
from models import db, Friend, User, UserAvailability
from services.open_dates import (
    get_available_dates_for_user,
    get_available_dates_for_users,
    get_open_date_matches,
    replace_current_availability,
)
from tests.conftest import _login, _make_user, form_post


def _future(days):
    return date.today() + timedelta(days=days)


def _current_rows(user_id):
    return UserAvailability.query.filter(
        UserAvailability.user_id == user_id,
        UserAvailability.date >= date.today(),
    ).order_by(UserAvailability.date).all()


def test_legacy_resolution_is_strict_deduplicated_and_current(client):
    valid_day = _future(10)
    with app.app_context():
        user = _make_user("legacy-contract")
        user.open_dates = [
            valid_day.isoformat(),
            valid_day.isoformat(),
            (date.today() - timedelta(days=1)).isoformat(),
            "2026-99-99",
            "not-a-date",
            123,
        ]
        db.session.commit()

        assert get_available_dates_for_user(user) == {valid_day.isoformat()}


def test_normalized_resolution_includes_today_and_excludes_past_and_inactive(client):
    today = date.today()
    future_day = _future(10)
    inactive_day = _future(11)
    with app.app_context():
        user = _make_user("normalized-contract", open_dates=[])
        db.session.add_all([
            UserAvailability(user_id=user.id, date=today, is_available=True),
            UserAvailability(user_id=user.id, date=future_day, is_available=True),
            UserAvailability(user_id=user.id, date=inactive_day, is_available=False),
            UserAvailability(
                user_id=user.id,
                date=today - timedelta(days=1),
                is_available=True,
            ),
        ])
        db.session.commit()

        assert get_available_dates_for_user(user) == {
            today.isoformat(),
            future_day.isoformat(),
        }


def test_mixed_resolution_uses_per_date_normalized_overlay(client):
    legacy_only_day = _future(10)
    normalized_only_day = _future(11)
    tombstoned_day = _future(12)
    with app.app_context():
        user = _make_user(
            "mixed-contract",
            open_dates=[
                legacy_only_day.isoformat(),
                tombstoned_day.isoformat(),
            ],
        )
        db.session.add_all([
            UserAvailability(
                user_id=user.id,
                date=normalized_only_day,
                is_available=True,
            ),
            UserAvailability(
                user_id=user.id,
                date=tombstoned_day,
                is_available=False,
            ),
        ])
        db.session.commit()

        expected = {
            legacy_only_day.isoformat(),
            normalized_only_day.isoformat(),
        }
        assert get_available_dates_for_user(user) == expected
        assert get_available_dates_for_users([user]) == {user.id: expected}


def test_historical_only_normalized_rows_preserve_future_legacy_dates(client):
    future_day = _future(10)
    with app.app_context():
        user = _make_user(
            "historical-contract",
            open_dates=[future_day.isoformat()],
        )
        db.session.add(UserAvailability(
            user_id=user.id,
            date=date.today() - timedelta(days=1),
            is_available=True,
        ))
        db.session.commit()

        assert get_available_dates_for_user(user) == {future_day.isoformat()}


def test_open_date_matching_batch_resolves_many_friends_in_one_query(client):
    shared_day = _future(10)
    with app.app_context():
        viewer = _make_user(
            "batch-match-viewer",
            open_dates=[shared_day.isoformat()],
        )
        friends = [
            _make_user(
                f"batch-match-friend-{index}",
                open_dates=[shared_day.isoformat()],
            )
            for index in range(3)
        ]
        for friend in friends:
            db.session.add_all([
                Friend(user_id=viewer.id, friend_id=friend.id),
                Friend(user_id=friend.id, friend_id=viewer.id),
            ])
        db.session.commit()

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "user_availability" in statement.lower():
                statements.append(statement.lower())

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            matches = get_open_date_matches(
                viewer,
                cached_my_dates={shared_day.isoformat()},
                cached_friends=friends,
            )
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)

        assert {match["friend_id"] for match in matches} == {
            friend.id for friend in friends
        }
        assert len(statements) == 1
        assert " in " in statements[0]


def test_writer_replaces_future_set_mirrors_json_and_preserves_history(client):
    old_day = _future(10)
    first_new_day = _future(20)
    second_new_day = _future(21)
    historical_day = date.today() - timedelta(days=5)
    with app.app_context():
        user = _make_user("writer-contract", open_dates=[old_day.isoformat()])
        db.session.add_all([
            UserAvailability(
                user_id=user.id,
                date=historical_day,
                is_available=True,
            ),
            UserAvailability(user_id=user.id, date=old_day, is_available=True),
            UserAvailability(
                user_id=user.id,
                date=first_new_day,
                is_available=False,
            ),
        ])
        db.session.commit()
        user_id = user.id

        saved = replace_current_availability(
            user,
            [
                second_new_day.isoformat(),
                first_new_day.isoformat(),
                second_new_day.isoformat(),
            ],
        )
        db.session.commit()

        assert saved == {
            first_new_day.isoformat(),
            second_new_day.isoformat(),
        }
        assert user.open_dates == [
            first_new_day.isoformat(),
            second_new_day.isoformat(),
        ]
        assert [(row.date, row.is_available) for row in _current_rows(user_id)] == [
            (first_new_day, True),
            (second_new_day, True),
        ]
        assert UserAvailability.query.filter_by(
            user_id=user_id,
            date=historical_day,
        ).one().is_available is True

        replace_current_availability(user, [second_new_day.isoformat()])
        db.session.commit()
        assert user.open_dates == [second_new_day.isoformat()]
        assert [row.date for row in _current_rows(user_id)] == [second_new_day]

        replace_current_availability(user, [])
        db.session.commit()
        assert user.open_dates == []
        assert _current_rows(user_id) == []
        assert get_available_dates_for_user(user) == set()


def test_writer_repeated_submission_is_idempotent(client):
    selected_day = _future(10)
    with app.app_context():
        user = _make_user("idempotent-contract", open_dates=[])
        replace_current_availability(user, [selected_day.isoformat()])
        db.session.commit()
        first_row_id = _current_rows(user.id)[0].id

        replace_current_availability(
            user,
            [selected_day.isoformat(), selected_day.isoformat()],
        )
        db.session.commit()

        rows = _current_rows(user.id)
        assert len(rows) == 1
        assert rows[0].id == first_row_id
        assert rows[0].is_available is True
        assert user.open_dates == [selected_day.isoformat()]


@pytest.mark.parametrize(
    "invalid_value",
    ["not-a-date", (date.today() - timedelta(days=1)).isoformat()],
)
def test_owner_route_rejects_invalid_set_without_mutation(client, invalid_value):
    original_day = _future(10)
    with app.app_context():
        user = _make_user(
            "invalid-owner-contract",
            open_dates=[original_day.isoformat()],
        )
        db.session.add(UserAvailability(
            user_id=user.id,
            date=original_day,
            is_available=True,
        ))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = form_post(
        client,
        "/add-open-dates",
        data={"selected_dates": f"{_future(20).isoformat()},{invalid_value}"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/add-open-dates")

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.open_dates == [original_day.isoformat()]
        assert [row.date for row in _current_rows(user_id)] == [original_day]


def test_owner_route_adds_and_reads_back_canonical_dates(client):
    first_day = _future(10)
    replacement_day = _future(20)
    historical_day = date.today() - timedelta(days=1)
    with app.app_context():
        user = _make_user(
            "owner-readback-contract",
            open_dates=[first_day.isoformat()],
        )
        db.session.add(UserAvailability(
            user_id=user.id,
            date=historical_day,
            is_available=True,
        ))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    response = form_post(
        client,
        "/add-open-dates",
        data={
            "selected_dates": (
                f"{first_day.isoformat()},{first_day.isoformat()}"
            ),
        },
    )
    assert response.status_code == 302

    with app.app_context():
        assert [row.date for row in _current_rows(user_id)] == [first_day]
        user = db.session.get(User, user_id)
        assert user.open_dates == [first_day.isoformat()]
        assert get_available_dates_for_user(user) == {first_day.isoformat()}

    editor = client.get("/add-open-dates")
    assert editor.status_code == 200
    assert f'const existingDates = ["{first_day.isoformat()}"];' in editor.get_data(
        as_text=True,
    )

    response = form_post(
        client,
        "/add-open-dates",
        data={"selected_dates": replacement_day.isoformat()},
    )
    assert response.status_code == 302
    editor = client.get("/add-open-dates")
    assert (
        f'const existingDates = ["{replacement_day.isoformat()}"];'
        in editor.get_data(as_text=True)
    )

    response = form_post(
        client,
        "/add-open-dates",
        data={"selected_dates": ""},
    )
    assert response.status_code == 302
    editor = client.get("/add-open-dates")
    assert "const existingDates = [];" in editor.get_data(as_text=True)

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.open_dates == []
        assert _current_rows(user_id) == []
        assert get_available_dates_for_user(user) == set()


def test_transaction_rollback_restores_rows_and_compatibility_mirror(client):
    original_day = _future(10)
    replacement_day = _future(20)
    with app.app_context():
        user = _make_user(
            "rollback-contract",
            open_dates=[original_day.isoformat()],
        )
        db.session.add(UserAvailability(
            user_id=user.id,
            date=original_day,
            is_available=True,
        ))
        db.session.commit()
        user_id = user.id

        replace_current_availability(user, [replacement_day.isoformat()])
        db.session.flush()
        db.session.rollback()

        user = db.session.get(user.__class__, user_id)
        assert user.open_dates == [original_day.isoformat()]
        assert [row.date for row in _current_rows(user_id)] == [original_day]


def test_owner_route_database_failure_rolls_back_both_representations(
    client,
    monkeypatch,
):
    original_day = _future(10)
    replacement_day = _future(20)
    with app.app_context():
        user = _make_user(
            "route-rollback-contract",
            open_dates=[original_day.isoformat()],
        )
        db.session.add(UserAvailability(
            user_id=user.id,
            date=original_day,
            is_available=True,
        ))
        db.session.commit()
        user_id = user.id

    _login(client, user_id)

    def fail_commit():
        raise SQLAlchemyError("simulated commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = form_post(
        client,
        "/add-open-dates",
        data={"selected_dates": replacement_day.isoformat()},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/add-open-dates")

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.open_dates == [original_day.isoformat()]
        assert [row.date for row in _current_rows(user_id)] == [original_day]