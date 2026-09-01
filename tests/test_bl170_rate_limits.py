"""Focused BL-170 targeted abuse-protection contracts."""

import os
from unittest.mock import patch

from app import (
    app,
    limiter,
    _auth_pair_key,
    _rate_limit_fingerprint,
)
from models import db
from tests.conftest import _TEST_CSRF, _login, _make_user, form_post, json_post


def test_sensitive_fingerprints_are_deterministic_and_opaque():
    email = "victim@example.com"
    token = "raw-reset-token"
    first = _rate_limit_fingerprint(email, token)
    assert first == _rate_limit_fingerprint(email, token)
    assert email not in first
    assert token not in first
    assert len(first) == 32


def test_login_pair_limit_does_not_lock_a_different_email(rate_limit_client):
    client = rate_limit_client
    with client.session_transaction() as session:
        session["_csrf_token"] = "csrf"

    for _ in range(5):
        response = client.post(
            "/auth",
            data={
                "csrf_token": "csrf",
                "form_type": "login",
                "email": "first@example.com",
                "password": "wrong-password",
            },
        )
        assert response.status_code == 200

    limited = client.post(
        "/auth",
        data={
            "csrf_token": "csrf",
            "form_type": "login",
            "email": "first@example.com",
            "password": "wrong-password",
        },
    )
    other = client.post(
        "/auth",
        data={
            "csrf_token": "csrf",
            "form_type": "login",
            "email": "other@example.com",
            "password": "wrong-password",
        },
    )
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert other.status_code == 200


def test_api_429_contract_and_no_beacon_side_effect(rate_limit_client):
    client = rate_limit_client
    with app.app_context():
        user = _make_user("bl170-beacon")
        db.session.commit()
        user_id = user.id
    _login(client, user_id)

    with patch.object(app.logger, "warning") as warning:
        for number in range(10):
            response = json_post(
                client,
                "/api/push/beacon",
                {"step": f"step-{number}", "data": {}},
            )
            assert response.status_code == 200
        limited = json_post(
            client,
            "/api/push/beacon",
            {"step": "must-not-log", "data": {}},
        )

    assert limited.status_code == 429
    assert limited.get_json()["code"] == "rate_limited"
    assert limited.get_json()["retry_after"] >= 1
    assert limited.headers["Retry-After"]
    assert warning.call_count == 10


def test_auth_pair_key_never_contains_email(client):
    with app.test_request_context(
        "/auth",
        method="POST",
        data={"form_type": "login", "email": "private@example.com"},
        environ_base={"REMOTE_ADDR": "203.0.113.9"},
    ):
        key = _auth_pair_key()
    assert "private@example.com" not in key
    assert "203.0.113.9" not in key


def test_forgot_password_target_cooldown_is_silent(rate_limit_client):
    client = rate_limit_client
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF
    with app.app_context():
        user = _make_user(
            "bl170-reset",
            email="bl170-reset@example.com",
            auth_provider="email",
        )
        db.session.commit()
        email = user.email

    with patch("app.SendGridAPIClient") as sendgrid:
        sendgrid.return_value.send.return_value.status_code = 202
        responses = [
            form_post(client, "/forgot-password", {"email": email})
            for _ in range(4)
        ]

    assert all(response.status_code == 200 for response in responses)
    assert all(
        b"If an account exists with that email" in response.data
        for response in responses
    )
    assert sendgrid.return_value.send.call_count == 3


def test_shared_storage_configuration_is_explicit():
    assert app.config["RATELIMIT_STORAGE_URI"]
    assert app.config["RATELIMIT_SHARED_STORAGE_CONFIGURED"] is (
        app.config["RATELIMIT_STORAGE_URI"] != "memory://"
    )


def test_app_store_in_flight_lock_prevents_provider_calls(rate_limit_client):
    client = rate_limit_client
    email = "bl170-admin@example.com"
    with app.app_context():
        admin = _make_user("bl170-admin", email=email)
        db.session.commit()
        admin_id = admin.id
    _login(client, admin_id)

    lock_key = "LIMITER/baselodge/admin-app-store-refresh/in-flight"
    limiter.storage.incr(lock_key, 600)
    try:
        with (
            patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": email}),
            patch("services.app_store_client.fetch_daily_downloads") as ios_fetch,
            patch("services.play_store_client.fetch_daily_installs") as android_fetch,
        ):
            response = form_post(client, "/admin/app-store/refresh")
    finally:
        limiter.storage.clear(lock_key)

    assert response.status_code == 429
    assert response.headers["Retry-After"]
    ios_fetch.assert_not_called()
    android_fetch.assert_not_called()