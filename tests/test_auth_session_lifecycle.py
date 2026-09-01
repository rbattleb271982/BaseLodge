"""Focused BL-168 authentication and session lifecycle regressions."""

from unittest.mock import patch
from datetime import datetime

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
    assert client.get("/profile").status_code == 200

    with app.app_context():
        user = db.session.get(User, user_id)
        user.set_password("LegacyChanged2!")
        user.password_changed_at = datetime.utcnow()
        db.session.commit()
    assert client.get("/profile").status_code == 302