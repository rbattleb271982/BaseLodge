"""BL-218 regressions: explicit, CSRF-protected browser mutations only."""

from datetime import datetime, timedelta

import pytest

from app import _CSRF_EXEMPT_ENDPOINTS, app
from models import db, EquipmentDiscipline, EquipmentSetup, Friend, InviteToken, User
from tests.conftest import _TEST_CSRF, _login, _make_user, form_post, json_post


@pytest.fixture
def bl218_setup(client):
    """A viewer, a reciprocal friend, and deliberately non-normalized gear."""
    with app.app_context():
        viewer = _make_user("bl218-viewer")
        friend = _make_user("bl218-friend")
        db.session.add_all((
            Friend(
                user_id=viewer.id,
                friend_id=friend.id,
                has_viewed_profile=False,
            ),
            Friend(
                user_id=friend.id,
                friend_id=viewer.id,
                has_viewed_profile=False,
            ),
        ))
        first = EquipmentSetup(
            user_id=viewer.id,
            discipline=EquipmentDiscipline.SKIER,
            brand="First",
            is_primary=True,
            created_at=datetime.utcnow() - timedelta(minutes=1),
        )
        second = EquipmentSetup(
            user_id=viewer.id,
            discipline=EquipmentDiscipline.SKIER,
            brand="Second",
            is_primary=True,
            created_at=datetime.utcnow(),
        )
        db.session.add_all((first, second))
        db.session.commit()
        result = {
            "viewer_id": viewer.id,
            "friend_id": friend.id,
            "first_setup_id": first.id,
            "second_setup_id": second.id,
        }
    return result


def _persistent_state(setup):
    with app.app_context():
        viewed = Friend.query.filter_by(
            user_id=setup["viewer_id"], friend_id=setup["friend_id"]
        ).one().has_viewed_profile
        primaries = tuple(
            row.is_primary for row in EquipmentSetup.query.filter_by(
                user_id=setup["viewer_id"]
            ).order_by(EquipmentSetup.id).all()
        )
        user = db.session.get(User, setup["viewer_id"])
        return {
            "invite_count": InviteToken.query.filter_by(
                inviter_id=setup["viewer_id"]
            ).count(),
            "friend_viewed": viewed,
            "primaries": primaries,
            "last_active_at": user.last_active_at,
        }


