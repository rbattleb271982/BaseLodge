"""Focused BL-173 bounded Friends-acceptance presentation tests."""

from datetime import datetime, timedelta

from models import Friend, FriendSuggestion, Invitation, InviteType, db
from tests.conftest import _TEST_CSRF, _login, _make_user


def _invitation(sender, receiver):
    invitation = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        trip_id=None,
        invite_type=InviteType.OUTBOUND,
        status="pending",
    )
    db.session.add(invitation)
    db.session.flush()
    return invitation


def test_acceptance_returns_canonical_bounded_presentation(client):
    with client.application.app_context():
        receiver = _make_user("accept-presentation-receiver")
        sender = _make_user("accept-presentation-sender")
        suggester = _make_user("accept-presentation-suggester")
        suggestion = FriendSuggestion(
            recipient_id=receiver.id,
            suggested_user_id=sender.id,
            suggester_id=suggester.id,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        invitation = _invitation(sender, receiver)
        db.session.add(suggestion)
        db.session.commit()
        receiver_id, sender_id, invitation_id = (
            receiver.id, sender.id, invitation.id
        )

    _login(client, receiver_id)
    response = client.post(
        f"/api/friends/invite/{invitation_id}/accept",
        headers={"X-CSRF-Token": _TEST_CSRF},
    )

    assert response.status_code == 200
    presentation = response.get_json()["presentation"]
    assert presentation["kind"] == "friends_acceptance"
    assert presentation["accepted_user_id"] == sender_id
    assert presentation["friend_count"] == 1
    assert presentation["pending_count"] == 0
    assert presentation["suggested_count"] == 0
    assert f'data-friend-id="{sender_id}"' in presentation["directory_html"]
    assert "fr-alpha-list" in presentation["directory_html"]
    assert presentation["directory_html"].count("fr-friend-row") == 1

    with client.application.app_context():
        assert Friend.query.filter_by(
            user_id=receiver_id, friend_id=sender_id
        ).count() == 1
        assert Friend.query.filter_by(
            user_id=sender_id, friend_id=receiver_id
        ).count() == 1
        assert FriendSuggestion.query.filter_by(
            recipient_id=receiver_id,
            suggested_user_id=sender_id,
        ).filter(FriendSuggestion.dismissed_at.is_not(None)).count() == 1


def test_acceptance_presentation_stays_on_first_bounded_page(client):
    with client.application.app_context():
        receiver = _make_user("accept-bounded-receiver")
        existing = [_make_user(f"accept-existing-{index:02d}") for index in range(25)]
        for friend in existing:
            db.session.add_all([
                Friend(user_id=receiver.id, friend_id=friend.id),
                Friend(user_id=friend.id, friend_id=receiver.id),
            ])
        sender = _make_user("accept-bounded-sender")
        invitation = _invitation(sender, receiver)
        db.session.commit()
        receiver_id, invitation_id = receiver.id, invitation.id

    _login(client, receiver_id)
    response = client.post(
        f"/api/friends/invite/{invitation_id}/accept",
        headers={"X-CSRF-Token": _TEST_CSRF},
    )

    presentation = response.get_json()["presentation"]
    assert presentation["friend_count"] == 26
    assert presentation["directory_html"].count("fr-friend-row") == 20
    assert 'id="fr-load-more"' in presentation["directory_html"]
    assert 'data-cursor=""' not in presentation["directory_html"]


def test_failed_acceptance_has_no_success_presentation(client):
    with client.application.app_context():
        receiver = _make_user("accept-failure-receiver")
        other = _make_user("accept-failure-other")
        sender = _make_user("accept-failure-sender")
        invitation = _invitation(sender, other)
        db.session.commit()
        receiver_id, invitation_id = receiver.id, invitation.id

    _login(client, receiver_id)
    response = client.post(
        f"/api/friends/invite/{invitation_id}/accept",
        headers={"X-CSRF-Token": _TEST_CSRF},
    )

    assert response.status_code == 403
    assert "presentation" not in response.get_json()


def test_acceptance_still_requires_csrf(client):
    with client.application.app_context():
        receiver = _make_user("accept-csrf-receiver")
        sender = _make_user("accept-csrf-sender")
        invitation = _invitation(sender, receiver)
        db.session.commit()
        receiver_id, invitation_id = receiver.id, invitation.id

    _login(client, receiver_id)
    response = client.post(f"/api/friends/invite/{invitation_id}/accept")
    assert response.status_code == 403