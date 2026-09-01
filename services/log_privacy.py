"""Production-only privacy guard for legacy BaseLodge diagnostics."""

from __future__ import annotations

import builtins
import inspect
import json
import logging
import os
import re

from flask import current_app, g, has_app_context, has_request_context, request


_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9_./<>:-]+")
_PROJECT_LOGGER_NAMES = (
    "analytics",
    "services.app_store_client",
    "services.message_dispatch",
    "services.message_events",
    "services.play_store_client",
    "services.posthog_query",
    "services.push_providers",
    "werkzeug",
)


def _safe_identifier(value, fallback):
    cleaned = _SAFE_IDENTIFIER.sub("_", str(value or ""))[:160].strip("_")
    return cleaned or fallback


def _exception_class(record):
    if record.exc_info and record.exc_info[1] is not None:
        return type(record.exc_info[1]).__name__

    if isinstance(record.args, dict):
        values = record.args.values()
    elif isinstance(record.args, (tuple, list)):
        values = record.args
    else:
        values = (record.args,)
    if not values:
        values = (values,)
    for value in values:
        if isinstance(value, BaseException):
            return type(value).__name__
    return None


def _status_code(record):
    explicit = getattr(record, "bl_status_code", None)
    if isinstance(explicit, int) and 100 <= explicit <= 599:
        return explicit

    if record.name == "werkzeug" and isinstance(record.args, tuple):
        if len(record.args) >= 3:
            candidate = str(record.args[2])
            if candidate.isdigit() and 100 <= int(candidate) <= 599:
                return int(candidate)
    return None


class ProductionLogPrivacyFilter(logging.Filter):
    """Replace legacy log content with explicit, privacy-safe metadata."""

    def __init__(self, environment="production"):
        super().__init__()
        self.environment = _safe_identifier(environment, "production")

    def filter(self, record):
        if getattr(record, "_bl_privacy_sanitized", False):
            return True

        payload = {
            "environment": self.environment,
            "event_type": _safe_identifier(
                getattr(record, "bl_event_type", None), "legacy_log"
            ),
            "severity": _safe_identifier(record.levelname.lower(), "unknown"),
            "source": "{}.{}".format(
                _safe_identifier(
                    getattr(record, "bl_source_module", None) or record.module,
                    "unknown",
                ),
                _safe_identifier(
                    getattr(record, "bl_source_function", None) or record.funcName,
                    "unknown",
                ),
            ),
            "source_line": int(
                getattr(record, "bl_source_line", None) or record.lineno or 0
            ),
        }

        exception_class = _exception_class(record)
        if exception_class:
            payload["exception_class"] = _safe_identifier(
                exception_class, "Exception"
            )
        status_code = _status_code(record)
        if status_code is not None:
            payload["status_code"] = status_code

        if has_request_context():
            rule = getattr(request, "url_rule", None)
            payload.update({
                "endpoint": _safe_identifier(
                    request.endpoint or "unmatched", "unmatched"
                ),
                "method": _safe_identifier(request.method, "UNKNOWN"),
                "request_id": _safe_identifier(
                    getattr(g, "_bl_request_id", None), "unavailable"
                ),
                "route": _safe_identifier(
                    getattr(rule, "rule", None) or "unmatched", "unmatched"
                ),
            })

        record.msg = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record._bl_privacy_sanitized = True
        return True


def install_production_log_privacy(app):
    """Install the privacy filter on every BaseLodge project logger."""
    if app.config.get("BASELODGE_RUNTIME_ENV") != "production":
        return None

    existing = next(
        (
            log_filter
            for log_filter in app.logger.filters
            if isinstance(log_filter, ProductionLogPrivacyFilter)
        ),
        None,
    )
    privacy_filter = existing or ProductionLogPrivacyFilter("production")

    logger_names = {app.logger.name, *_PROJECT_LOGGER_NAMES}
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        if not any(
            isinstance(log_filter, ProductionLogPrivacyFilter)
            for log_filter in logger.filters
        ):
            logger.addFilter(privacy_filter)
    return privacy_filter


def _emit_production_stdout(caller):
    extra = {
        "bl_event_type": "legacy_stdout",
        "bl_source_module": caller.f_globals.get("__name__", "unknown"),
        "bl_source_function": caller.f_code.co_name,
        "bl_source_line": caller.f_lineno,
    }
    logger = current_app.logger if has_app_context() else logging.getLogger("app")
    logger.info("Production stdout diagnostic", extra=extra)


def production_safe_print(*_values, **_kwargs):
    """Emit only call-site metadata, never the supplied diagnostic values."""
    _emit_production_stdout(inspect.currentframe().f_back)


def privacy_safe_print(*values, **kwargs):
    """Preserve normal diagnostics outside Production; sanitize them in Production."""
    if has_app_context():
        environment = current_app.config.get("BASELODGE_RUNTIME_ENV")
    else:
        environment = os.environ.get("BASELODGE_RUNTIME_ENV")

    if environment != "production":
        builtins.print(*values, **kwargs)
        return

    _emit_production_stdout(inspect.currentframe().f_back)