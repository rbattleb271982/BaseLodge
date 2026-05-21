"""
BaseLodge Centralized Messaging Orchestration Layer — Phase C.

This module is the single entry point for all product messaging events.
Routes call emit_messaging_event() with intent. This layer decides execution.

Architecture contract:
    - The orchestration switch reads ONLY spec.delivery_strategy.
    - The orchestration layer has NO knowledge of OneSignal, APNs, FCM,
      HTTP payloads, or any vendor-specific details.
    - Provider knowledge lives exclusively inside dispatch functions, which
      call services/push_providers.py.
    - Every emit_messaging_event() call produces exactly one MEL row
      (one per dispatch function; two rows for IMMEDIATE_PUSH_AND_AUTOMATION).
    - This function never raises. All exceptions are caught internally.

Phase C status:
    _dispatch_immediate_push() is fully internalized — no dependency on
    app._notify_push(). Pipeline: render → dedupe → send → map → MEL.
    Title/body/push_data are owned by the registry and rendered from
    EventSpec templates. Routes pass context-only metadata.
    _notify_push() in app.py is DEPRECATED and unreachable.

Public API:
    emit_messaging_event(event_name, actor_user_id, recipient_user_id,
                         entity_type, entity_id, metadata, source_route)
"""

from dataclasses import dataclass, field
from datetime import datetime

from flask import current_app

from services.message_events import create_message_event, is_duplicate_event
from services.messaging_constants import (
    Category,
    Channel,
    DeliveryStatus,
    DeliveryStrategy,
    EventName,
    Provider,
    SuppressionReason,
)
from services.push_providers import send_onesignal_push


# ─────────────────────────────────────────────────────────────────────────────
# EventSpec — registry entry describing how each event should be handled
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EventSpec:
    """Describes the behavioral contract for a single product event.

    The orchestration layer reads delivery_strategy only. All other fields
    are available to dispatch functions and Phase C template rendering.

    Fields:
        event_name:            Must match an EventName constant.
        category:              Category.* value for MEL grouping.
        delivery_strategy:     DeliveryStrategy.* — the ONLY field the
                               orchestration switch reads.
        title_template:        Message title template string. None in Phase A;
                               populated in Phase C when routes stop owning copy.
        body_template:         Message body template string. None in Phase A.
        data_keys:             Keys extracted from metadata and forwarded as the
                               push payload data dict.
        automation_event_name: Event name sent to the external automation
                               platform (currently OneSignal Custom Events).
                               Required when strategy includes AUTOMATION_EVENT.
                               Named generically — changing automation providers
                               means updating this value and the dispatch fn,
                               not the strategy or registry structure.
        bypass_dedupe:         True for test/admin events and AUTOMATION_EVENT
                               events, which must not be suppressed by the
                               standard push dedupe window.
        email_eligible:        Phase D flag. No orchestration effect yet.
                               True = this event may eventually warrant an email.
    """
    event_name:            str
    category:              str
    delivery_strategy:     str
    title_template:        str | None       = None
    body_template:         str | None       = None
    deep_link_template:    str | None       = None
    url_template:          str | None       = None
    screen:                str | None       = None
    context_keys:          list             = field(default_factory=list)
    data_keys:             list             = field(default_factory=list)
    automation_event_name: str | None       = None
    bypass_dedupe:         bool             = False
    email_eligible:        bool             = False


# ─────────────────────────────────────────────────────────────────────────────
# Event registry
# ─────────────────────────────────────────────────────────────────────────────

