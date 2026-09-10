import json
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


def test_shutdown_uses_guarded_client_shutdown(monkeypatch):
    client = _install_client(monkeypatch)
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
