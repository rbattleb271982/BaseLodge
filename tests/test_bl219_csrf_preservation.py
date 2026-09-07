"""BL-219: rejected CSRF requests must not enter or mutate application code."""

import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock, patch

import pytest

from app import _CSRF_EXEMPT_ENDPOINTS, app
from models import PushDeviceToken, SkiTripParticipant, TripInviteToken, db
from tests.conftest import _TEST_CSRF, _login, _make_trip, _make_user, form_post, json_post


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bl219_users(client):
    with app.app_context():
        owner = _make_user("bl219-owner")
        guest = _make_user("bl219-guest")
        trip = _make_trip(owner)
        token = TripInviteToken(
            token="bl219-trip-invite-token",
            trip_id=trip.id,
            inviter_user_id=owner.id,
        )
        db.session.add(token)
        db.session.commit()
        return {"owner_id": owner.id, "guest_id": guest.id, "trip_id": trip.id,
                "token": token.token}


@pytest.mark.parametrize(
    ("endpoint", "path", "is_json"),
    (
        ("logout", "/logout", False),
        ("trip_invite_token_accept", "/trip-invite/bl219-trip-invite-token/accept", False),
        ("acknowledge_friend_profile_view", "/api/friends/999999/viewed", True),
        ("settings_equipment_save", "/settings/equipment/save", False),
        ("acknowledge_notifications_viewed", "/api/notifications/viewed", True),
        ("activity_heartbeat", "/api/activity/heartbeat", True),
        ("planning_posts_create", "/api/trip/999999/planning-posts", True),
        ("admin_test_push", "/admin/test-push", True),
    ),
)
@pytest.mark.parametrize("csrf", (None, "incorrect-csrf-token"))
def test_rejected_csrf_never_enters_representative_mutation_or_side_effects(
    client, bl219_users, endpoint, path, is_json, csrf
):
    """The global guard runs before auth, handlers, writes, analytics, or sends."""
    _login(client, bl219_users["guest_id"])
    entered = Mock(name=endpoint)
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    request_kwargs = {"json": {}} if is_json else {"data": {}}

    with (
        patch.dict(app.view_functions, {endpoint: entered}),
        patch.object(db.session, "add") as add,
        patch.object(db.session, "flush") as flush,
        patch.object(db.session, "commit") as commit,
        patch("app.ph_analytics.track") as analytics,
        patch("app._stage_route_messaging_events") as stage_outbox,
        patch("app._finish_route_messaging_events") as finish_outbox,
        patch("app.send_fcm_push") as fcm,
        patch("app.send_apns_push") as apns,
        patch("app.send_onesignal_push") as onesignal,
    ):
        response = client.post(path, headers=headers, **request_kwargs)

    assert response.status_code == 403
    assert "Location" not in response.headers
    entered.assert_not_called()
    add.assert_not_called()
    flush.assert_not_called()
    commit.assert_not_called()
    analytics.assert_not_called()
    stage_outbox.assert_not_called()
    finish_outbox.assert_not_called()
    fcm.assert_not_called()
    apns.assert_not_called()
    onesignal.assert_not_called()


def test_valid_trip_invite_token_response_preserves_rsvp_contract(client, bl219_users):
    _login(client, bl219_users["guest_id"])

    response = form_post(
        client,
        f"/trip-invite/{bl219_users['token']}/accept",
        {"action": "going"},
    )

    assert response.status_code == 302
    with app.app_context():
        participant = SkiTripParticipant.query.filter_by(
            trip_id=bl219_users["trip_id"], user_id=bl219_users["guest_id"]
        ).one()
        assert participant.status.value == "going"
        assert TripInviteToken.query.filter_by(
            token=bl219_users["token"]
        ).one().used_at is not None


def test_valid_native_webview_push_requests_remain_csrf_protected(client, bl219_users):
    _login(client, bl219_users["guest_id"])

    beacon = json_post(client, "/api/push/beacon", {
        "step": "bl219_test", "data": {"platform": "ios"},
    })
    registered = json_post(client, "/api/push/register-token", {
        "token": "bl219-native-device-token", "platform": "android",
    })

    assert beacon.status_code == 200
    assert registered.status_code == 200
    assert registered.get_json()["action"] == "inserted"
    with app.app_context():
        row = PushDeviceToken.query.filter_by(
            user_id=bl219_users["guest_id"], token="bl219-native-device-token"
        ).one()
        assert row.platform == "android"
        assert row.apns_environment == "n/a"


