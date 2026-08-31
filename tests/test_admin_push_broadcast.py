"""Focused safety regressions for the direct APNs/FCM admin broadcast."""

import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import app
from models import db, PushDeviceToken
from services.messaging_constants import DeliveryStatus
from tests.conftest import _TEST_CSRF, _login, _make_user, json_post


ROUTE = "/admin/test-push-broadcast"


@pytest.fixture
def broadcast_setup(client):
    with app.app_context():
        admin = _make_user("broadcast-admin", email="broadcast-admin@bl.test")
        opted_in = _make_user("broadcast-opted-in")
        opted_out = _make_user("broadcast-opted-out")
        opted_out.push_notifications_enabled = False
        no_token = _make_user("broadcast-no-token")
        db.session.commit()
        result = {
            "admin_id": admin.id,
            "admin_email": admin.email,
            "opted_in_id": opted_in.id,
            "opted_out_id": opted_out.id,
            "no_token_id": no_token.id,
        }
    return result


def _token(user_id, token, platform="ios", *, active=True,
           environment="production", updated_at=None):
    row = PushDeviceToken(
        user_id=user_id,
        token=token,
        platform=platform,
        active=active,
        apns_environment=environment,
        updated_at=updated_at or datetime.utcnow(),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _post_as_admin(client, setup, data=None):
    _login(client, setup["admin_id"])
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": setup["admin_email"]}):
        return json_post(client, ROUTE, data or {})


def _successful_apns():
    return {
        "success": True,
        "final_success": True,
        "retry_attempted": False,
        "first_attempt_error": None,
    }


def _successful_fcm():
    return {"success": True, "message_id": "fcm-message-id", "error": None}


def test_successful_development_broadcast_routes_opted_in_apns_and_fcm_once(
        client, broadcast_setup):
    with app.app_context():
        _token(
            broadcast_setup["opted_in_id"],
            "ios-production-token",
            environment="production",
        )
        _token(
            broadcast_setup["admin_id"],
            "android-token",
            platform="android",
            environment="n/a",
        )
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push", return_value=_successful_apns()) as apns,
        patch("app.send_fcm_push", return_value=_successful_fcm()) as fcm,
        patch("app.create_message_event") as audit,
    ):
        response = _post_as_admin(
            client,
            broadcast_setup,
            {"title": "Safety title", "body": "Safety body"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_active_tokens"] == 2
    assert payload["unique_users_targeted"] == 2
    assert payload["ios_attempted"] == 1
    assert payload["android_attempted"] == 1
    assert payload["total_success"] == 2
    apns.assert_called_once_with(
        "ios-production-token",
        title="Safety title",
        body="Safety body",
        prefer_sandbox=False,
    )
    fcm.assert_called_once_with(
        "android-token",
        title="Safety title",
        body="Safety body",
        data={"source": "admin_test_push_broadcast"},
    )
    assert audit.call_count == 2


@pytest.mark.parametrize("environment, expected", [
    ("sandbox", True),
    ("production", False),
    ("unknown", None),
])
def test_apns_environment_is_forwarded(client, broadcast_setup,
                                       environment, expected):
    with app.app_context():
        _token(
            broadcast_setup["opted_in_id"],
            f"ios-{environment}-token",
            environment=environment,
        )
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push", return_value=_successful_apns()) as apns,
        patch("app.create_message_event"),
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    assert apns.call_args.kwargs["prefer_sandbox"] is expected


def test_opted_out_inactive_orphaned_and_no_token_users_are_excluded(
        client, broadcast_setup):
    with app.app_context():
        _token(broadcast_setup["opted_out_id"], "opted-out-token")
        _token(
            broadcast_setup["opted_in_id"],
            "inactive-token",
            active=False,
        )
        # SQLite test databases do not enforce this FK, allowing a legacy
        # orphan to verify the route's inner join fails closed.
        orphan = PushDeviceToken(
            user_id=999999,
            token="orphan-token",
            platform="ios",
            active=True,
            apns_environment="production",
        )
        db.session.add(orphan)
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push") as apns,
        patch("app.send_fcm_push") as fcm,
        patch("app.create_message_event") as audit,
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    assert response.get_json()["reason"] == "no_active_tokens"
    apns.assert_not_called()
    fcm.assert_not_called()
    audit.assert_not_called()


def test_duplicate_user_platform_rows_keep_only_newest(client, broadcast_setup):
    now = datetime.utcnow()
    with app.app_context():
        older = _token(
            broadcast_setup["opted_in_id"],
            "older-ios-token",
            updated_at=now - timedelta(hours=1),
        )
        newer = _token(
            broadcast_setup["opted_in_id"],
            "newer-ios-token",
            updated_at=now,
        )
        older_id, newer_id = older.id, newer.id
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push", return_value=_successful_apns()) as apns,
        patch("app.create_message_event") as audit,
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    apns.assert_called_once()
    assert apns.call_args.args[0] == "newer-ios-token"
    assert response.get_json()["results"][0]["token_id"] == newer_id
    assert response.get_json()["results"][0]["token_id"] != older_id
    assert audit.call_count == 1


def test_repeated_physical_platform_token_sends_once(client, broadcast_setup):
    now = datetime.utcnow()
    with app.app_context():
        other_user = _make_user("broadcast-other-owner")
        db.session.flush()
        _token(
            broadcast_setup["opted_in_id"],
            "shared-physical-token",
            updated_at=now - timedelta(hours=1),
        )
        newest = _token(
            other_user.id,
            "shared-physical-token",
            updated_at=now,
        )
        newest_id = newest.id
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push", return_value=_successful_apns()) as apns,
        patch("app.create_message_event"),
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    apns.assert_called_once()
    assert response.get_json()["total_active_tokens"] == 1
    assert response.get_json()["results"][0]["token_id"] == newest_id


def test_unsupported_platform_is_reported_without_dispatch(
        client, broadcast_setup):
    with app.app_context():
        _token(
            broadcast_setup["opted_in_id"],
            "unsupported-token",
            platform="web",
            environment="n/a",
        )
        db.session.commit()

    with (
        patch("app.is_production", False),
        patch("app.send_apns_push") as apns,
        patch("app.send_fcm_push") as fcm,
        patch("app.create_message_event") as audit,
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["unsupported_platforms"] == 1
    assert payload["results"][0]["error"] == "unsupported_platform"
    apns.assert_not_called()
    fcm.assert_not_called()
    audit.assert_not_called()


def test_production_blocks_before_token_query_or_provider_activity(
        client, broadcast_setup):
    _login(client, broadcast_setup["admin_id"])
    with (
        patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": broadcast_setup["admin_email"]}),
        patch("app.is_production", True),
        patch("app.send_apns_push") as apns,
        patch("app.send_fcm_push") as fcm,
    ):
        response = json_post(client, ROUTE)

    assert response.status_code == 403
    assert response.get_json()["error"] == "not_available_in_production"
    apns.assert_not_called()
    fcm.assert_not_called()


def test_get_no_longer_executes_broadcast(client, broadcast_setup):
    _login(client, broadcast_setup["admin_id"])
    with (
        patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": broadcast_setup["admin_email"]}),
        patch("app.send_apns_push") as apns,
        patch("app.send_fcm_push") as fcm,
    ):
        response = client.get(ROUTE)

    assert response.status_code == 405
    apns.assert_not_called()
    fcm.assert_not_called()


def test_post_requires_csrf(client, broadcast_setup):
    _login(client, broadcast_setup["admin_id"])
    with (
        patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": broadcast_setup["admin_email"]}),
        patch("app.send_apns_push") as apns,
    ):
        response = client.post(ROUTE, json={})

    assert response.status_code == 403
    apns.assert_not_called()


def test_unauthenticated_user_is_blocked(client):
    response = client.post(
        ROUTE,
        json={},
        headers={"X-CSRF-Token": _TEST_CSRF},
    )
    assert response.status_code in (302, 401)


def test_non_admin_user_is_blocked(client, broadcast_setup):
    _login(client, broadcast_setup["opted_in_id"])
    with patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": broadcast_setup["admin_email"]}):
        response = json_post(client, ROUTE)
    assert response.status_code == 403


def test_qa_override_still_only_narrows_eligible_recipients(
        client, broadcast_setup):
    with app.app_context():
        qa_token = _token(broadcast_setup["opted_in_id"], "qa-token")
        _token(broadcast_setup["admin_id"], "non-qa-token")
        qa_token_id = qa_token.id
        db.session.commit()

    qa_user = SimpleNamespace(
        id=broadcast_setup["opted_in_id"],
        email="qa-user@bl.test",
    )
    with (
        patch("app.is_production", False),
        patch("app._get_qa_push_override_user", return_value=qa_user),
        patch("app.send_apns_push", return_value=_successful_apns()) as apns,
        patch("app.create_message_event"),
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 200
    apns.assert_called_once()
    payload = response.get_json()
    assert payload["total_active_tokens"] == 1
    assert payload["results"][0]["token_id"] == qa_token_id


def test_provider_failure_retains_failed_result_and_audit_logging(
        client, broadcast_setup):
    with app.app_context():
        token = _token(
            broadcast_setup["opted_in_id"],
            "failed-android-token",
            platform="android",
            environment="n/a",
        )
        token_id = token.id
        db.session.commit()

    provider_result = {
        "success": False,
        "message_id": None,
        "error": "provider rejected token",
    }
    with (
        patch("app.is_production", False),
        patch("app.send_fcm_push", return_value=provider_result),
        patch("app.create_message_event") as audit,
    ):
        response = _post_as_admin(client, broadcast_setup)

    assert response.status_code == 502
    payload = response.get_json()
    assert payload["total_failed"] == 1
    assert payload["results"][0]["token_id"] == token_id
    assert payload["results"][0]["error"] == "provider rejected token"
    assert audit.call_count == 1
    assert audit.call_args.kwargs["delivery_status"] == DeliveryStatus.FAILED
    assert audit.call_args.kwargs["error_message"] == "provider rejected token"