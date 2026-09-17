"""Focused accessible Auth error rendering regressions."""

from unittest.mock import patch

import pytest

from app import app
from models import db
from tests.conftest import _TEST_CSRF, _make_user


def _prime_csrf(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF


def _post_signup(client, **overrides):
    _prime_csrf(client)
    data = {
        "csrf_token": _TEST_CSRF,
        "form_type": "signup",
        "first_name": "Accessible",
        "last_name": "Signup",
        "email": "accessible-signup@example.test",
        "password": "ValidPass1!",
    }
    data.update(overrides)
    with patch("app.ph_analytics.track"):
        return client.post("/auth", data=data)


def test_clean_auth_render_has_no_server_alert_and_keeps_dynamic_alerts_empty(client):
    response = client.get("/auth")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<div class="auth-error" role="alert">' not in html
    assert 'id="login-error" role="alert" aria-atomic="true"' in html
    assert 'id="pw-error" role="alert"' in html
    assert 'aria-invalid="true"' not in html
    assert 'aria-describedby="pw-error"' not in html


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"first_name": ""}, "Please fill in all fields."),
        ({"password": "short"}, "Password must be at least 8 characters."),
    ),
)
def test_signup_validation_alert_preserves_signup_mode_and_values(
    client, overrides, message
):
    response = _post_signup(client, **overrides)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'<div class="auth-error" role="alert">{message}</div>' in html
    assert "const formType = 'signup';" in html
    assert "switchTab('signup');" in html
    assert 'value="Signup"' in html
    assert 'value="accessible-signup@example.test"' in html
    assert 'value="ValidPass1!"' not in html


def test_existing_account_signup_failure_uses_visible_server_alert(client):
    with app.app_context():
        existing = _make_user(
            "accessible-existing",
            email="accessible-existing@example.test",
        )
        db.session.commit()
        existing_email = existing.email

    response = _post_signup(
        client,
        email=existing_email,
        first_name="Retained",
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert (
        '<div class="auth-error" role="alert">'
        "An account with this email already exists.</div>"
    ) in html
    assert "const formType = 'signup';" in html
    assert 'value="Retained"' in html
    assert f'value="{existing_email}"' in html