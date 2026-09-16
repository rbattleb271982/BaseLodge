"""Focused regressions for the final BL-225 Friends ship blockers."""

from datetime import datetime, timedelta

from app import app, create_friend_request
from models import (
    Friend,
    FriendConnectionEvent,
    FriendCooldown,
    FriendSuggestion,
    Invitation,
    InviteType,
    db,
)
from tests.conftest import _login, _make_user, json_delete, json_post


def _null_trip_request(sender_id, receiver_id):
    invitation = Invitation(
        sender_id=sender_id,
        receiver_id=receiver_id,
        status="pending",
        invite_type=InviteType.REQUEST,
    )
    db.session.add(invitation)
    db.session.commit()
    return invitation.id


def test_null_trip_non_outbound_does_not_block_legitimate_social_request(client):
    with app.app_context():
        sender = _make_user("bl225-scope-sender")
        receiver = _make_user("bl225-scope-receiver")
        db.session.commit()
        request_id = _null_trip_request(sender.id, receiver.id)

        result = create_friend_request(sender.id, receiver.id)

        assert result["ok"] is True
        assert result["invitation_id"] != request_id
        social = db.session.get(Invitation, result["invitation_id"])
        assert social.invite_type == InviteType.OUTBOUND


def test_null_trip_non_outbound_is_not_incoming_badge_search_or_notifications(client):
    with app.app_context():
        sender = _make_user("bl225-scope-hidden-sender")
        sender.first_name = "Scope"
        sender.last_name = "Hidden"
        sender.search_first_name = "scope"
        sender.search_last_name = "hidden"
        receiver = _make_user("bl225-scope-viewer")
        receiver.first_name = "Scope"
        receiver.last_name = "Viewer"
        receiver.search_first_name = "scope"
        receiver.search_last_name = "viewer"
        db.session.commit()
        invitation_id = _null_trip_request(sender.id, receiver.id)
        sender_id = sender.id
        receiver_id = receiver.id

    _login(client, receiver_id)
    friends_html = client.get("/friends").get_data(as_text=True)
    profile_html = client.get("/profile").get_data(as_text=True)
    search = client.get("/api/users/search?q=Scope+Hidden").get_json()
    notifications_html = client.get("/notifications").get_data(as_text=True)

    assert f'id="fr-req-{invitation_id}"' not in friends_html
    assert 'class="bl-nav-badge"' not in profile_html
    match = next(row for row in search if row["id"] == sender_id)
    assert match["relationship_state"] == "none"
    assert match["invitation_id"] is None
    assert f'connect-row-{invitation_id}' not in notifications_html

    _login(client, sender_id)
    outgoing_search = client.get("/api/users/search?q=Scope+Viewer").get_json()
    outgoing_match = next(
        row for row in outgoing_search if row["id"] == receiver_id
    )
    assert outgoing_match["relationship_state"] == "none"
    assert outgoing_match["invitation_id"] is None


def test_null_trip_non_outbound_is_not_suggested_requested_state(client):
    with app.app_context():
        viewer = _make_user("bl225-scope-suggestion-viewer")
        suggester = _make_user("bl225-scope-suggester")
        target = _make_user("bl225-scope-suggested")
        db.session.add(FriendSuggestion(
            suggester_id=suggester.id,
            recipient_id=viewer.id,
            suggested_user_id=target.id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        ))
        db.session.commit()
        invitation_id = _null_trip_request(viewer.id, target.id)
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = client.get("/api/friends/suggestions/page").get_json()["html"]

    assert f'data-sugg-invitation-id="{invitation_id}"' not in html
    assert 'data-sugg-action="requested"' not in html


def test_null_trip_non_outbound_cannot_be_accepted_or_cancelled(client):
    with app.app_context():
        sender = _make_user("bl225-scope-mutation-sender")
        receiver = _make_user("bl225-scope-mutation-receiver")
        db.session.commit()
        invitation_id = _null_trip_request(sender.id, receiver.id)
        sender_id, receiver_id = sender.id, receiver.id

    _login(client, receiver_id)
    accepted = json_post(
        client, f"/api/friends/invite/{invitation_id}/accept"
    )
    assert accepted.status_code == 400

    _login(client, sender_id)
    cancelled = json_delete(client, f"/api/friends/invite/{invitation_id}")
    assert cancelled.status_code == 400

    with app.app_context():
        invitation = db.session.get(Invitation, invitation_id)
        assert invitation.status == "pending"
        assert Friend.query.filter(
            Friend.user_id.in_((sender_id, receiver_id)),
            Friend.friend_id.in_((sender_id, receiver_id)),
        ).count() == 0
        assert FriendCooldown.query.count() == 0


