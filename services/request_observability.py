"""Safe, request-local correlation and low-noise request events."""

import json
import secrets
import sys
import time
from datetime import datetime, timezone

from flask import current_app, g, request


DEFAULT_SLOW_REQUEST_MS = 1000
REQUEST_ID_HEADER = "X-Request-ID"


def _request_id():
    return getattr(g, "_bl_request_id", None)


def ensure_request_context():
    """Create request-local state if an early Flask failure skipped the hook."""
    if not _request_id():
        g._bl_request_id = secrets.token_urlsafe(18)
    if not hasattr(g, "_bl_request_started"):
        g._bl_request_started = time.monotonic()
    return g._bl_request_id


def begin_request():
    """Start a request using only request-local state."""
    g._bl_request_id = secrets.token_urlsafe(18)
    g._bl_request_started = time.monotonic()
    g._bl_observability_error_emitted = False


def _duration_ms():
    started = getattr(g, "_bl_request_started", None)
    if started is None:
        return 0
    return max(0, int((time.monotonic() - started) * 1000))


def _route_metadata():
    rule = getattr(request, "url_rule", None)
    return {
        "endpoint": request.endpoint or "unmatched",
        "route": getattr(rule, "rule", None) or "unmatched",
    }


def _environment():
    return current_app.config.get("BASELODGE_RUNTIME_ENV") or (
        "production" if current_app.config.get("ENV") == "production" else "development"
    )


def _emit(event_type, severity, response_status, exception_class=None):
    try:
        metadata = _route_metadata()
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "severity": severity,
            "event_type": event_type,
            "request_id": ensure_request_context(),
            "method": request.method,
            "endpoint": metadata["endpoint"],
            "route": metadata["route"],
            "status_code": int(response_status),
            "duration_ms": _duration_ms(),
            "environment": _environment(),
        }
        if exception_class is not None:
            event["exception_class"] = exception_class
        # Keep this a single allowlisted JSON line for Replit stdout capture.
        sys.stdout.write(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
        )
        sys.stdout.flush()
    except Exception:
        # Observability must never change request or provider failure semantics.
        pass


def emit_unhandled_error(error, status_code=500):
    """Emit at most one safe structured event for the current request."""
    if getattr(g, "_bl_observability_error_emitted", False):
        return
    g._bl_observability_error_emitted = True
    _emit("request_error", "error", status_code, type(error).__name__)


def finish_response(response):
    """Attach correlation and emit only low-noise slow-request events."""
    request_id = ensure_request_context()
    response.headers[REQUEST_ID_HEADER] = request_id
    if not getattr(g, "_bl_observability_error_emitted", False):
        threshold = current_app.config.get(
            "BL_OBSERVABILITY_SLOW_MS", DEFAULT_SLOW_REQUEST_MS
        )
        try:
            threshold = max(0, int(threshold))
        except (TypeError, ValueError):
            threshold = DEFAULT_SLOW_REQUEST_MS
        duration = _duration_ms()
        if duration >= threshold:
            _emit("request_slow", "warning", response.status_code)
    return response