"""Production-equivalent anonymous root readiness contracts."""

import time
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from redis.exceptions import TimeoutError as RedisTimeoutError

import app as app_module
from app import app, limiter
from models import db
from tests.conftest import _TEST_CSRF, _make_user


_ROOT_HOSTS = (
    "app.baselodgeapp.com",
    "candidate.example.replit.app",
    "candidate.example.replit.dev",
    "localhost",
    "127.0.0.1",
)


@pytest.mark.parametrize("host", _ROOT_HOSTS)
def test_anonymous_root_is_dependency_free_200(client, monkeypatch, host):
    statements = []

    with app.app_context():
        engine = db.engine

    def record_statement(*_args):
        statements.append("database")

    def unexpected_dependency(*_args, **_kwargs):
        raise AssertionError("anonymous root attempted an external dependency")

    sa.event.listen(engine, "before_cursor_execute", record_statement)
    original_limiter_enabled = limiter.enabled
    limiter.enabled = True
    monkeypatch.setattr(limiter._limiter, "test", unexpected_dependency)
    monkeypatch.setattr(limiter._limiter, "hit", unexpected_dependency)
    monkeypatch.setattr(app_module.httpx, "get", unexpected_dependency)
    monkeypatch.setattr(app_module.httpx, "post", unexpected_dependency)
    try:
        response = client.get("/", headers={"Host": host}, follow_redirects=False)
    finally:
        limiter.enabled = original_limiter_enabled
        sa.event.remove(engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert "Location" not in response.headers
    assert statements == []


def test_anonymous_root_survives_database_unavailability(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("fake-database-unavailable-sentinel")

    monkeypatch.setattr(sa.engine.Engine, "connect", unavailable)

    started = time.monotonic()
    response = client.get("/", headers={"Host": "app.baselodgeapp.com"})

    assert response.status_code == 200
    assert time.monotonic() - started < 1
    assert b"fake-database-unavailable-sentinel" not in response.data


def test_health_reports_sanitized_database_unavailability(client, monkeypatch):
    sentinel = "fake-database-unavailable-sentinel"

    def unavailable(*_args, **_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(app_module, "is_production", True)
    monkeypatch.setattr(db.session, "execute", unavailable)
    response = client.get("/health")

    assert response.status_code == 500
    assert response.get_json()["status"] == "unhealthy"
    assert response.get_json()["error"] == "Internal Server Error"
    assert sentinel.encode() not in response.data


def test_rate_limited_endpoint_fails_closed_on_redis_timeout(
    rate_limit_client, monkeypatch
):
    sentinel = "fake-redis-timeout-sentinel"

    def unavailable(*_args, **_kwargs):
        raise RedisTimeoutError(sentinel)

    monkeypatch.setattr(limiter._limiter, "hit", unavailable)
    with rate_limit_client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF

    started = time.monotonic()
    response = rate_limit_client.post(
        "/auth",
        data={
            "csrf_token": _TEST_CSRF,
            "form_type": "login",
            "email": "redis-unavailable@example.test",
            "password": "not-a-real-password",
        },
    )

    assert response.status_code == 500
    assert time.monotonic() - started < 1
    assert sentinel.encode() not in response.data


def test_generated_host_deep_link_still_redirects_to_canonical_domain(client):
    response = client.get(
        "/friends",
        headers={"Host": "candidate.example.replit.app"},
        follow_redirects=False,
    )

    assert response.status_code == 301
    assert response.headers["Location"].startswith("https://app.baselodgeapp.com/")


def test_canonical_deep_link_still_uses_anonymous_auth_gate(client):
    response = client.get(
        "/friends",
        headers={"Host": "app.baselodgeapp.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth")


def test_authenticated_root_retains_home_navigation(client):
    with app.app_context():
        user = _make_user("root-readiness-authenticated")
        db.session.commit()
        email = user.email

    with client.session_transaction(
        base_url="https://app.baselodgeapp.com"
    ) as session:
        session["_csrf_token"] = _TEST_CSRF

    with (
        patch("app.ph_analytics.identify"),
        patch("app.ph_analytics.track"),
        patch("app._queue_founder_login_push"),
    ):
        login_response = client.post(
            "/auth",
            headers={"Host": "app.baselodgeapp.com"},
            data={
                "csrf_token": _TEST_CSRF,
                "form_type": "login",
                "email": email,
                "password": "TestPass1!",
            },
            follow_redirects=False,
        )

    response = client.get(
        "/",
        headers={"Host": "app.baselodgeapp.com"},
        follow_redirects=False,
    )

    assert login_response.status_code == 302
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")