_EVENT_REGISTRY: dict[str, EventSpec] = {

    # ── Immediate push events (active — product routes use these today) ──

    EventName.FRIEND_REQUEST_CREATED: EventSpec(
        event_name=EventName.FRIEND_REQUEST_CREATED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} wants to connect",
        body_template="You have a new friend request on BaseLodge.",
        deep_link_template="/friends",
        url_template="/friends",
        screen="friends",
        context_keys=["actor_name", "invitation_id", "user_id"],
        data_keys=["user_id", "invitation_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.FRIEND_REQUEST_ACCEPTED: EventSpec(
        event_name=EventName.FRIEND_REQUEST_ACCEPTED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} accepted your request",
        body_template="You're now connected on BaseLodge.",
        deep_link_template="/friends/{actor_user_id}",
        url_template="/friends",
        screen="friend_profile",
        context_keys=["actor_name", "user_id"],
        data_keys=["user_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_INVITE_CREATED: EventSpec(
        event_name=EventName.TRIP_INVITE_CREATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} invited you to a trip",
        body_template="You've been invited to {resort}.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_INVITE_ACCEPTED: EventSpec(
        event_name=EventName.TRIP_INVITE_ACCEPTED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} accepted your invite",
        body_template="They're joining you for {resort}.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    # ── Automation event (active — currently unlogged friend.pass.changed path) ──

    EventName.FRIEND_PASS_CHANGED: EventSpec(
        event_name=EventName.FRIEND_PASS_CHANGED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.AUTOMATION_EVENT,
        automation_event_name="friend_pass_changed",  # OneSignal Custom Event name
        # data_keys: forwarded from metadata into Journey properties.
        # actor_user_id is injected automatically by _dispatch_automation_event.
        data_keys=["actor_first_name", "new_pass", "new_pass_display"],
        bypass_dedupe=True,   # Journey events bypass push dedupe (see architecture notes)
        email_eligible=False,
        # Note: automation_event_name is the signal identifier sent to the
        # automation platform. If the platform changes, update this value
        # and the dispatch function. DeliveryStrategy.AUTOMATION_EVENT is unchanged.
    ),

    # ── Silent events (registered but produce MEL log rows only) ──
    # These are not wired to product routes yet. Registering them here ensures
    # emit_messaging_event() produces a well-formed MEL row if called,
    # rather than falling through to _dispatch_not_implemented().

    EventName.TRIP_INVITE_DECLINED: EventSpec(
        event_name=EventName.TRIP_INVITE_DECLINED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.OVERLAP_DETECTED: EventSpec(
        event_name=EventName.OVERLAP_DETECTED,
        category=Category.OVERLAP,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=True,  # Future candidate for email digest
    ),

    EventName.FRIEND_TRIP_CREATED: EventSpec(
        event_name=EventName.FRIEND_TRIP_CREATED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.FRIEND_TRIP_UPDATED: EventSpec(
        event_name=EventName.FRIEND_TRIP_UPDATED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.WISHLIST_MATCH_DETECTED: EventSpec(
        event_name=EventName.WISHLIST_MATCH_DETECTED,
        category=Category.WISHLIST,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=True,  # Future candidate for email
    ),

    EventName.DIGEST_WEEKLY_GENERATED: EventSpec(
        event_name=EventName.DIGEST_WEEKLY_GENERATED,
        category=Category.DIGEST,
        delivery_strategy=DeliveryStrategy.SILENT,
        bypass_dedupe=False,
        email_eligible=True,  # Future candidate for email digest
    ),
}


def _get_event_spec(event_name: str) -> EventSpec | None:
    """Return the EventSpec for event_name, or None if not registered."""
    return _EVENT_REGISTRY.get(event_name)


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers — Phase C
# ─────────────────────────────────────────────────────────────────────────────

class _SafeFormatMap(dict):
    """dict subclass that returns '' for missing keys during template rendering.

    Prevents KeyError when a context key is absent from route metadata.
    A missing key degrades gracefully to an empty string and writes a warning
    to the server log — the push still fires rather than being suppressed.
    """
    def __init__(self, data, event_name=""):
        super().__init__(data)
        self._event_name = event_name

    def __missing__(self, key):
        current_app.logger.warning(
            "[MessageDispatch] _render_immediate_push: template key %r missing "
            "for event=%s — using empty string fallback",
            key, self._event_name,
        )
        return ""


def _render_immediate_push(spec, metadata, actor_user_id, entity_id):
    """Render title, body, and push_data from registry-owned templates.

    Returns a dict with keys: title, body, push_data.

    Registry templates are the sole rendering source (Phase C final).
    Routes pass context-only metadata; no title/body/push_data keys expected.

    Args:
        spec:          EventSpec for the event being dispatched.
        metadata:      dict passed by the route (context keys only).
        actor_user_id: int — available as {actor_user_id} in templates.
        entity_id:     int | None — available as {entity_id} in templates.
    """
    meta = metadata or {}

    # Build rendering context: all scalar metadata values + call-site parameters.
    context = _SafeFormatMap(
        {
            **{k: v for k, v in meta.items()
               if isinstance(v, (str, int, float, bool, type(None)))},
            "entity_id":     entity_id if entity_id is not None else "",
            "actor_user_id": actor_user_id if actor_user_id is not None else "",
        },
        event_name=spec.event_name,
    )

    # ── Title ──
    title = spec.title_template.format_map(context) if spec.title_template is not None else ""

    # ── Body ──
    body = spec.body_template.format_map(context) if spec.body_template is not None else ""

    # ── push_data — registry owns the full structure ──
    push_data = {"event": spec.event_name}
    # Forward data_keys from metadata (entity ID fields, invitation_id, etc.).
    for key in (spec.data_keys or []):
        if key in meta:
            push_data[key] = meta[key]
    # Render deep_link from template.
    if spec.deep_link_template is not None:
        push_data["deep_link"] = spec.deep_link_template.format_map(context)
    # Render url for client-side push-tap navigation (_extractPushUrl in analytics_head.html).
    # Must be a same-origin relative path. url_template is kept separate from deep_link_template
    # so that deep_link can carry entity-specific paths (e.g. /trips/42) while url always
    # points to a stable, guaranteed-valid in-app route.
    if spec.url_template is not None:
        rendered_url = spec.url_template.format_map(context)
        if rendered_url.startswith("/") and not rendered_url.startswith("//"):
            push_data["url"] = rendered_url
    # Screen is a constant per event.
    if spec.screen is not None:
        push_data["screen"] = spec.screen

    return {"title": title, "body": body, "push_data": push_data}


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch functions — one per delivery strategy branch
# Each dispatch fn is the ONLY place that knows how to execute its strategy.
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_immediate_push(spec, actor_user_id, recipient_user_id,
                             entity_type, entity_id, metadata, source_route):
    """Execute the IMMEDIATE_PUSH delivery path.

    Phase C: fully internalized — no dependency on app._notify_push().
    Pipeline: render payload → dedupe guard → send → map outcome → write MEL.

    Opt-out filtering is handled inside send_onesignal_push() in
    push_providers.py (queries push_notifications_enabled per recipient).
    Dedupe uses is_duplicate_event() from message_events.py.
    """
    # 1. Render push payload from registry templates (Phase C) with metadata fallback.
    rendered  = _render_immediate_push(spec, metadata, actor_user_id, entity_id)
    title     = rendered["title"]
    body      = rendered["body"]
    push_data = rendered["push_data"]

    # Include source_route in push_data for audit trail continuity.
    if source_route:
        push_data = {**push_data, "source_route": source_route}

    # 2. Dedupe guard — skip if a non-suppressed event for the same
    #    (name, recipient, object) was already sent within the dedupe window.
    #    NOT_IMPLEMENTED rows are excluded from dedupe by is_duplicate_event().
    if is_duplicate_event(spec.event_name, recipient_user_id, entity_type, entity_id):
        try:
            create_message_event(
                event_name=spec.event_name,
                category=spec.category,
                actor_user_id=actor_user_id,
                recipient_user_id=recipient_user_id,
                object_type=entity_type,
                object_id=entity_id,
                channel=Channel.PUSH,
                provider=Provider.ONESIGNAL,
                payload_json=push_data,
                message_title=title,
                message_body=body,
                delivery_status=DeliveryStatus.SKIPPED,
                suppression_reason=SuppressionReason.DUPLICATE_EVENT,
            )
        except Exception as _e:
            current_app.logger.warning(
                "[MessageDispatch] _dispatch_immediate_push: dedupe MEL write failed: %s", _e,
            )
        return

    # 3. Send — opt-out filter (push_notifications_enabled) is handled inside.
    try:
        result = send_onesignal_push(
            user_ids=[recipient_user_id],
            title=title,
            body=body,
            data=push_data or None,
        )
    except Exception as _send_err:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_immediate_push: send_onesignal_push raised: %s",
            _send_err,
        )
        result = {"success": False, "provider_message_id": None,
                  "skipped": False, "error": f"send_raised: {_send_err}"}

    # 4. Map result → delivery outcome.
    _skipped = result.get("skipped", False)
    _success = bool(result.get("success")) and not _skipped

    if _success:
        _status              = DeliveryStatus.SENT
        _suppression         = None
        _error               = None
        _provider_message_id = result.get("provider_message_id")
        _sent_at             = datetime.utcnow()
    elif _skipped:
        _status              = DeliveryStatus.SKIPPED
        # Distinguish permanent channel gap (external_id not in OneSignal)
        # from a user preference opt-out.  send_onesignal_push sets
        # skipped_reason="channel_unavailable" when OneSignal returns
        # invalid_aliases; everything else keeps USER_OPTED_OUT.
        _suppression = (
            SuppressionReason.CHANNEL_UNAVAILABLE
            if result.get("skipped_reason") == "channel_unavailable"
            else SuppressionReason.USER_OPTED_OUT
        )
        _error               = None
        _provider_message_id = None
        _sent_at             = None
    else:
        _status              = DeliveryStatus.FAILED
        _suppression         = None
        _error               = result.get("error") or "unknown_onesignal_error"
        _provider_message_id = None
        _sent_at             = None

    # 5. MEL audit write — canonical record of actual delivery outcome.
    #    Phase D-1: provider_message_id and sent_at are written on SENT rows only;
    #    both are None for SKIPPED and FAILED. processed_at is set internally by
    #    create_message_event() for all rows.
    try:
        create_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=Channel.PUSH,
            provider=Provider.ONESIGNAL,
            payload_json=push_data,
            message_title=title,
            message_body=body,
            delivery_status=_status,
            suppression_reason=_suppression,
            error_message=_error,
            provider_message_id=_provider_message_id,
            sent_at=_sent_at,
        )
    except Exception as _e:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_immediate_push: MEL audit write failed: %s", _e,
        )


