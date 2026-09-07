"""Focused BL-168 authentication and session lifecycle regressions."""

from unittest.mock import patch
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import time

import pytest

from app import app, _trusted_local_redirect
from models import db, User
from tests.conftest import _TEST_CSRF, _make_user, form_post


def _prime_csrf(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF


def _real_login(client, email, *, remember=False):
    data = {
        "form_type": "login",
        "email": email,
        "password": "TestPass1!",
    }
    if remember:
        data["remember_me"] = "on"
    _prime_csrf(client)
    data["csrf_token"] = _TEST_CSRF
    with (
        patch("app.ph_analytics.identify"),
        patch("app.ph_analytics.track"),
        patch("app._queue_founder_login_push"),
    ):
        return client.post("/auth", data=data, follow_redirects=False)


def _assert_versioned_login(client, user_id, auth_method):
    with client.session_transaction() as session:
        assert session["_user_id"].startswith(f"{user_id}:")
        assert session["_bl_auth_method"] == auth_method
        assert session["_fresh"] is True
        assert math.isfinite(session["_bl_authenticated_at"])


def _set_cookie_header(response, name):
    prefix = f"{name}="
    return next(
        (
            header
            for header in response.headers.getlist("Set-Cookie")
            if header.startswith(prefix)
        ),
        None,
    )


def _cookie_expiration(header):
    expires = next(
        part.split("=", 1)[1]
        for part in header.split("; ")
        if part.startswith("Expires=")
    )
    return parsedate_to_datetime(expires).astimezone(timezone.utc)


def test_email_login_clears_unapproved_state_and_rejects_external_redirect(
    client,
):
    with app.app_context():
        user = _make_user("auth-session-email")
        db.session.commit()
        user_id = user.id
        email = user.email

    with client.session_transaction() as session:
        session["unapproved"] = "remove-me"
        session["post_onboarding_redirect"] = "/invite/safe-invite-token"
        session["post_login_redirect"] = "https://evil.example/steal"

    response = _real_login(client, email)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")
    _assert_versioned_login(client, user_id, "email")
    with client.session_transaction() as session:
        assert "unapproved" not in session
        assert "post_login_redirect" not in session
        assert session["post_onboarding_redirect"] == "/invite/safe-invite-token"


def test_email_login_preserves_and_consumes_trusted_local_redirect(client):
    with app.app_context():
        user = _make_user("auth-session-redirect")
        db.session.commit()
        email = user.email

    with client.session_transaction() as session:
        session["post_login_redirect"] = "/invite/safe-token"

    response = _real_login(client, email)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/invite/safe-token")
    with client.session_transaction() as session:
        assert "post_login_redirect" not in session


def test_trusted_local_redirect_rejects_browser_normalization_bypasses():
    assert _trusted_local_redirect("/invite/safe-token") == "/invite/safe-token"
    for unsafe in (
        "https://evil.example/steal",
        "//evil.example/steal",
        "/\\evil.example/steal",
        "/invite/\r\nLocation: https://evil.example",
        "   //evil.example/steal",
    ):
        assert _trusted_local_redirect(unsafe) is None


def test_email_login_remember_behavior_and_cookie_samesite(client):
    no_remember_client = app.test_client()
    with app.app_context():
        user = _make_user("auth-session-remember")
        db.session.commit()
        email = user.email

    _real_login(no_remember_client, email, remember=False)
    assert no_remember_client.get_cookie("remember_token") is None

    response = _real_login(client, email, remember=True)
    remember_cookie = client.get_cookie("remember_token")
    assert remember_cookie is not None
    assert remember_cookie.same_site == "Lax"
    assert "SameSite=Lax" in "\n".join(response.headers.getlist("Set-Cookie"))
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == app.config[
        "SESSION_COOKIE_SAMESITE"
    ]


def test_nonremembered_login_uses_browser_session_cookie(client):
    with app.app_context():
        user = _make_user("auth-session-browser-only")
        db.session.commit()
        email = user.email

    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        response = _real_login(client, email, remember=False)

    session_header = _set_cookie_header(response, "session")
    assert session_header is not None
    assert "Expires=" not in session_header
    assert "Max-Age=" not in session_header
    assert client.get_cookie("remember_token") is None
    with client.session_transaction() as session:
        assert session.permanent is False
        assert session["_fresh"] is True
        assert session["_bl_authenticated_at"] == 1_000_000.0


def test_remembered_login_uses_seven_and_thirty_day_cookie_expirations(client):
    with app.app_context():
        user = _make_user("auth-session-expirations")
        db.session.commit()
        email = user.email

    observed = datetime.now(timezone.utc)
    response = _real_login(client, email, remember=True)
    session_expiry = _cookie_expiration(_set_cookie_header(response, "session"))
    remember_expiry = _cookie_expiration(
        _set_cookie_header(response, "remember_token")
    )

    assert abs((session_expiry - observed).total_seconds() - 7 * 86400) < 3
    assert abs((remember_expiry - observed).total_seconds() - 30 * 86400) < 3
    with client.session_transaction() as session:
        assert session.permanent is True
        assert session["_fresh"] is True


def test_authenticated_at_stays_fixed_and_ordinary_request_does_not_roll_cookie(
    client,
):
    with app.app_context():
        user = _make_user("auth-session-fixed-age")
        db.session.commit()
        email = user.email

    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        _real_login(client, email, remember=True)
    with client.session_transaction() as session:
        session["_auth_session_logged"] = True
        session["_last_active_stamp"] = time.time()

    with patch("app._authenticated_session_now", return_value=1_000_200.0):
        first_response = client.get("/profile")
        response = client.get("/profile")

    assert first_response.status_code == 200
    assert response.status_code == 200
    assert _set_cookie_header(response, "session") is None
    with client.session_transaction() as session:
        assert session["_bl_authenticated_at"] == 1_000_000.0


def test_repeated_requests_cannot_extend_authentication_past_seven_days(client):
    with app.app_context():
        user = _make_user("auth-session-absolute-expiry")
        db.session.commit()
        email = user.email

    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        _real_login(client, email, remember=False)
    with patch(
        "app._authenticated_session_now",
        return_value=1_000_000.0 + 7 * 86400 - 1,
    ):
        assert client.get("/profile").status_code == 200
    with patch(
        "app._authenticated_session_now",
        return_value=1_000_000.0 + 7 * 86400,
    ):
        assert client.get("/profile").status_code == 302
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert "_bl_authenticated_at" not in session


@pytest.mark.parametrize(
    "invalid_value",
    [None, "1000000", float("nan"), float("inf"), -1.0, 1_000_001.0],
)
def test_invalid_authenticated_at_fails_closed(client, invalid_value):
    with app.app_context():
        user = _make_user("auth-session-invalid-age")
        db.session.commit()
        user_id = user.id
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        if invalid_value is not None:
            session["_bl_authenticated_at"] = invalid_value

    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        response = client.get("/profile")

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_tampered_signed_session_fails_closed(client):
    with app.app_context():
        user = _make_user("auth-session-tampered")
        db.session.commit()
        email = user.email
    _real_login(client, email, remember=False)
    cookie = client.get_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    parts = cookie.value.split(".")
    payload_index = 1 if parts[0] == "" else 0
    replacement = "A" if parts[payload_index][0] != "A" else "B"
    parts[payload_index] = replacement + parts[payload_index][1:]
    client.set_cookie("session", ".".join(parts))

    assert client.get("/profile").status_code == 302
    with client.session_transaction() as session:
        assert "_user_id" not in session


def test_remember_cookie_restoration_creates_nonfresh_session(client):
    with app.app_context():
        user = _make_user(
            "auth-session-restore-freshness",
            auth_provider="email",
        )
        db.session.commit()
        email = user.email

    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        login_response = _real_login(client, email, remember=True)
    assert client.get_cookie("remember_token") is not None
    remember_expiry = _cookie_expiration(
        _set_cookie_header(login_response, "remember_token")
    )
    client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))

    with patch("app._authenticated_session_now", return_value=1_000_100.0):
        response = client.get("/profile")

    assert response.status_code == 200
    assert _set_cookie_header(response, "remember_token") is None
    assert (
        client.get_cookie("remember_token").expires.replace(tzinfo=timezone.utc)
        == remember_expiry
    )
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert session["_bl_auth_method"] == "remember_cookie"
        assert session["_bl_authenticated_at"] == 1_000_100.0
        assert session.permanent is True


