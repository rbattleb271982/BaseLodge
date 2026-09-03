"""Readiness contract excludes automatic startup diagnostics."""

import app as app_module
from app import app


def test_startup_diagnostics_are_not_registered_or_request_triggered(client):
    before_request_names = {
        function.__name__ for function in app.before_request_funcs.get(None, ())
    }

    assert "run_startup_diagnostics_once" not in before_request_names
    assert not hasattr(app_module, "log_startup_diagnostics")
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200