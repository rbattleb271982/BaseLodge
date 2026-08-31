"""Security regressions for logout and admin state-changing POST routes."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import app
from models import db, PushDeviceToken
from tests.conftest import _TEST_CSRF, _login, _make_user, form_post, json_post


ADMIN_ROUTES = (
    "/admin/test-push",
    "/admin/test-push-all",
    "/admin/test-onesignal-push",
    "/admin/push-token-dedup",
    "/admin/test-message-event",
)


@pytest.fixture
def route_setup(client):
    with app.app_context():
        admin = _make_user("route-admin", email="route-admin@bl.test")
        member = _make_user("route-member")
        db.session.commit()
        result = {
            "admin_id": admin.id,
            "admin_email": admin.email,
            "member_id": member.id,
        }
    return result


def _token(user_id, token, platform="ios", *, active=True,
           environment="production"):
    row = PushDeviceToken(
        user_id=user_id,
        token=token,
        platform=platform,
        active=active,
        apns_environment=environment,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _admin_post(client, setup, route, *, csrf=_TEST_CSRF):
    _login(client, setup["admin_id"])
    with patch.dict(
        os.environ, {"ALLOWED_ADMIN_EMAILS": setup["admin_email"]}
    ):
        return client.post(
            route,
            headers={"X-CSRF-Token": csrf} if csrf is not None else {},
        )


def _provider_patches():
    return (
        patch("app.send_apns_push"),
        patch("app.send_fcm_push"),
        patch("app.send_onesignal_push"),
        patch("app.create_message_event"),
    )


def test_logout_valid_post_deactivates_all_tokens_and_only_current_session(
        client, route_setup):
    second_session = app.test_client()
    with app.app_context():
        ios = _token(route_setup["member_id"], "logout-ios")
        android = _token(
            route_setup["member_id"],
            "logout-android",
            platform="android",
            environment="n/a",
        )
        db.session.commit()
        token_ids = (ios.id, android.id)

    _login(client, route_setup["member_id"])
    _login(second_session, route_setup["member_id"])
    with patch("app.ph_analytics.track") as analytics:
        response = form_post(client, "/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth")
    analytics.assert_called_once_with(route_setup["member_id"], "logout")
    with client.session_transaction() as session:
        assert "_user_id" not in session
        assert session["ph_reset"] is True
    with second_session.session_transaction() as session:
        assert session["_user_id"] == str(route_setup["member_id"])
    with app.app_context():
        assert all(
            db.session.get(PushDeviceToken, token_id).active is False
            for token_id in token_ids
        )


def test_logout_valid_post_preserves_invite_return_and_transient_cleanup(
        client, route_setup):
    _login(client, route_setup["member_id"])
    with client.session_transaction() as session:
        session["invite_token"] = "invite-token"
        session["post_login_redirect"] = "/invite/invite-token"
        session["post_onboarding_redirect"] = "/invite/invite-token"
        session["trip_invite_token"] = "trip-token"
        session["_auth_session_logged"] = True
        session["_last_active_stamp"] = 123.0
        session["_bl_auth_method"] = "email"

    with patch("app.ph_analytics.track"):
        response = form_post(
            client,
            "/logout?return_to=/invite/invite-token",
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/invite/invite-token")
    with client.session_transaction() as session:
        for key in (
            "invite_token",
            "post_login_redirect",
            "post_onboarding_redirect",
            "trip_invite_token",
            "_auth_session_logged",
            "_last_active_stamp",
            "_bl_auth_method",
        ):
            assert key not in session


def test_logout_get_is_405_without_token_session_or_analytics_side_effects(
        client, route_setup):
    with app.app_context():
        token = _token(route_setup["member_id"], "logout-get-token")
        db.session.commit()
        token_id = token.id
    _login(client, route_setup["member_id"])
    with client.session_transaction() as session:
        csrf_before = session["_csrf_token"]

    with (
        patch("app.ph_analytics.track") as analytics,
        patch.object(db.session, "commit") as commit,
    ):
        response = client.get("/logout")

    assert response.status_code == 405
    analytics.assert_not_called()
    commit.assert_not_called()
    with client.session_transaction() as session:
        assert session["_user_id"] == str(route_setup["member_id"])
        assert session["_csrf_token"] == csrf_before
        assert "ph_reset" not in session
    with app.app_context():
        assert db.session.get(PushDeviceToken, token_id).active is True


@pytest.mark.parametrize("csrf", [None, "invalid-csrf"])
def test_logout_bad_csrf_has_no_side_effects(client, route_setup, csrf):
    with app.app_context():
        token = _token(route_setup["member_id"], f"logout-bad-{csrf}")
        db.session.commit()
        token_id = token.id
    _login(client, route_setup["member_id"])
    with client.session_transaction() as session:
        csrf_before = session["_csrf_token"]

    with (
        patch("app.ph_analytics.track") as analytics,
        patch.object(db.session, "commit") as commit,
    ):
        response = client.post(
            "/logout",
            data={"csrf_token": csrf} if csrf is not None else {},
        )

    assert response.status_code == 403
    analytics.assert_not_called()
    commit.assert_not_called()
    with client.session_transaction() as session:
        assert session["_user_id"] == str(route_setup["member_id"])
        assert session["_csrf_token"] == csrf_before
        assert "ph_reset" not in session
    with app.app_context():
        assert db.session.get(PushDeviceToken, token_id).active is True


def test_logout_unauthenticated_post_remains_blocked(client):
    response = client.post(
        "/logout",
        data={"csrf_token": _TEST_CSRF},
    )
    assert response.status_code in (302, 401)


def test_logout_templates_use_protected_post_forms_and_native_ordering():
    profile = Path("templates/profile.html").read_text()
    invite = Path("templates/invite_landing.html").read_text()
    trip_invite = Path("templates/trip_invite_token_landing.html").read_text()

    for source in (profile, invite, trip_invite):
        assert 'method="POST"' in source
        assert "url_for('logout" in source
        assert 'name="csrf_token"' in source
    assert 'href="{{ url_for(\'logout\')' not in profile
    assert profile.index("window.blOSLogout().then") < profile.index(
        "_form.submit();"
    )
    assert "window.location.href = _href" not in profile


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_mutation_gets_are_405_without_side_effects(
        client, route_setup, route):
    _login(client, route_setup["admin_id"])
    apns_patch, fcm_patch, onesignal_patch, event_patch = _provider_patches()
    with (
        patch.dict(
            os.environ, {"ALLOWED_ADMIN_EMAILS": route_setup["admin_email"]}
        ),
        apns_patch as apns,
        fcm_patch as fcm,
        onesignal_patch as onesignal,
        event_patch as event,
        patch.object(db.session, "commit") as commit,
    ):
        response = client.get(route)

    assert response.status_code == 405
    apns.assert_not_called()
    fcm.assert_not_called()
    onesignal.assert_not_called()
    event.assert_not_called()
    commit.assert_not_called()


def test_admin_message_event_page_uses_protected_post_controls(
        client, route_setup):
    _login(client, route_setup["admin_id"])
    with patch.dict(
        os.environ, {"ALLOWED_ADMIN_EMAILS": route_setup["admin_email"]}
    ):
        response = client.get("/admin/message-events")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert html.count('action="/admin/test-message-event"') == 2
    assert html.count('name="csrf_token"') >= 2
    assert 'href="/admin/test-message-event"' not in html


@pytest.mark.parametrize("route", ADMIN_ROUTES)
@pytest.mark.parametrize("csrf", [None, "invalid-csrf"])
def test_admin_mutation_posts_reject_bad_csrf_before_side_effects(
        client, route_setup, route, csrf):
    apns_patch, fcm_patch, onesignal_patch, event_patch = _provider_patches()
    with (
        apns_patch as apns,
        fcm_patch as fcm,
        onesignal_patch as onesignal,
        event_patch as event,
        patch.object(db.session, "commit") as commit,
    ):
        response = _admin_post(
            client, route_setup, route, csrf=csrf
        )

    assert response.status_code == 403
    apns.assert_not_called()
    fcm.assert_not_called()
    onesignal.assert_not_called()
    event.assert_not_called()
    commit.assert_not_called()


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_mutation_posts_block_non_admin_without_side_effects(
        client, route_setup, route):
    _login(client, route_setup["member_id"])
    apns_patch, fcm_patch, onesignal_patch, event_patch = _provider_patches()
    with (
        patch.dict(
            os.environ, {"ALLOWED_ADMIN_EMAILS": route_setup["admin_email"]}
        ),
        apns_patch as apns,
        fcm_patch as fcm,
        onesignal_patch as onesignal,
        event_patch as event,
    ):
        response = json_post(client, route)

    assert response.status_code == 403
    apns.assert_not_called()
    fcm.assert_not_called()
    onesignal.assert_not_called()
    event.assert_not_called()


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_mutation_posts_block_unauthenticated(client, route):
    response = client.post(
        route,
        headers={"X-CSRF-Token": _TEST_CSRF},
    )
    assert response.status_code in (302, 401)


def test_admin_test_push_valid_post_preserves_fcm_and_audit(
        client, route_setup):
    with app.app_context():
        _token(
            route_setup["admin_id"],
            "test-push-android",
            platform="android",
            environment="n/a",
        )
        db.session.commit()

    with (
        patch("app._get_qa_push_override_user", return_value=None),
        patch(
            "app.send_fcm_push",
            return_value={
                "success": True,
                "message_id": "fcm-id",
                "error": None,
            },
        ) as fcm,
        patch("app.create_message_event") as event,
    ):
        response = _admin_post(
            client,
            route_setup,
            f"/admin/test-push?user_id={route_setup['admin_id']}",
        )

    assert response.status_code == 200
    assert response.get_json()["provider"] == "fcm"
    fcm.assert_called_once()
    event.assert_called_once()


def test_admin_test_push_all_valid_post_preserves_provider_routing(
        client, route_setup):
    with app.app_context():
        _token(
            route_setup["admin_id"],
            "push-all-ios",
            environment="production",
        )
        _token(
            route_setup["admin_id"],
            "push-all-android",
            platform="android",
            environment="n/a",
        )
        db.session.commit()

    with (
        patch("app._get_qa_push_override_user", return_value=None),
        patch(
            "app.send_apns_push",
            return_value={
                "success": True,
                "final_success": True,
                "retry_attempted": False,
                "first_attempt_error": None,
            },
        ) as apns,
        patch(
            "app.send_fcm_push",
            return_value={
                "success": True,
                "message_id": "fcm-id",
                "error": None,
            },
        ) as fcm,
        patch("app.create_message_event") as event,
    ):
        response = _admin_post(
            client, route_setup, "/admin/test-push-all"
        )

    assert response.status_code == 200
    assert response.get_json()["total_success"] == 2
    apns.assert_called_once()
    fcm.assert_called_once()
    assert event.call_count == 2


def test_admin_onesignal_valid_post_preserves_provider_and_audit(
        client, route_setup):
    with (
        patch("app._get_qa_push_override_user", return_value=None),
        patch(
            "app.send_onesignal_push",
            return_value={
                "success": True,
                "skipped": False,
                "provider_message_id": "onesignal-id",
            },
        ) as onesignal,
        patch("app.create_message_event") as event,
    ):
        response = _admin_post(
            client, route_setup, "/admin/test-onesignal-push"
        )

    assert response.status_code == 200
    onesignal.assert_called_once()
    event.assert_called_once()


def test_admin_token_dedup_valid_post_preserves_newest_active_token(
        client, route_setup):
    with app.app_context():
        first = _token(route_setup["member_id"], "dedup-first")
        second = _token(route_setup["member_id"], "dedup-second")
        db.session.commit()
        first_id, second_id = first.id, second.id

    response = _admin_post(
        client, route_setup, "/admin/push-token-dedup"
    )

    assert response.status_code == 200
    assert response.get_json()["tokens_deactivated"] == 1
    with app.app_context():
        states = {
            token_id: db.session.get(PushDeviceToken, token_id).active
            for token_id in (first_id, second_id)
        }
        assert sorted(states.values()) == [False, True]


def test_admin_message_event_valid_post_preserves_three_event_creations(
        client, route_setup):
    with (
        patch("app.create_message_event") as event,
        patch("app.is_duplicate_event", return_value=True),
    ):
        response = _admin_post(
            client, route_setup, "/admin/test-message-event"
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin/message-events")
    assert event.call_count == 3