"""Focused tests for bounded Friends directory retrieval."""

from datetime import date, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app import app
from models import Friend, GuestStatus, SkiTripParticipant, db
from services.friends_paging import (
    FRIENDS_PAGE_SIZE,
    FriendsCursorError,
    build_friends_candidate_query,
    decode_friends_cursor,
    load_friends_page,
)
from tests.conftest import _add_participant, _login, _make_trip, _make_user


def _connect(left, right, reciprocal=True):
    db.session.add(Friend(user_id=left.id, friend_id=right.id))
    if reciprocal:
        db.session.add(Friend(user_id=right.id, friend_id=left.id))
    db.session.flush()


def test_page_boundary_ties_and_reciprocal_authorization(client):
    with app.app_context():
        viewer = _make_user("paging-viewer")
        expected = []
        for index in range(FRIENDS_PAGE_SIZE + 3):
            user = _make_user(f"paging-{index}")
            user.first_name = "CASE" if index % 2 else "case"
            user.last_name = "Tie"
            _connect(viewer, user)
            expected.append(user.id)
        one_way = _make_user("one-way")
        _connect(viewer, one_way, reciprocal=False)
        db.session.commit()

        first = load_friends_page(viewer.id)
        second = load_friends_page(viewer.id, cursor_value=first.next_cursor)

        assert len(first.rows) == FRIENDS_PAGE_SIZE
        assert first.has_more and first.next_cursor
        assert len(second.rows) == 3
        assert not second.has_more
        assert first.authorized_count == first.matching_count == len(expected)
        assert [row.id for row in first.rows + second.rows] == expected
        assert one_way.id not in {row.id for row in first.rows + second.rows}


def test_filters_counts_and_template_properties(client):
    with app.app_context():
        viewer = _make_user("filter-viewer")
        match = _make_user("filter-match")
        match.first_name = "Ada"
        match.last_name = "Lovelace"
        match.pass_type = "ikon,mountain_collective"
        match.rider_types = ["Snowboarder"]
        match.skill_level = "Expert"
        _connect(viewer, match)
        other = _make_user("filter-other")
        _connect(viewer, other)
        db.session.commit()

        page = load_friends_page(
            viewer.id,
            q="lovelace",
            passes=["mountain_collective"],
            riders=["snowboarder"],
            skills=["expert"],
        )
        assert page.authorized_count == 2
        assert page.matching_count == 1
        assert len(page.rows) == 1
        assert page.rows[0].id == match.id
        assert page.rows[0]._trip_count == 0
        assert page.rows[0]._is_new_friend
        assert page.alpha_groups[0]["letter"] == "A"


def test_cursor_is_strict_versioned_typed_and_filter_scoped(client):
    with app.app_context():
        viewer = _make_user("cursor-viewer")
        for index in range(FRIENDS_PAGE_SIZE + 1):
            _connect(viewer, _make_user(f"cursor-{index}"))
        db.session.commit()
        page = load_friends_page(viewer.id)

        with pytest.raises(FriendsCursorError):
            load_friends_page(viewer.id, q="different", cursor_value=page.next_cursor)
        with pytest.raises(FriendsCursorError):
            decode_friends_cursor("not-base64!")

        replacement = "a" if page.next_cursor[-1] != "a" else "b"
        tampered = page.next_cursor[:-1] + replacement
        with pytest.raises(FriendsCursorError):
            decode_friends_cursor(tampered)

        with pytest.raises(FriendsCursorError):
            load_friends_page(
                viewer.id + 999, cursor_value=page.next_cursor
            )


