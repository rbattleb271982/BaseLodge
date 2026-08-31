"""
#242 — CSRF tests (spec sections 14, 15, 17).

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import os
import unittest.mock
import pytest
from app import app
from models import (
    db, User, SkiTrip, SkiTripPlanningPost, GuestStatus, PushDeviceToken,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post, form_post, _TEST_CSRF,
)


@pytest.fixture
def csrf_setup(client):
    with app.app_context():
        resort = _make_resort()
        owner  = _make_user("owner")
        other  = _make_user("other")
        trip   = _make_trip(owner, resort=resort)
        _add_participant(trip, other, GuestStatus.ACCEPTED)
        db.session.commit()
        data = {
            "owner_id":    owner.id,
            "owner_email": owner.email,
            "other_id":    other.id,
            "trip_id":     trip.id,
            "resort_id":   resort.id,
        }
    yield data


def _json_no_csrf(client, url, data=None):
    return client.post(url, json=data or {})


def _json_bad_csrf(client, url, data=None):
    return client.post(url, json=data or {},
                       headers={"X-CSRF-Token": "wrong-token-xyz"})


def _form_no_csrf(client, url, data=None):
    return client.post(url, data=data or {})


def _form_bad_csrf(client, url, data=None):
    payload = dict(data or {})
    payload["csrf_token"] = "bad-token-xyz"
    return client.post(url, data=payload)


# ── Native push registration and diagnostics ──────────────────────────────────

def test_push_register_ios_valid_csrf_succeeds(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, "/api/push/register-token", {
        "token": "ios-valid-csrf-token",
        "platform": "ios",
        "apns_environment": "production",
    })
    assert rv.status_code == 200
    assert rv.get_json()["action"] == "inserted"
    with app.app_context():
        row = PushDeviceToken.query.filter_by(
            user_id=csrf_setup["owner_id"],
            token="ios-valid-csrf-token",
        ).one()
        assert row.platform == "ios"
        assert row.apns_environment == "production"
        assert row.active is True


def test_push_register_android_valid_csrf_succeeds(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, "/api/push/register-token", {
        "token": "android-valid-csrf-token",
        "platform": "android",
    })
    assert rv.status_code == 200
    with app.app_context():
        row = PushDeviceToken.query.filter_by(
            user_id=csrf_setup["owner_id"],
            token="android-valid-csrf-token",
        ).one()
        assert row.platform == "android"
        assert row.apns_environment == "n/a"
        assert row.active is True


@pytest.mark.parametrize("request_csrf", [None, "wrong-token-xyz"])
def test_push_register_rejects_bad_csrf_without_token_side_effects(
        client, csrf_setup, request_csrf):
    with app.app_context():
        existing = PushDeviceToken(
            user_id=csrf_setup["owner_id"],
            token="existing-active-ios-token",
            platform="ios",
            active=True,
            apns_environment="production",
        )
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

    _login(client, csrf_setup["owner_id"])
    headers = {"X-CSRF-Token": request_csrf} if request_csrf else {}
    rv = client.post(
        "/api/push/register-token",
        json={
            "token": "forged-new-ios-token",
            "platform": "ios",
            "apns_environment": "production",
        },
        headers=headers,
    )
    assert rv.status_code == 403
    with app.app_context():
        assert PushDeviceToken.query.filter_by(
            user_id=csrf_setup["owner_id"]
        ).count() == 1
        assert db.session.get(PushDeviceToken, existing_id).active is True
        assert PushDeviceToken.query.filter_by(
            token="forged-new-ios-token"
        ).first() is None


def test_push_register_unauthenticated_remains_blocked(client):
    rv = client.post(
        "/api/push/register-token",
        json={"token": "unauthenticated-token", "platform": "ios"},
        headers={"X-CSRF-Token": _TEST_CSRF},
    )
    assert rv.status_code in (302, 401)
    with app.app_context():
        assert PushDeviceToken.query.filter_by(
            token="unauthenticated-token"
        ).first() is None


def test_push_register_valid_csrf_preserves_same_platform_deactivation(
        client, csrf_setup):
    with app.app_context():
        old = PushDeviceToken(
            user_id=csrf_setup["owner_id"],
            token="old-ios-token",
            platform="ios",
            active=True,
            apns_environment="production",
        )
        db.session.add(old)
        db.session.commit()
        old_id = old.id

    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, "/api/push/register-token", {
        "token": "new-ios-token",
        "platform": "ios",
        "apns_environment": "production",
    })
    assert rv.status_code == 200
    with app.app_context():
        assert db.session.get(PushDeviceToken, old_id).active is False
        assert PushDeviceToken.query.filter_by(
            user_id=csrf_setup["owner_id"],
            token="new-ios-token",
            active=True,
        ).count() == 1


def test_push_register_valid_csrf_preserves_refresh_reactivation(
        client, csrf_setup):
    with app.app_context():
        existing = PushDeviceToken(
            user_id=csrf_setup["owner_id"],
            token="inactive-ios-token",
            platform="ios",
            active=False,
            apns_environment="production",
        )
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, "/api/push/register-token", {
        "token": "inactive-ios-token",
        "platform": "ios",
        "apns_environment": "production",
    })
    assert rv.status_code == 200
    assert rv.get_json()["action"] == "refreshed"
    with app.app_context():
        assert db.session.get(PushDeviceToken, existing_id).active is True
        assert PushDeviceToken.query.filter_by(
            user_id=csrf_setup["owner_id"],
            token="inactive-ios-token",
        ).count() == 1


def test_push_beacon_valid_csrf_logs_diagnostic(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    with unittest.mock.patch.object(app.logger, "warning") as warning:
        rv = json_post(client, "/api/push/beacon", {
            "step": "csrf_valid",
            "data": {"platform": "ios"},
        })
    assert rv.status_code == 200
    assert rv.get_json() == {"ok": True}
    assert any(
        call.args and call.args[0].startswith("[PushBeacon]")
        for call in warning.call_args_list
    )


@pytest.mark.parametrize("request_csrf", [None, "wrong-token-xyz"])
def test_push_beacon_rejects_bad_csrf_before_diagnostic_logging(
        client, csrf_setup, request_csrf):
    _login(client, csrf_setup["owner_id"])
    headers = {"X-CSRF-Token": request_csrf} if request_csrf else {}
    with unittest.mock.patch.object(app.logger, "warning") as warning:
        rv = client.post(
            "/api/push/beacon",
            json={"step": "must_not_log", "data": {"platform": "android"}},
            headers=headers,
        )
    assert rv.status_code == 403
    assert not any(
        call.args and call.args[0].startswith("[PushBeacon]")
        for call in warning.call_args_list
    )


def test_push_beacon_unauthenticated_remains_blocked(client):
    with unittest.mock.patch.object(app.logger, "warning") as warning:
        rv = client.post(
            "/api/push/beacon",
            json={"step": "unauthenticated"},
            headers={"X-CSRF-Token": _TEST_CSRF},
        )
    assert rv.status_code in (302, 401)
    assert not any(
        call.args and call.args[0].startswith("[PushBeacon]")
        for call in warning.call_args_list
    )


# ── update-visibility ─────────────────────────────────────────────────────────

def test_csrf_update_visibility_valid(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{csrf_setup['trip_id']}/update-visibility",
                   {"is_public": False})
    assert rv.status_code == 200


def test_csrf_update_visibility_missing_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_no_csrf(client, f"/api/trip/{csrf_setup['trip_id']}/update-visibility",
                       {"is_public": False})
    assert rv.status_code == 403


def test_csrf_update_visibility_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_bad_csrf(client, f"/api/trip/{csrf_setup['trip_id']}/update-visibility",
                        {"is_public": False})
    assert rv.status_code == 403


def test_csrf_update_visibility_no_mutation_on_failure(client, csrf_setup):
    trip_id = csrf_setup["trip_id"]
    _login(client, csrf_setup["owner_id"])

    with app.app_context():
        original = SkiTrip.query.get(trip_id).is_public

    _json_no_csrf(client, f"/api/trip/{trip_id}/update-visibility",
                  {"is_public": not original})

    with app.app_context():
        assert SkiTrip.query.get(trip_id).is_public == original


# ── planning-post create ──────────────────────────────────────────────────────

def test_csrf_planning_post_valid(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, f"/api/trip/{csrf_setup['trip_id']}/planning-posts",
                   {"category": "Other", "body": "Test"})
    assert rv.status_code == 201


def test_csrf_planning_post_missing_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_no_csrf(client, f"/api/trip/{csrf_setup['trip_id']}/planning-posts",
                       {"category": "Other", "body": "Test"})
    assert rv.status_code == 403


def test_csrf_planning_post_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_bad_csrf(client, f"/api/trip/{csrf_setup['trip_id']}/planning-posts",
                        {"category": "Other", "body": "Test"})
    assert rv.status_code == 403


def test_csrf_planning_post_no_row_created_on_failure(client, csrf_setup):
    trip_id = csrf_setup["trip_id"]
    _login(client, csrf_setup["owner_id"])

    with app.app_context():
        before = SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count()

    _json_no_csrf(client, f"/api/trip/{trip_id}/planning-posts",
                  {"category": "Other", "body": "Blocked"})

    with app.app_context():
        after = SkiTripPlanningPost.query.filter_by(trip_id=trip_id).count()
    assert after == before


# ── Friend invite accept ──────────────────────────────────────────────────────

def test_csrf_friend_accept_missing_403(client, csrf_setup):
    _login(client, csrf_setup["other_id"])
    rv = _json_no_csrf(client, "/api/friends/invite/999/accept")
    assert rv.status_code == 403


def test_csrf_friend_accept_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["other_id"])
    rv = _json_bad_csrf(client, "/api/friends/invite/999/accept")
    assert rv.status_code == 403


# ── Wishlist ──────────────────────────────────────────────────────────────────

def test_csrf_wishlist_add_valid(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = json_post(client, "/api/wishlist/add", {"resort_id": csrf_setup["resort_id"]})
    assert rv.status_code != 403


def test_csrf_wishlist_add_missing_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_no_csrf(client, "/api/wishlist/add", {"resort_id": 1})
    assert rv.status_code == 403


def test_csrf_wishlist_add_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _json_bad_csrf(client, "/api/wishlist/add", {"resort_id": 1})
    assert rv.status_code == 403


# ── Trip invite token accept (form) ───────────────────────────────────────────

def test_csrf_trip_invite_accept_form_missing_403(client, csrf_setup):
    _login(client, csrf_setup["other_id"])
    rv = _form_no_csrf(client, "/trip-invite/faketoken99/accept")
    assert rv.status_code == 403


def test_csrf_trip_invite_accept_form_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["other_id"])
    rv = _form_bad_csrf(client, "/trip-invite/faketoken99/accept")
    assert rv.status_code == 403


# ── Delete account ────────────────────────────────────────────────────────────

def test_csrf_delete_account_missing_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _form_no_csrf(client, "/delete-account",
                       {"confirm_email": csrf_setup["owner_email"]})
    assert rv.status_code == 403


def test_csrf_delete_account_invalid_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _form_bad_csrf(client, "/delete-account",
                        {"confirm_email": csrf_setup["owner_email"]})
    assert rv.status_code == 403


def test_csrf_delete_account_no_deletion_on_failure(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    _form_no_csrf(client, "/delete-account",
                  {"confirm_email": csrf_setup["owner_email"]})

    with app.app_context():
        assert User.query.get(csrf_setup["owner_id"]) is not None


# ── /skip-pass-prompt ─────────────────────────────────────────────────────────

def test_skip_pass_prompt_get_returns_405(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = client.get("/skip-pass-prompt")
    assert rv.status_code == 405


def test_skip_pass_prompt_get_does_not_set_session(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    client.get("/skip-pass-prompt")
    with client.session_transaction() as sess:
        assert not sess.get("pass_prompt_skipped")


def test_skip_pass_prompt_post_valid_csrf_sets_session(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = form_post(client, "/skip-pass-prompt")
    assert rv.status_code in (200, 302)
    with client.session_transaction() as sess:
        assert sess.get("pass_prompt_skipped") is True


def test_skip_pass_prompt_post_missing_csrf_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _form_no_csrf(client, "/skip-pass-prompt")
    assert rv.status_code == 403
    with client.session_transaction() as sess:
        assert not sess.get("pass_prompt_skipped")


def test_skip_pass_prompt_post_invalid_csrf_403(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    rv = _form_bad_csrf(client, "/skip-pass-prompt")
    assert rv.status_code == 403
    with client.session_transaction() as sess:
        assert not sess.get("pass_prompt_skipped")


# ── Admin CSRF smoke tests ────────────────────────────────────────────────────

@pytest.fixture
def admin_setup(client):
    with app.app_context():
        admin = _make_user("admin", email="admin_csrf_test@bl.test")
        db.session.commit()
        data = {"admin_id": admin.id, "admin_email": admin.email}
    yield data


def test_admin_mutation_valid_csrf_reaches_handler(client, admin_setup):
    _login(client, admin_setup["admin_id"])
    with unittest.mock.patch.dict(os.environ,
                                  {"ALLOWED_ADMIN_EMAILS": admin_setup["admin_email"]}):
        rv = json_post(client, "/api/admin/resorts/toggle-active",
                       {"resort_id": 99999, "is_active": True})
    assert rv.status_code in (200, 404), (
        f"Expected 200/404 (handler reached), got {rv.status_code}"
    )


def test_admin_mutation_missing_csrf_403(client, admin_setup):
    _login(client, admin_setup["admin_id"])
    with unittest.mock.patch.dict(os.environ,
                                  {"ALLOWED_ADMIN_EMAILS": admin_setup["admin_email"]}):
        rv = _json_no_csrf(client, "/api/admin/resorts/toggle-active",
                           {"resort_id": 99999, "is_active": True})
    assert rv.status_code == 403


def test_admin_mutation_invalid_csrf_403(client, admin_setup):
    _login(client, admin_setup["admin_id"])
    with unittest.mock.patch.dict(os.environ,
                                  {"ALLOWED_ADMIN_EMAILS": admin_setup["admin_email"]}):
        rv = _json_bad_csrf(client, "/api/admin/resorts/toggle-active",
                            {"resort_id": 99999, "is_active": True})
    assert rv.status_code == 403


def test_non_admin_blocked_regardless_of_csrf(client, csrf_setup):
    _login(client, csrf_setup["owner_id"])
    with unittest.mock.patch.dict(os.environ, {"ALLOWED_ADMIN_EMAILS": ""}):
        rv = json_post(client, "/api/admin/resorts/toggle-active",
                       {"resort_id": 99999, "is_active": True})
    assert rv.status_code == 403
