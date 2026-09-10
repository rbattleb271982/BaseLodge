from unittest.mock import patch

import analytics
from app import app
from models import User, db
from tests.conftest import _TEST_CSRF, _make_user, form_post


def _prime_csrf(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF


def test_email_signup_aliases_identifies_mutable_internal_and_tracks(client):
    _prime_csrf(client)
    with (
        patch("app.ph_analytics.get_anon_id", return_value="browser-anon"),
        patch("app.ph_analytics.alias") as alias,
        patch("app.ph_analytics.identify") as identify,
        patch("app.ph_analytics.track") as track,
    ):
        response = form_post(
            client,
            "/auth",
            data={
                "form_type": "signup",
                "email": "bl116-signup@test.bl",
                "password": "TestPass1!",
                "first_name": "Analytics",
                "last_name": "Signup",
            },
        )

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email="bl116-signup@test.bl").one()
        user_id = user.id
    alias.assert_called_once_with("browser-anon", user_id)
    identify.assert_called_once_with(
        user_id, properties={"is_internal": False}
    )
    track.assert_called_once_with(
        user_id,
        "signup_completed",
        {"method": "email", "signup_source": "organic"},
    )


def test_existing_email_login_identifies_and_tracks_without_alias(client):
    with app.app_context():
        user = _make_user("bl116-email-login", auth_provider="email")
        db.session.commit()
        user_id = user.id
        email = user.email

    _prime_csrf(client)
    with (
        patch("app.ph_analytics.alias") as alias,
        patch("app.ph_analytics.identify") as identify,
        patch("app.ph_analytics.track") as track,
    ):
        response = form_post(
            client,
            "/auth",
            data={
                "form_type": "login",
                "email": email,
                "password": "TestPass1!",
            },
        )

    assert response.status_code == 302
    alias.assert_not_called()
    identify.assert_called_once_with(
        user_id, properties={"is_internal": False}
    )
    track.assert_called_once_with(
        user_id, "login_completed", {"method": "email"}
    )


def test_google_signup_has_alias_identify_and_signup_parity(client):
    with (
        patch(
            "app.oauth.google.authorize_access_token",
            return_value={
                "userinfo": {
                    "email": "bl116-google-signup@test.bl",
                    "sub": "google-new",
                    "given_name": "Google",
                    "family_name": "Signup",
                }
            },
        ),
        patch("app.ph_analytics.get_anon_id", return_value="google-anon"),
        patch("app.ph_analytics.alias") as alias,
        patch("app.ph_analytics.identify") as identify,
        patch("app.ph_analytics.track") as track,
        patch("app._queue_founder_login_push"),
    ):
        response = client.get("/auth/google/callback")

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(
            email="bl116-google-signup@test.bl"
        ).one()
        user_id = user.id
    alias.assert_called_once_with("google-anon", user_id)
    identify.assert_called_once_with(
        user_id, properties={"is_internal": False}
    )
    track.assert_called_once_with(
        user_id,
        "signup_completed",
        {
            "method": "google",
            "signup_source": "organic",
            "is_invite_signup": False,
        },
    )


def test_existing_google_login_identifies_and_tracks_without_alias(client):
    with app.app_context():
        user = _make_user(
            "bl116-google-login",
            auth_provider="google",
            provider_id="google-existing",
        )
        db.session.commit()
        user_id = user.id
        email = user.email

    with (
        patch(
            "app.oauth.google.authorize_access_token",
            return_value={
                "userinfo": {
                    "email": email,
                    "sub": "google-existing",
                    "given_name": "Google",
                    "family_name": "Login",
                }
            },
        ),
        patch("app.ph_analytics.alias") as alias,
        patch("app.ph_analytics.identify") as identify,
        patch("app.ph_analytics.track") as track,
        patch("app._queue_founder_login_push"),
    ):
        response = client.get("/auth/google/callback")

    assert response.status_code == 302
    alias.assert_not_called()
    identify.assert_called_once_with(
        user_id, properties={"is_internal": False}
    )
    track.assert_called_once_with(
        user_id, "login_completed", {"method": "google"}
    )


def test_password_reset_identifies_and_tracks_authenticated_login(client):
    with app.app_context():
        user = _make_user("bl116-reset", auth_provider="email")
        db.session.commit()
        user_id = user.id
        token = user.get_reset_token()

    _prime_csrf(client)
    with (
        patch("app.ph_analytics.alias") as alias,
        patch("app.ph_analytics.identify") as identify,
        patch("app.ph_analytics.track") as track,
        patch("app._queue_founder_login_push"),
    ):
        response = form_post(
            client,
            f"/reset-password/{token}",
            data={
                "password": "ChangedPass2!",
                "confirm_password": "ChangedPass2!",
            },
        )

    assert response.status_code == 302
    alias.assert_not_called()
    identify.assert_called_once_with(
        user_id, properties={"is_internal": False}
    )
    track.assert_called_once_with(
        user_id, "login_completed", {"method": "password_reset"}
    )


def test_open_to_ski_uses_valid_browser_anonymous_id(client):
    with app.app_context():
        user = _make_user("bl116-open-to-ski")
        db.session.commit()
        user_id = user.id
    from tests.conftest import _login

    _login(client, user_id)
    with (
        patch("app.ph_analytics.get_anon_id", return_value="ots-anon"),
        patch("app.ph_analytics.track") as track,
    ):
        response = client.post(
            "/api/open-to-ski/analytics",
            json={
                "event": "availability_share_succeeded",
                "properties": {"format": "png", "delivery": "download"},
            },
            headers={"X-CSRF-Token": _TEST_CSRF},
        )

    assert response.status_code == 204
    track.assert_called_once_with(
        None,
        "availability_share_succeeded",
        {"format": "png", "delivery": "download"},
        anonymous_id="ots-anon",
    )


def test_open_to_ski_without_browser_id_uses_fresh_ids_per_event(
    client, monkeypatch
):
    with app.app_context():
        user = _make_user("bl116-open-to-ski-fallback")
        db.session.commit()
        user_id = user.id
    from tests.conftest import _login

    class CaptureClient:
        def __init__(self):
            self.distinct_ids = []

        def capture(self, _event, *, distinct_id, properties):
            self.distinct_ids.append(distinct_id)

    capture_client = CaptureClient()
    monkeypatch.setattr(analytics, "POSTHOG_KEY", "test-key")
    monkeypatch.setattr(analytics, "_client", capture_client)
    monkeypatch.setattr(analytics, "get_anon_id", lambda _cookies: None)
    _login(client, user_id)
    payload = {
        "event": "availability_share_succeeded",
        "properties": {"format": "png", "delivery": "download"},
    }

    first = client.post(
        "/api/open-to-ski/analytics",
        json=payload,
        headers={"X-CSRF-Token": _TEST_CSRF},
    )
    second = client.post(
        "/api/open-to-ski/analytics",
        json=payload,
        headers={"X-CSRF-Token": _TEST_CSRF},
    )

    assert first.status_code == 204
    assert second.status_code == 204
    assert len(capture_client.distinct_ids) == 2
    assert all(
        value.startswith("anonymous_event:")
        for value in capture_client.distinct_ids
    )
    assert capture_client.distinct_ids[0] != capture_client.distinct_ids[1]
