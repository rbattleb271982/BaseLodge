"""Focused BL-215C server-enforced remember-token age regressions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask_login.utils import encode_cookie

import app as app_module
from app import app
from models import db, User
from tests.conftest import _TEST_CSRF, _make_user, form_post


ISSUED_AT = 2_000_000_000
MAX_AGE = 30 * 24 * 60 * 60
SESSION_COOKIE = app.config.get("SESSION_COOKIE_NAME", "session")
REMEMBER_COOKIE = app.config.get("REMEMBER_COOKIE_NAME", "remember_token")


def _prime_csrf(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF


def _real_login(client, email, *, remember=True, now=ISSUED_AT):
    data = {
        "form_type": "login",
        "email": email,
        "password": "TestPass1!",
        "csrf_token": _TEST_CSRF,
    }
    if remember:
        data["remember_me"] = "on"
    _prime_csrf(client)
    with (
        patch("app._remember_token_now", return_value=now),
        patch("app.ph_analytics.identify"),
        patch("app.ph_analytics.track"),
        patch("app._queue_founder_login_push"),
    ):
        return client.post("/auth", data=data, follow_redirects=False)


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
    from email.utils import parsedate_to_datetime

    return parsedate_to_datetime(expires).astimezone(timezone.utc)


def _remember_value(client):
    cookie = client.get_cookie(REMEMBER_COOKIE)
    return cookie.value if cookie is not None else None


def _restore(client, *, now, authenticated_now=None):
    authenticated_now = now if authenticated_now is None else authenticated_now
    with (
        patch("app._remember_token_now", return_value=now),
        patch("app._authenticated_session_now", return_value=authenticated_now),
    ):
        return client.get("/profile", follow_redirects=False)


def _copy_remember_cookie(source, target):
    target.set_cookie(REMEMBER_COOKIE, _remember_value(source))


def _assert_invalid_cookie_cleared(client, *, now):
    with (
        patch("app._remember_token_now", return_value=now),
        patch("app.ph_analytics.track") as analytics,
        patch.object(db.session, "commit") as commit,
    ):
        response = client.get("/profile", follow_redirects=False)

    assert response.status_code == 302
    analytics.assert_not_called()
    commit.assert_not_called()
    clear_header = _set_cookie_header(response, REMEMBER_COOKIE)
    assert clear_header is not None
    assert "Max-Age=0" in clear_header
    assert client.get_cookie(REMEMBER_COOKIE) is None
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert "_bl_authenticated_at" not in session


def test_fresh_remembered_login_issues_timed_token_and_exact_browser_expiry(client):
    with app.app_context():
        user = _make_user("remember-timed-issuance")
        db.session.commit()
        identity = user.get_id()
        email = user.email

    response = _real_login(client, email)
    token = _remember_value(client)
    expected_expiry = datetime.fromtimestamp(
        ISSUED_AT, tz=timezone.utc
    ) + timedelta(seconds=MAX_AGE)

    assert response.status_code == 302
    assert token is not None
    with (
        app.app_context(),
        patch("app._remember_token_now", return_value=ISSUED_AT),
    ):
        assert app_module._decode_timed_remember_identity(token) == identity
    assert _cookie_expiration(
        _set_cookie_header(response, REMEMBER_COOKIE)
    ) == expected_expiry
    with client.session_transaction() as session:
        assert session["_fresh"] is True
        assert session["_bl_authenticated_at"] > 0
        assert session.permanent is True


def test_fractional_issuance_uses_exact_server_boundary_and_one_browser_expiry(
    client,
):
    fractional_issuance = ISSUED_AT + 0.75
    with app.app_context():
        user = _make_user("remember-fractional-boundary")
        db.session.commit()
        email = user.email

    response = _real_login(client, email, now=fractional_issuance)
    expected_expiry = datetime.fromtimestamp(
        ISSUED_AT + MAX_AGE + 1,
        tz=timezone.utc,
    )
    assert _cookie_expiration(
        _set_cookie_header(response, REMEMBER_COOKIE)
    ) == expected_expiry

    client.delete_cookie(SESSION_COOKIE)
    assert _restore(
        client,
        now=fractional_issuance + MAX_AGE - 0.001,
    ).status_code == 200
    client.delete_cookie(SESSION_COOKIE)
    _assert_invalid_cookie_cleared(
        client,
        now=fractional_issuance + MAX_AGE,
    )


@pytest.mark.parametrize("age", [0, MAX_AGE - 1])
def test_timed_token_restores_only_before_thirty_day_boundary(client, age):
    with app.app_context():
        user = _make_user(f"remember-valid-{age}")
        db.session.commit()
        email = user.email
    login_response = _real_login(client, email)
    original_value = _remember_value(client)
    original_expiry = _cookie_expiration(
        _set_cookie_header(login_response, REMEMBER_COOKIE)
    )
    client.delete_cookie(SESSION_COOKIE)

    response = _restore(client, now=ISSUED_AT + age)

    assert response.status_code == 200
    assert _set_cookie_header(response, REMEMBER_COOKIE) is None
    assert _remember_value(client) == original_value
    assert (
        client.get_cookie(REMEMBER_COOKIE).expires.replace(tzinfo=timezone.utc)
        == original_expiry
    )
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert session["_bl_auth_method"] == "remember_cookie"
        assert session["_bl_authenticated_at"] == ISSUED_AT + age
        assert session.permanent is True


@pytest.mark.parametrize("age", [MAX_AGE, MAX_AGE + 1])
def test_timed_token_is_rejected_at_and_after_thirty_days(client, age):
    with app.app_context():
        user = _make_user(f"remember-expired-{age}")
        db.session.commit()
        email = user.email
    _real_login(client, email)
    client.delete_cookie(SESSION_COOKIE)

    _assert_invalid_cookie_cleared(client, now=ISSUED_AT + age)


def test_copied_expired_token_is_rejected_server_side(client):
    replay_client = app.test_client()
    with app.app_context():
        user = _make_user("remember-copied-expired")
        db.session.commit()
        email = user.email
    _real_login(client, email)
    _copy_remember_cookie(client, replay_client)

    _assert_invalid_cookie_cleared(
        replay_client,
        now=ISSUED_AT + MAX_AGE + 86400,
    )


def test_repeated_restoration_never_resets_remember_token_age(client):
    with app.app_context():
        user = _make_user("remember-fixed-age")
        db.session.commit()
        email = user.email
    login_response = _real_login(client, email)
    original_value = _remember_value(client)
    original_expiry = _cookie_expiration(
        _set_cookie_header(login_response, REMEMBER_COOKIE)
    )

    for age in (10 * 86400, 20 * 86400):
        client.delete_cookie(SESSION_COOKIE)
        response = _restore(client, now=ISSUED_AT + age)
        assert response.status_code == 200
        assert _set_cookie_header(response, REMEMBER_COOKIE) is None
        assert _remember_value(client) == original_value
        assert (
            client.get_cookie(REMEMBER_COOKIE).expires.replace(
                tzinfo=timezone.utc
            )
            == original_expiry
        )

    client.delete_cookie(SESSION_COOKIE)
    _assert_invalid_cookie_cleared(client, now=ISSUED_AT + MAX_AGE)


def test_ordinary_request_does_not_replace_or_extend_timed_token(client):
    with app.app_context():
        user = _make_user("remember-ordinary-request")
        db.session.commit()
        email = user.email
    login_response = _real_login(client, email)
    original_value = _remember_value(client)
    original_expiry = _cookie_expiration(
        _set_cookie_header(login_response, REMEMBER_COOKIE)
    )

    with patch("app._remember_token_now", return_value=ISSUED_AT + 86400):
        response = client.get("/profile")

    assert response.status_code == 200
    assert _set_cookie_header(response, REMEMBER_COOKIE) is None
    assert _remember_value(client) == original_value
    assert (
        client.get_cookie(REMEMBER_COOKIE).expires.replace(tzinfo=timezone.utc)
        == original_expiry
    )


def test_confirm_login_does_not_replace_or_extend_timed_token(client):
    with app.app_context():
        user = _make_user("remember-confirm-login", auth_provider="email")
        db.session.commit()
        email = user.email
    login_response = _real_login(client, email)
    original_value = _remember_value(client)
    original_expiry = _cookie_expiration(
        _set_cookie_header(login_response, REMEMBER_COOKIE)
    )
    client.delete_cookie(SESSION_COOKIE)
    assert _restore(client, now=ISSUED_AT + 86400).status_code == 200
    _prime_csrf(client)

    with (
        patch("app._remember_token_now", return_value=ISSUED_AT + 86400),
        patch.object(
            db.session,
            "commit",
            side_effect=RuntimeError("forced deletion rollback"),
        ),
    ):
        response = client.post(
            "/delete-account",
            data={
                "confirm_email": email,
                "current_password": "TestPass1!",
                "csrf_token": _TEST_CSRF,
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert _set_cookie_header(response, REMEMBER_COOKIE) is None
    assert _remember_value(client) == original_value
    assert (
        client.get_cookie(REMEMBER_COOKIE).expires.replace(tzinfo=timezone.utc)
        == original_expiry
    )
    with client.session_transaction() as session:
        assert session["_fresh"] is True
        assert session["_bl_authenticated_at"] > 0


def test_later_fresh_login_issues_distinct_token_without_revoking_first(client):
    later_client = app.test_client()
    with app.app_context():
        user = _make_user("remember-fresh-reissue")
        db.session.commit()
        email = user.email

    first_response = _real_login(client, email, now=ISSUED_AT)
    first_value = _remember_value(client)
    first_expiry = _cookie_expiration(
        _set_cookie_header(first_response, REMEMBER_COOKIE)
    )
    second_response = _real_login(
        later_client,
        email,
        now=ISSUED_AT + 3600,
    )
    second_value = _remember_value(later_client)
    second_expiry = _cookie_expiration(
        _set_cookie_header(second_response, REMEMBER_COOKIE)
    )

    assert second_value != first_value
    assert second_expiry - first_expiry == timedelta(hours=1)
    client.delete_cookie(SESSION_COOKIE)
    assert _restore(client, now=ISSUED_AT + 7200).status_code == 200
    assert _remember_value(client) == first_value


def test_two_fresh_logins_in_same_second_still_issue_distinct_tokens(client):
    other_client = app.test_client()
    with app.app_context():
        user = _make_user("remember-same-second-reissue")
        db.session.commit()
        email = user.email

    _real_login(client, email, now=ISSUED_AT)
    _real_login(other_client, email, now=ISSUED_AT)

    assert _remember_value(client) != _remember_value(other_client)


def test_expired_normal_session_restores_only_while_remember_token_is_valid(client):
    with app.app_context():
        user = _make_user("remember-normal-session-window")
        db.session.commit()
        email = user.email
    _real_login(client, email)
    client.delete_cookie(SESSION_COOKIE)
    restored_at = ISSUED_AT + 20 * 86400
    assert _restore(
        client,
        now=restored_at,
        authenticated_now=restored_at,
    ).status_code == 200

    seven_days_later = restored_at + 7 * 86400
    response = _restore(
        client,
        now=seven_days_later,
        authenticated_now=seven_days_later,
    )
    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["_fresh"] is False
        assert session["_bl_authenticated_at"] == seven_days_later

    client.delete_cookie(SESSION_COOKIE)
    _assert_invalid_cookie_cleared(client, now=ISSUED_AT + MAX_AGE)


def test_logout_clears_only_current_browser_timed_token(client):
    other_client = app.test_client()
    with app.app_context():
        user = _make_user("remember-multi-browser-logout")
        db.session.commit()
        email = user.email
    _real_login(client, email, now=ISSUED_AT)
    _real_login(other_client, email, now=ISSUED_AT + 1)
    other_value = _remember_value(other_client)

    _prime_csrf(client)
    with patch("app.ph_analytics.track"):
        response = form_post(client, "/logout")

    assert response.status_code == 302
    assert client.get_cookie(REMEMBER_COOKIE) is None
    assert other_client.get("/profile").status_code == 200
    assert _remember_value(other_client) == other_value
    other_client.delete_cookie(SESSION_COOKIE)
    assert _restore(other_client, now=ISSUED_AT + 2).status_code == 200
    assert _remember_value(other_client) == other_value


def test_supported_account_deletion_invalidates_other_clients_timed_token(client):
    other_client = app.test_client()
    replay_client = app.test_client()
    with app.app_context():
        user = _make_user("remember-account-deletion", auth_provider="email")
        db.session.commit()
        user_id = user.id
        email = user.email
    _real_login(client, email, now=ISSUED_AT)
    _real_login(other_client, email, now=ISSUED_AT + 1)
    _copy_remember_cookie(other_client, replay_client)
    _prime_csrf(client)

    response = form_post(
        client,
        "/delete-account",
        data={"confirm_email": email},
    )

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, user_id) is None
    with patch("app._remember_token_now", return_value=ISSUED_AT + 2):
        other_response = other_client.get("/profile")
    assert other_response.status_code == 302
    assert _set_cookie_header(other_response, REMEMBER_COOKIE) is not None
    assert other_client.get_cookie(REMEMBER_COOKIE) is None
    _assert_invalid_cookie_cleared(replay_client, now=ISSUED_AT + 2)


def test_legacy_token_does_not_invalidate_valid_normal_session_but_cannot_restore(
    client,
):
    with app.app_context():
        user = _make_user("remember-legacy-rollout")
        db.session.commit()
        email = user.email
        identity = user.get_id()
    _real_login(client, email)
    with app.test_request_context("/"):
        legacy_value = encode_cookie(identity)
    client.set_cookie(REMEMBER_COOKIE, legacy_value)

    response = client.get("/profile")

    assert response.status_code == 200
    assert _set_cookie_header(response, REMEMBER_COOKIE) is None
    assert _remember_value(client) == legacy_value
    client.delete_cookie(SESSION_COOKIE)
    _assert_invalid_cookie_cleared(client, now=ISSUED_AT + 1)


def test_invalid_timed_tokens_fail_closed_and_are_cleared(client):
    with app.app_context():
        user = _make_user("remember-invalid-values")
        db.session.commit()
        identity = user.get_id()

    with (
        app.app_context(),
        patch("app._remember_token_now", return_value=ISSUED_AT + 1),
    ):
        future_value = app_module._encode_timed_remember_identity(identity)
    with (
        app.app_context(),
        patch("app._remember_token_now", return_value=ISSUED_AT),
    ):
        unknown_version = app_module._remember_token_serializer().dumps(
            {"version": 999, "identity": identity, "nonce": "x" * 22}
        )
        valid_value = app_module._encode_timed_remember_identity(identity)

    parts = valid_value.split(".")
    payload_index = next(index for index, part in enumerate(parts) if part)
    replacement = "A" if parts[payload_index][0] != "A" else "B"
    parts[payload_index] = replacement + parts[payload_index][1:]
    tampered_value = ".".join(parts)

    with app.test_request_context("/"):
        legacy_value = encode_cookie(identity)

    for value in (
        "not-a-remember-token",
        tampered_value,
        future_value,
        unknown_version,
        legacy_value,
    ):
        invalid_client = app.test_client()
        invalid_client.set_cookie(REMEMBER_COOKIE, value)
        _assert_invalid_cookie_cleared(invalid_client, now=ISSUED_AT)