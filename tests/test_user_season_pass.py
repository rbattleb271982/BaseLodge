"""Season-specific pass-history foundation regressions."""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app import app
from models import db, User, UserSeasonPass
from services.ski_seasons import (
    get_ski_season_label,
    get_ski_season_start_year,
    get_ski_season_window,
    get_ski_season_year,
)
from services.user_season_passes import (
    get_user_pass_for_season,
    upsert_user_season_pass,
)
from tests.conftest import _login, _make_user, form_post, json_post


@pytest.fixture
def pass_user(client):
    with app.app_context():
        user = _make_user("season-pass")
        db.session.commit()
        return user.id


@pytest.mark.parametrize(
    ("value", "years", "start_year", "window", "label"),
    [
        (
            date(2027, 5, 31),
            (2026, 2027),
            2026,
            (date(2026, 6, 1), date(2027, 5, 31)),
            "2026/27",
        ),
        (
            date(2027, 6, 1),
            (2027, 2028),
            2027,
            (date(2027, 6, 1), date(2028, 5, 31)),
            "2027/28",
        ),
    ],
)
def test_canonical_season_boundaries(value, years, start_year, window, label):
    assert get_ski_season_year(value) == years
    assert get_ski_season_start_year(value) == start_year
    assert get_ski_season_window(value) == window
    assert get_ski_season_label(value) == label


def test_same_season_correction_and_explicit_no_pass_update_one_row(
        client, pass_user):
    with app.app_context():
        user = db.session.get(User, pass_user)
        row = upsert_user_season_pass(
            user, "Epic, Ikon", as_of=date(2026, 8, 1)
        )
        db.session.commit()
        assert row.pass_type == "epic,ikon"

        corrected = upsert_user_season_pass(
            user, "no pass", as_of=date(2027, 5, 31)
        )
        db.session.commit()

        rows = UserSeasonPass.query.filter_by(user_id=pass_user).all()
        assert len(rows) == 1
        assert corrected.id == row.id
        assert corrected.season_start_year == 2026
        assert corrected.pass_type == "no_pass"


def test_blank_input_does_not_erase_existing_history(client, pass_user):
    with app.app_context():
        user = db.session.get(User, pass_user)
        existing = upsert_user_season_pass(
            user, "ikon", as_of=date(2026, 12, 1)
        )
        db.session.commit()

        assert upsert_user_season_pass(
            user, "", as_of=date(2027, 1, 1)
        ) is None
        db.session.commit()
        assert db.session.get(UserSeasonPass, existing.id).pass_type == "ikon"


def test_rollover_creates_cross_season_history(client, pass_user):
    with app.app_context():
        user = db.session.get(User, pass_user)
        upsert_user_season_pass(user, "epic", as_of=date(2027, 5, 31))
        upsert_user_season_pass(user, "ikon", as_of=date(2027, 6, 1))
        db.session.commit()

        assert get_user_pass_for_season(pass_user, 2026) == "epic"
        assert get_user_pass_for_season(pass_user, 2027) == "ikon"
        assert UserSeasonPass.query.filter_by(user_id=pass_user).count() == 2


def test_database_constraint_prevents_duplicate_user_season(
        client, pass_user):
    with app.app_context():
        db.session.add_all([
            UserSeasonPass(
                user_id=pass_user,
                season_start_year=2026,
                pass_type="epic",
            ),
            UserSeasonPass(
                user_id=pass_user,
                season_start_year=2026,
                pass_type="ikon",
            ),
        ])
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_legacy_user_without_history_remains_unknown(client, pass_user):
    with app.app_context():
        assert UserSeasonPass.query.filter_by(user_id=pass_user).count() == 0
        assert get_user_pass_for_season(pass_user, 2025) is None


def test_onboarding_persists_active_season_without_changing_current_behavior(
        client, pass_user):
    _login(client, pass_user)
    response = form_post(
        client,
        "/onboarding",
        {
            "rider_types": "Skier",
            "skill_level": "Advanced",
            "pass_type": "Ikon, Epic",
            "home_state": "CO",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        user = db.session.get(User, pass_user)
        assert user.pass_type == "epic,ikon"
        assert get_user_pass_for_season(
            pass_user, get_ski_season_start_year()
        ) == "epic,ikon"


def test_edit_profile_explicit_no_pass_corrects_active_season(
        client, pass_user):
    _login(client, pass_user)
    response = form_post(
        client,
        "/edit_profile",
        {
            "first_name": "Season",
            "last_name": "Tester",
            "rider_types": "Skier",
            "skill_level": "Intermediate",
            "pass_type": "no_pass",
            "home_state": "CO",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        user = db.session.get(User, pass_user)
        assert user.pass_type == "no_pass"
        assert get_user_pass_for_season(
            pass_user, get_ski_season_start_year()
        ) == "no_pass"


def test_profile_api_persists_pass_and_ignores_blank_correction(
        client, pass_user):
    _login(client, pass_user)
    response = json_post(
        client,
        "/api/profile/update",
        {"pass_type": "ikon,mountain collective"},
    )
    assert response.status_code == 200

    blank_response = json_post(
        client,
        "/api/profile/update",
        {"pass_type": ""},
    )
    assert blank_response.status_code == 200

    with app.app_context():
        user = db.session.get(User, pass_user)
        assert user.pass_type == "ikon,mountain_collective"
        assert get_user_pass_for_season(
            pass_user, get_ski_season_start_year()
        ) == "ikon,mountain_collective"


def test_select_pass_persists_active_season_and_rejects_blank(
        client, pass_user):
    _login(client, pass_user)
    response = form_post(
        client,
        "/select-pass",
        {"pass_type": "no_pass_yet"},
    )
    assert response.status_code == 302

    blank_response = form_post(
        client,
        "/select-pass",
        {"pass_type": ""},
    )
    assert blank_response.status_code == 302
    assert blank_response.headers["Location"].endswith("/select-pass")

    with app.app_context():
        user = db.session.get(User, pass_user)
        assert user.pass_type == "no_pass_yet"
        assert get_user_pass_for_season(
            pass_user, get_ski_season_start_year()
        ) == "no_pass_yet"


@pytest.mark.parametrize(
    ("route", "request_kind"),
    [
        ("/api/profile/update", "json"),
        ("/select-pass", "form"),
        ("/onboarding", "onboarding"),
    ],
)
def test_unknown_pass_values_never_diverge_current_and_history(
        client, pass_user, route, request_kind):
    _login(client, pass_user)
    if request_kind == "json":
        response = json_post(client, route, {"pass_type": "mystery pass"})
        assert response.status_code == 400
    elif request_kind == "form":
        response = form_post(client, route, {"pass_type": "mystery pass"})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/select-pass")
    else:
        response = form_post(
            client,
            route,
            {
                "rider_types": "Skier",
                "skill_level": "Intermediate",
                "pass_type": "mystery pass",
                "home_state": "CO",
            },
        )
        assert response.status_code == 200

    with app.app_context():
        user = db.session.get(User, pass_user)
        assert user.pass_type == "epic"
        assert UserSeasonPass.query.filter_by(user_id=pass_user).count() == 0