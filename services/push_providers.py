"""
BaseLodge push provider functions.

Provider-specific delivery functions live here, not in app.py.
This isolation prevents circular imports when the orchestration layer
(services/message_dispatch.py) needs to call provider functions.

Functions:
    send_onesignal_push         — immediate push via OneSignal REST API
    send_onesignal_custom_event — automation signal via OneSignal Custom Events API

The orchestration layer DOES NOT import from this file directly.
Dispatch functions (_dispatch_immediate_push, _dispatch_automation_event)
are the only callers — they live in services/message_dispatch.py and
encapsulate all provider knowledge from the orchestration switch.

Canonical return shape (Phase D-1):
    Both functions return:
        {
            "success":             bool,
            "provider_message_id": str | None,
            "skipped":             bool,
            "error":               str | None,
        }

    success=True + skipped=True  → recipient opted out or no eligible recipients;
                                   no delivery attempted, no error.
    success=True + skipped=False → delivery accepted by the provider.
    success=False                → provider error or configuration failure;
                                   error field contains detail.
    provider_message_id          → OneSignal notification ID on SENT rows;
                                   None on all other outcomes.
                                   send_onesignal_custom_event always returns None
                                   (Custom Events API provides no per-send ID).
"""

import os

import httpx
from flask import current_app

from models import db, User


