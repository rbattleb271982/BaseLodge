"""BL-155 query-growth and roster-privacy regression coverage."""

from datetime import datetime, timedelta

from sqlalchemy import event

from app import app
from models import (
    Friend,
    GuestStatus,
    ParticipantRole,
    SkiTripPlanningPost,
    User,
    db,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


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


def _warm_and_measure(client, user_id, trip_id):
    _login(client, user_id)
    assert client.get(f"/trips/{trip_id}").status_code == 200
    return _measured_get(client, f"/trips/{trip_id}")


def _trip_with_guests(owner, guest_count, *, resort=None, **trip_fields):
    resort = resort or _make_resort()
    trip = _make_trip(owner, resort=resort, **trip_fields)
    guests = []
    for index in range(guest_count):
        guest = _make_user(f"query-guest-{guest_count}-{index}")
        _add_participant(trip, guest, GuestStatus.GOING)
        guests.append(guest)
    return trip, guests


def test_participant_query_growth_is_constant_for_1_5_20(client):
    with app.app_context():
        owner = _make_user("query-owner")
        trip_ids = {}
        for guest_count in (1, 5, 20):
            trip, _guests = _trip_with_guests(owner, guest_count)
            trip_ids[guest_count] = trip.id
        db.session.commit()
        owner_id = owner.id

    measurements = {}
    for guest_count in (1, 5, 20):
        _response, statements = _warm_and_measure(
            client, owner_id, trip_ids[guest_count]
        )
        measurements[guest_count] = {
            "total": len(statements),
            "users": _table_select_count(statements, "user"),
            "participants": _table_select_count(
                statements, "ski_trip_participant"
            ),
        }

    for category in ("total", "users", "participants"):
        values = [
            measurements[guest_count][category]
            for guest_count in (1, 5, 20)
        ]
        assert max(values) - min(values) <= 1, measurements

    assert max(row["total"] for row in measurements.values()) <= 24


def test_roster_filters_before_loading_user_identities(client):
    with app.app_context():
        owner = _make_user("privacy-owner")
        going = _make_user("privacy-going")
        interested = _make_user("privacy-interested")
        pending = _make_user("privacy-pending")
        declined = _make_user("privacy-declined")
        removed = _make_user("privacy-removed")
        owner.first_name = "RosterOwner"
        going.first_name = "RosterGoing"
        interested.first_name = "RosterInterested"
        pending.first_name = "RosterPending"
        declined.first_name = "RosterDeclined"
        removed.first_name = "RosterRemoved"
        trip = _make_trip(owner, resort=_make_resort())
        _add_participant(trip, going, GuestStatus.GOING)
        _add_participant(trip, interested, GuestStatus.INTERESTED)
        _add_participant(trip, pending, GuestStatus.PENDING)
        _add_participant(trip, declined, GuestStatus.DECLINED)
        _add_participant(trip, removed, GuestStatus.REMOVED)
        db.session.commit()
        ids = {
            "owner": owner.id,
            "going": going.id,
            "interested": interested.id,
            "pending": pending.id,
            "declined": declined.id,
            "removed": removed.id,
            "trip": trip.id,
        }

    def loaded_user_ids_for(viewer_id):
        loaded_ids = set()

        def record_load(target, _context):
            loaded_ids.add(target.id)

        _login(client, viewer_id)
        event.listen(User, "load", record_load)
        try:
            response = client.get(f"/trips/{ids['trip']}")
        finally:
            event.remove(User, "load", record_load)
        assert response.status_code == 200
        return response.get_data(as_text=True), loaded_ids

    owner_html, owner_loaded_ids = loaded_user_ids_for(ids["owner"])
    assert "RosterGoing" in owner_html
    assert "RosterInterested" in owner_html
    assert "RosterPending" in owner_html
    assert "RosterDeclined" in owner_html
    assert "RosterRemoved" not in owner_html
    assert ids["removed"] not in owner_loaded_ids

    participant_html, participant_loaded_ids = loaded_user_ids_for(ids["going"])
    assert f'data-participant-user-id="{ids["going"]}"' in participant_html
    assert "RosterInterested" in participant_html
    assert "RosterPending" not in participant_html
    assert "RosterDeclined" not in participant_html
    assert "RosterRemoved" not in participant_html
    assert ids["pending"] not in participant_loaded_ids
    assert ids["declined"] not in participant_loaded_ids
    assert ids["removed"] not in participant_loaded_ids


def test_planning_preview_author_queries_are_bounded(client):
    with app.app_context():
        owner = _make_user("planning-query-owner")
        trip_ids = {}
        for author_count in (1, 3):
            trip = _make_trip(owner, resort=_make_resort())
            for index in range(author_count):
                author = _make_user(
                    f"planning-query-author-{author_count}-{index}"
                )
                _add_participant(trip, author, GuestStatus.GOING)
                db.session.add(
                    SkiTripPlanningPost(
                        trip_id=trip.id,
                        user_id=author.id,
                        category="Other",
                        body=f"Post {index}",
                        created_at=datetime.utcnow() - timedelta(minutes=index),
                    )
                )
            trip_ids[author_count] = trip.id
        db.session.commit()
        owner_id = owner.id

    measurements = {}
    for author_count in (1, 3):
        _response, statements = _warm_and_measure(
            client, owner_id, trip_ids[author_count]
        )
        measurements[author_count] = {
            "total": len(statements),
            "users": _table_select_count(statements, "user"),
        }

    assert (
        measurements[3]["total"] - measurements[1]["total"]
    ) <= 1, measurements
    assert (
        measurements[3]["users"] - measurements[1]["users"]
    ) <= 1, measurements
    assert max(row["total"] for row in measurements.values()) <= 28


def test_friend_overlap_query_growth_is_constant_for_1_5_20(client):
    with app.app_context():
        scenarios = {}
        start = datetime.utcnow().date() + timedelta(days=10)
        for friend_count in (1, 5, 20):
            viewer = _make_user(f"overlap-viewer-{friend_count}")
            resort = _make_resort()
            trip = _make_trip(
                viewer,
                resort=resort,
                start_date=start,
                end_date=start + timedelta(days=3),
            )
            for index in range(friend_count):
                friend = _make_user(
                    f"overlap-friend-{friend_count}-{index}"
                )
                db.session.add_all([
                    Friend(user_id=viewer.id, friend_id=friend.id),
                    Friend(user_id=friend.id, friend_id=viewer.id),
                ])
                _make_trip(
                    friend,
                    resort=resort,
                    start_date=start + timedelta(days=1),
                    end_date=start + timedelta(days=2),
                )
            scenarios[friend_count] = (viewer.id, trip.id)
        db.session.commit()

    measurements = {}
    for friend_count in (1, 5, 20):
        viewer_id, trip_id = scenarios[friend_count]
        _response, statements = _warm_and_measure(client, viewer_id, trip_id)
        measurements[friend_count] = {
            "total": len(statements),
            "users": _table_select_count(statements, "user"),
            "participants": _table_select_count(
                statements, "ski_trip_participant"
            ),
        }

    for category in ("total", "users", "participants"):
        values = [
            measurements[friend_count][category]
            for friend_count in (1, 5, 20)
        ]
        assert max(values) - min(values) <= 1, measurements

    assert max(row["total"] for row in measurements.values()) <= 28


def test_combined_planning_and_friend_overlap_stays_under_ceiling(client):
    with app.app_context():
        start = datetime.utcnow().date() + timedelta(days=10)
        owner = _make_user("combined-query-owner")
        resort = _make_resort()
        trip = _make_trip(
            owner,
            resort=resort,
            start_date=start,
            end_date=start + timedelta(days=3),
        )
        for index in range(3):
            author = _make_user(f"combined-query-author-{index}")
            _add_participant(trip, author, GuestStatus.GOING)
            db.session.add(
                SkiTripPlanningPost(
                    trip_id=trip.id,
                    user_id=author.id,
                    category="Other",
                    body=f"Combined post {index}",
                )
            )
        for index in range(20):
            friend = _make_user(f"combined-query-friend-{index}")
            db.session.add_all([
                Friend(user_id=owner.id, friend_id=friend.id),
                Friend(user_id=friend.id, friend_id=owner.id),
            ])
            _make_trip(
                friend,
                resort=resort,
                start_date=start + timedelta(days=1),
                end_date=start + timedelta(days=2),
            )
        db.session.commit()
        owner_id, trip_id = owner.id, trip.id

    _response, statements = _warm_and_measure(client, owner_id, trip_id)
    assert len(statements) <= 28


def test_ordinary_trip_detail_variants_remain_under_warm_ceiling(client):
    with app.app_context():
        owner = _make_user("variant-query-owner")
        guest = _make_user("variant-query-guest")
        pending = _make_user("variant-query-pending")

        active_trip, _guests = _trip_with_guests(owner, 5)
        _add_participant(active_trip, guest, GuestStatus.GOING)
        _add_participant(active_trip, pending, GuestStatus.PENDING)
        stay_trip, _stay_guests = _trip_with_guests(
            owner, 2, stay_name="Bounded Lodge"
        )
        terminal_trip, _terminal_guests = _trip_with_guests(
            owner, 2, lifecycle_state="completed"
        )
        db.session.commit()
        scenarios = (
            (owner.id, active_trip.id),
            (guest.id, active_trip.id),
            (pending.id, active_trip.id),
            (owner.id, stay_trip.id),
            (owner.id, terminal_trip.id),
        )

    for viewer_id, trip_id in scenarios:
        _response, statements = _warm_and_measure(client, viewer_id, trip_id)
        assert len(statements) <= 24