def _dispatch_automation_event(spec, actor_user_id, recipient_user_id,
                               entity_type, entity_id, metadata, source_route):
    """Execute the AUTOMATION_EVENT delivery path.

    Emits a signal into the external automation platform (currently OneSignal
    Journeys via the Custom Events API). The platform decides if, when, and
    how to communicate with the user.

    ┌─────────────────────────────────────────────────────────────────────┐
    │  IMPORTANT: delivery_status=sent in the MEL row for this strategy   │
    │  means "the automation signal was emitted successfully."             │
    │  It does NOT mean "a notification was delivered to the user."        │
    │  The downstream automation platform controls whether communication   │
    │  happens, when it happens, and which channel it uses.                │
    └─────────────────────────────────────────────────────────────────────┘

    Opt-out: honors push_notifications_enabled for now (Phase A/B default).
    Automation events bypass push dedupe (bypass_dedupe=True on their specs).
    If the automation platform changes, only this function and push_providers.py
    need updating — DeliveryStrategy.AUTOMATION_EVENT and the registry are stable.
    """
    from services.push_providers import send_onesignal_custom_event
    from models import db, User

    if not spec.automation_event_name:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_automation_event: automation_event_name "
            "not configured for event=%s — writing NOT_IMPLEMENTED row",
            spec.event_name,
        )
        try:
            create_message_event(
                event_name=spec.event_name,
                category=spec.category,
                actor_user_id=actor_user_id,
                recipient_user_id=recipient_user_id,
                object_type=entity_type,
                object_id=entity_id,
                channel=Channel.PUSH,
                provider=Provider.ONESIGNAL_JOURNEY,
                payload_json={"source_route": source_route or ""},
                delivery_status=DeliveryStatus.SKIPPED,
                suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
            )
        except Exception as _mel_err:
            current_app.logger.warning(
                "[MessageDispatch] _dispatch_automation_event: MEL write failed: %s", _mel_err,
            )
        return

    # Opt-out check — honor push_notifications_enabled (Phase A/B default).
    # Note: if Journeys later send email-only, a separate preference will be
    # needed. For now, opt-out of push = opt-out of automation signals.
    try:
        user = db.session.get(User, recipient_user_id)
        if user and user.push_notifications_enabled is False:
            current_app.logger.warning(
                "[MessageDispatch] automation_event: recipient_id=%d opted out — skipping signal",
                recipient_user_id,
            )
            try:
                create_message_event(
                    event_name=spec.event_name,
                    category=spec.category,
                    actor_user_id=actor_user_id,
                    recipient_user_id=recipient_user_id,
                    object_type=entity_type,
                    object_id=entity_id,
                    channel=Channel.PUSH,
                    provider=Provider.ONESIGNAL_JOURNEY,
                    payload_json={"source_route": source_route or ""},
                    delivery_status=DeliveryStatus.SKIPPED,
                    suppression_reason=SuppressionReason.USER_OPTED_OUT,
                )
            except Exception as _mel_err:
                current_app.logger.warning(
                    "[MessageDispatch] automation_event opt-out MEL write failed: %s", _mel_err,
                )
            return
    except Exception as _user_err:
        current_app.logger.warning(
            "[MessageDispatch] automation_event: opt-out check failed (%s) — proceeding",
            _user_err,
        )

    # Build properties forwarded to the automation platform.
    meta       = metadata or {}
    properties = {k: v for k, v in meta.items() if k in (spec.data_keys or [])}
    if actor_user_id:
        properties.setdefault("actor_user_id", actor_user_id)
    if source_route:
        properties["source_route"] = source_route

    # Emit the automation signal.
    try:
        result = send_onesignal_custom_event(
            user_ids=[recipient_user_id],
            event_name=spec.automation_event_name,
            properties=properties,
        )
    except Exception as _send_err:
        current_app.logger.warning(
            "[MessageDispatch] automation_event: send_onesignal_custom_event raised: %s",
            _send_err,
        )
        result = {"success": False, "sent": 0, "failed": 1}

    # Map result → delivery status and write MEL audit row.
    # Reminder: sent = signal emitted, NOT notification delivered.
    _success = result.get("success", False)
    _status      = DeliveryStatus.SENT  if _success else DeliveryStatus.FAILED
    _error       = None                 if _success else f"sent={result.get('sent',0)} failed={result.get('failed',0)}"

    try:
        create_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=Channel.PUSH,
            provider=Provider.ONESIGNAL_JOURNEY,
            payload_json={
                "automation_event_name": spec.automation_event_name,
                "properties": properties,
                "source_route": source_route or "",
            },
            delivery_status=_status,
            error_message=_error,
        )
    except Exception as _mel_err:
        current_app.logger.warning(
            "[MessageDispatch] automation_event MEL write failed: %s", _mel_err,
        )


