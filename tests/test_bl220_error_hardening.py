"""Focused BL-220 unexpected-server-error response hardening contracts."""

import ast
import json
import logging
from pathlib import Path

from flask import abort

import app as app_module
from app import app
from models import User, db
from services.log_privacy import ProductionLogPrivacyFilter
from services.request_observability import REQUEST_ID_HEADER
from tests.conftest import _login, _make_user, json_post


ROOT = Path(__file__).resolve().parents[1]
SAFE_JSON_BODY_KEYS = {"error", "message", "request_id"}


def _events(capsys):
    return [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and '"event_type":' in line
    ]


def _explode(message="synthetic-private-database-provider-detail"):
    raise RuntimeError(message)


def _login_admin(client, monkeypatch):
    with app.app_context():
        admin = _make_user(
            "bl220-admin",
            email="bl220-admin@test.bl",
        )
        db.session.commit()
        admin_id = admin.id
    monkeypatch.setenv("ALLOWED_ADMIN_EMAILS", "bl220-admin@test.bl")
    _login(client, admin_id)


def _assert_safe_json_error(response, events):
    assert response.status_code == 500
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert set(body) == SAFE_JSON_BODY_KEYS
    assert body["error"] == "internal_server_error"
    assert body["message"] == "An unexpected error occurred. Please try again."
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert len(events) == 1
    assert events[0]["event_type"] == "request_error"
    assert events[0]["request_id"] == body["request_id"]
    assert events[0]["status_code"] == 500


def test_unexpected_500_negotiates_html_and_json_accept(
    client, monkeypatch, capsys
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)
    monkeypatch.setitem(app.view_functions, "health_check", _explode)

    html = client.get("/health")
    html_events = _events(capsys)
    assert html.status_code == 500
    assert html.mimetype == "text/html"
    assert b"synthetic-private" not in html.data
    assert len(html_events) == 1
    assert html_events[0]["request_id"] == html.headers[REQUEST_ID_HEADER]

    json_response = client.get(
        "/health", headers={"Accept": "application/json"}
    )
    _assert_safe_json_error(json_response, _events(capsys))
    assert b"synthetic-private" not in json_response.data


def test_json_request_and_api_path_each_select_safe_json(
    client, monkeypatch, capsys
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)
    monkeypatch.setitem(app.view_functions, "health_check", _explode)

    explicit_json = client.get("/health", json={"private": "request-body"})
    _assert_safe_json_error(explicit_json, _events(capsys))

    monkeypatch.setitem(app.view_functions, "api_mountains_data", _explode)
    api_response = client.get("/api/mountains-data")
    _assert_safe_json_error(api_response, _events(capsys))


def test_standard_abort_500_is_safe_and_emits_once(
    client, monkeypatch, capsys
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 0)

    def aborting():
        abort(500, "synthetic-sensitive-abort-description")

    monkeypatch.setitem(app.view_functions, "health_check", aborting)
    response = client.get("/health")
    events = _events(capsys)

    assert response.status_code == 500
    assert response.mimetype == "text/html"
    assert b"synthetic-sensitive-abort-description" not in response.data
    assert len(events) == 1
    assert events[0]["event_type"] == "request_error"
    assert events[0]["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_non_http_catchall_has_safe_correlated_body(
    client, monkeypatch, capsys
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 0)
    monkeypatch.setitem(app.view_functions, "health_check", _explode)

    response = client.get("/health", headers={"Accept": "application/json"})
    events = _events(capsys)
    _assert_safe_json_error(response, events)
    assert len(events) == 1


