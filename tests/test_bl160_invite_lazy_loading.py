"""BL-160 bounded Trip Detail invite-candidate lazy-loading coverage."""

from sqlalchemy import event

from app import app
from models import Friend, GuestStatus, SkiTrip, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _connect(left, right):
    db.session.add_all([
        Friend(user_id=left.id, friend_id=right.id),
        Friend(user_id=right.id, friend_id=left.id),
    ])


def _setup_candidates():
    owner = _make_user("lazy-owner")
    trip = _make_trip(owner, resort=_make_resort("Lazy Peak"))
    candidates = {}
    for label, first_name, status in (
        ("zulu", "Zoe", None),
        ("active", "Anna", GuestStatus.GOING),
        ("pending", "Mia", GuestStatus.PENDING),
        ("declined", "Riley", GuestStatus.DECLINED),
        ("removed", "Casey", GuestStatus.REMOVED),
    ):
        user = _make_user(f"lazy-{label}")
        user.first_name = first_name
        user.last_name = "Candidate"
        _connect(owner, user)
        if status is not None:
            _add_participant(trip, user, status)
        candidates[label] = user
    outsider = _make_user("lazy-outsider")
    db.session.commit()
    return owner.id, outsider.id, trip.id, {
        label: user.id for label, user in candidates.items()
    }


def test_initial_trip_detail_keeps_shell_without_candidate_identity_data(client):
    with app.app_context():
        owner_id, _outsider_id, trip_id, candidate_ids = _setup_candidates()

    _login(client, owner_id)
    response = client.get(f"/trips/{trip_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Invite friends to this trip" in html
    assert 'id="inviteModal"' in html
    assert f'data-invite-candidates-url="/trips/{trip_id}/invite-candidates"' in html
    assert 'id="inviteFriendsLoading"' in html
    assert 'id="inviteFriendsEmpty"' in html
    assert 'id="inviteFriendsError"' in html
    friends_list = html.split('id="friendsList"', 1)[1].split("</div>", 1)[0]
    assert "friend-select-row" not in friends_list
    for candidate_id in candidate_ids.values():
        assert f'id="friend_{candidate_id}"' not in html
    for serialized_name in ("zoe candidate", "anna candidate", "mia candidate",
                            "riley candidate", "casey candidate"):
        assert f'data-full-name="{serialized_name}"' not in html
    assert "Zoe Candidate" not in html


def test_candidate_endpoint_rechecks_authentication_owner_and_lifecycle(client):
    with app.app_context():
        owner_id, outsider_id, trip_id, _candidate_ids = _setup_candidates()

    assert client.get(f"/trips/{trip_id}/invite-candidates").status_code == 302

    _login(client, outsider_id)
    assert client.get(f"/trips/{trip_id}/invite-candidates").status_code == 403

    _login(client, owner_id)
    assert client.get(f"/trips/{trip_id}/invite-candidates").status_code == 200

    with app.app_context():
        trip = db.session.get(SkiTrip, trip_id)
        trip.lifecycle_state = "completed"
        db.session.commit()
    assert client.get(f"/trips/{trip_id}/invite-candidates").status_code == 409


def test_candidate_endpoint_preserves_order_and_current_status_labels(client):
    with app.app_context():
        owner_id, _outsider_id, trip_id, candidate_ids = _setup_candidates()

    _login(client, owner_id)
    response = client.get(f"/trips/{trip_id}/invite-candidates")
    data = response.get_json()
    html = data["html"]

    assert response.status_code == 200
    assert data["count"] == 5
    assert html.index("Anna Candidate") < html.index("Casey Candidate")
    assert html.index("Casey Candidate") < html.index("Mia Candidate")
    assert html.index("Mia Candidate") < html.index("Riley Candidate")
    assert html.index("Riley Candidate") < html.index("Zoe Candidate")
    assert "Already on trip" in html
    assert "Invite sent" in html
    assert "Declined — reinvite" in html
    assert "Removed — reinvite" in html
    assert f'id="friend_{candidate_ids["active"]}"' in html
    assert f'id="friend_{candidate_ids["pending"]}"' in html
    assert html.count(" disabled") >= 4


def test_high_cardinality_candidate_endpoint_has_constant_query_count(client):
    with app.app_context():
        scenarios = {}
        for friend_count in (1, 20, 100):
            owner = _make_user(f"lazy-scale-owner-{friend_count}")
            trip = _make_trip(owner, resort=_make_resort())
            for index in range(friend_count):
                friend = _make_user(f"lazy-scale-{friend_count}-{index}")
                _connect(owner, friend)
            scenarios[friend_count] = (owner.id, trip.id)
        db.session.commit()

    measurements = {}
    for friend_count, (owner_id, trip_id) in scenarios.items():
        _login(client, owner_id)
        statements = []
        with app.app_context():
            engine = db.engine

        def record(_connection, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get(f"/trips/{trip_id}/invite-candidates")
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert response.status_code == 200
        assert response.get_json()["count"] == friend_count
        measurements[friend_count] = len(statements)

    assert max(measurements.values()) - min(measurements.values()) <= 1, measurements
    assert max(measurements.values()) <= 6, measurements