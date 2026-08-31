"""BL-161 authenticated-page query-shape and privacy regressions."""

from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import event

import app as app_module
from app import app
from models import (
    Friend,
    GuestStatus,
    ResortPass,
    User,
    UserAvailability,
    db,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _connect(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


def _normalized(statement):
    return " ".join(statement.lower().split())


def _table_select_count(statements, table_name):
    return sum(
        statement.startswith("select ")
        and f" from {table_name} " in f" {statement} "
        for statement in statements
    )


def _measured_get(client, path):
    statements = []
    with app.app_context():
        engine = db.engine

    def record(_connection, _cursor, statement, _params, _context, _many):
        statements.append(_normalized(statement))

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    return response, statements


def _warm_and_measure(client, user_id, path):
    _login(client, user_id)
    assert client.get(path).status_code == 200
    return _measured_get(client, path)


def test_trip_idea_participant_queries_are_bounded_for_1_5_20(client):
    with app.app_context():
        viewer = _make_user("idea-query-viewer")
        trip_ids = {}
        for participant_count in (1, 5, 20):
            owner = _make_user(f"idea-query-owner-{participant_count}")
            _connect(viewer, owner)
            trip = _make_trip(
                owner,
                resort=_make_resort(f"Idea Query Peak {participant_count}"),
                is_public=True,
            )
            for index in range(participant_count):
                guest = _make_user(
                    f"idea-query-guest-{participant_count}-{index}"
                )
                _add_participant(trip, guest, GuestStatus.GOING)
            trip_ids[participant_count] = trip.id
        db.session.commit()
        viewer_id = viewer.id

    measurements = {}
    for participant_count in (1, 5, 20):
        _response, statements = _warm_and_measure(
            client,
            viewer_id,
            f"/idea/trip/{trip_ids[participant_count]}",
        )
        measurements[participant_count] = {
            "total": len(statements),
            "users": _table_select_count(statements, "user"),
            "participants": _table_select_count(
                statements, "ski_trip_participant"
            ),
        }

    for category in ("total", "users", "participants"):
        values = [
            measurements[participant_count][category]
            for participant_count in (1, 5, 20)
        ]
        assert max(values) - min(values) <= 1, measurements


def test_trip_idea_filters_hidden_statuses_before_user_hydration(client):
    with app.app_context():
        viewer = _make_user("idea-privacy-viewer")
        owner = _make_user("idea-privacy-owner")
        _connect(viewer, owner)
        trip = _make_trip(
            owner,
            resort=_make_resort("Idea Privacy Peak"),
            is_public=True,
        )
        users_by_status = {}
        for status in (
            GuestStatus.GOING,
            GuestStatus.INTERESTED,
            GuestStatus.PENDING,
            GuestStatus.DECLINED,
            GuestStatus.REMOVED,
        ):
            participant_user = _make_user(f"idea-privacy-{status.value}")
            participant_user.first_name = f"Idea{status.value.title()}"
            users_by_status[status] = participant_user
            _add_participant(trip, participant_user, status)
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id
        participant_ids = {
            status: participant_user.id
            for status, participant_user in users_by_status.items()
        }

    loaded_user_ids = set()

    def record_load(target, _context):
        loaded_user_ids.add(target.id)

    _login(client, viewer_id)
    event.listen(User, "load", record_load)
    try:
        response = client.get(f"/idea/trip/{trip_id}")
    finally:
        event.remove(User, "load", record_load)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "IdeaGoing" in html
    assert "IdeaInterested" in html
    for hidden_status in (
        GuestStatus.PENDING,
        GuestStatus.DECLINED,
        GuestStatus.REMOVED,
    ):
        assert f"Idea{hidden_status.value.title()}" not in html
        assert participant_ids[hidden_status] not in loaded_user_ids


def test_friends_reuses_participant_identity_from_join(client):
    with app.app_context():
        viewer = _make_user("friends-query-viewer")
        trip_owner = _make_user("friends-query-trip-owner")
        for index in range(5):
            friend = _make_user(f"friends-query-{index}")
            _connect(viewer, friend)
            trip = _make_trip(
                trip_owner,
                resort=_make_resort(f"Friends Query Peak {index}"),
                is_public=True,
            )
            _add_participant(trip, friend, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _response, statements = _warm_and_measure(client, viewer_id, "/friends")

    assert len(statements) <= 18
    participant_selects = [
        statement
        for statement in statements
        if statement.startswith("select ")
        and " from ski_trip_participant " in f" {statement} "
    ]
    assert not any(
        "ski_trip_participant.trip_id in" in statement
        and "ski_trip_participant.user_id in" in statement
        for statement in participant_selects
    )


def test_mountain_detail_resolves_pass_mappings_once(client):
    with app.app_context():
        viewer = _make_user("mountain-pass-query-viewer")
        viewer.pass_type = "Epic"
        resort = _make_resort("Mountain Pass Query Peak")
        db.session.add(ResortPass(
            resort_id=resort.id,
            pass_name="Epic",
            is_primary=True,
        ))
        db.session.commit()
        viewer_id = viewer.id
        resort_slug = resort.slug

    response, statements = _warm_and_measure(
        client, viewer_id, f"/mountain/{resort_slug}"
    )

    assert "Epic" in response.get_data(as_text=True)
    assert len(statements) <= 12
    assert _table_select_count(statements, "resort_pass") == 1


@pytest.mark.parametrize(
    (
        "mapped_passes",
        "legacy_passes",
        "expected_primary",
        "expected_names",
    ),
    [
        (
            [("Epic", False), ("Ikon", False)],
            [],
            "Epic",
            ["Epic", "Ikon"],
        ),
        ([], ["Ikon"], "Ikon", ["Ikon"]),
    ],
)
def test_mountain_detail_preserves_pass_fallbacks(
    client,
    monkeypatch,
    mapped_passes,
    legacy_passes,
    expected_primary,
    expected_names,
):
    with app.app_context():
        viewer = _make_user(f"mountain-pass-fallback-{expected_primary}")
        resort = _make_resort(f"Mountain Pass Fallback {expected_primary}")
        resort.pass_brands_json = legacy_passes
        for pass_name, is_primary in mapped_passes:
            db.session.add(ResortPass(
                resort_id=resort.id,
                pass_name=pass_name,
                is_primary=is_primary,
            ))
        db.session.commit()
        viewer_id = viewer.id
        resort_slug = resort.slug

    captured_context = {}
    original_render_template = app_module.render_template

    def capture_mountain_context(template_name, *args, **kwargs):
        if template_name == "mountain_detail.html":
            captured_context.update(kwargs)
        return original_render_template(template_name, *args, **kwargs)

    monkeypatch.setattr(
        app_module, "render_template", capture_mountain_context
    )
    _login(client, viewer_id)
    response = client.get(f"/mountain/{resort_slug}")

    assert response.status_code == 200
    assert captured_context["primary_pass"] == expected_primary
    assert captured_context["pass_names"] == expected_names


def test_friend_profile_reuses_reciprocal_authorization(client, monkeypatch):
    with app.app_context():
        viewer = _make_user("profile-friend-query-viewer")
        friend = _make_user("profile-friend-query-target")
        _connect(viewer, friend)
        db.session.commit()
        viewer_id, friend_id = viewer.id, friend.id

    original = app_module.is_reciprocal_friend
    calls = []

    def counted_is_reciprocal_friend(first_id, second_id):
        calls.append((first_id, second_id))
        return original(first_id, second_id)

    monkeypatch.setattr(
        app_module, "is_reciprocal_friend", counted_is_reciprocal_friend
    )
    _response, statements = _warm_and_measure(
        client, viewer_id, f"/friends/{friend_id}"
    )

    assert calls == [(viewer_id, friend_id), (viewer_id, friend_id)]
    assert len(statements) <= 25


def test_friend_profile_reuses_authorized_friend_availability(
    client, monkeypatch
):
    with app.app_context():
        viewer = _make_user("profile-availability-viewer")
        friend = _make_user("profile-availability-friend")
        _connect(viewer, friend)
        resort = _make_resort("Profile Availability Peak")
        overlap_day = date.today() + timedelta(days=10)
        _make_trip(
            viewer,
            resort=resort,
            start_date=overlap_day,
            end_date=overlap_day,
        )
        db.session.add_all([
            UserAvailability(user_id=viewer.id, date=overlap_day),
            UserAvailability(user_id=friend.id, date=overlap_day),
        ])
        db.session.commit()
        viewer_id, friend_id = viewer.id, friend.id
        resort_id = resort.id

    original = app_module.get_available_dates_for_user
    calls = []

    def counted_get_available_dates_for_user(target_user):
        calls.append(target_user.id)
        return original(target_user)

    monkeypatch.setattr(
        app_module,
        "get_available_dates_for_user",
        counted_get_available_dates_for_user,
    )
    path = (
        f"/friends/{friend_id}?resort_id={resort_id}"
        f"&overlap_start={overlap_day.isoformat()}"
        f"&overlap_end={overlap_day.isoformat()}"
    )
    response, statements = _warm_and_measure(client, viewer_id, path)

    assert response.status_code == 200
    assert calls.count(friend_id) == 2
    assert calls.count(viewer_id) == 2
    availability_selects = [
        statement
        for statement in statements
        if statement.startswith("select ")
        and " from user_availability " in f" {statement} "
    ]
    assert len(availability_selects) == 2