def test_upcoming_public_active_or_legacy_trip_count_is_deduplicated(client):
    with app.app_context():
        viewer = _make_user("trip-viewer")
        friend = _make_user("trip-friend")
        owner = _make_user("trip-owner")
        _connect(viewer, friend)
        future = date.today() + timedelta(days=10)
        owned = _make_trip(friend, start_date=future, end_date=future)
        both = _make_trip(friend, start_date=future, end_date=future)
        participant = _make_trip(owner, start_date=future, end_date=future)
        _add_participant(participant, friend, GuestStatus.INTERESTED)
        private = _make_trip(friend, start_date=future, end_date=future, is_public=False)
        cancelled = _make_trip(friend, start_date=future, end_date=future)
        cancelled.lifecycle_state = "cancelled"
        declined = _make_trip(owner, start_date=future, end_date=future)
        _add_participant(declined, friend, GuestStatus.DECLINED)
        owned.lifecycle_state = None
        db.session.commit()

        page = load_friends_page(viewer.id)
        assert page.rows[0].upcoming_trip_count == 3


@pytest.mark.parametrize(
    "source_count", [0, 1, 10, 19, 20, 21, 40, 41, 50, 100, 500]
)
def test_hydration_cardinality_is_bounded_to_visible_page(client, source_count):
    with app.app_context():
        viewer = _make_user(f"cardinality-viewer-{source_count}")
        for index in range(source_count):
            _connect(
                viewer, _make_user(f"cardinality-{source_count}-{index}")
            )
        db.session.commit()
        viewer_id = viewer.id
        db.session.expunge_all()

        page = load_friends_page(viewer_id)
        expected = min(source_count, FRIENDS_PAGE_SIZE)
        assert len(page.rows) == expected
        assert len({row.user.id for row in page.rows}) == expected
        assert len({row.friendship.id for row in page.rows}) == expected
        assert page.authorized_count == source_count
        assert page.has_more is (source_count > FRIENDS_PAGE_SIZE)


def test_candidate_query_compiles_for_postgresql(client):
    with app.app_context():
        statement = build_friends_candidate_query(
            7,
            q="ada",
            passes=["ikon"],
            riders=["skier"],
            skills=["expert"],
        ).statement
        sql = str(statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        assert "reverse_friend" in sql
        assert "lower" in sql.lower()
        assert "ORDER BY" in sql


def test_directory_route_and_endpoint_page_complete_set(client):
    with app.app_context():
        viewer = _make_user("directory-route-viewer")
        matching_ids = []
        for index in range(FRIENDS_PAGE_SIZE + 1):
            friend = _make_user(f"directory-route-{index:02d}")
            friend.first_name = f"Route{index:02d}"
            friend.pass_type = "ikon" if index % 2 == 0 else "epic"
            _connect(viewer, friend)
            if index % 2 == 0:
                matching_ids.append(friend.id)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    initial = client.get("/friends")
    assert initial.status_code == 200
    assert initial.get_data(as_text=True).count('class="fr-friend-row"') == 20

    filtered = client.get("/api/friends/page", query_string={"pass": "ikon"})
    assert filtered.status_code == 200
    payload = filtered.get_json()
    assert payload["matching_count"] == len(matching_ids)
    assert set(payload["friend_ids"]) == set(matching_ids)


def test_directory_endpoint_budget_and_cursor_reauthorization(client):
    with app.app_context():
        viewer = _make_user("directory-budget-viewer")
        friends = []
        for index in range(FRIENDS_PAGE_SIZE + 1):
            friend = _make_user(f"directory-budget-{index:02d}")
            _connect(viewer, friend)
            friends.append(friend)
        db.session.commit()
        viewer_id = viewer.id
        revoked_friend_id = friends[-1].id

    _login(client, viewer_id)
    assert client.get("/api/friends/page").status_code == 200
    statements = []
    with app.app_context():
        engine = db.engine

    def record(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        first = client.get("/api/friends/page")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert first.status_code == 200
    assert len(statements) <= 4
    cursor = first.get_json()["next_cursor"]

    with app.app_context():
        Friend.query.filter_by(
            user_id=revoked_friend_id, friend_id=viewer_id
        ).delete()
        db.session.commit()
    second = client.get("/api/friends/page", query_string={"cursor": cursor})
    assert second.status_code == 200
    assert revoked_friend_id not in second.get_json()["friend_ids"]
    assert client.get(
        "/api/friends/page", query_string={"cursor": "not-a-cursor"}
    ).status_code == 400