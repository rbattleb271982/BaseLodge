"""Focused BL-178 request correlation, event, and privacy contracts."""

import json
import time
from types import SimpleNamespace

from flask import g, jsonify

import app as app_module
from app import app
import services.request_observability as request_observability
from services.request_observability import REQUEST_ID_HEADER


def _parse_events(output):
    events = []
    for line in output.splitlines():
        if line.startswith("{") and '"event_type":' in line:
            events.append(json.loads(line))
    return events


def _events(capsys):
    return _parse_events(capsys.readouterr().out)


def test_server_owned_request_ids_cover_success_redirect_404_and_csrf(
    client, monkeypatch
):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)
    success = client.get("/health", headers={REQUEST_ID_HEADER: "attacker-id"})
    redirect = client.get("/friends")
    missing = client.get("/api/private-secret-route?token=query-secret")
    csrf = client.post("/auth", data={"password": "body-secret"})

    responses = [success, redirect, missing, csrf]
    assert [response.status_code for response in responses] == [200, 302, 404, 403]
    ids = [response.headers[REQUEST_ID_HEADER] for response in responses]
    assert all(ids)
    assert len(set(ids)) == len(ids)
    assert "attacker-id" not in ids


def test_request_id_is_available_during_view_and_matches_response(client, monkeypatch):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)

    def correlated_health():
        return jsonify({"request_id": g._bl_request_id})

    monkeypatch.setitem(app.view_functions, "health_check", correlated_health)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unhandled_error_emits_one_safe_structured_event(client, monkeypatch, capsys):
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 0)
    raw_values = {
        "email": "private-observability@example.com",
        "query": "query-secret-value",
        "body": "body-secret-value",
        "cookie": "cookie-secret-value",
        "csrf": "csrf-secret-value",
        "auth": "auth-secret-value",
        "push": "push-secret-value",
        "exception": "exception-secret-value",
    }

    def exploding_health():
        raise RuntimeError(raw_values["exception"])

    monkeypatch.setitem(app.view_functions, "health_check", exploding_health)
    response = client.open(
        f"/health?token={raw_values['query']}&email={raw_values['email']}",
        method="GET",
        json={"secret": raw_values["body"]},
        headers={
            "Cookie": f"session={raw_values['cookie']}",
            "X-CSRF-Token": raw_values["csrf"],
            "Authorization": f"Bearer {raw_values['auth']}",
            "X-Push-Token": raw_values["push"],
            REQUEST_ID_HEADER: "inbound-correlation-secret",
        },
    )
    captured = capsys.readouterr()
    events = _parse_events(captured.out)

    assert response.status_code == 500
    assert response.mimetype == "text/html"
    assert response.headers[REQUEST_ID_HEADER]
    assert len(events) == 1
    event = events[0]
    assert event == {
        "duration_ms": event["duration_ms"],
        "endpoint": "health_check",
        "environment": app.config["BASELODGE_RUNTIME_ENV"],
        "event_type": "request_error",
        "exception_class": "RuntimeError",
        "method": "GET",
        "request_id": response.headers[REQUEST_ID_HEADER],
        "route": "/health",
        "severity": "error",
        "status_code": 500,
        "timestamp": event["timestamp"],
    }
    assert event["duration_ms"] >= 0
    serialized = json.dumps(event)
    for value in raw_values.values():
        assert value not in serialized
        assert value not in captured.out
        assert value not in captured.err
    assert "inbound-correlation-secret" not in serialized


def test_slow_request_event_is_thresholded_and_correlated(client, monkeypatch, capsys):
    def slow_health():
        time.sleep(0.01)
        return jsonify({"ok": True}), 201

    monkeypatch.setitem(app.view_functions, "health_check", slow_health)

    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 60_000)
    fast_response = client.get("/health")
    assert _events(capsys) == []

    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 1)
    slow_response = client.get("/health")
    events = _events(capsys)

    assert fast_response.status_code == 201
    assert slow_response.status_code == 201
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "request_slow"
    assert event["severity"] == "warning"
    assert event["request_id"] == slow_response.headers[REQUEST_ID_HEADER]
    assert event["endpoint"] == "health_check"
    assert event["route"] == "/health"
    assert event["status_code"] == 201
    assert event["duration_ms"] >= 1
    assert "exception_class" not in event


def test_limiter_rejection_starts_with_request_local_correlation(
    rate_limit_client, monkeypatch
):
    observed = []
    original_finish = app_module.finish_response

    def recording_finish(response):
        observed.append((
            getattr(g, "_bl_request_id", None),
            getattr(g, "_bl_request_started", None),
            response.status_code,
        ))
        return original_finish(response)

    monkeypatch.setattr(app_module, "finish_response", recording_finish)
    with rate_limit_client.session_transaction() as session:
        session["_csrf_token"] = "csrf"
    responses = [
        rate_limit_client.post(
            "/auth",
            environ_overrides={"REMOTE_ADDR": "198.51.100.178"},
            data={
                "csrf_token": "csrf",
                "form_type": "login",
                "email": "limited-observability@example.com",
                "password": "wrong-password",
            },
        )
        for _ in range(6)
    ]

    assert responses[-1].status_code == 429
    request_id, started, status = observed[-1]
    assert request_id
    assert isinstance(started, float)
    assert status == 429
    assert responses[-1].headers[REQUEST_ID_HEADER] == request_id


def test_structured_sink_failure_cannot_change_error_or_slow_response(
    client, monkeypatch
):
    class FailingSink:
        def write(self, _value):
            raise RuntimeError("sink unavailable")

        def flush(self):
            raise RuntimeError("sink unavailable")

    monkeypatch.setattr(
        request_observability, "sys",
        SimpleNamespace(stdout=FailingSink()),
    )

    def exploding_health():
        raise RuntimeError("private exception")

    monkeypatch.setitem(app.view_functions, "health_check", exploding_health)
    monkeypatch.setitem(app.config, "BL_OBSERVABILITY_SLOW_MS", 0)
    error_response = client.get("/health")
    assert error_response.status_code == 500
    assert error_response.headers[REQUEST_ID_HEADER]

    monkeypatch.setitem(
        app.view_functions, "health_check",
        lambda: (jsonify({"ok": True}), 202),
    )
    slow_response = client.get("/health")
    assert slow_response.status_code == 202
    assert slow_response.get_json() == {"ok": True}
    assert slow_response.headers[REQUEST_ID_HEADER]