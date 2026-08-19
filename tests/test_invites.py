"""
#242 — Invite & visibility tests (spec sections 6, 13, 16).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import secrets
import unittest.mock
import pytest
from datetime import datetime, timedelta

from app import app
from models import (
    db, SkiTripParticipant, TripInviteToken, Invitation,
    Friend, GuestStatus,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, form_post, json_post,
)


# ── Section 6: private friend-trip visibility ─────────────────────────────────

@pytest.fixture
def visibility_setup(client):
    with app.app_context():
        resort   = _make_resort()
        owner    = _make_user("owner")
        friend   = _make_user("friend")
        stranger = _make_user("stranger")
        pub_trip  = _make_trip(owner, resort=resort, is_public=True)
        priv_trip = _make_trip(owner, resort=resort, is_public=False)
        db.session.add(Friend(user_id=owner.id,  friend_id=friend.id))
        db.session.add(Friend(user_id=friend.id, friend_id=owner.id))
        db.session.commit()
        data = {
            "owner_id":     owner.id,
            "friend_id":    friend.id,
            "stranger_id":  stranger.id,
            "pub_trip_id":  pub_trip.id,
            "priv_trip_id": priv_trip.id,
        }
    yield data


def test_friend_can_view_public_trip(client, visibility_setup):
    _login(client, visibility_setup["friend_id"])
    rv = client.get(f"/friend-trip/{visibility_setup['pub_trip_id']}")
    assert rv.status_code == 200


def test_friend_blocked_from_private_trip(client, visibility_setup):
    _login(client, visibility_setup["friend_id"])
    rv = client.get(f"/friend-trip/{visibility_setup['priv_trip_id']}")
    assert rv.status_code == 404


def test_non_friend_blocked_from_public_trip(client, visibility_setup):
    _login(client, visibility_setup["stranger_id"])
    rv = client.get(f"/friend-trip/{visibility_setup['pub_trip_id']}")
    assert rv.status_code == 403


def test_owner_can_view_own_private_trip_via_friend_trip(client, visibility_setup):
    _login(client, visibility_setup["owner_id"])
    rv = client.get(f"/friend-trip/{visibility_setup['priv_trip_id']}")
    assert rv.status_code == 200


# ── Section 13: TripInviteToken ───────────────────────────────────────────────

def _make_token(trip_id, inviter_id, expires_at=None, is_active=True):
    tok = TripInviteToken(
        token=secrets.token_urlsafe(32),
        trip_id=trip_id,
        inviter_user_id=inviter_id,
        expires_at=expires_at,
        is_active=is_active,
    )
    db.session.add(tok)
    db.session.flush()
    return tok.token


@pytest.fixture
def token_setup(client):
    with app.app_context():
        resort  = _make_resort()
        owner   = _make_user("owner")
        joiner1 = _make_user("joiner1")
        joiner2 = _make_user("joiner2")
        trip    = _make_trip(owner, resort=resort)
        db.session.commit()
        data = {
            "owner_id":   owner.id,
            "joiner1_id": joiner1.id,
            "joiner2_id": joiner2.id,
            "trip_id":    trip.id,
        }
    yield data


def test_token_no_expiry_landing_ok(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        db.session.commit()

    _login(client, token_setup["joiner1_id"])
    rv = client.get(f"/trip-invite/{token_str}")
    assert rv.status_code == 200


def test_token_future_expiry_landing_ok(client, token_setup):
    with app.app_context():
        token_str = _make_token(
            token_setup["trip_id"], token_setup["owner_id"],
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db.session.commit()

    _login(client, token_setup["joiner1_id"])
    rv = client.get(f"/trip-invite/{token_str}")
    assert rv.status_code == 200


def test_token_past_expiry_blocks_landing(client, token_setup):
    with app.app_context():
        token_str = _make_token(
            token_setup["trip_id"], token_setup["owner_id"],
            expires_at=datetime.utcnow() - timedelta(hours=72),
        )
        db.session.commit()

    _login(client, token_setup["joiner1_id"])
    rv = client.get(f"/trip-invite/{token_str}")
    assert rv.status_code in (200, 404)
    if rv.status_code == 200:
        body = rv.data.lower()
        assert b"expired" in body or b"invalid" in body or b"no longer" in body


def test_token_past_expiry_blocks_acceptance(client, token_setup):
    with app.app_context():
        token_str = _make_token(
            token_setup["trip_id"], token_setup["owner_id"],
            expires_at=datetime.utcnow() - timedelta(hours=72),
        )
        db.session.commit()

    _login(client, token_setup["joiner1_id"])
    rv = form_post(client, f"/trip-invite/{token_str}/accept")
    assert rv.status_code in (200, 302, 404)
    if rv.status_code == 302:
        assert f"/trips/{token_setup['trip_id']}" not in rv.headers.get("Location", "")

    with app.app_context():
        assert SkiTripParticipant.query.filter_by(
            trip_id=token_setup["trip_id"], user_id=token_setup["joiner1_id"]
        ).count() == 0


def test_inactive_token_blocked(client, token_setup):
    with app.app_context():
        token_str = _make_token(
            token_setup["trip_id"], token_setup["owner_id"],
            is_active=False,
        )
        db.session.commit()

    _login(client, token_setup["joiner1_id"])
    rv = client.get(f"/trip-invite/{token_str}")
    assert rv.status_code in (200, 404)
    if rv.status_code == 200:
        body = rv.data.lower()
        assert b"no longer" in body or b"invalid" in body or b"expired" in body


def test_same_user_accepts_token_twice_creates_one_participant_row(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        db.session.commit()

    trip_id = token_setup["trip_id"]
    user_id = token_setup["joiner1_id"]

    with unittest.mock.patch("app.emit_messaging_event"), \
         unittest.mock.patch("app.emit_trip_invite_accepted_activity"), \
         unittest.mock.patch("app.emit_friend_joined_trip_activities"):
        _login(client, user_id)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})

    with app.app_context():
        count = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=user_id
        ).count()
    assert count == 1, f"Expected 1 participant row, got {count}"


def test_same_user_second_acceptance_sends_no_new_notification(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        db.session.commit()
    user_id = token_setup["joiner1_id"]

    with unittest.mock.patch("app.emit_messaging_event") as mock_emit, \
         unittest.mock.patch("app.emit_trip_invite_accepted_activity"), \
         unittest.mock.patch("app.emit_friend_joined_trip_activities"):
        _login(client, user_id)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})
        first_count = mock_emit.call_count
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})
        second_count = mock_emit.call_count

    assert second_count == first_count, (
        "Second acceptance must not fire additional notifications"
    )


def test_two_users_can_both_accept_same_token(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        db.session.commit()

    trip_id = token_setup["trip_id"]
    j1      = token_setup["joiner1_id"]
    j2      = token_setup["joiner2_id"]

    with unittest.mock.patch("app.emit_messaging_event"), \
         unittest.mock.patch("app.emit_trip_invite_accepted_activity"), \
         unittest.mock.patch("app.emit_friend_joined_trip_activities"):
        _login(client, j1)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})
        _login(client, j2)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})

    with app.app_context():
        rows = SkiTripParticipant.query.filter(
            SkiTripParticipant.trip_id == trip_id,
            SkiTripParticipant.user_id.in_([j1, j2]),
            SkiTripParticipant.status == GuestStatus.GOING,
        ).all()
    assert len(rows) == 2, f"Both users should be Going; got {len(rows)}"


def test_pending_invitation_reconciled_on_token_accept(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        inv = Invitation(
            sender_id=token_setup["owner_id"],
            receiver_id=token_setup["joiner1_id"],
            trip_id=token_setup["trip_id"],
            status="pending",
        )
        db.session.add(inv)
        db.session.commit()
        inv_id = inv.id
    user_id = token_setup["joiner1_id"]

    with unittest.mock.patch("app.emit_messaging_event"), \
         unittest.mock.patch("app.emit_trip_invite_accepted_activity"), \
         unittest.mock.patch("app.emit_friend_joined_trip_activities"):
        _login(client, user_id)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})

    with app.app_context():
        updated = Invitation.query.get(inv_id)
        assert updated.status == "accepted", (
            f"Invitation must be reconciled to 'accepted'; got {updated.status!r}"
        )


# ── Section 16: notification recipient rules ──────────────────────────────────

def test_trip_invite_accepted_notifies_owner(client, token_setup):
    with app.app_context():
        token_str = _make_token(token_setup["trip_id"], token_setup["owner_id"])
        db.session.commit()
    owner_id  = token_setup["owner_id"]
    joiner_id = token_setup["joiner1_id"]

    with unittest.mock.patch("app.emit_messaging_event") as mock_emit, \
         unittest.mock.patch("app.emit_trip_invite_accepted_activity"), \
         unittest.mock.patch("app.emit_friend_joined_trip_activities"):
        _login(client, joiner_id)
        form_post(client, f"/trip-invite/{token_str}/accept", {"response": "going"})

    accepted_calls = [
        c for c in mock_emit.call_args_list
        if c.kwargs.get("event_name") == "trip.invite.accepted"
    ]
    recipient_ids = [c.kwargs.get("recipient_user_id") for c in accepted_calls]
    assert owner_id in recipient_ids, "Trip owner must receive TRIP_INVITE_ACCEPTED"
    assert joiner_id not in recipient_ids, "Joiner must not receive their own notification"


def test_trip_planning_post_created_notifies_other_members(client):
    with app.app_context():
        resort  = _make_resort()
        owner   = _make_user("owner")
        member1 = _make_user("member1")
        member2 = _make_user("member2")
        trip    = _make_trip(owner, resort=resort)
        _add_participant(trip, member1, GuestStatus.INTERESTED)
        _add_participant(trip, member2, GuestStatus.INTERESTED)
        db.session.commit()
        trip_id  = trip.id
        owner_id = owner.id
        m1_id    = member1.id
        m2_id    = member2.id

    _login(client, m1_id)
    with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
        json_post(client, f"/api/trip/{trip_id}/planning-posts",
                  {"category": "Other", "body": "What bindings?"})

    post_created_calls = [
        c for c in mock_emit.call_args_list
        if c.kwargs.get("event_name") == "trip.planning_post.created"
    ]
    recipient_ids = [c.kwargs.get("recipient_user_id") for c in post_created_calls]

    assert m1_id not in recipient_ids, "Author must not receive their own post notification"
    assert owner_id in recipient_ids or m2_id in recipient_ids, (
        "Other accepted members must receive TRIP_PLANNING_POST_CREATED"
    )