@pytest.mark.parametrize(
    ("route_template", "body"),
    (
        ("/api/invite/token", None),
        ("/api/friends/{friend_id}/viewed", None),
        ("/api/notifications/viewed", None),
        ("/api/activity/heartbeat", None),
    ),
)
@pytest.mark.parametrize("csrf", (None, "not-the-session-token"))
def test_new_mutations_reject_missing_or_invalid_csrf_before_writing(
    client, bl218_setup, route_template, body, csrf
):
    _login(client, bl218_setup["viewer_id"])
    with client.session_transaction() as session:
        session["_auth_session_logged"] = True
        session.pop("notif_last_viewed_at", None)
        session["_last_active_stamp"] = 0
    before = _persistent_state(bl218_setup)

    response = client.post(
        route_template.format(**bl218_setup),
        json=body,
        headers={"X-CSRF-Token": csrf} if csrf is not None else {},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_failed"
    assert _persistent_state(bl218_setup) == before
    with client.session_transaction() as session:
        assert "notif_last_viewed_at" not in session
        assert session["_last_active_stamp"] == 0


def test_new_mutations_with_valid_csrf_preserve_their_intended_semantics(
    client, bl218_setup
):
    _login(client, bl218_setup["viewer_id"])
    with client.session_transaction() as session:
        session["_auth_session_logged"] = True
        session["_last_active_stamp"] = 0
        session.pop("notif_last_viewed_at", None)

    invite = json_post(client, "/api/invite/token")
    assert invite.status_code == 200
    first_url = invite.get_json()["invite_url"]
    assert invite.get_json()["qr_url"] == "/my-qr"

    repeated_invite = json_post(client, "/api/invite/token")
    assert repeated_invite.status_code == 200
    assert repeated_invite.get_json()["invite_url"] == first_url
    with app.app_context():
        assert InviteToken.query.filter_by(
            inviter_id=bl218_setup["viewer_id"]
        ).count() == 1

    friend_viewed = json_post(
        client, f"/api/friends/{bl218_setup['friend_id']}/viewed"
    )
    assert friend_viewed.status_code == 200
    with app.app_context():
        assert Friend.query.filter_by(
            user_id=bl218_setup["viewer_id"],
            friend_id=bl218_setup["friend_id"],
        ).one().has_viewed_profile is True

    notifications = json_post(client, "/api/notifications/viewed")
    assert notifications.status_code == 200
    with client.session_transaction() as session:
        assert session["notif_last_viewed_at"]

    heartbeat = json_post(client, "/api/activity/heartbeat")
    assert heartbeat.status_code == 200
    with app.app_context():
        assert db.session.get(
            User, bl218_setup["viewer_id"]
        ).last_active_at is not None


@pytest.mark.parametrize(
    "route_template",
    (
        "/friends",
        "/invite",
        "/my-qr",
        "/friends/{friend_id}",
        "/profile",
        "/notifications",
        "/settings/equipment",
    ),
)
@pytest.mark.parametrize("method", ("get", "head", "options"))
def test_read_and_preflight_requests_never_perform_bl218_writes(
    client, bl218_setup, route_template, method
):
    _login(client, bl218_setup["viewer_id"])
    with client.session_transaction() as session:
        # Ignore the unrelated one-time audit-session marker in before_request.
        session["_auth_session_logged"] = True
        session.pop("notif_last_viewed_at", None)
    before = _persistent_state(bl218_setup)

    response = getattr(client, method)(route_template.format(**bl218_setup))

    assert response.status_code in (200, 204, 404, 405)
    assert _persistent_state(bl218_setup) == before
    with client.session_transaction() as session:
        assert "notif_last_viewed_at" not in session


def test_equipment_normalization_happens_only_in_explicit_mutations(
    client, bl218_setup
):
    _login(client, bl218_setup["viewer_id"])
    with client.session_transaction() as session:
        session["_auth_session_logged"] = True

    # Read paths leave the deliberately invalid two-primary legacy state alone.
    assert client.get("/profile").status_code == 200
    assert _persistent_state(bl218_setup)["primaries"] == (True, True)

    saved = form_post(
        client,
        "/settings/equipment/save",
        {
            "setup_id": bl218_setup["second_setup_id"],
            "discipline": "Skier",
            "brand": "Second updated",
        },
    )
    assert saved.status_code == 200
    assert _persistent_state(bl218_setup)["primaries"] == (True, False)

    primary = form_post(
        client,
        "/settings/equipment/make-primary",
        {"setup_id": bl218_setup["second_setup_id"]},
    )
    assert primary.status_code == 200
    assert _persistent_state(bl218_setup)["primaries"] == (False, True)

    deleted = form_post(
        client,
        "/settings/equipment/delete",
        {"setup_id": bl218_setup["second_setup_id"]},
    )
    assert deleted.status_code == 200
    assert _persistent_state(bl218_setup)["primaries"] == (True,)


def test_bl218_endpoints_have_no_csrf_exemptions():
    protected_endpoints = {
        "provision_invite_token",
        "acknowledge_friend_profile_view",
        "acknowledge_notifications_viewed",
        "activity_heartbeat",
    }
    assert protected_endpoints.isdisjoint(_CSRF_EXEMPT_ENDPOINTS)


def test_csrf_failure_representation_is_stable_for_html_and_json(
    client, bl218_setup
):
    _login(client, bl218_setup["viewer_id"])

    api_response = client.post("/api/notifications/viewed")
    assert api_response.status_code == 403
    assert api_response.mimetype == "application/json"
    assert api_response.get_json() == {
        "error": "csrf_failed",
        "message": "CSRF token missing or invalid.",
    }

    html_response = client.post("/logout")
    assert html_response.status_code == 403
    assert html_response.mimetype == "text/html"
    assert b"CSRF token missing or invalid." in html_response.data


def test_web_callers_use_the_shared_csrf_fetch_wrapper():
    expected_calls = {
        "templates/friends.html": "/api/invite/token",
        "templates/invite.html": "/api/invite/token",
        "templates/friend_profile.html": "acknowledge_friend_profile_view",
        "templates/notifications.html": "/api/notifications/viewed",
        "templates/components/analytics_head.html": "/api/activity/heartbeat",
    }
    for file_name, route_reference in expected_calls.items():
        source = open(file_name, encoding="utf-8").read()
        assert "window.blFetch" in source
        assert route_reference in source