def _dispatch_silent(spec, actor_user_id, recipient_user_id,
                     entity_type, entity_id, metadata, source_route):
    """Execute the SILENT delivery path.

    Records the event in the MEL audit trail. No delivery attempt is made.
    The decision not to communicate is itself a traceable product decision —
    every emission of a SILENT event produces exactly one MEL row.
    """
    meta = metadata or {}
    try:
        create_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=None,
            payload_json={**{k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, type(None)))},
                          "source_route": source_route or ""},
            delivery_status=DeliveryStatus.SKIPPED,
            suppression_reason=SuppressionReason.SILENT_BY_DESIGN,
        )
    except Exception as _e:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_silent: MEL write failed for event=%s: %s",
            spec.event_name, _e,
        )


def _dispatch_not_implemented(event_name, actor_user_id, recipient_user_id,
                              entity_type, entity_id, source_route):
    """Safe fallback for unknown or unregistered event names.

    Writes a NOT_IMPLEMENTED MEL row and logs a warning. Never raises.
    Callers should add the event to _EVENT_REGISTRY to resolve this.
    """
    current_app.logger.warning(
        "[MessageDispatch] emit_messaging_event: unregistered event_name=%r — "
        "writing NOT_IMPLEMENTED MEL row. Add to _EVENT_REGISTRY to resolve.",
        event_name,
    )
    try:
        create_message_event(
            event_name=str(event_name),
            category=Category.SYSTEM,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=None,
            payload_json={"source_route": source_route or ""},
            delivery_status=DeliveryStatus.SKIPPED,
            suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
        )
    except Exception as _e:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_not_implemented: MEL write failed: %s", _e,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def emit_messaging_event(
    event_name,
    actor_user_id,
    recipient_user_id,
    entity_type=None,
    entity_id=None,
    metadata=None,
    source_route=None,
):
    """Emit a standardized product messaging event.

    This is the single entry point for all product messaging. Routes call
    this function with intent. This layer decides execution strategy.

    The orchestration switch reads spec.delivery_strategy only. It has no
    knowledge of providers, channels, HTTP APIs, or vendor details.

    Args:
        event_name:        str — must be an EventName constant.
        actor_user_id:     int — user who caused the event (sender, inviter, etc.).
        recipient_user_id: int — user who should potentially receive communication.
        entity_type:       str | None — object context (e.g. "trip", "user").
        entity_id:         int | None — object ID context.
        metadata:          dict | None — extra context: title, body, push_data,
                           and any keys listed in EventSpec.data_keys.
                           Phase A: title/body must be in metadata for push events.
                           Phase C: title/body will be rendered from spec templates.
        source_route:      str | None — calling route name for audit trail.

    Returns:
        None. Never raises. All exceptions are caught internally.

    MEL guarantee:
        Every call produces exactly one MessageEventLog row (Phase A/B).
        IMMEDIATE_PUSH_AND_AUTOMATION produces two rows (Phase C, not yet active).
    """
    try:
        spec = _get_event_spec(event_name)

        if spec is None:
            _dispatch_not_implemented(
                event_name, actor_user_id, recipient_user_id,
                entity_type, entity_id, source_route,
            )
            return

        current_app.logger.debug(
            "[MESSAGE_DISPATCH] event=%s strategy=%s actor=%s recipient=%s",
            event_name, spec.delivery_strategy, actor_user_id, recipient_user_id,
        )

        if spec.delivery_strategy == DeliveryStrategy.IMMEDIATE_PUSH:
            _dispatch_immediate_push(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )

        elif spec.delivery_strategy == DeliveryStrategy.AUTOMATION_EVENT:
            _dispatch_automation_event(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )

        elif spec.delivery_strategy == DeliveryStrategy.IMMEDIATE_PUSH_AND_AUTOMATION:
            # Phase C: produces two MEL rows (one per channel/provider).
            # Not active in Phase A/B — no EventSpec uses this strategy yet.
            _dispatch_immediate_push(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )
            _dispatch_automation_event(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )

        elif spec.delivery_strategy == DeliveryStrategy.SILENT:
            _dispatch_silent(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )

        else:
            # Unknown strategy — treat as not implemented.
            current_app.logger.warning(
                "[MessageDispatch] unknown delivery_strategy=%r for event=%s",
                spec.delivery_strategy, event_name,
            )
            _dispatch_not_implemented(
                event_name, actor_user_id, recipient_user_id,
                entity_type, entity_id, source_route,
            )

    except Exception as _top_err:
        # Absolute safety net — emit_messaging_event must never raise.
        current_app.logger.warning(
            "[MessageDispatch] emit_messaging_event: unhandled exception for "
            "event=%s: %s", event_name, _top_err,
        )
