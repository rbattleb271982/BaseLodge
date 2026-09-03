"""Readiness contract for the first-request startup diagnostics."""

import threading

import app as app_module
from app import app


def test_initial_request_does_not_wait_for_startup_diagnostics(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocked_diagnostics():
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(app_module, "log_startup_diagnostics", blocked_diagnostics)
    app.__dict__.pop("_diagnostics_started", None)

    try:
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200
        assert started.wait(timeout=1)
    finally:
        release.set()