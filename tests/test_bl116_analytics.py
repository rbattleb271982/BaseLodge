import json
import runpy
from urllib.parse import quote

import analytics


class FakePostHog:
    def __init__(self):
        self.captures = []
        self.sets = []
        self.set_once_calls = []
        self.aliases = []
        self.flush_calls = 0
        self.shutdown_calls = 0

    def capture(self, event, *, distinct_id, properties):
        self.captures.append((event, distinct_id, properties))

    def set(self, *, distinct_id, properties):
        self.sets.append((distinct_id, properties))

    def set_once(self, *, distinct_id, properties):
        self.set_once_calls.append((distinct_id, properties))

    def alias(self, previous_id, distinct_id):
        self.aliases.append((previous_id, distinct_id))

    def flush(self):
        self.flush_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1


def _install_client(monkeypatch):
    client = FakePostHog()
    monkeypatch.setattr(analytics, "POSTHOG_KEY", "test-key")
    monkeypatch.setattr(analytics, "_client", client)
    return client


def test_anonymous_events_use_fresh_non_linking_ids(monkeypatch):
    client = _install_client(monkeypatch)

    analytics.track(None, "first")
    analytics.track(None, "second")

    first_id = client.captures[0][1]
    second_id = client.captures[1][1]
    assert first_id.startswith("anonymous_event:")
    assert second_id.startswith("anonymous_event:")
    assert first_id != second_id
    assert "anonymous" not in {first_id, second_id}


def test_valid_explicit_browser_anonymous_id_is_honored(monkeypatch):
    client = _install_client(monkeypatch)

    analytics.track(None, "open_to_ski", anonymous_id="browser-anon_123")

    assert client.captures[0][1] == "browser-anon_123"


def test_get_anon_id_decodes_and_rejects_malformed_values(monkeypatch):
    monkeypatch.setattr(analytics, "POSTHOG_KEY", "test-key")
    cookie_name = "ph_test-key_posthog"
    valid = quote(json.dumps({"distinct_id": "browser-anon:abc"}))
    assert analytics.get_anon_id({cookie_name: valid}) == "browser-anon:abc"

    invalid_values = [
        None,
        123,
        "",
        "anonymous",
        "anonymous_event:shared",
        "12345",
        "contains whitespace",
        "x" * 201,
    ]
    for value in invalid_values:
        cookie = quote(json.dumps({"distinct_id": value}))
        assert analytics.get_anon_id({cookie_name: cookie}) is None
    assert analytics.get_anon_id({cookie_name: "%not-json"}) is None


def test_track_and_identify_do_not_flush_synchronously(monkeypatch):
    client = _install_client(monkeypatch)

    analytics.track(12, "login_completed")
    analytics.identify(
        12,
        properties={"is_internal": True},
        set_once_props={"created_source": "signup"},
    )

    assert client.flush_calls == 0
    assert client.sets == [("12", {"is_internal": True})]
    assert client.set_once_calls == [("12", {"created_source": "signup"})]


def test_delivery_boundary_removes_prohibited_properties(monkeypatch):
    client = _install_client(monkeypatch)

    analytics.track(
        12,
        "safe_event",
        {
            "method": "email",
            "email": "person@example.com",
            "nested": {
                "invite_token": "private",
                "delivery": "download",
            },
            "recipients": ["person@example.com", "category"],
            "token_type": "trip_invite",
        },
        set_props={"is_internal": False, "full_name": "Private Person"},
    )
    analytics.identify(
        12,
        properties={"is_internal": True, "email": "person@example.com"},
    )

    assert client.captures == [(
        "safe_event",
        "12",
        {
            "method": "email",
            "nested": {"delivery": "download"},
            "recipients": ["category"],
            "token_type": "trip_invite",
            "$set": {"is_internal": False},
        },
    )]
    assert client.sets == [("12", {"is_internal": True})]


def test_alias_accepts_only_valid_browser_anonymous_ids(monkeypatch):
    client = _install_client(monkeypatch)

    analytics.alias("browser-anon_123", 12)
    analytics.alias("anonymous", 12)
    analytics.alias("person@example.com", 12)
    analytics.alias("12345", 12)

    assert client.aliases == [("browser-anon_123", "12")]


def test_delivery_failures_never_escape_product_calls(monkeypatch):
    class BrokenClient:
        def capture(self, *_args, **_kwargs):
            raise RuntimeError("capture unavailable")

        def set(self, *_args, **_kwargs):
            raise RuntimeError("identify unavailable")

        def set_once(self, *_args, **_kwargs):
            raise RuntimeError("identify unavailable")

        def alias(self, *_args, **_kwargs):
            raise RuntimeError("alias unavailable")

    monkeypatch.setattr(analytics, "POSTHOG_KEY", "test-key")
    monkeypatch.setattr(analytics, "_client", BrokenClient())

    analytics.track(12, "login_completed", {"method": "email"})
    analytics.identify(
        12,
        properties={"is_internal": False},
        set_once_props={"created_source": "signup"},
    )
    analytics.alias("browser-anon_123", 12)


def test_disabled_analytics_is_a_noop(monkeypatch):
    monkeypatch.setattr(analytics, "POSTHOG_KEY", "")
    monkeypatch.setattr(analytics, "_client", None)

    analytics.track(12, "login_completed")
    analytics.identify(12, properties={"is_internal": False})
    analytics.alias("browser-anon_123", 12)


def test_shutdown_uses_guarded_client_shutdown(monkeypatch):
    client = _install_client(monkeypatch)
    analytics._shutdown_client()
    assert client.shutdown_calls == 1
    analytics._shutdown_client()
    assert client.shutdown_calls == 1

    class BrokenClient:
        def shutdown(self):
            raise RuntimeError("delivery unavailable")

    monkeypatch.setattr(analytics, "_client", BrokenClient())
    analytics._shutdown_client()


def test_shutdown_falls_back_to_flush_when_shutdown_is_unavailable(monkeypatch):
    class FlushOnlyClient:
        def __init__(self):
            self.flush_calls = 0

        def flush(self):
            self.flush_calls += 1

    client = FlushOnlyClient()
    monkeypatch.setattr(analytics, "_client", client)
    analytics._shutdown_client()
    assert client.flush_calls == 1


def test_post_fork_reset_discards_inherited_client(monkeypatch):
    _install_client(monkeypatch)
    monkeypatch.setattr(analytics, "_init_logged", True)

    analytics._reset_client_after_fork()

    assert analytics._client is None
    assert analytics._init_logged is False


def test_gunicorn_hooks_reset_after_fork_and_shutdown_on_worker_exit(
    monkeypatch
):
    hooks = runpy.run_path("gunicorn.conf.py")
    inherited = _install_client(monkeypatch)

    hooks["post_fork"](None, None)
    assert analytics._client is None
    assert inherited.shutdown_calls == 0

    worker_client = _install_client(monkeypatch)
    hooks["worker_exit"](None, None)
    assert worker_client.shutdown_calls == 1
