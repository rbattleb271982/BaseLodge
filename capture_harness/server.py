"""Isolated Flask server for deterministic capture runs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from freezegun import freeze_time
from models import Invitation

from .config import CAPTURE_NOW, capture_database, resolve_capture_config
from .effects import install_capture_effects


def _logical_bindings(registry: dict[str, Any]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    heavy = registry["personas"]["HEAVY"]
    for index, trip in enumerate(heavy["trips"], 1):
        bindings[f"HT{index:02d}"] = trip.id
    for logical_id, trip in registry["state_trips"].items():
        bindings[logical_id] = trip.id
    for friend_id, metadata in heavy["friend_ids"].items():
        bindings[metadata["logical_id"]] = friend_id
    for key, resort in registry["resorts"].items():
        bindings[key] = resort.slug
        bindings[resort.slug] = resort.slug
    bindings["capture-friend-invite"] = registry["invite_token"].token
    return bindings


def create_capture_application() -> tuple[Any, dict[str, Any]]:
    """Import and initialize BaseLodge only after capture safety is validated."""
    config = resolve_capture_config()
    if Path(config.database_path).exists():
        Path(config.database_path).unlink()

    # These overrides exist only in this dedicated process.
    os.environ["BASELODGE_TEST_DATABASE_URL"] = config.database_url
    os.environ["RATELIMIT_STORAGE_URI"] = "memory://"
    for key in (
        "POSTHOG_KEY",
        "SENDGRID_API_KEY",
        "ONESIGNAL_APP_ID",
        "ONESIGNAL_REST_API_KEY",
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        "APNS_KEY_P8",
        "ASC_KEY_P8",
    ):
        os.environ.pop(key, None)

    import app as application
    from capture_harness.fixtures import seed_all

    application.app.config.update(
        TESTING=True,
        SESSION_COOKIE_SECURE=False,
        REMEMBER_COOKIE_SECURE=False,
        SERVER_NAME=None,
    )
    with application.app.app_context():
        application.db.create_all()
        registry = seed_all(application.db)
        persona_emails = {
            name.lower(): data["user"].email
            for name, data in registry["personas"].items()
        }
        bindings = _logical_bindings(registry)

    def capture_health():
        return {
            "ok": True,
            "capture_mode": True,
            "frozen_at": CAPTURE_NOW.isoformat(),
        }

    def capture_auth():
        payload = application.request.get_json(silent=True) or {}
        persona = str(payload.get("persona", "")).strip().lower()
        email = persona_emails.get(persona)
        if email is None:
            return {"ok": False, "error": "unknown_capture_persona"}, 404
        user = application.db.session.execute(
            application.db.select(application.User).filter_by(email=email)
        ).scalar_one()
        application._establish_authenticated_session(
            user,
            remember=False,
            auth_method="capture",
            update_remember_cookie=False,
        )
        return {"ok": True, "persona": persona, "bindings": bindings}

    def capture_prepare():
        payload = application.request.get_json(silent=True) or {}
        capture_id = str(payload.get("capture_id", ""))
        pending = registry["state_trips"]["HOME_PENDING"]
        participant = registry["state_trips"]["HOME_PARTICIPANT"]
        pending.lifecycle_state = (
            "active" if "pending-invite" in capture_id or "pending-invites" in capture_id
            else "cancelled"
        )
        participant.lifecycle_state = (
            "active" if "next-trip-participant" in capture_id else "cancelled"
        )
        pending_friend_request = application.db.session.get(
            Invitation, registry["pending_friend_request_id"]
        )
        pending_friend_request.status = (
            "pending" if "friends__typical__pending-requests" in capture_id
            else "declined"
        )
        if "home__edge__edge-error" in capture_id:
            application.flash("Some trip suggestions could not be loaded.", "error")
        application.db.session.commit()
        assert pending_friend_request.status in {"pending", "declined"}
        return {"ok": True}

    def capture_global_flash():
        application.flash("Something went wrong. Please try again.", "error")
        return application.redirect(application.url_for("home"))

    application.app.add_url_rule(
        "/api/capture/health",
        endpoint="capture_health",
        view_func=capture_health,
        methods=["GET"],
    )
    application.csrf_exempt(capture_auth)
    application.csrf_exempt(capture_prepare)
    application.app.add_url_rule(
        "/api/capture/auth",
        endpoint="capture_auth",
        view_func=capture_auth,
        methods=["POST"],
    )
    application.app.add_url_rule(
        "/api/capture/prepare",
        endpoint="capture_prepare",
        view_func=capture_prepare,
        methods=["POST"],
    )
    application.app.add_url_rule(
        "/capture-global-flash",
        endpoint="capture_global_flash",
        view_func=capture_global_flash,
    )
    return application.app, registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    config = resolve_capture_config()
    frozen_utc = CAPTURE_NOW.astimezone().astimezone(__import__("datetime").timezone.utc)
    with capture_database(config), freeze_time(frozen_utc), install_capture_effects():
        capture_app, _ = create_capture_application()
        capture_app.run(
            host=args.host,
            port=args.port,
            debug=False,
            use_reloader=False,
            threaded=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())