def test_health_database_failure_preserves_contract_and_emits_once(
    client, monkeypatch, capsys
):
    secret = "synthetic-private-health-database-detail"

    def fail_database_probe(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)
    monkeypatch.setattr(app_module, "is_production", True)
    monkeypatch.setattr(db.session, "execute", fail_database_probe)

    response = client.get("/health")
    events = _events(capsys)

    assert response.status_code == 500
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "disconnected"
    assert body["error"] == "Internal Server Error"
    assert secret not in response.get_data(as_text=True)
    assert len(events) == 1
    assert events[0]["event_type"] == "request_error"
    assert events[0]["exception_class"] == "RuntimeError"
    assert events[0]["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_seed_failure_rolls_back_and_returns_safe_correlated_error(
    client, monkeypatch, capsys
):
    import seed_screenshots

    secret = "synthetic-private-seed-database-detail"
    staged_email = "bl220-staged-seed@test.bl"
    _login_admin(client, monkeypatch)
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)

    def fail_after_staging(*_args, **_kwargs):
        _make_user("bl220-staged", email=staged_email)
        raise RuntimeError(secret)

    monkeypatch.setattr(
        seed_screenshots,
        "seed_screenshot_data",
        fail_after_staging,
    )

    response = json_post(client, "/admin/seed-screenshot-data")
    _assert_safe_json_error(response, _events(capsys))
    assert secret not in response.get_data(as_text=True)

    with app.app_context():
        assert User.query.filter_by(email=staged_email).count() == 0


def test_excel_failure_uses_privacy_filtered_error_logger(
    client, monkeypatch, capsys, caplog
):
    import openpyxl

    secret = "synthetic-private-excel-traceback-detail"
    _login_admin(client, monkeypatch)
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)

    def fail_workbook():
        raise RuntimeError(secret)

    monkeypatch.setattr(openpyxl, "Workbook", fail_workbook)
    privacy_filter = ProductionLogPrivacyFilter("production")
    app.logger.addFilter(privacy_filter)
    try:
        with caplog.at_level(logging.ERROR, logger=app.logger.name):
            response = client.get(
                "/admin/resorts/export-excel",
                headers={"Accept": "application/json"},
            )
    finally:
        app.logger.removeFilter(privacy_filter)

    _assert_safe_json_error(response, _events(capsys))
    records = [
        record
        for record in caplog.records
        if getattr(record, "_bl_privacy_sanitized", False)
    ]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["severity"] == "error"
    assert payload["exception_class"] == "RuntimeError"
    assert payload["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert secret not in records[0].getMessage()
    assert records[0].exc_info is None


def test_expected_404_and_csrf_remain_non_error_events(
    client, monkeypatch, capsys
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)

    missing = client.get("/api/missing-bl220")
    assert missing.status_code == 404
    assert missing.mimetype == "text/html"
    assert _events(capsys) == []

    csrf = client.post(
        "/auth",
        json={"password": "synthetic-private-password"},
        headers={"Accept": "application/json"},
    )
    assert csrf.status_code == 403
    assert csrf.get_json() == {
        "error": "csrf_failed",
        "message": "CSRF token missing or invalid.",
    }
    assert _events(capsys) == []


def test_route_normalization_contract_is_unchanged(client, monkeypatch, capsys):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 0)
    response = client.get("/friends/987654?token=synthetic-query-secret")
    events = _events(capsys)

    assert response.status_code in (302, 404)
    assert len(events) == 1
    assert events[0]["event_type"] == "request_slow"
    assert events[0]["route"] == "/friends/<int:friend_id>"
    assert "synthetic-query-secret" not in json.dumps(events)


def test_no_raw_traceback_or_exception_in_500_response_source():
    source = (ROOT / "app.py").read_text()
    tree = ast.parse(source)

    assert "traceback.print_exc" not in source
    assert "traceback.format_exc" not in source

    for node in ast.walk(tree):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if not (
            isinstance(value, ast.Tuple)
            and len(value.elts) == 2
            and isinstance(value.elts[1], ast.Constant)
            and value.elts[1].value == 500
        ):
            continue
        payload = value.elts[0]
        has_str_call = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "str"
            for child in ast.walk(payload)
        )
        if has_str_call:
            # /health preserves richer local diagnostics but guards Production.
            payload_source = ast.get_source_segment(source, payload) or ""
            assert "is_production" in payload_source
        assert not any(
            isinstance(child, ast.FormattedValue)
            and isinstance(child.value, ast.Name)
            and child.value.id in {"e", "exc", "_qe"}
            for child in ast.walk(payload)
        )

    helper = app_module.unexpected_server_error_response
    assert helper.__name__ == "unexpected_server_error_response"