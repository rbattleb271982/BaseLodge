"""
#242 — Account deletion tests (spec section 12).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import secrets
import pytest
from app import app
from models import (
    db, User, SkiTrip, SkiTripParticipant, SkiTripPlanningPost,
    TripInviteToken, Invitation, Friend, GuestStatus,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, form_post,
)


@pytest.fixture
def deletion_setup(client):
    with app.app_context():
        resort = _make_resort()
        user   = _make_user("doomed")
        other  = _make_user("other")

        owned_trip = _make_trip(user, resort=resort)
        _add_participant(owned_trip, other, GuestStatus.ACCEPTED)

        db.session.add(SkiTripPlanningPost(
            trip_id=owned_trip.id, user_id=user.id,
            category="Other", body="Pack light",
        ))
        db.session.add(TripInviteToken(
            token=secrets.token_urlsafe(32),
            trip_id=owned_trip.id,
            inviter_user_id=user.id,
        ))
        db.session.add(Invitation(
            sender_id=user.id, receiver_id=other.id, status="pending",
        ))
        db.session.add(Friend(user_id=user.id,  friend_id=other.id))
        db.session.add(Friend(user_id=other.id, friend_id=user.id))

        other_trip = _make_trip(other, resort=resort)
        _add_participant(other_trip, user, GuestStatus.ACCEPTED)
        db.session.commit()
        data = {
            "user_id":       user.id,
            "user_email":    user.email,
            "other_id":      other.id,
            "owned_trip_id": owned_trip.id,
            "other_trip_id": other_trip.id,
        }
    yield data


# ── Correct email → full deletion ─────────────────────────────────────────────

def test_delete_account_removes_user(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    rv = form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})
    assert rv.status_code in (200, 302)

    with app.app_context():
        assert User.query.get(s["user_id"]) is None


def test_delete_account_removes_owned_trip_and_children(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert SkiTrip.query.get(s["owned_trip_id"]) is None
        assert SkiTripPlanningPost.query.filter_by(trip_id=s["owned_trip_id"]).count() == 0
        assert SkiTripParticipant.query.filter_by(trip_id=s["owned_trip_id"]).count() == 0
        assert TripInviteToken.query.filter_by(trip_id=s["owned_trip_id"]).count() == 0


def test_delete_account_removes_friendships(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert Friend.query.filter(
            db.or_(Friend.user_id == s["user_id"], Friend.friend_id == s["user_id"])
        ).count() == 0


def test_delete_account_removes_participant_rows_on_others_trips(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert SkiTripParticipant.query.filter_by(user_id=s["user_id"]).count() == 0


def test_delete_account_other_users_data_survives(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert SkiTrip.query.get(s["other_trip_id"]) is not None
        assert User.query.get(s["other_id"]) is not None


# ── Wrong confirmation email → user preserved ─────────────────────────────────

def test_wrong_email_blocks_deletion(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": "wrong@example.com"})

    with app.app_context():
        assert User.query.get(s["user_id"]) is not None


def test_empty_email_blocks_deletion(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": ""})

    with app.app_context():
        assert User.query.get(s["user_id"]) is not None
