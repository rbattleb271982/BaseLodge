"""
#242 — Account deletion tests (spec section 12).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import logging
import secrets
import time
from datetime import date
from unittest.mock import patch
import pytest
from app import app
from models import (
    db, User, SkiTrip, SkiDay, SkiTripParticipant, SkiTripPlanningPost,
    SkiTripRsvpTransition, TripInviteToken, Invitation, Friend, GuestStatus,
    FriendConnectionEvent, WishlistResortEvent,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login as _base_login, form_post,
)


@pytest.fixture
def deletion_setup(client):
    with app.app_context():
        resort = _make_resort()
        user   = _make_user("doomed", auth_provider="email")
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
            WishlistResortEvent(
                user_id=user.id,
                resort_id=resort.id,
                actor_user_id=user.id,
                event_type="added",
                source="settings",
            ),
            WishlistResortEvent(
                user_id=other.id,
                resort_id=resort.id,
                actor_user_id=user.id,
                event_type="added",
                source="mountain_detail",
            ),
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


def _login(client, user_id):
    _base_login(client, user_id)
    with app.test_request_context(
        "/",
        environ_base={
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": "Werkzeug/3.1.4",
        },
    ):
        session_identifier = app.login_manager._session_identifier_generator()
    with client.session_transaction() as session:
        session["_id"] = session_identifier
        session["_last_active_stamp"] = time.time()


def _login_nonfresh(client, user_id):
    _login(client, user_id)
    with client.session_transaction() as session:
        session["_fresh"] = False


# ── Correct email → full deletion ─────────────────────────────────────────────

def test_delete_account_removes_user(client, deletion_setup):
    s = deletion_setup
    _login(client, s["user_id"])
    rv = form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})
    assert rv.status_code in (200, 302)

    with app.app_context():
        assert User.query.get(s["user_id"]) is None


def test_delete_account_modal_requests_password_only_for_nonfresh_session(
    client, deletion_setup
):
    s = deletion_setup
    _login(client, s["user_id"])

    fresh_response = client.get("/profile")
    assert fresh_response.status_code == 200
    assert b'name="current_password"' not in fresh_response.data

    with client.session_transaction() as session:
        session["_fresh"] = False
    nonfresh_response = client.get("/profile")
    assert nonfresh_response.status_code == 200
    assert b'name="current_password"' in nonfresh_response.data
    assert b"remembered session" in nonfresh_response.data


@pytest.mark.parametrize("current_password", [None, "", "WrongPass9!"])
def test_nonfresh_delete_requires_correct_current_password_without_side_effects(
    client, deletion_setup, current_password
):
    s = deletion_setup
    _login_nonfresh(client, s["user_id"])
    data = {"confirm_email": s["user_email"]}
    if current_password is not None:
        data["current_password"] = current_password

    with patch.object(db.session, "commit") as commit:
        response = form_post(client, "/delete-account", data=data)

    assert response.status_code == 302
    commit.assert_not_called()
    with app.app_context():
        user = db.session.get(User, s["user_id"])
        assert user is not None
        assert user.email == s["user_email"]
        assert SkiTrip.query.get(s["owned_trip_id"]) is not None
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert "_user_id" in session


def test_nonfresh_delete_failure_defers_global_request_side_effects(
    client, deletion_setup
):
    s = deletion_setup
    _login_nonfresh(client, s["user_id"])
    with client.session_transaction() as session:
        session.pop("_last_active_stamp", None)
        session.pop("_auth_session_logged", None)

    with patch.object(db.session, "commit") as commit:
        response = form_post(
            client,
            "/delete-account",
            data={
                "confirm_email": s["user_email"],
                "current_password": "WrongPass9!",
            },
        )

    assert response.status_code == 302
    commit.assert_not_called()
    with app.app_context():
        user = db.session.get(User, s["user_id"])
        assert user is not None
        assert user.last_active_at is None
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert "_auth_session_logged" not in session
        assert "_last_active_stamp" not in session


def test_nonfresh_delete_correct_password_confirms_and_deletes(
    client, deletion_setup
):
    s = deletion_setup
    _login_nonfresh(client, s["user_id"])

    response = form_post(
        client,
        "/delete-account",
        data={
            "confirm_email": s["user_email"],
            "current_password": "TestPass1!",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, s["user_id"]) is None
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_nonfresh_delete_mismatched_email_does_not_confirm_login(
    client, deletion_setup
):
    s = deletion_setup
    _login_nonfresh(client, s["user_id"])

    response = form_post(
        client,
        "/delete-account",
        data={
            "confirm_email": "wrong@example.com",
            "current_password": "TestPass1!",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, s["user_id"]) is not None
    with client.session_transaction() as session:
        assert session["_fresh"] is False


def test_nonfresh_delete_provider_mismatch_fails_closed(
    client, deletion_setup
):
    s = deletion_setup
    with app.app_context():
        user = db.session.get(User, s["user_id"])
        user.auth_provider = "google"
        db.session.commit()
    _login_nonfresh(client, s["user_id"])

    response = form_post(
        client,
        "/delete-account",
        data={
            "confirm_email": s["user_email"],
            "current_password": "TestPass1!",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, s["user_id"]) is not None
    with client.session_transaction() as session:
        assert session["_fresh"] is False


def test_nonfresh_delete_reauth_stays_fresh_when_deletion_rolls_back(
    client, deletion_setup, monkeypatch
):
    s = deletion_setup
    _login_nonfresh(client, s["user_id"])

    def fail_commit():
        raise RuntimeError("forced deletion failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    response = form_post(
        client,
        "/delete-account",
        data={
            "confirm_email": s["user_email"],
            "current_password": "TestPass1!",
        },
    )

    assert response.status_code == 302
    set_cookie_headers = response.headers.getlist("Set-Cookie")
    session_header = next(
        header for header in set_cookie_headers if header.startswith("session=")
    )
    assert "Expires=" not in session_header
    assert "Max-Age=" not in session_header
    assert client.get_cookie("remember_token") is None
    with app.app_context():
        assert db.session.get(User, s["user_id"]) is not None
        assert SkiTrip.query.get(s["owned_trip_id"]) is not None
    with client.session_transaction() as session:
        assert session["_fresh"] is True
        assert "_user_id" in session
        assert session["_bl_authenticated_at"] > 0
        assert session.permanent is False


def test_nonfresh_delete_reauthentication_is_rate_limited(rate_limit_client):
    client = rate_limit_client
    with app.app_context():
        user = _make_user("delete-reauth-limit", auth_provider="email")
        db.session.commit()
        user_id = user.id
        email = user.email
    _login_nonfresh(client, user_id)

    responses = [
        form_post(
            client,
            "/delete-account",
            data={
                "confirm_email": email,
                "current_password": "WrongPass9!",
            },
        )
        for _ in range(6)
    ]

    assert all(response.status_code == 302 for response in responses[:5])
    assert responses[5].status_code == 429
    assert responses[5].headers["Retry-After"]
    with app.app_context():
        assert db.session.get(User, user_id) is not None
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert "_user_id" in session


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


def test_delete_account_erases_subject_wishlist_history_and_anonymizes_actor(
    client, deletion_setup
):
    s = deletion_setup
    _login(client, s["user_id"])
    form_post(client, "/delete-account", data={"confirm_email": s["user_email"]})

    with app.app_context():
        assert WishlistResortEvent.query.filter_by(
            user_id=s["user_id"]
        ).count() == 0
        surviving = WishlistResortEvent.query.filter_by(
            user_id=s["other_id"]
        ).one()
        assert surviving.actor_user_id is None
        assert WishlistResortEvent.query.filter_by(
            event_type="removed"
        ).count() == 0


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


def test_delete_account_attempt_log_excludes_raw_email_and_preserves_deletion(
    client, deletion_setup, caplog
):
    s = deletion_setup
    marker = "bl79-delete-email-marker-7f2d@example.test"
    with app.app_context():
        user = db.session.get(User, s["user_id"])
        user.email = marker
        db.session.commit()

    _login(client, s["user_id"])
    with caplog.at_level(logging.INFO, logger=app.logger.name):
        response = form_post(client, "/delete-account", data={"confirm_email": marker})

    messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "[delete_account]" in record.getMessage()
    )
    assert response.status_code in (200, 302)
    assert "[delete_account] attempt" in messages
    assert "confirmation_matched=True" in messages
    assert marker not in messages

    with app.app_context():
        assert User.query.get(s["user_id"]) is None


def test_delete_account_error_log_excludes_raw_email_and_keeps_user(
    client, deletion_setup, caplog, monkeypatch
):
    s = deletion_setup
    marker = "bl79-delete-error-email-marker-91ab@example.test"
    with app.app_context():
        user = db.session.get(User, s["user_id"])
        user.email = marker
        db.session.commit()

    def fail_commit():
        raise RuntimeError(f"database failure for {marker}")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    _login(client, s["user_id"])
    with caplog.at_level(logging.ERROR, logger=app.logger.name):
        response = form_post(client, "/delete-account", data={"confirm_email": marker})

    messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "[delete_account]" in record.getMessage()
    )
    assert response.status_code in (200, 302)
    assert "[delete_account] failed" in messages
    assert "error_type=RuntimeError" in messages
    assert marker not in messages

    with app.app_context():
        assert User.query.get(s["user_id"]) is not None
