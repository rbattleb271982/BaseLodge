"""
BaseLodge Centralized Messaging Orchestration Layer — Phase A.

This module is the single entry point for all product messaging events.
Routes call emit_messaging_event() with intent. This layer decides execution.

Architecture contract:
    - The orchestration switch reads ONLY spec.delivery_strategy.
    - The orchestration layer has NO knowledge of OneSignal, APNs, FCM,
      HTTP payloads, or any vendor-specific details.
    - Provider knowledge lives exclusively inside dispatch functions, which
      call services/push_providers.py.
    - Every emit_messaging_event() call produces exactly one MEL row
      (one per dispatch function in Phase A; two rows for
      IMMEDIATE_PUSH_AND_AUTOMATION in Phase C).
    - This function never raises. All exceptions are caught internally.

Phase A status:
    _dispatch_immediate_push() wraps _notify_push() from app.py.
    Full internalization of delivery logic is deferred to Phase C.
    _dispatch_automation_event() is fully implemented here.

Public API:
    emit_messaging_event(event_name, actor_user_id, recipient_user_id,
                         entity_type, entity_id, metadata, source_route)
"""

from dataclasses import dataclass, field

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
        bypass_dedupe=False,
        email_eligible=False,
        # Phase C: title_template="{actor_name} wants to connect"
        # Phase C: body_template="You have a new friend request on BaseLodge."
        # Phase C: data_keys=["user_id", "invitation_id"]
    ),

    EventName.FRIEND_REQUEST_ACCEPTED: EventSpec(
        event_name=EventName.FRIEND_REQUEST_ACCEPTED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        bypass_dedupe=False,
        email_eligible=False,
        # Phase C: title_template="{actor_name} accepted your request"
        # Phase C: body_template="You're now connected on BaseLodge."
        # Phase C: data_keys=["user_id"]
    ),

    EventName.TRIP_INVITE_CREATED: EventSpec(
        event_name=EventName.TRIP_INVITE_CREATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        bypass_dedupe=False,
        email_eligible=False,
        # Phase C: title_template="{actor_name} invited you to a trip"
        # Phase C: body_template="You've been invited to {resort}."
        # Phase C: data_keys=["trip_id", "deep_link", "screen"]
    ),

    EventName.TRIP_INVITE_ACCEPTED: EventSpec(
        event_name=EventName.TRIP_INVITE_ACCEPTED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        bypass_dedupe=False,
        email_eligible=False,
        # Phase C: title_template="{actor_name} accepted your invite"
        # Phase C: body_template="They're joining you for {resort}."
        # Phase C: data_keys=["trip_id", "deep_link", "screen"]
    ),

    # ── Automation event (active — currently unlogged friend.pass.changed path) ──

    EventName.FRIEND_PASS_CHANGED: EventSpec(
        event_name=EventName.FRIEND_PASS_CHANGED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.AUTOMATION_EVENT,
        automation_event_name="friend_pass_changed",  # OneSignal Custom Event name
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
# Dispatch functions — one per delivery strategy branch
# Each dispatch fn is the ONLY place that knows how to execute its strategy.
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_immediate_push(spec, actor_user_id, recipient_user_id,
                             entity_type, entity_id, metadata, source_route):
    """Execute the IMMEDIATE_PUSH delivery path.

    Phase A: delegates to _notify_push() in app.py, preserving all existing
    behavior — dedupe, opt-out filtering, OneSignal delivery, MEL logging.

    Phase C: _notify_push() will be retired and this function will contain
    the full delivery logic directly, using services/push_providers.py.

    The orchestration layer is not aware of this delegation detail.
    """
    # Phase A: import _notify_push lazily to avoid circular import.
    # app.py imports from services/*, so services/* must not import from app.py
    # at module load time. A function-level import is safe and is explicitly
    # the right pattern for Phase A's "shim" approach.
    try:
        import app as _app_module
        _notify_push = getattr(_app_module, "_notify_push")
    except Exception as _imp_err:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_immediate_push: could not import _notify_push: %s",
            _imp_err,
        )
        return

    meta = metadata or {}

    # Extract the fields _notify_push expects from metadata.
    # In Phase C these come from spec.title_template / spec.body_template rendering.
    title      = meta.get("title", "")
    body       = meta.get("body", "")
    push_data  = meta.get("push_data") or {}

    # Include source_route in push_data for audit trail continuity.
    if source_route:
        push_data = {**push_data, "source_route": source_route}

    try:
        _notify_push(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            title=title,
            body=body,
            data=push_data or None,
        )
    except Exception as _e:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_immediate_push: _notify_push raised: %s", _e,
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

        # TEMP PHASE B DEBUG LOGGING
        # Remove or downgrade to .debug() after Phase B stabilizes.
        current_app.logger.info(
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