def test_legacy_session_uses_remember_cookie_to_restore_nonfresh(client):
    with app.app_context():
        user = _make_user("auth-session-legacy-restore")
        db.session.commit()
        email = user.email
    with patch("app._authenticated_session_now", return_value=1_000_000.0):
        _real_login(client, email, remember=True)
    with client.session_transaction() as session:
        session.pop("_bl_authenticated_at")

    with patch("app._authenticated_session_now", return_value=1_000_200.0):
        response = client.get("/profile")

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert session["_bl_auth_method"] == "remember_cookie"
        assert session["_bl_authenticated_at"] == 1_000_200.0


def test_remember_restoration_sets_policy_metadata_even_if_audit_log_fails(client):
    with app.app_context():
        user = _make_user("auth-session-restore-log-failure")
        db.session.commit()
        email = user.email
    _real_login(client, email, remember=True)
    client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))

    with (
        patch("app.app.logger.info", side_effect=RuntimeError("audit unavailable")),
        patch("app._authenticated_session_now", return_value=1_000_300.0),
    ):
        response = client.get("/profile")

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert session["_bl_auth_method"] == "remember_cookie"
        assert session["_bl_authenticated_at"] == 1_000_300.0


def test_expired_logout_request_has_no_authenticated_side_effects(client):
    with app.app_context():
        user = _make_user("auth-session-expired-logout")
        db.session.commit()
        user_id = user.id
        email = user.email
    _real_login(client, email, remember=False)
    _prime_csrf(client)
    with client.session_transaction() as session:
        session["_bl_authenticated_at"] = 1_000_000.0
        session.pop("_auth_session_logged", None)
        session.pop("_last_active_stamp", None)

    with (
        patch("app._authenticated_session_now", return_value=1_000_000.0 + 7 * 86400),
        patch("app.ph_analytics.track") as analytics,
        patch.object(db.session, "commit") as commit,
    ):
        response = form_post(client, "/logout")

    assert response.status_code == 302
    analytics.assert_not_called()
    commit.assert_not_called()
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert "_auth_session_logged" not in session
        assert "_last_active_stamp" not in session
    with app.app_context():
        assert db.session.get(User, user_id) is not None


