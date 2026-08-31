"""Focused BL-133 current-state authorization matrix."""

from datetime import date, timedelta

import pytest

from app import (
    app,
    build_friend_at_mountain_card,
    build_trip_overlap_today_card,
)
from models import (
    Friend,
    FriendConnectionEvent,
    GuestStatus,
    Invitation,
    UserAvailability,
    db,
)
from services.open_dates import (
    get_available_dates_for_users,
    get_open_date_matches,
)
from services.visibility import (
    is_reciprocal_friend,
    issue_availability_idea_capability,
    trip_view_capability,
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


@pytest.mark.parametrize(
    "state,expected_status",
    [
        ("reciprocal", 200),
        ("outgoing_only", 403),
        ("incoming_only", 403),
        ("pending_outgoing", 403),
        ("pending_incoming", 403),
        ("declined", 403),
        ("former", 403),
        ("unrelated", 403),
        ("history_only", 403),
    ],
)
def test_friend_profile_api_current_relationship_matrix(
    client, state, expected_status
):
    with app.app_context():
        viewer = _make_user(f"matrix-viewer-{state}")
        target = _make_user(f"matrix-target-{state}")
        if state == "reciprocal":
            _connect(viewer, target)
        elif state == "outgoing_only":
            db.session.add(Friend(user_id=viewer.id, friend_id=target.id))
        elif state == "incoming_only":
            db.session.add(Friend(user_id=target.id, friend_id=viewer.id))
        elif state in {"pending_outgoing", "pending_incoming", "declined"}:
            sender, receiver = (
                (viewer, target)
                if state != "pending_incoming"
                else (target, viewer)
            )
            db.session.add(Invitation(
                sender_id=sender.id,
                receiver_id=receiver.id,
                status="declined" if state == "declined" else "pending",
            ))
        elif state == "history_only":
            a, b = sorted((viewer.id, target.id))
            db.session.add(FriendConnectionEvent(
                user_a_id=a,
                user_b_id=b,
                event_type="formed",
                actor_user_id=viewer.id,
                source="friend_request_accept",
            ))
        # former and unrelated intentionally have no current Friend rows.
        db.session.commit()
        viewer_id, target_id = viewer.id, target.id

    _login(client, viewer_id)
    response = client.get(f"/api/friends/{target_id}")
    assert response.status_code == expected_status


def test_friend_profile_api_allows_self(client):
    with app.app_context():
        viewer = _make_user("matrix-self")
        db.session.commit()
        viewer_id = viewer.id
    _login(client, viewer_id)
    assert client.get(f"/api/friends/{viewer_id}").status_code == 200


def test_friends_api_uses_minimal_allowlist_and_excludes_one_sided(client):
    with app.app_context():
        viewer = _make_user("friends-api-viewer")
        confirmed = _make_user("friends-api-confirmed")
        stale = _make_user("friends-api-stale")
        _connect(viewer, confirmed)
        db.session.add(Friend(user_id=viewer.id, friend_id=stale.id))
        db.session.commit()
        viewer_id, confirmed_id, stale_id = viewer.id, confirmed.id, stale.id

    _login(client, viewer_id)
    payload = client.get("/api/friends").get_json()["friends"]
    assert {row["id"] for row in payload} == {confirmed_id}
    assert stale_id not in {row["id"] for row in payload}
    assert set(payload[0]) == {"id", "name", "pass_type"}
    assert "email" not in payload[0]


def test_history_event_never_creates_current_friendship(client):
    with app.app_context():
        first = _make_user("history-first")
        second = _make_user("history-second")
        a, b = sorted((first.id, second.id))
        db.session.add(FriendConnectionEvent(
            user_a_id=a,
            user_b_id=b,
            event_type="formed",
            actor_user_id=first.id,
            source="friend_request_accept",
        ))
        db.session.commit()
        assert is_reciprocal_friend(first.id, second.id) is False


def test_trip_capability_preserves_current_and_terminal_matrix(client):
    with app.app_context():
        owner = _make_user("cap-owner")
        going = _make_user("cap-going")
        interested = _make_user("cap-interested")
        pending = _make_user("cap-pending")
        declined = _make_user("cap-declined")
        removed = _make_user("cap-removed")
        friend = _make_user("cap-friend")
        outsider = _make_user("cap-outsider")
        resort = _make_resort("Capability Peak")
        trip = _make_trip(owner, resort=resort, is_public=True)
        rows = {
            user.id: _add_participant(trip, user, status)
            for user, status in [
                (going, GuestStatus.GOING),
                (interested, GuestStatus.INTERESTED),
                (pending, GuestStatus.PENDING),
                (declined, GuestStatus.DECLINED),
                (removed, GuestStatus.REMOVED),
            ]
        }
        _connect(owner, friend)
        db.session.commit()

        assert trip_view_capability(trip, owner.id).allowed
        assert trip_view_capability(
            trip, going.id, participant=rows[going.id]
        ).allowed
        assert trip_view_capability(
            trip, interested.id, participant=rows[interested.id]
        ).allowed
        assert trip_view_capability(
            trip, pending.id, participant=rows[pending.id]
        ).allowed
        assert not trip_view_capability(
            trip, declined.id, participant=rows[declined.id]
        ).allowed
        assert not trip_view_capability(
            trip, removed.id, participant=rows[removed.id]
        ).allowed
        assert trip_view_capability(
            trip, friend.id, allow_friend_public=True
        ).friend_public
        assert not trip_view_capability(
            trip, outsider.id, allow_friend_public=True
        ).allowed

        trip.lifecycle_state = "completed"
        assert trip_view_capability(
            trip, going.id, participant=rows[going.id]
        ).allowed
        assert not trip_view_capability(
            trip, pending.id, participant=rows[pending.id]
        ).allowed
        assert not trip_view_capability(
            trip, friend.id, allow_friend_public=True
        ).allowed


def test_nonorganizer_roster_never_receives_invitation_identities(client):
    with app.app_context():
        owner = _make_user("roster-owner")
        active = _make_user("roster-active")
        pending = _make_user("roster-pending-secret")
        declined = _make_user("roster-declined-secret")
        removed = _make_user("roster-removed-secret")
        active.first_name = "ActiveVisible"
        pending.first_name = "PendingSecret"
        declined.first_name = "DeclinedSecret"
        removed.first_name = "RemovedSecret"
        trip = _make_trip(owner, resort=_make_resort("Roster Peak"))
        _add_participant(trip, active, GuestStatus.GOING)
        _add_participant(trip, pending, GuestStatus.PENDING)
        _add_participant(trip, declined, GuestStatus.DECLINED)
        _add_participant(trip, removed, GuestStatus.REMOVED)
        db.session.commit()
        ids = owner.id, active.id, trip.id

    owner_id, active_id, trip_id = ids
    _login(client, active_id)
    active_html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert "Going" in active_html
    assert "PendingSecret" not in active_html
    assert "DeclinedSecret" not in active_html
    assert "RemovedSecret" not in active_html

    _login(client, owner_id)
    owner_html = client.get(f"/trips/{trip_id}").get_data(as_text=True)
    assert "PendingSecret" in owner_html
    assert "DeclinedSecret" in owner_html
    assert "RemovedSecret" not in owner_html


def test_wishlist_idea_detail_recomputes_shared_current_state(client):
    with app.app_context():
        viewer = _make_user("wishlist-detail-viewer")
        friend = _make_user("wishlist-detail-friend")
        other_friend = _make_user("wishlist-detail-other")
        shared = _make_resort("Wishlist Detail Shared")
        manipulated = _make_resort("Wishlist Detail Manipulated")
        viewer.wish_list_resorts = [shared.id]
        friend.wish_list_resorts = [shared.id]
        other_friend.wish_list_resorts = []
        _connect(viewer, friend)
        _connect(viewer, other_friend)
        db.session.commit()
        values = (
            viewer.id, friend.id, other_friend.id, shared.id, manipulated.id
        )

    viewer_id, friend_id, other_id, shared_id, manipulated_id = values
    _login(client, viewer_id)
    assert client.get(
        f"/idea/wishlist?resort_id={shared_id}&friend_ids={friend_id}"
    ).status_code == 200
    assert client.get(
        f"/idea/wishlist?resort_id={manipulated_id}&friend_ids={friend_id}"
    ).status_code == 404
    assert client.get(
        f"/idea/wishlist?resort_id={shared_id}&friend_ids={friend_id},{other_id}"
    ).status_code == 404


def test_availability_idea_requires_actual_shared_dates(client):
    with app.app_context():
        viewer = _make_user("availability-detail-viewer")
        friend = _make_user("availability-detail-friend")
        _connect(viewer, friend)
        first_day = date.today() + timedelta(days=10)
        second_day = first_day + timedelta(days=1)
        viewer.open_dates = [first_day.isoformat()]
        friend.open_dates = [second_day.isoformat()]
        db.session.commit()
        viewer_id, friend_id = viewer.id, friend.id

    _login(client, viewer_id)
    response = client.get(
        "/idea/availability",
        query_string={
            "friend_ids": str(friend_id),
            "start_date": first_day.isoformat(),
            "end_date": second_day.isoformat(),
        },
    )
    assert response.status_code == 404


def test_availability_idea_accepts_only_server_issued_viewer_scope(client):
    with app.app_context():
        viewer = _make_user("availability-capability-viewer")
        friend = _make_user("availability-capability-friend")
        other = _make_user("availability-capability-other")
        _connect(viewer, friend)
        _connect(other, friend)
        overlap_day = date.today() + timedelta(days=10)
        viewer.open_dates = [overlap_day.isoformat()]
        friend.open_dates = [overlap_day.isoformat()]
        db.session.commit()
        capability = issue_availability_idea_capability(
            viewer_id=viewer.id,
            friend_ids=[friend.id],
            start_date=overlap_day.isoformat(),
            end_date=overlap_day.isoformat(),
        )
        viewer_id, friend_id, other_id = viewer.id, friend.id, other.id

    _login(client, viewer_id)
    assert client.get(
        "/idea/availability",
        query_string={"capability": capability},
    ).status_code == 200
    assert client.get(
        "/idea/availability",
        query_string={
            "capability": capability,
            "friend_ids": str(friend_id),
            "start_date": (overlap_day + timedelta(days=1)).isoformat(),
            "end_date": (overlap_day + timedelta(days=1)).isoformat(),
        },
    ).status_code == 200

    _login(client, other_id)
    assert client.get(
        "/idea/availability",
        query_string={"capability": capability},
    ).status_code == 404


def test_participant_friend_grants_only_current_public_social_trip_access(client):
    with app.app_context():
        viewer = _make_user("participant-friend-viewer")
        owner = _make_user("participant-friend-owner")
        friend = _make_user("participant-friend-active")
        pending_friend = _make_user("participant-friend-pending")
        resort = _make_resort("Participant Friend Peak")
        trip = _make_trip(owner, resort=resort, is_public=True)
        _add_participant(trip, friend, GuestStatus.GOING)
        _add_participant(trip, pending_friend, GuestStatus.PENDING)
        _connect(viewer, friend)
        _connect(viewer, pending_friend)
        db.session.commit()
        values = viewer.id, friend.id, pending_friend.id, trip.id

    viewer_id, friend_id, pending_friend_id, trip_id = values
    _login(client, viewer_id)
    assert client.get(f"/idea/trip/{trip_id}").status_code == 200
    assert client.get(f"/friend-trip/{trip_id}").status_code == 200

    with app.app_context():
        Friend.query.filter(
            db.or_(
                db.and_(
                    Friend.user_id == viewer_id,
                    Friend.friend_id == friend_id,
                ),
                db.and_(
                    Friend.user_id == friend_id,
                    Friend.friend_id == viewer_id,
                ),
            )
        ).delete(synchronize_session=False)
        db.session.commit()

    assert client.get(f"/idea/trip/{trip_id}").status_code == 404
    assert client.get(f"/friend-trip/{trip_id}").status_code == 403


def test_normalized_availability_never_falls_back_to_stale_legacy_dates(client):
    with app.app_context():
        viewer = _make_user("normalized-availability-viewer")
        friend = _make_user("normalized-availability-friend")
        _connect(viewer, friend)
        future_day = date.today() + timedelta(days=10)
        viewer.open_dates = [future_day.isoformat()]
        friend.open_dates = [future_day.isoformat()]
        db.session.add(UserAvailability(
            user_id=friend.id,
            date=date.today() - timedelta(days=1),
            is_available=True,
        ))
        db.session.commit()

        resolved = get_available_dates_for_users([viewer, friend])
        assert resolved[friend.id] == set()
        assert get_open_date_matches(
            viewer,
            cached_my_dates={future_day.isoformat()},
            cached_friends=[friend],
        ) == []


def test_friend_public_trip_access_expires_with_trip_and_attendance(client):
    with app.app_context():
        viewer = _make_user("expired-public-viewer")
        owner_friend = _make_user("expired-public-owner")
        participant_friend = _make_user("ended-attendance-friend")
        unrelated_owner = _make_user("ended-attendance-owner")
        resort = _make_resort("Expired Public Peak")
        _connect(viewer, owner_friend)
        _connect(viewer, participant_friend)

        expired_trip = _make_trip(
            owner_friend,
            resort=resort,
            is_public=True,
            start_date=date.today() - timedelta(days=5),
            end_date=date.today() - timedelta(days=1),
        )
        current_trip = _make_trip(
            unrelated_owner,
            resort=resort,
            is_public=True,
            start_date=date.today() - timedelta(days=5),
            end_date=date.today() + timedelta(days=5),
        )
        participant = _add_participant(
            current_trip, participant_friend, GuestStatus.GOING
        )
        participant.start_date = date.today() - timedelta(days=5)
        participant.end_date = date.today() - timedelta(days=1)
        db.session.commit()
        values = viewer.id, expired_trip.id, current_trip.id

    viewer_id, expired_trip_id, current_trip_id = values
    _login(client, viewer_id)
    assert client.get(f"/idea/trip/{expired_trip_id}").status_code == 404
    assert client.get(f"/friend-trip/{expired_trip_id}").status_code == 404
    assert client.get(f"/idea/trip/{current_trip_id}").status_code == 404
    assert client.get(f"/friend-trip/{current_trip_id}").status_code == 403


def test_private_friend_trips_never_power_home_social_cards(client):
    with app.app_context():
        viewer = _make_user("private-card-viewer")
        friend = _make_user("private-card-friend")
        resort = _make_resort("Private Card Peak")
        _connect(viewer, friend)
        today = date.today()

        _make_trip(
            viewer,
            resort=resort,
            start_date=today,
            end_date=today,
        )
        _make_trip(
            friend,
            resort=resort,
            start_date=today,
            end_date=today,
            is_public=False,
        )

        future_trip = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=12),
        )
        viewer.wish_list_resorts = [resort.id]
        private_past_trip = _make_trip(
            friend,
            resort=resort,
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=8),
            is_public=False,
        )
        db.session.commit()

        assert build_trip_overlap_today_card(
            viewer, today, [friend.id]
        ) is None
        assert build_friend_at_mountain_card(
            viewer, today, [friend.id]
        ) is None

        future_trip.is_public = True
        private_past_trip.is_public = True
        db.session.flush()
        assert build_friend_at_mountain_card(
            viewer, today, [friend.id]
        ) is not None