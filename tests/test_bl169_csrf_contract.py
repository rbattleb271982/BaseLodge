"""Focused BL-169 regressions for the centralized CSRF contract."""

import os
from unittest.mock import Mock, patch

import pytest

from app import (
    _CSRF_EXEMPT_ENDPOINTS,
    _CSRF_UNSAFE_METHODS,
    app,
    begin_request_observability,
    enforce_csrf_for_unsafe_methods,
    limiter,
)
from models import GroupTrip, db
from tests.conftest import _TEST_CSRF, _login, _make_user, json_post


ADMIN_POST_ONLY_ROUTES = (
    "/admin/posthog-test",
    "/admin/seed-test-users",
    "/admin/seed-narrative-states",
    "/admin/seed-screenshot-data",
    "/admin/seed-screenshot-expansion",
    "/admin/backfill-planning-timestamp",
    "/admin/backfill-primary-rider-type",
    "/admin/backfill-organizers-as-participants",
    "/admin/backfill-country-codes",
)


def test_every_unsafe_route_uses_the_central_contract_or_explicit_exemption():
    assert _CSRF_UNSAFE_METHODS == {"POST", "PUT", "PATCH", "DELETE"}
    assert _CSRF_EXEMPT_ENDPOINTS == set()

    hooks = app.before_request_funcs[None]
    assert enforce_csrf_for_unsafe_methods in hooks
    prior_hooks = hooks[:hooks.index(enforce_csrf_for_unsafe_methods)]
    assert prior_hooks
    assert begin_request_observability in prior_hooks
    assert hooks[0] is begin_request_observability
    assert all(
        hook is begin_request_observability
        or getattr(hook, "__self__", None) is limiter
        for hook in prior_hooks
    )

    unsafe_endpoints = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if set(rule.methods) & _CSRF_UNSAFE_METHODS
    }
    assert unsafe_endpoints
    assert _CSRF_EXEMPT_ENDPOINTS <= unsafe_endpoints


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/auth"),
        ("PUT", "/api/admin/resorts/1"),
        ("PATCH", "/api/trip/1/planning-posts/1"),
        ("DELETE", "/api/friends/1"),
    ),
)
def test_each_unsafe_method_rejects_missing_csrf_before_handlers(
    client, method, path
):
    with patch.object(db.session, "commit") as commit:
        response = client.open(path, method=method)

    assert response.status_code == 403
    commit.assert_not_called()


def test_confirmed_group_trip_gap_rejects_missing_csrf_without_write(client):
    with app.app_context():
        user = _make_user("bl169-group-trip")
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with patch.object(db.session, "commit") as commit:
        response = client.post(
            "/api/group-trip/create",
            json={"title": "Forged", "start_date": "2026-12-01",
                  "end_date": "2026-12-02"},
        )

    assert response.status_code == 403
    commit.assert_not_called()
    with app.app_context():
        assert GroupTrip.query.count() == 0


def test_confirmed_group_trip_gap_accepts_valid_csrf(client):
    with app.app_context():
        user = _make_user("bl169-group-trip-valid")
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    with patch("app.ph_analytics.track"):
        response = json_post(
            client,
            "/api/group-trip/create",
            {"title": "Protected", "start_date": "2026-12-01",
             "end_date": "2026-12-02"},
        )

    assert response.status_code == 200
    with app.app_context():
        assert GroupTrip.query.filter_by(host_id=user_id, title="Protected").count() == 1


@pytest.mark.parametrize("route", ADMIN_POST_ONLY_ROUTES)
def test_identified_admin_execution_routes_are_post_only(route):
    rules = {rule.rule: set(rule.methods) for rule in app.url_map.iter_rules()}
    assert "POST" in rules[route]
    assert "GET" not in rules[route]


@pytest.mark.parametrize("route", ADMIN_POST_ONLY_ROUTES)
def test_converted_admin_gets_are_405_without_side_effects(client, route):
    with patch.object(db.session, "commit") as commit:
        response = client.get(route)

    assert response.status_code == 405
    commit.assert_not_called()


def test_admin_backfill_posthog_get_is_always_read_only(client):
    with app.app_context():
        admin = _make_user("bl169-admin", email="bl169-admin@bl.test")
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    with (
        patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": "bl169-admin@bl.test"}),
        patch("app.ph_analytics._get_client") as get_client,
    ):
        response = client.get("/admin/backfill-posthog")

    assert response.status_code == 200
    assert response.get_json()["dry_run"] is True
    assert response.get_json()["sent"] is False
    get_client.assert_not_called()


@pytest.mark.parametrize("route", ADMIN_POST_ONLY_ROUTES)
def test_converted_admin_posts_require_valid_csrf(client, route):
    rule = next(rule for rule in app.url_map.iter_rules() if rule.rule == route)
    view = Mock(return_value=("", 204))
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF

    with patch.dict(app.view_functions, {rule.endpoint: view}):
        response = client.post(
            route,
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert response.status_code == 403
        view.assert_not_called()

        response = client.post(
            route,
            headers={"X-CSRF-Token": _TEST_CSRF},
        )

    assert response.status_code == 204
    view.assert_called_once_with()