def send_onesignal_push(user_ids, title, body, data=None):
    """Send a push notification via the OneSignal REST API.

    Targets BaseLodge users by their internal integer user ID, which is
    registered as the OneSignal external_id from the client SDK init block.

    Args:
        user_ids: iterable of integer BaseLodge user IDs.
        title:    notification title string.
        body:     notification body / message string.
        data:     optional dict of extra key/value data forwarded to the device.

    Returns canonical dict:
        {
            "success":             bool,
            "provider_message_id": str | None,   # OneSignal notification ID
            "skipped":             bool,
            "error":               str | None,
        }

    Environment variables required (never exposed client-side):
        ONESIGNAL_APP_ID        — public app identifier (safe to log).
        ONESIGNAL_REST_API_KEY  — secret REST key (never logged).
    """
    app_id   = os.environ.get("ONESIGNAL_APP_ID", "")
    rest_key = os.environ.get("ONESIGNAL_REST_API_KEY", "")

    if not app_id or not rest_key:
        current_app.logger.warning(
            "[OneSignal] send_onesignal_push: ONESIGNAL_APP_ID or "
            "ONESIGNAL_REST_API_KEY not set — push skipped"
        )
        return {"success": False, "provider_message_id": None, "skipped": False,
                "error": "missing_config"}

    all_ids = list(user_ids)

    # Filter out users who have opted out of push notifications
    try:
        opted_out = {
            row.id for row in
            db.session.query(User.id).filter(
                User.id.in_(all_ids),
                User.push_notifications_enabled == False  # noqa: E712
            ).all()
        }
        if opted_out:
            current_app.logger.warning(
                "[OneSignal] send_push: skipping %d opted-out user(s): %s",
                len(opted_out), sorted(opted_out),
            )
        all_ids = [uid for uid in all_ids if uid not in opted_out]
    except Exception as _filter_err:
        current_app.logger.warning(
            "[OneSignal] send_push: opt-out filter failed (%s) — proceeding with all ids", _filter_err
        )

    if not all_ids:
        current_app.logger.warning("[OneSignal] send_push: all recipients opted out — silent skip (no delivery attempt)")
        return {"success": True, "provider_message_id": None, "skipped": True, "error": None}

    external_ids = [str(uid) for uid in all_ids]

    payload = {
        "app_id":          app_id,
        "include_aliases": {"external_id": external_ids},
        "target_channel":  "push",
        "headings":        {"en": title},
        "contents":        {"en": body},
        "ios_badgeType":   "SetTo",
        "ios_badgeCount":  1,
    }
    if data:
        payload["data"] = data

    current_app.logger.warning(
        "[OneSignal] send_push → external_ids=%s title=%r",
        external_ids, title,
    )

    try:
        resp = httpx.post(
            "https://onesignal.com/api/v1/notifications",
            headers={
                "Authorization":  f"Basic {rest_key}",
                "Content-Type":   "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        result          = resp.json()
        notification_id = result.get("id")
        errors          = result.get("errors")
        current_app.logger.warning(
            "[OneSignal] response status=%d notification_id=%s errors=%s",
            resp.status_code, notification_id, errors,
        )
        if resp.status_code in (200, 202) and not errors:
            return {"success": True, "provider_message_id": notification_id,
                    "skipped": False, "error": None}
        return {"success": False, "provider_message_id": notification_id,
                "skipped": False, "error": str(errors or result)}
    except Exception as _exc:
        current_app.logger.exception("[OneSignal] request failed: %s", _exc)
        return {"success": False, "provider_message_id": None,
                "skipped": False, "error": str(_exc)}


def send_onesignal_custom_event(user_ids, event_name, properties=None):
    """Send a OneSignal Custom Event for each user in user_ids.

    Used to trigger OneSignal Journeys (e.g. a delayed push) rather than
    sending an immediate notification. The Custom Events API accepts one
    external_id per request, so this function loops and fires one POST per
    recipient.

    Args:
        user_ids:   iterable of integer BaseLodge user IDs.
        event_name: string event name registered in the OneSignal dashboard.
        properties: optional dict of key/value properties attached to the event.

    Returns canonical dict:
        {
            "success":             bool,
            "provider_message_id": None,   # Custom Events API provides no per-send ID
            "skipped":             bool,
            "error":               str | None,
        }

    Environment variables required:
        ONESIGNAL_APP_ID       — public app identifier (safe to log).
        ONESIGNAL_REST_API_KEY — secret REST key (never logged).
    """
    app_id   = os.environ.get("ONESIGNAL_APP_ID", "")
    rest_key = os.environ.get("ONESIGNAL_REST_API_KEY", "")

    if not app_id or not rest_key:
        current_app.logger.warning(
            "[OneSignal] send_onesignal_event: ONESIGNAL_APP_ID or "
            "ONESIGNAL_REST_API_KEY not set — event skipped"
        )
        return {"success": False, "provider_message_id": None,
                "skipped": False, "error": "missing_config"}

    all_ids = list(user_ids)
    if not all_ids:
        return {"success": True, "provider_message_id": None, "skipped": True, "error": None}

    url     = f"https://api.onesignal.com/apps/{app_id}/events"
    headers = {
        "Authorization": f"Basic {rest_key}",
        "Content-Type":  "application/json",
    }
    props = properties or {}

    current_app.logger.warning(
        "[OneSignal] send_event → event_name=%r recipient_count=%d",
        event_name, len(all_ids),
    )

    sent   = 0
    failed = 0
    for uid in all_ids:
        ext_id  = str(uid)
        payload = {
            "name":       event_name,
            "properties": props,
            "identity":   {"external_id": ext_id},
        }
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=10.0)
            if resp.status_code in (200, 202):
                current_app.logger.warning(
                    "[OneSignal] send_event: external_id=%s status=%d",
                    ext_id, resp.status_code,
                )
                sent += 1
            else:
                current_app.logger.warning(
                    "[OneSignal] send_event: external_id=%s status=%d error=%s",
                    ext_id, resp.status_code, resp.text[:200],
                )
                failed += 1
        except Exception as _exc:
            current_app.logger.exception(
                "[OneSignal] send_event: request failed for external_id=%s: %s",
                ext_id, _exc,
            )
            failed += 1

    _error = None if failed == 0 else f"sent={sent} failed={failed}"
    return {"success": failed == 0, "provider_message_id": None,
            "skipped": False, "error": _error}