def test_logout_removes_this_browsers_remember_cookie_and_policy_metadata(client):
    with app.app_context():
        user = _make_user("auth-session-remember-logout")
        db.session.commit()
        email = user.email
    _real_login(client, email, remember=True)
    _prime_csrf(client)
    assert client.get_cookie("remember_token") is not None

    with patch("app.ph_analytics.track"):
        response = form_post(client, "/logout")

    assert response.status_code == 302
    remember_header = _set_cookie_header(response, "remember_token")
    assert remember_header is not None
    assert "Max-Age=0" in remember_header
    assert client.get_cookie("remember_token") is None
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert "_bl_authenticated_at" not in session


def test_nonremembered_reset_clears_prior_accounts_remember_cookie(client):
    with app.app_context():
        first = _make_user("auth-session-prior-remember")
        second = _make_user("auth-session-new-account")
        db.session.commit()
        first_email = first.email
        second_id = second.id
        reset_token = second.get_reset_token()

    _real_login(client, first_email, remember=True)
    assert client.get_cookie("remember_token") is not None

    _prime_csrf(client)
    with patch("app._queue_founder_login_push"):
        response = form_post(
            client,
            f"/reset-password/{reset_token}",
            data={
                "password": "NewAccountPass2!",
                "confirm_password": "NewAccountPass2!",
            },
        )

    assert response.status_code == 302
    _assert_versioned_login(client, second_id, "reset")
    assert client.get_cookie("remember_token") is None


