"""
#242 — Account deletion tests (spec section 12).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import secrets
from datetime import date
import pytest
from app import app
from models import (
    db, User, SkiTrip, SkiDay, SkiTripParticipant, SkiTripPlanningPost,
    SkiTripRsvpTransition, TripInviteToken, Invitation, Friend, GuestStatus,
    FriendConnectionEvent,
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
        unrelated_a = _make_user("unrelated-a")
        unrelated_b = _make_user("unrelated-b")

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
        pair_connection_event = FriendConnectionEvent(
            user_a_id=min(user.id, other.id),
            user_b_id=max(user.id, other.id),
            event_type="formed",
            actor_user_id=user.id,
            source="qr_connect",
        )
        actor_only_connection_event = FriendConnectionEvent(
            user_a_id=min(unrelated_a.id, unrelated_b.id),
            user_b_id=max(unrelated_a.id, unrelated_b.id),
            event_type="formed",
            actor_user_id=user.id,
            source="shared_trip_connect",
        )

        other_trip = _make_trip(other, resort=resort)
        _add_participant(other_trip, user, GuestStatus.ACCEPTED)
        subject_history = SkiTripRsvpTransition(
            trip_id=other_trip.id,
            user_id=user.id,
            previous_status="pending",
            new_status="interested",
            actor_user_id=user.id,
            source="invite_response",
        )
        surviving_actor_history = SkiTripRsvpTransition(
            trip_id=other_trip.id,
            user_id=other.id,
            previous_status="interested",
            new_status="going",
            actor_user_id=user.id,
            source="organizer_rsvp",
        )
        owned_trip_history = SkiTripRsvpTransition(
            trip_id=owned_trip.id,
            user_id=other.id,
            previous_status="pending",
            new_status="going",
            actor_user_id=user.id,
            source="invite_response",
        )
        db.session.add_all([
            subject_history,
            surviving_actor_history,
            owned_trip_history,
            pair_connection_event,
            actor_only_connection_event,
        ])
        db.session.add_all([
            SkiDay(
                user_id=user.id,
                resort_id=resort.id,
                ski_date=date(2026, 1, 15),
                trip_id=owned_trip.id,
                source="trip_confirmation",
            ),
            SkiDay(
                user_id=other.id,
                resort_id=resort.id,
                ski_date=date(2026, 1, 16),
                trip_id=other_trip.id,
                source="user_confirmation",
            ),
        ])
        db.session.commit()
        data = {
            "user_id":       user.id,
            "user_email":    user.email,
            "other_id":      other.id,
            "owned_trip_id": owned_trip.id,
            "other_trip_id": other_trip.id,
            "subject_history_id": subject_history.id,
            "surviving_actor_history_id": surviving_actor_history.id,
            "owned_trip_history_id": owned_trip_history.id,
            "pair_connection_event_id": pair_connection_event.id,
            "actor_only_connection_event_id": actor_only_connection_event.id,
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
        assert SkiDay.query.filter_by(user_id=s["other_id"]).count() == 1


def test_delete_account_erases_subject_and_owned_trip_history_but_nulls_actor(
    client, deletion_setup
):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert SkiTripRsvpTransition.query.get(s["subject_history_id"]) is None
        assert SkiTripRsvpTransition.query.get(s["owned_trip_history_id"]) is None
        surviving = SkiTripRsvpTransition.query.get(
            s["surviving_actor_history_id"]
        )
        assert surviving is not None
        assert surviving.user_id == s["other_id"]
        assert surviving.actor_user_id is None


def test_delete_account_erases_pair_connection_history_without_removed_event(
    client, deletion_setup
):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert db.session.get(
            FriendConnectionEvent, s["pair_connection_event_id"]
        ) is None
        # Account deletion erases history; it is not an unfriend lifecycle action.
        assert FriendConnectionEvent.query.filter_by(
            event_type="removed", actor_user_id=s["user_id"]
        ).count() == 0


def test_delete_account_nulls_actor_on_unrelated_connection_history(
    client, deletion_setup
):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        surviving = db.session.get(
            FriendConnectionEvent, s["actor_only_connection_event_id"]
        )
        assert surviving is not None
        assert surviving.actor_user_id is None


def test_delete_account_removes_only_deleted_users_ski_days(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert SkiDay.query.filter_by(user_id=s["user_id"]).count() == 0
        assert SkiDay.query.filter_by(user_id=s["other_id"]).count() == 1


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
