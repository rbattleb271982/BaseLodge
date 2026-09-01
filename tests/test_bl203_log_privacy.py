"""Focused Production privacy contracts for legacy BaseLodge diagnostics."""

import json
import logging
from types import SimpleNamespace

from flask import g

import app as app_module
from app import app
from services.log_privacy import (
    ProductionLogPrivacyFilter,
    install_production_log_privacy,
    privacy_safe_print,
)


def _payloads(caplog):
    payloads = []
    for record in caplog.records:
        message = record.getMessage()
        if message.startswith("{") and '"event_type":' in message:
            payloads.append(json.loads(message))
    return payloads


def test_auth_restore_log_drops_identity_and_request_fingerprints(caplog):
    raw = {
        "email": "bl203-auth@example.com",
        "ip": "198.51.100.203",
        "xff": "203.0.113.203, 10.0.0.1",
        "ua": "BL203SecretUserAgent/1.0",
    }
    privacy_filter = ProductionLogPrivacyFilter("production")
    app.logger.addFilter(privacy_filter)

    try:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=app.logger.name):
            with app.test_request_context(
                "/health",
                headers={
                    "User-Agent": raw["ua"],
                    "X-Forwarded-For": raw["xff"],
                },
                environ_base={"REMOTE_ADDR": raw["ip"]},
            ):
                g._bl_request_id = "server-request-bl203"
                app_module._on_user_loaded_from_cookie(
                    app,
                    SimpleNamespace(id=987654321, email=raw["email"]),
                )
    finally:
        app.logger.removeFilter(privacy_filter)

    payloads = _payloads(caplog)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["environment"] == "production"
    assert payload["event_type"] == "legacy_log"
    assert payload["request_id"] == "server-request-bl203"
    assert payload["route"] == "/health"
    assert payload["endpoint"] == "health_check"
    assert payload["method"] == "GET"
    assert payload["source"].endswith(".on_user_loaded_from_cookie")

    serialized = json.dumps(payloads)
    for value in raw.values():
        assert value not in serialized
    assert "987654321" not in serialized


def test_provider_exception_log_keeps_class_but_drops_raw_details(caplog):
    class ProviderFailure(RuntimeError):
        pass

    logger = logging.getLogger("services.push_providers")
    privacy_filter = ProductionLogPrivacyFilter("production")
    logger.addFilter(privacy_filter)
    raw_values = (
        "bl203-provider@example.com",
        "token-prefix-bl203",
        "provider-message-id-bl203",
        "provider response body bl203",
        "exception text bl203",
    )

    try:
        caplog.clear()
        with app.test_request_context("/health"):
            g._bl_request_id = "server-provider-request"
            try:
                raise ProviderFailure(raw_values[-1])
            except ProviderFailure:
                logger.exception(
                    "email=%s token=%s provider_id=%s response=%s",
                    *raw_values[:-1],
                )
    finally:
        logger.removeFilter(privacy_filter)

    payloads = _payloads(caplog)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["environment"] == "production"
    assert payload["event_type"] == "legacy_log"
    assert payload["exception_class"] == "ProviderFailure"
    assert payload["request_id"] == "server-provider-request"
    assert payload["route"] == "/health"

    serialized = json.dumps(payloads)
    for value in raw_values:
        assert value not in serialized


def test_werkzeug_access_log_drops_ip_and_raw_request_target(caplog):
    logger = logging.getLogger("werkzeug")
    privacy_filter = ProductionLogPrivacyFilter("production")
    logger.addFilter(privacy_filter)
    raw_values = (
        "198.51.100.204",
        "/invite/token-path-bl203?email=access-log-bl203@example.com",
        "WerkzeugSecretAgent/bl203",
    )

    try:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=logger.name):
            logger.info(
                '%s - - [date] "GET %s HTTP/1.1" %s %s user_agent=%s',
                raw_values[0],
                raw_values[1],
                "200",
                "123",
                raw_values[2],
            )
    finally:
        logger.removeFilter(privacy_filter)

    payloads = _payloads(caplog)
    assert len(payloads) == 1
    assert payloads[0]["environment"] == "production"
    assert payloads[0]["event_type"] == "legacy_log"
    assert payloads[0]["status_code"] == 200
    serialized = json.dumps(payloads)
    for value in raw_values:
        assert value not in serialized


def test_production_stdout_diagnostics_never_emit_supplied_values(
    caplog, capsys, monkeypatch
):
    raw_values = (
        "ideas-user-id-bl203",
        "legacy-pass-value-bl203",
        "raw-exception-bl203",
    )
    privacy_filter = ProductionLogPrivacyFilter("production")
    app.logger.addFilter(privacy_filter)
    monkeypatch.setitem(app.config, "BASELODGE_RUNTIME_ENV", "production")

    try:
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=app.logger.name):
            with app.app_context():
                privacy_safe_print(*raw_values)
    finally:
        app.logger.removeFilter(privacy_filter)

    captured = capsys.readouterr()
    payloads = _payloads(caplog)
    assert len(payloads) == 1
    assert payloads[0]["event_type"] == "legacy_stdout"
    assert payloads[0]["environment"] == "production"
    assert payloads[0]["source"].endswith(
        ".test_production_stdout_diagnostics_never_emit_supplied_values"
    )

    serialized = json.dumps(payloads)
    for value in raw_values:
        assert value not in serialized
        assert value not in captured.out
        assert value not in captured.err


def test_non_production_stdout_diagnostics_remain_available(capsys, monkeypatch):
    monkeypatch.setitem(app.config, "BASELODGE_RUNTIME_ENV", "development")
    with app.app_context():
        privacy_safe_print("development-diagnostic-bl203")
    assert "development-diagnostic-bl203" in capsys.readouterr().out


def test_base_url_resolution_does_not_print_configuration(capsys, monkeypatch):
    raw_url = "https://private-provider-detail-bl203.example.test"
    monkeypatch.setenv("BASE_URL", raw_url)
    assert app_module._resolve_base_url() == raw_url
    captured = capsys.readouterr()
    assert raw_url not in captured.out
    assert raw_url not in captured.err


def test_installer_covers_active_project_logger_names():
    project_logger_names = (
        "analytics",
        "services.app_store_client",
        "services.message_dispatch",
        "services.message_events",
        "services.play_store_client",
        "services.posthog_query",
        "services.push_providers",
        "werkzeug",
    )
    original_filters = {
        name: list(logging.getLogger(name).filters)
        for name in project_logger_names
    }
    original_app_filters = list(app.logger.filters)
    original_environment = app.config["BASELODGE_RUNTIME_ENV"]
    app.config["BASELODGE_RUNTIME_ENV"] = "production"

    try:
        installed = install_production_log_privacy(app)
        assert isinstance(installed, ProductionLogPrivacyFilter)
        assert any(
            isinstance(log_filter, ProductionLogPrivacyFilter)
            for log_filter in app.logger.filters
        )
        for name in project_logger_names:
            assert any(
                isinstance(log_filter, ProductionLogPrivacyFilter)
                for log_filter in logging.getLogger(name).filters
            )
    finally:
        app.config["BASELODGE_RUNTIME_ENV"] = original_environment
        app.logger.filters[:] = original_app_filters
        for name, filters in original_filters.items():
            logging.getLogger(name).filters[:] = filters