def test_signup_uses_fresh_remembered_session_and_preserves_onboarding(client):
    with client.session_transaction() as session:
        session["unapproved"] = "remove-me"
        session["post_onboarding_redirect"] = "/invite/signup-token"
        session["_csrf_token"] = _TEST_CSRF

    with (
        patch("app.ph_analytics.get_anon_id", return_value="anon"),
        patch("app.ph_analytics.alias"),
        patch("app.ph_analytics.identify"),
        patch("app.ph_analytics.track"),
    ):
        response = client.post(
            "/auth",
            data={
                "form_type": "signup",
                "email": "bl168-signup@test.bl",
                "password": "TestPass1!",
                "first_name": "Session",
                "last_name": "Signup",
                "csrf_token": _TEST_CSRF,
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/onboarding")
    with app.app_context():
        user_id = User.query.filter_by(email="bl168-signup@test.bl").one().id
    _assert_versioned_login(client, user_id, "signup")
    assert client.get_cookie("remember_token") is not None
    with client.session_transaction() as session:
        assert "unapproved" not in session
        assert session["post_onboarding_redirect"] == "/invite/signup-token"


def test_password_change_invalidates_all_clients_and_logs_out_current(client):
    second_client = app.test_client()
    with app.app_context():
        user = _make_user("auth-session-change", auth_provider="email")
        db.session.commit()
        email = user.email

    _real_login(client, email, remember=True)
    _real_login(second_client, email, remember=True)
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF

    response = form_post(
        client,
        "/change-password",
        data={
            "current_password": "TestPass1!",
            "new_password": "ChangedPass2!",
            "confirm_password": "ChangedPass2!",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth")
    with client.session_transaction() as session:
        assert "_user_id" not in session
    assert client.get_cookie("remember_token") is None
    assert second_client.get("/profile").status_code == 302

    second_client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    assert second_client.get("/profile").status_code == 302


def test_password_reset_revokes_old_sessions_and_creates_fresh_login(client):
    reset_client = app.test_client()
    with app.app_context():
        user = _make_user("auth-session-reset")
        db.session.commit()
        user_id = user.id
        email = user.email
        token = user.get_reset_token()

    _real_login(client, email, remember=True)
    _prime_csrf(reset_client)
    with (
        patch("app._queue_founder_login_push"),
        patch("app.ph_analytics.track"),
    ):
        response = reset_client.post(
            f"/reset-password/{token}",
            data={
                "password": "ResetPass2!",
                "confirm_password": "ResetPass2!",
                "csrf_token": _TEST_CSRF,
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    _assert_versioned_login(reset_client, user_id, "reset")
    session_header = _set_cookie_header(response, "session")
    assert "Expires=" not in session_header
    assert "Max-Age=" not in session_header
    assert reset_client.get_cookie("remember_token") is None
    assert reset_client.get("/home").status_code == 200
    assert client.get("/profile").status_code == 302

    client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    assert client.get("/profile").status_code == 302


def test_google_callback_uses_fresh_nonremembered_session(client):
    with app.app_context():
        user = _make_user(
            "auth-session-google",
            email="bl168-google@test.bl",
            auth_provider="google",
            provider_id="google-subject",
        )
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session["unapproved"] = "remove-me"
    userinfo = {
        "email": "bl168-google@test.bl",
        "sub": "google-subject",
        "given_name": "Google",
        "family_name": "Session",
    }
    with (
        patch("app.oauth.google.authorize_access_token", return_value={
            "userinfo": userinfo
        }),
        patch("app._queue_founder_login_push"),
    ):
        response = client.get("/auth/google/callback", follow_redirects=False)

    assert response.status_code == 302
    _assert_versioned_login(client, user_id, "google")
    assert client.get_cookie("remember_token") is None
    with client.session_transaction() as session:
        assert "unapproved" not in session


def test_deleted_user_versioned_cookie_fails_closed(client):
    with app.app_context():
        user = _make_user("auth-session-deleted")
        db.session.commit()
        user_id = user.id
        email = user.email

    _real_login(client, email, remember=True)
    _assert_versioned_login(client, user_id, "email")
    with app.app_context():
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()

    assert client.get("/profile").status_code == 302

    client.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    assert client.get("/profile").status_code == 302


def test_legacy_identity_is_accepted_only_until_password_changes(client):
    with app.app_context():
        user = _make_user("auth-session-legacy")
        db.session.commit()
        user_id = user.id

    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
        session["_bl_authenticated_at"] = 1_000_000.0
    with patch("app._authenticated_session_now", return_value=1_000_100.0):
        assert client.get("/profile").status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        user.set_password("LegacyChanged2!")
        user.password_changed_at = datetime.utcnow()
        db.session.commit()
    assert client.get("/profile").status_code == 302