def test_accept_then_cancel_has_one_terminal_state_and_no_cooldown(client):
    with app.app_context():
        sender = _make_user("bl225-serial-sender")
        receiver = _make_user("bl225-serial-receiver")
        invitation = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add(invitation)
        db.session.commit()
        invitation_id = invitation.id
        sender_id, receiver_id = sender.id, receiver.id

    _login(client, receiver_id)
    assert json_post(
        client, f"/api/friends/invite/{invitation_id}/accept"
    ).status_code == 200

    _login(client, sender_id)
    assert json_delete(
        client, f"/api/friends/invite/{invitation_id}"
    ).status_code == 409

    with app.app_context():
        assert db.session.get(Invitation, invitation_id).status == "accepted"
        assert Friend.query.filter(
            Friend.user_id.in_((sender_id, receiver_id)),
            Friend.friend_id.in_((sender_id, receiver_id)),
        ).count() == 2
        assert FriendCooldown.query.count() == 0


def test_acceptance_presentation_ignores_non_outbound_pending_count(client):
    with app.app_context():
        sender = _make_user("bl225-presentation-sender")
        receiver = _make_user("bl225-presentation-receiver")
        other = _make_user("bl225-presentation-other")
        social = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        unrelated = Invitation(
            sender_id=other.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.REQUEST,
        )
        db.session.add_all([social, unrelated])
        db.session.commit()
        social_id = social.id
        unrelated_id = unrelated.id
        receiver_id = receiver.id

    _login(client, receiver_id)
    response = json_post(
        client, f"/api/friends/invite/{social_id}/accept"
    )

    assert response.status_code == 200
    assert response.get_json()["presentation"]["pending_count"] == 0
    with app.app_context():
        assert db.session.get(Invitation, unrelated_id).status == "pending"


def test_repeated_accept_is_idempotent_without_duplicate_side_effects(client):
    with app.app_context():
        sender = _make_user("bl225-repeat-accept-sender")
        receiver = _make_user("bl225-repeat-accept-receiver")
        invitation = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add(invitation)
        db.session.commit()
        invitation_id = invitation.id
        sender_id, receiver_id = sender.id, receiver.id

    _login(client, receiver_id)
    first = json_post(client, f"/api/friends/invite/{invitation_id}/accept")
    second = json_post(client, f"/api/friends/invite/{invitation_id}/accept")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["message"] == "Already friends"
    with app.app_context():
        assert db.session.get(Invitation, invitation_id).status == "accepted"
        assert Friend.query.filter(
            Friend.user_id.in_((sender_id, receiver_id)),
            Friend.friend_id.in_((sender_id, receiver_id)),
        ).count() == 2
        assert FriendConnectionEvent.query.filter_by(
            user_a_id=min(sender_id, receiver_id),
            user_b_id=max(sender_id, receiver_id),
            event_type="formed",
        ).count() == 1
        assert FriendCooldown.query.count() == 0


def test_accept_and_cancel_load_invitation_with_row_lock(client, monkeypatch):
    query_type = None
    with app.app_context():
        sender = _make_user("bl225-lock-sender")
        receiver = _make_user("bl225-lock-receiver")
        first = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        second = Invitation(
            sender_id=sender.id,
            receiver_id=receiver.id,
            status="pending",
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add_all([first, second])
        db.session.commit()
        first_id, second_id = first.id, second.id
        sender_id, receiver_id = sender.id, receiver.id
        query_type = type(Invitation.query)

    calls = []
    original = query_type.with_for_update

    def recording_with_for_update(self, *args, **kwargs):
        if self.column_descriptions[0].get("entity") is Invitation:
            calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(query_type, "with_for_update", recording_with_for_update)

    _login(client, receiver_id)
    assert json_post(
        client, f"/api/friends/invite/{first_id}/accept"
    ).status_code == 200
    _login(client, sender_id)
    assert json_delete(
        client, f"/api/friends/invite/{second_id}"
    ).status_code == 200
    assert calls == [True, True]