def test_csrf_403_is_stable_and_never_redirects_authenticated_clients(
    client, bl219_users
):
    _login(client, bl219_users["guest_id"])

    api = client.post("/api/push/beacon", json={"csrf_token": _TEST_CSRF})
    html = client.post("/logout", data={"csrf_token": "incorrect"})

    assert api.status_code == 403
    assert api.mimetype == "application/json"
    assert api.get_json() == {
        "error": "csrf_failed", "message": "CSRF token missing or invalid."
    }
    assert "Location" not in api.headers
    assert html.status_code == 403
    assert html.mimetype == "text/html"
    assert b"CSRF token missing or invalid." in html.data
    assert "Location" not in html.headers


@pytest.mark.parametrize(
    "path",
    ("/api/push/beacon", "/api/push/register-token", "/api/notifications/viewed"),
)
def test_unauthenticated_mutations_do_not_accept_bearer_or_native_bypass(client, path):
    response = client.post(
        path,
        json={"token": "not-a-session-token", "step": "native"},
        headers={"Authorization": "Bearer not-an-authenticated-session"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_failed"
    assert "Location" not in response.headers


def test_bl219_has_no_csrf_exemptions():
    assert _CSRF_EXEMPT_ENDPOINTS == set()


def test_browser_and_native_client_use_the_single_synchronizer_token_contract():
    head = (ROOT / "templates/components/analytics_head.html").read_text()
    native = (ROOT / "static/js/bl-native.js").read_text()
    bl218_calls = {
        "templates/friends.html": "/api/invite/token",
        "templates/invite.html": "/api/invite/token",
        "templates/friend_profile.html": "acknowledge_friend_profile_view",
        "templates/notifications.html": "/api/notifications/viewed",
        "templates/components/analytics_head.html": "/api/activity/heartbeat",
    }

    assert 'meta[name="csrf-token"]' in head
    assert "'X-CSRF-Token'" in head
    assert "(isRequest && url.credentials) || 'same-origin'" in head
    assert "new Headers(isRequest ? url.headers : undefined)" in head
    assert "request.json" not in (ROOT / "app.py").read_text().split(
        "def validate_csrf_request()", 1
    )[1].split("def handle_csrf_validation_error", 1)[0]
    assert "Bearer " not in native
    assert "Authorization" not in native
    assert "csrf_exempt" not in native
    for filename, call in bl218_calls.items():
        source = (ROOT / filename).read_text()
        assert "window.blFetch" in source
        assert call in source
    assert "window.blFetch('/api/push/beacon'" in native
    assert "window.blFetch('/api/push/register-token'" in native


def test_fetch_wrapper_preserves_request_and_init_cookie_contracts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for executable fetch-wrapper coverage")

    script = r"""
const fs = require('fs');
const source = fs.readFileSync(
  'templates/components/analytics_head.html', 'utf8'
);
const match = source.match(/<script>([\s\S]*?)<\/script>/);
if (!match) throw new Error('CSRF wrapper script not found');

global.document = {
  querySelector: () => ({ content: 'runtime-csrf-token' })
};
global.window = {};
const calls = [];
window.fetch = (input, init) => {
  calls.push({ input, init });
  return Promise.resolve({ ok: true });
};
eval(match[1]);

(async () => {
  const request = new Request('https://app.baselodgeapp.com/api/test', {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      'X-Request-Header': 'preserved'
    }
  });
  await window.blFetch(request);
  const requestCall = calls.shift();
  if (requestCall.init.credentials !== 'include') {
    throw new Error('Request credentials were not preserved');
  }
  if (requestCall.init.headers.get('X-Request-Header') !== 'preserved') {
    throw new Error('Request headers were not preserved');
  }
  if (requestCall.init.headers.get('X-CSRF-Token') !== 'runtime-csrf-token') {
    throw new Error('CSRF header was not injected for Request input');
  }

  await window.blFetch('https://app.baselodgeapp.com/api/test', {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-Init-Header': 'preserved' },
    body: '{}'
  });
  const initCall = calls.shift();
  if (initCall.init.credentials !== 'include') {
    throw new Error('Explicit init credentials were not preserved');
  }
  if (initCall.init.headers.get('X-Init-Header') !== 'preserved') {
    throw new Error('Init headers were not preserved');
  }
  if (initCall.init.headers.get('X-CSRF-Token') !== 'runtime-csrf-token') {
    throw new Error('CSRF header was not injected for URL input');
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    result = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
