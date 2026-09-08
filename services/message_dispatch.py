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
from datetime import date, datetime
import hashlib
import os
import re
from string import Formatter

from flask import current_app

from models import (
    GuestStatus,
    Invitation,
    InviteType,
    InviteShareEvent,
    PushDeviceToken,
    Resort,
    SkiTrip,
    SkiTripLifecycleEvent,
    SkiTripParticipant,
    SkiTripPlanningPost,
    SkiTripRsvpTransition,
    User,
    UserSeasonPass,
    db,
)
from services.message_events import (
    claim_message_event,
    create_message_event,
    finalize_message_event,
    is_duplicate_event,
)
from services.messaging_constants import (
    Category,
    Channel,
    DeliveryStatus,
    DeliveryStrategy,
    EventName,
    Provider,
    SuppressionReason,
    is_opportunity_event,
)
from services.push_providers import send_onesignal_push
from services.message_outbox import (
    enqueue_message,
    mark_opportunity_provider_started,
    sanitize_error,
)
from services.pass_utils import format_passes_for_display, normalize_pass_selection
from services.visibility import is_reciprocal_friend


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


@dataclass(frozen=True)
class MessagingSafetyDecision:
    allowed: bool
    event_name: str
    occurrence_id: str | None
    recipient_user_id: int | None
    actor_user_id: int | None
    entity_type: str | None
    entity_id: int | None
    channel: str | None
    provider: str | None
    suppression_reason: str | None
    audit_metadata: dict


@dataclass(frozen=True)
class MessagingEmitResult:
    status: str
    mel_id: int | None = None
    occurrence_id: str | None = None
    suppression_reason: str | None = None
    provider_message_id: str | None = None
    error: str | None = None


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
        deep_link_template="/friends?requests=1",
        url_template="/friends?requests=1",
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

    # Generic push to other accepted participants when someone accepts
    EventName.TRIP_PARTICIPANT_ADDED: EventSpec(
        event_name=EventName.TRIP_PARTICIPANT_ADDED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Someone accepted an invitation",
        body_template="A new participant has been added to the {resort} trip.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    # Push to owner + remaining accepted participants when someone leaves
    EventName.TRIP_PARTICIPANT_LEFT: EventSpec(
        event_name=EventName.TRIP_PARTICIPANT_LEFT,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="A participant left the trip",
        body_template="A participant has left the {resort} trip.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    # Push to accepted+invited participants when trip is hard-deleted
    # url_template and deep_link_template both use /trips — original page is gone
    EventName.TRIP_CANCELLED: EventSpec(
        event_name=EventName.TRIP_CANCELLED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{resort} trip cancelled",
        body_template="The trip has been cancelled by the organizer.",
        deep_link_template="/trips",
        url_template="/trips",
        screen="trips",
        context_keys=["resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    # Trip update events — separate names prevent cross-event dedupe suppression
    # (a dates change and a resort change in the same hour must not suppress each other)
    EventName.TRIP_DATES_UPDATED: EventSpec(
        event_name=EventName.TRIP_DATES_UPDATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Trip updated from {actor_name}",
        body_template="The details of the {resort} trip have changed.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_RESORT_UPDATED: EventSpec(
        event_name=EventName.TRIP_RESORT_UPDATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Trip updated from {actor_name}",
        body_template="The details of the {resort} trip have changed.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_DETAILS_UPDATED: EventSpec(
        event_name=EventName.TRIP_DETAILS_UPDATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Trip updated from {actor_name}",
        body_template="The details of the {resort} trip have changed.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_ACCOMMODATION_UPDATED: EventSpec(
        event_name=EventName.TRIP_ACCOMMODATION_UPDATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Trip updated from {actor_name}",
        body_template="The details of the {resort} trip have changed.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_PLANNING_POST_CREATED: EventSpec(
        event_name=EventName.TRIP_PLANNING_POST_CREATED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} added a planning post",
        body_template="{actor_name} added a new planning post for {resort}.",
        deep_link_template="/trips/{entity_id}/planning",
        url_template="/trips/{entity_id}/planning",
        screen="trip_planning",
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
        context_keys=["actor_first_name", "new_pass", "new_pass_display"],
        bypass_dedupe=False,
        email_eligible=False,
        # Note: automation_event_name is the signal identifier sent to the
        # automation platform. If the platform changes, update this value
        # and the dispatch function. DeliveryStrategy.AUTOMATION_EVENT is unchanged.
    ),

    EventName.FRIEND_SUGGESTIONS_CREATED: EventSpec(
        event_name=EventName.FRIEND_SUGGESTIONS_CREATED,
        category=Category.FRIEND,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="New connection suggestions",
        body_template="{actor_name} suggested some people you may know. See who.",
        deep_link_template="/friends",
        url_template="/friends",
        screen="friends",
        context_keys=["actor_name", "suggestion_batch_id"],
        data_keys=["suggestion_batch_id"],
    ),

    EventName.FOUNDER_NEW_USER: EventSpec(
        event_name=EventName.FOUNDER_NEW_USER,
        category=Category.SYSTEM,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="New BaseLodge User 🎿",
        body_template="{alert_body}",
        deep_link_template="/admin/users",
        url_template="/admin/users",
        screen="admin_users",
        context_keys=["subject_user_id", "alert_body"],
        data_keys=["subject_user_id"],
    ),

    EventName.FOUNDER_APP_OPEN: EventSpec(
        event_name=EventName.FOUNDER_APP_OPEN,
        category=Category.SYSTEM,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="BaseLodge Opened",
        body_template="{alert_body}",
        deep_link_template="/admin/users",
        url_template="/admin/users",
        screen="admin_users",
        context_keys=[
            "subject_user_id",
            "alert_body",
            "app_open_occurrence",
        ],
        data_keys=["subject_user_id"],
    ),

    EventName.FOUNDER_INVITE_SHARE: EventSpec(
        event_name=EventName.FOUNDER_INVITE_SHARE,
        category=Category.SYSTEM,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="Invite Sent",
        body_template="{alert_body}",
        deep_link_template="/admin/users",
        url_template="/admin/users",
        screen="admin_users",
        context_keys=[
            "subject_user_id",
            "alert_body",
            "invite_share_event_id",
        ],
        data_keys=["subject_user_id", "invite_share_event_id"],
    ),

    EventName.PUSH_TEST_SENT: EventSpec(
        event_name=EventName.PUSH_TEST_SENT,
        category=Category.SYSTEM,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="BaseLodge",
        body_template="Test push from BaseLodge (OneSignal)",
        deep_link_template="/admin",
        url_template="/admin",
        screen="admin",
        bypass_dedupe=True,
    ),

    # ── Silent events (registered but produce MEL log rows only) ──
    # These are not wired to product routes yet. Registering them here ensures
    # emit_messaging_event() produces a well-formed MEL row if called,
    # rather than falling through to _dispatch_not_implemented().

    EventName.TRIP_INVITE_DECLINED: EventSpec(
        event_name=EventName.TRIP_INVITE_DECLINED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} declined your invite",
        body_template="They won't be participating in the {resort} trip.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
        bypass_dedupe=False,
        email_eligible=False,
    ),

    EventName.TRIP_JOIN_REQUESTED: EventSpec(
        event_name=EventName.TRIP_JOIN_REQUESTED,
        category=Category.TRIP,
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_name} wants to join your trip",
        body_template="They've requested to join your {resort} trip.",
        deep_link_template="/trips/{entity_id}",
        url_template="/trips",
        screen="trip_detail",
        context_keys=["actor_name", "resort", "trip_id"],
        data_keys=["trip_id"],
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
        delivery_strategy=DeliveryStrategy.IMMEDIATE_PUSH,
        title_template="{actor_first_name} added a trip",
        body_template=(
            "{actor_first_name} just added a trip to {resort}. Check it out."
        ),
        deep_link_template="/friend-trip/{entity_id}",
        url_template="/friend-trip/{entity_id}",
        context_keys=["actor_first_name", "resort", "trip_id"],
        data_keys=["trip_id"],
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


_TRIP_OWNER_EVENTS = frozenset({
    EventName.TRIP_INVITE_CREATED,
    EventName.TRIP_DATES_UPDATED,
    EventName.TRIP_RESORT_UPDATED,
    EventName.TRIP_DETAILS_UPDATED,
    EventName.TRIP_ACCOMMODATION_UPDATED,
})
_TRIP_MEMBER_TO_OWNER_EVENTS = frozenset({
    EventName.TRIP_INVITE_ACCEPTED,
    EventName.TRIP_INVITE_DECLINED,
})
_TRIP_MEMBER_TO_MEMBER_EVENTS = frozenset({
    EventName.TRIP_PARTICIPANT_ADDED,
    EventName.TRIP_PARTICIPANT_LEFT,
    EventName.TRIP_PLANNING_POST_CREATED,
})
_INTERNAL_PATH_RE = re.compile(
    r"^/(?:friends(?:/\d+)?(?:\?requests=1)?|friend-trip/[1-9][0-9]*|"
    r"trips(?:/\d+(?:/planning)?)?|"
    r"admin(?:/users)?)$"
)


def _audit_metadata(source_route, decision_reason=None):
    data = {}
    if source_route:
        data["source_route"] = str(source_route)[:120]
    if decision_reason:
        data["decision_reason"] = str(decision_reason)[:80]
    return data


def _template_fields(spec):
    fields = set()
    formatter = Formatter()
    for template in (
        spec.title_template,
        spec.body_template,
        spec.deep_link_template,
        spec.url_template,
    ):
        if not template:
            continue
        fields.update(
            field_name
            for _literal, field_name, _format_spec, _conversion
            in formatter.parse(template)
            if field_name
        )
    return fields


def _render_context(spec, metadata, actor_user_id, entity_id):
    meta = metadata if isinstance(metadata, dict) else {}
    context = {
        **{
            key: value
            for key, value in meta.items()
            if isinstance(value, (str, int, float, bool, type(None)))
        },
        "entity_id": entity_id,
        "actor_user_id": actor_user_id,
    }
    required = _template_fields(spec)
    if spec.delivery_strategy == DeliveryStrategy.AUTOMATION_EVENT:
        required |= set(spec.context_keys or [])
    missing = sorted(
        key
        for key in required
        if key not in context
        or context[key] is None
        or (isinstance(context[key], str) and not context[key].strip())
    )
    return context, missing


def _is_active_participant(participant):
    return bool(
        participant
        and participant.status in (GuestStatus.GOING, GuestStatus.INTERESTED)
    )


def _authorize_trip_event(
    spec,
    actor_user_id,
    recipient_user_id,
    trip,
    metadata,
):
    actor_participant = SkiTripParticipant.query.filter_by(
        trip_id=trip.id,
        user_id=actor_user_id,
    ).first()
    recipient_participant = SkiTripParticipant.query.filter_by(
        trip_id=trip.id,
        user_id=recipient_user_id,
    ).first()
    active_trip = (trip.lifecycle_state or "active") == "active"
    recipient_is_owner = trip.user_id == recipient_user_id
    recipient_is_active = _is_active_participant(recipient_participant)

    if spec.event_name == EventName.FRIEND_TRIP_CREATED:
        direct_invitation = Invitation.query.filter_by(
            trip_id=trip.id,
            sender_id=actor_user_id,
            receiver_id=recipient_user_id,
            invite_type=InviteType.OUTBOUND,
            status="pending",
        ).first()
        return bool(
            trip.user_id == actor_user_id
            and recipient_user_id != actor_user_id
            and trip.is_public is True
            and (trip.lifecycle_state or "active") == "active"
            and trip.start_date is not None
            and trip.end_date is not None
            and trip.end_date >= date.today()
            and is_reciprocal_friend(actor_user_id, recipient_user_id)
            and direct_invitation is None
            and not (
                recipient_participant
                and recipient_participant.status in (
                    GuestStatus.PENDING,
                    GuestStatus.INTERESTED,
                    GuestStatus.GOING,
                )
            )
        )

    if spec.event_name == EventName.TRIP_CANCELLED:
        lifecycle_event_id = (metadata or {}).get("lifecycle_event_id")
        lifecycle_event = (
            db.session.get(SkiTripLifecycleEvent, lifecycle_event_id)
            if isinstance(lifecycle_event_id, int)
            else None
        )
        return bool(
            trip.lifecycle_state == "cancelled"
            and trip.user_id == actor_user_id
            and recipient_is_active
            and lifecycle_event
            and lifecycle_event.trip_id == trip.id
            and lifecycle_event.actor_user_id == actor_user_id
            and lifecycle_event.event_type == "cancelled"
        )

    if not active_trip:
        return False

    if spec.event_name == EventName.TRIP_INVITE_CREATED:
        return bool(
            trip.user_id == actor_user_id
            and recipient_participant
            and recipient_participant.status == GuestStatus.PENDING
        )

    if spec.event_name in _TRIP_OWNER_EVENTS:
        return bool(
            trip.user_id == actor_user_id
            and (recipient_is_active or recipient_is_owner)
        )

    if spec.event_name in _TRIP_MEMBER_TO_OWNER_EVENTS:
        expected_statuses = (
            (GuestStatus.GOING, GuestStatus.INTERESTED)
            if spec.event_name == EventName.TRIP_INVITE_ACCEPTED
            else (GuestStatus.DECLINED,)
        )
        return bool(
            recipient_is_owner
            and actor_participant
            and actor_participant.status in expected_statuses
        )

    if spec.event_name == EventName.TRIP_PARTICIPANT_ADDED:
        return bool(
            _is_active_participant(actor_participant)
            and (recipient_is_active or recipient_is_owner)
        )

    if spec.event_name == EventName.TRIP_PARTICIPANT_LEFT:
        return bool(
            actor_participant
            and actor_participant.status in (
                GuestStatus.DECLINED,
                GuestStatus.REMOVED,
            )
            and (recipient_is_active or recipient_is_owner)
        )

    if spec.event_name == EventName.TRIP_PLANNING_POST_CREATED:
        post_id = (metadata or {}).get("planning_post_id")
        post = (
            db.session.get(SkiTripPlanningPost, post_id)
            if isinstance(post_id, int)
            else None
        )
        return bool(
            _is_active_participant(actor_participant)
            and (recipient_is_active or recipient_is_owner)
            and post
            and post.trip_id == trip.id
            and post.user_id == actor_user_id
        )

    if spec.event_name == EventName.TRIP_JOIN_REQUESTED:
        invitation_id = (metadata or {}).get("invitation_id")
        invitation = (
            db.session.get(Invitation, invitation_id)
            if isinstance(invitation_id, int)
            else None
        )
        return bool(
            recipient_is_owner
            and invitation
            and invitation.trip_id == trip.id
            and invitation.sender_id == actor_user_id
            and invitation.receiver_id == recipient_user_id
            and invitation.invite_type == InviteType.REQUEST
            and invitation.status == "pending"
        )

    return False


def _privacy_allowed(
    spec,
    actor_user_id,
    recipient_user_id,
    entity_type,
    entity_id,
    metadata,
):
    admin_emails = {
        email.strip().lower()
        for email in os.environ.get("ALLOWED_ADMIN_EMAILS", "").split(",")
        if email.strip()
    }
    if spec.event_name in {
        EventName.FOUNDER_NEW_USER,
        EventName.FOUNDER_APP_OPEN,
        EventName.FOUNDER_INVITE_SHARE,
    }:
        recipient = db.session.get(User, recipient_user_id)
        return bool(
            recipient
            and recipient.email.lower() == "richardbattlebaxter@gmail.com"
            and recipient.email.lower() in admin_emails
        )

    if spec.event_name == EventName.PUSH_TEST_SENT:
        recipient = db.session.get(User, recipient_user_id)
        return bool(
            recipient
            and recipient.email.lower() in admin_emails
        )

    if spec.event_name == EventName.FRIEND_REQUEST_CREATED:
        invitation_id = (metadata or {}).get("invitation_id")
        invitation = (
            db.session.get(Invitation, invitation_id)
            if isinstance(invitation_id, int)
            else None
        )
        return bool(
            invitation
            and invitation.trip_id is None
            and invitation.sender_id == actor_user_id
            and invitation.receiver_id == recipient_user_id
            and invitation.status == "pending"
        )

    if spec.event_name == EventName.FRIEND_REQUEST_ACCEPTED:
        invitation_id = (metadata or {}).get("invitation_id")
        invitation = (
            db.session.get(Invitation, invitation_id)
            if isinstance(invitation_id, int)
            else None
        )
        return bool(
            invitation
            and invitation.trip_id is None
            and invitation.sender_id == recipient_user_id
            and invitation.receiver_id == actor_user_id
            and invitation.status == "accepted"
            and is_reciprocal_friend(actor_user_id, recipient_user_id)
        )

    if spec.event_name in {
        EventName.FRIEND_PASS_CHANGED,
        EventName.FRIEND_SUGGESTIONS_CREATED,
    }:
        return is_reciprocal_friend(actor_user_id, recipient_user_id)

    if entity_type == "trip" and isinstance(entity_id, int):
        trip = db.session.get(SkiTrip, entity_id)
        return bool(
            trip
            and _authorize_trip_event(
                spec,
                actor_user_id,
                recipient_user_id,
                trip,
                metadata,
            )
        )

    return spec.delivery_strategy == DeliveryStrategy.SILENT


def _provider_for_spec(spec):
    if is_opportunity_event(spec.event_name):
        return Provider.ONESIGNAL
    if spec.delivery_strategy == DeliveryStrategy.AUTOMATION_EVENT:
        return Provider.ONESIGNAL_JOURNEY
    if spec.delivery_strategy == DeliveryStrategy.SILENT:
        return None
    return Provider.ONESIGNAL


def evaluate_message_safety(
    spec,
    actor_user_id,
    recipient_user_id,
    entity_type,
    entity_id,
    metadata,
    source_route,
    occurrence_id=None,
):
    """Return the canonical fail-closed pre-send decision."""
    channel = (
        None if spec.delivery_strategy == DeliveryStrategy.SILENT
        else Channel.PUSH
    )
    provider = _provider_for_spec(spec)
    audit = _audit_metadata(source_route)

    if (
        is_opportunity_event(spec.event_name)
        and spec.event_name != EventName.FRIEND_TRIP_CREATED
    ):
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, Channel.PUSH, provider,
            SuppressionReason.NOT_IMPLEMENTED,
            _audit_metadata(source_route, "opportunity_authorization_incomplete"),
        )

    if spec.delivery_strategy == DeliveryStrategy.SILENT:
        return MessagingSafetyDecision(
            True, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider, None, audit,
        )

    runtime = (
        os.environ.get("BASELODGE_RUNTIME_ENV")
        or ("test" if current_app.config.get("TESTING") else "development")
    ).lower()
    if runtime not in {"development", "test", "testing", "production"}:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.ENVIRONMENT_BLOCKED,
            _audit_metadata(source_route, "invalid_runtime"),
        )

    if not isinstance(recipient_user_id, int):
        reason = SuppressionReason.INVALID_RECIPIENT
    else:
        try:
            recipient = db.session.get(User, recipient_user_id)
        except Exception:
            recipient = None
            reason = SuppressionReason.INVALID_RECIPIENT
        else:
            reason = None if recipient is not None else SuppressionReason.INVALID_RECIPIENT
    if reason:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider, reason,
            _audit_metadata(source_route, "recipient_lookup"),
        )

    try:
        actor_exists = (
            isinstance(actor_user_id, int)
            and db.session.get(User, actor_user_id) is not None
        )
    except Exception:
        actor_exists = False
    if not actor_exists:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.PRIVACY_DENIED,
            _audit_metadata(source_route, "actor_lookup"),
        )

    if (
        actor_user_id == recipient_user_id
        and spec.event_name != EventName.PUSH_TEST_SENT
    ):
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.SENDER_IS_RECIPIENT,
            _audit_metadata(source_route, "self_send"),
        )

    try:
        preference_enabled = recipient.push_notifications_enabled is True
    except Exception:
        preference_enabled = False
    if not preference_enabled:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.USER_OPTED_OUT,
            _audit_metadata(source_route, "push_preference"),
        )

    try:
        privacy_allowed = _privacy_allowed(
            spec,
            actor_user_id,
            recipient_user_id,
            entity_type,
            entity_id,
            metadata,
        )
    except Exception:
        privacy_allowed = False
    if not privacy_allowed:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.PRIVACY_DENIED,
            _audit_metadata(source_route, "content_access"),
        )

    _context, missing = _render_context(
        spec,
        metadata,
        actor_user_id,
        entity_id,
    )
    if missing:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            SuppressionReason.MISSING_REQUIRED_PAYLOAD,
            _audit_metadata(source_route, "render_context"),
        )

    channel_lookup_failed = False
    try:
        has_channel = db.session.query(PushDeviceToken.id).filter(
            PushDeviceToken.user_id == recipient_user_id,
            PushDeviceToken.active == True,  # noqa: E712
        ).first() is not None
    except Exception:
        has_channel = False
        channel_lookup_failed = True
    if not has_channel:
        return MessagingSafetyDecision(
            False, spec.event_name, occurrence_id, recipient_user_id,
            actor_user_id, entity_type, entity_id, channel, provider,
            (
                SuppressionReason.RECIPIENT_INELIGIBLE
                if channel_lookup_failed
                else SuppressionReason.NO_DEVICE_TOKEN
            ),
            _audit_metadata(source_route, "channel_lookup"),
        )

    return MessagingSafetyDecision(
        True, spec.event_name, occurrence_id, recipient_user_id,
        actor_user_id, entity_type, entity_id, channel, provider, None, audit,
    )


def _normalized_occurrence_id(value):
    if value is None:
        return None
    value = str(value)
    if len(value) <= 191:
        return value
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def messaging_delivery_mode():
    """Return the deployment-wide delivery family without changing config.

    MESSAGE_DELIVERY_MODE is deliberately read at the edge rather than adding a
    Production config default.  Development/test installations queue by
    default, while a production installation retains its existing inline
    behavior unless it explicitly opts into the durable worker.
    """
    configured = (
        current_app.config.get("MESSAGE_DELIVERY_MODE")
        or os.environ.get("MESSAGE_DELIVERY_MODE")
    )
    if configured:
        mode = str(configured).strip().lower()
        if mode in {"inline", "enqueue_only"}:
            return mode
    runtime = (
        os.environ.get("BASELODGE_RUNTIME_ENV")
        or ("test" if current_app.config.get("TESTING") else "development")
    ).lower()
    return "inline" if runtime == "production" else "enqueue_only"


def messaging_uses_outbox():
    """Whether normal delivery callers should use the durable outbox."""
    return messaging_delivery_mode() == "enqueue_only"


def _outbox_evidence_ids(metadata):
    """Extract identifiers only; never retain route-provided copy or identities."""
    meta = metadata if isinstance(metadata, dict) else {}
    keys = (
        "invitation_id", "planning_post_id", "lifecycle_event_id",
        "suggestion_batch_id", "subject_user_id", "invite_share_event_id",
        "resort_id", "rsvp_transition_id",
    )
    return [
        f"{key}:{meta[key]}"
        for key in keys
        if isinstance(meta.get(key), int)
    ]


def enqueue_messaging_event(
    event_name,
    actor_user_id,
    recipient_user_id,
    entity_type=None,
    entity_id=None,
    metadata=None,
    source_route=None,
    occurrence_id=None,
    *,
    session=None,
    configuration_epoch=1,
    activation_boundary=None,
    opportunity_policy_decision=None,
    producer_release_sha=None,
):
    """Transaction-neutral durable enqueue API.

    This intentionally stores no rendered content or caller metadata.  The
    worker re-reads authoritative records immediately before safety evaluation
    and rendering.  Callers must commit (or roll back) their own business
    transaction after this function returns.
    """
    spec = _get_event_spec(event_name)
    if (
        spec is None
        or (
            spec.delivery_strategy == DeliveryStrategy.SILENT
            and not is_opportunity_event(event_name)
        )
    ):
        raise ValueError("event is not a deliverable registered messaging event")
    occurrence_id = _normalized_occurrence_id(
        occurrence_id or _derive_occurrence_id(
            spec, actor_user_id, recipient_user_id, entity_type, entity_id, metadata,
        )
    )
    if not occurrence_id:
        raise ValueError("enqueue_messaging_event requires an occurrence identity")
    if is_opportunity_event(event_name):
        if opportunity_policy_decision is not None:
            decision = opportunity_policy_decision
            work_session = session if session is not None else db.session
            actual_session = (
                work_session()
                if callable(work_session)
                and not hasattr(work_session, "get_transaction")
                else work_session
            )
            current_scope = (
                actual_session.get_nested_transaction()
                or actual_session.get_transaction()
            )
            acquisition_scope = getattr(decision, "transaction", None)
            scope = current_scope
            scope_is_current = False
            while scope is not None:
                if scope is acquisition_scope:
                    scope_is_current = True
                    break
                scope = getattr(
                    scope, "parent", getattr(scope, "_parent", None)
                )
            valid_boundary = (
                getattr(decision, "event_name", None) == event_name
                and getattr(decision, "eligible", False) is True
                and getattr(decision, "cutover_epoch", None)
                == configuration_epoch
                and getattr(decision, "activation_boundary", None)
                == activation_boundary
                and acquisition_scope is not None
                and acquisition_scope.is_active
                and scope_is_current
            )
        else:
            from services.opportunity_messaging import (
                lock_opportunity_policy_decisions,
            )

            decision = lock_opportunity_policy_decisions(
                (event_name,), session=session
            )[event_name]
            valid_boundary = (
                activation_boundary is not None
                and decision.eligible
                and decision.activation_boundary == activation_boundary
                and decision.cutover_epoch == configuration_epoch
            )
        if not valid_boundary:
            raise ValueError(
                "opportunity enqueue requires its audited activation boundary"
            )
    provider = _provider_for_spec(spec)
    if provider is None:
        raise ValueError("event has no provider")
    if not isinstance(actor_user_id, int) or not isinstance(recipient_user_id, int):
        raise ValueError("enqueue_messaging_event requires integer actor and recipient IDs")
    if entity_type is not None and entity_type not in {"trip", "user"}:
        raise ValueError("enqueue_messaging_event requires a safe entity type")
    if entity_id is not None and not isinstance(entity_id, int):
        raise ValueError("enqueue_messaging_event entity_id must be an integer")
    # These are allowlisted by message_outbox and are selectors, not content.
    context = {
        "template": "enqueue_only",
        "object_type": str(entity_type)[:80] if entity_type else None,
        "object_id": entity_id if isinstance(entity_id, int) else None,
    }
    return enqueue_message(
        event_name=spec.event_name,
        category=spec.category,
        occurrence_id=occurrence_id,
        recipient_user_id=recipient_user_id,
        channel=Channel.PUSH,
        provider=provider,
        context=context,
        evidence_ids=_outbox_evidence_ids(metadata),
        actor_user_id=actor_user_id,
        object_type=entity_type,
        object_id=entity_id,
        configuration_epoch=configuration_epoch,
        producer_release_sha=producer_release_sha,
        session=session,
    )


def _derive_occurrence_id(
    spec,
    actor_user_id,
    recipient_user_id,
    entity_type,
    entity_id,
    metadata,
):
    meta = metadata if isinstance(metadata, dict) else {}
    explicit = meta.get("occurrence_id")
    if explicit:
        return _normalized_occurrence_id(explicit)

    if spec.event_name in {
        EventName.FRIEND_REQUEST_CREATED,
        EventName.FRIEND_REQUEST_ACCEPTED,
        EventName.TRIP_JOIN_REQUESTED,
    } and meta.get("invitation_id"):
        return f"{spec.event_name}:invitation:{meta['invitation_id']}"

    if spec.event_name == EventName.TRIP_PLANNING_POST_CREATED and meta.get(
        "planning_post_id"
    ):
        return f"{spec.event_name}:post:{meta['planning_post_id']}"

    if spec.event_name == EventName.TRIP_CANCELLED and meta.get(
        "lifecycle_event_id"
    ):
        return f"{spec.event_name}:lifecycle:{meta['lifecycle_event_id']}"

    if spec.event_name in {
        EventName.TRIP_INVITE_CREATED,
        EventName.TRIP_INVITE_ACCEPTED,
        EventName.TRIP_INVITE_DECLINED,
        EventName.TRIP_PARTICIPANT_ADDED,
        EventName.TRIP_PARTICIPANT_LEFT,
    } and isinstance(entity_id, int):
        subject_user_id = (
            recipient_user_id
            if spec.event_name == EventName.TRIP_INVITE_CREATED
            else actor_user_id
        )
        transition = (
            SkiTripRsvpTransition.query.filter_by(
                trip_id=entity_id,
                user_id=subject_user_id,
            )
            .order_by(SkiTripRsvpTransition.id.desc())
            .first()
        )
        if transition:
            return f"{spec.event_name}:rsvp:{transition.id}"

    if spec.event_name in {
        EventName.TRIP_DATES_UPDATED,
        EventName.TRIP_RESORT_UPDATED,
        EventName.TRIP_DETAILS_UPDATED,
        EventName.TRIP_ACCOMMODATION_UPDATED,
    } and isinstance(entity_id, int):
        trip = db.session.get(SkiTrip, entity_id)
        if trip and trip.updated_at:
            return (
                f"{spec.event_name}:trip:{entity_id}:"
                f"{trip.updated_at.isoformat()}"
            )

    if spec.event_name == EventName.FRIEND_PASS_CHANGED:
        actor = db.session.get(User, actor_user_id)
        if actor and actor.updated_at:
            return (
                f"{spec.event_name}:user:{actor_user_id}:"
                f"{actor.updated_at.isoformat()}"
            )

    if spec.event_name == EventName.FRIEND_SUGGESTIONS_CREATED and meta.get(
        "suggestion_batch_id"
    ):
        return (
            f"{spec.event_name}:batch:{meta['suggestion_batch_id']}"
        )

    if spec.event_name == EventName.FOUNDER_NEW_USER and meta.get(
        "subject_user_id"
    ):
        return f"{spec.event_name}:user:{meta['subject_user_id']}"

    if spec.event_name == EventName.FOUNDER_APP_OPEN and meta.get(
        "app_open_occurrence"
    ):
        return (
            f"{spec.event_name}:user:{meta.get('subject_user_id')}:"
            f"{meta['app_open_occurrence']}"
        )

    if spec.event_name == EventName.FOUNDER_INVITE_SHARE and meta.get(
        "invite_share_event_id"
    ):
        return (
            f"{spec.event_name}:share:{meta['invite_share_event_id']}"
        )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers — Phase C
# ─────────────────────────────────────────────────────────────────────────────

class _SafeFormatMap(dict):
    """Defensive formatter used only after required fields are validated."""
    def __init__(self, data, event_name=""):
        super().__init__(data)
        self._event_name = event_name

    def __missing__(self, key):
        current_app.logger.warning(
            "[MessageDispatch] _render_immediate_push: template key %r missing "
            "for event=%s after validation",
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


def _rendered_links_are_safe(rendered):
    for key in ("deep_link", "url"):
        value = (rendered.get("push_data") or {}).get(key)
        if value is not None and (
            not isinstance(value, str)
            or not value.startswith("/")
            or value.startswith("//")
            or _INTERNAL_PATH_RE.fullmatch(value) is None
        ):
            return False
    return True


def _outbox_evidence_value(row, kind):
    """Read a typed identifier from an outbox evidence list."""
    prefix = f"{kind}:"
    for value in row.evidence_ids_json or []:
        if isinstance(value, str) and value.startswith(prefix):
            try:
                return int(value[len(prefix):])
            except ValueError:
                return None
    return None


def _outbox_render_metadata(row, spec):
    """Rebuild render inputs from authoritative records, never outbox copy."""
    metadata = {}
    actor = db.session.get(User, row.actor_user_id) if row.actor_user_id else None
    if actor:
        metadata["actor_name"] = actor.first_name
        metadata["actor_first_name"] = actor.first_name
        if spec.event_name == EventName.FRIEND_PASS_CHANGED:
            # This event's Journey properties are regenerated from durable
            # ownership state, never caller metadata or rendered outbox copy.
            pass_value = normalize_pass_selection(actor.pass_type)
            if not pass_value:
                historic = (
                    UserSeasonPass.query.filter_by(user_id=actor.id)
                    .order_by(
                        UserSeasonPass.season_start_year.desc(),
                        UserSeasonPass.updated_at.desc(),
                    ).first()
                )
                pass_value = normalize_pass_selection(
                    historic.pass_type if historic is not None else ""
                )
            metadata["new_pass"] = pass_value
            metadata["new_pass_display"] = format_passes_for_display(pass_value)
    if isinstance(row.object_id, int) and row.object_type == "trip":
        trip = db.session.get(SkiTrip, row.object_id)
        if trip:
            metadata["trip_id"] = trip.id
            resort = (
                db.session.get(Resort, trip.resort_id)
                if isinstance(trip.resort_id, int)
                else None
            )
            resort_name = (
                resort.name.strip()
                if resort and isinstance(resort.name, str) and resort.name.strip()
                else (
                    trip.mountain.strip()
                    if isinstance(trip.mountain, str) and trip.mountain.strip()
                    else None
                )
            )
            if resort_name:
                metadata["resort"] = resort_name
    for key in (
        "invitation_id", "planning_post_id", "lifecycle_event_id",
        "suggestion_batch_id", "subject_user_id", "invite_share_event_id",
        "resort_id", "rsvp_transition_id",
    ):
        value = _outbox_evidence_value(row, key)
        if value is not None:
            metadata[key] = value

    # Founder templates historically accepted caller-owned alert text.  The
    # outbox deliberately never retains it; use fixed safe copy and validate
    # the referenced share record where applicable.
    if spec.event_name == EventName.FOUNDER_NEW_USER:
        metadata["alert_body"] = "A new user joined BaseLodge."
    elif spec.event_name == EventName.FOUNDER_APP_OPEN:
        metadata["alert_body"] = "A user opened BaseLodge."
        metadata["app_open_occurrence"] = row.occurrence_id
    elif spec.event_name == EventName.FOUNDER_INVITE_SHARE:
        share_id = metadata.get("invite_share_event_id")
        share = db.session.get(InviteShareEvent, share_id) if share_id else None
        if share is not None:
            metadata["alert_body"] = "An invite was shared."
        else:
            metadata.pop("invite_share_event_id", None)
    return metadata


def message_outbox_safety_callback(row):
    """Worker callback: refuse other delivery families and re-authorize now."""
    if (row.context_json or {}).get("template") != "enqueue_only":
        return MessagingSafetyDecision(
            False, row.event_name, row.occurrence_id, row.recipient_user_id,
            row.actor_user_id, row.object_type, row.object_id, row.channel,
            row.provider, SuppressionReason.ENVIRONMENT_BLOCKED,
            _audit_metadata(None, "outbox_family_refused"),
        )
    spec = _get_event_spec(row.event_name)
    if spec is None or _provider_for_spec(spec) != row.provider:
        return MessagingSafetyDecision(
            False, row.event_name, row.occurrence_id, row.recipient_user_id,
            row.actor_user_id, row.object_type, row.object_id, row.channel,
            row.provider, SuppressionReason.NOT_IMPLEMENTED,
            _audit_metadata(None, "outbox_spec_refused"),
        )
    return evaluate_message_safety(
        spec, row.actor_user_id, row.recipient_user_id, row.object_type,
        row.object_id, _outbox_render_metadata(row, spec),
        (row.context_json or {}).get("route"), row.occurrence_id,
    )


def message_outbox_provider_callback(row):
    """Worker callback which renders only after the current safety pass."""
    if (
        is_opportunity_event(row.event_name)
        and (
            row.event_name != EventName.FRIEND_TRIP_CREATED
            or row.provider_phase != "started"
        )
    ):
        return {
            "status": "dead_letter",
            "error": "opportunity_provider_start_required",
        }
    spec = _get_event_spec(row.event_name)
    if spec is None:
        return {"status": "dead_letter", "error": "unregistered_event"}
    metadata = _outbox_render_metadata(row, spec)
    if spec.delivery_strategy == DeliveryStrategy.AUTOMATION_EVENT:
        from services.push_providers import send_onesignal_custom_event
        result = send_onesignal_custom_event(
            [row.recipient_user_id], spec.automation_event_name,
            {key: metadata[key] for key in spec.data_keys or [] if key in metadata},
        )
    else:
        rendered = _render_immediate_push(
            spec, metadata, row.actor_user_id, row.object_id
        )
        if not _rendered_links_are_safe(rendered):
            return {"status": "suppressed", "error": SuppressionReason.INVALID_DEEP_LINK}
        result = send_onesignal_push(
            [row.recipient_user_id], rendered["title"], rendered["body"],
            rendered["push_data"] or None,
        )
    if result.get("success") and not result.get("skipped"):
        return {"status": "provider_accepted",
                "provider_message_id": result.get("provider_message_id")}
    if result.get("skipped"):
        return {"status": "suppressed", "error": result.get("skipped_reason")}
    if result.get("delivery_unknown"):
        return {
            "status": "delivery_unknown",
            "error": result.get("error") or "provider_result_unknown",
        }
    return {
        "status": "retryable" if result.get("retryable") else "dead_letter",
        "error": result.get("error") or "provider_error",
        "retry_after": result.get("retry_after"),
    }


def message_outbox_opportunity_start_callback(
    session,
    row,
    lease_token,
    *,
    safety_callback,
    event_log_callback=None,
    ownership_guard=None,
    worker_release_sha=None,
):
    """Run locked opportunity authorization/arbitration, or decline the row."""
    if not is_opportunity_event(row.event_name):
        return None
    return mark_opportunity_provider_started(
        row.id,
        lease_token,
        safety_callback=safety_callback,
        event_log_callback=event_log_callback,
        ownership_guard=ownership_guard,
        session=session,
        worker_release_sha=worker_release_sha,
    )


def message_outbox_event_log_callback(row, status, details):
    """Write one final MEL outcome in the worker transaction; never commit.

    Retryable rows intentionally have no MEL claim: a partial attempt must not
    consume MEL's logical-occurrence uniqueness or block the next lease.
    """
    if status == "retryable":
        return None
    mel_status = (
        DeliveryStatus.SENT if status == "provider_accepted"
        else DeliveryStatus.SKIPPED if status == "suppressed"
        else DeliveryStatus.FAILED
    )
    reason = details.get("suppression_reason") if status == "suppressed" else None
    if status == "suppressed" and reason not in {
        value for value in vars(SuppressionReason).values() if isinstance(value, str)
    }:
        reason = SuppressionReason.RECIPIENT_INELIGIBLE
    return create_message_event(
        event_name=row.event_name, category=row.category,
        actor_user_id=row.actor_user_id, recipient_user_id=row.recipient_user_id,
        object_type=row.object_type, object_id=row.object_id, channel=row.channel,
        provider=row.provider, occurrence_id=row.occurrence_id,
        payload_json={"event": row.event_name, "outbox_id": row.id},
        delivery_status=mel_status, suppression_reason=reason,
        error_message=sanitize_error(details.get("error")) if status != "suppressed" else None,
        provider_message_id=details.get("provider_message_id"),
        sent_at=datetime.utcnow() if status == "provider_accepted" else None,
        commit=False,
    )


# Stable, short names for services.message_outbox_worker CLI/callback wiring.
outbox_safety_callback = message_outbox_safety_callback
outbox_provider_callback = message_outbox_provider_callback
outbox_event_log_callback = message_outbox_event_log_callback
outbox_opportunity_start_callback = message_outbox_opportunity_start_callback


def _record_suppression(
    spec,
    decision,
    *,
    rendered=None,
):
    rendered = rendered or {"title": None, "body": None, "push_data": {}}
    payload = {
        **decision.audit_metadata,
        "event": spec.event_name,
    }
    try:
        row = create_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=decision.actor_user_id,
            recipient_user_id=decision.recipient_user_id,
            object_type=decision.entity_type,
            object_id=decision.entity_id,
            channel=decision.channel,
            provider=decision.provider,
            payload_json=payload,
            message_title=rendered.get("title"),
            message_body=rendered.get("body"),
            delivery_status=DeliveryStatus.SKIPPED,
            suppression_reason=decision.suppression_reason,
        )
        return MessagingEmitResult(
            status=DeliveryStatus.SKIPPED,
            mel_id=row.id,
            occurrence_id=decision.occurrence_id,
            suppression_reason=decision.suppression_reason,
        )
    except Exception:
        current_app.logger.warning(
            "[MessageDispatch] suppression audit write failed event=%s reason=%s",
            spec.event_name,
            decision.suppression_reason,
        )
        return MessagingEmitResult(
            status=DeliveryStatus.SKIPPED,
            occurrence_id=decision.occurrence_id,
            suppression_reason=decision.suppression_reason,
            error="audit_write_failed",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch functions — one per delivery strategy branch
# Each dispatch fn is the ONLY place that knows how to execute its strategy.
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch_immediate_push(spec, actor_user_id, recipient_user_id,
                             entity_type, entity_id, metadata, source_route,
                             occurrence_id=None):
    """Execute the IMMEDIATE_PUSH delivery path.

    Phase C: fully internalized — no dependency on app._notify_push().
    Pipeline: render payload → dedupe guard → send → map outcome → write MEL.

    Opt-out filtering is handled inside send_onesignal_push() in
    push_providers.py (queries push_notifications_enabled per recipient).
    Dedupe uses is_duplicate_event() from message_events.py.
    """
    decision = evaluate_message_safety(
        spec,
        actor_user_id,
        recipient_user_id,
        entity_type,
        entity_id,
        metadata,
        source_route,
        occurrence_id,
    )
    if not decision.allowed:
        return _record_suppression(spec, decision)

    rendered = _render_immediate_push(spec, metadata, actor_user_id, entity_id)
    if not _rendered_links_are_safe(rendered):
        denied = MessagingSafetyDecision(
            False,
            spec.event_name,
            occurrence_id,
            recipient_user_id,
            actor_user_id,
            entity_type,
            entity_id,
            Channel.PUSH,
            Provider.ONESIGNAL,
            SuppressionReason.INVALID_DEEP_LINK,
            _audit_metadata(source_route, "deep_link"),
        )
        return _record_suppression(spec, denied)

    title     = rendered["title"]
    body      = rendered["body"]
    push_data = rendered["push_data"]

    # Include source_route in push_data for audit trail continuity.
    if source_route:
        push_data = {**push_data, "source_route": source_route}

    claim_row = None
    if occurrence_id and not spec.bypass_dedupe:
        claim_row, claimed = claim_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=Channel.PUSH,
            provider=Provider.ONESIGNAL,
            payload_json={
                **decision.audit_metadata,
                "event": spec.event_name,
            },
            message_title=title,
            message_body=body,
            occurrence_id=occurrence_id,
        )
        if not claimed:
            duplicate = MessagingSafetyDecision(
                False,
                spec.event_name,
                occurrence_id,
                recipient_user_id,
                actor_user_id,
                entity_type,
                entity_id,
                Channel.PUSH,
                Provider.ONESIGNAL,
                SuppressionReason.DUPLICATE_EVENT,
                _audit_metadata(source_route, "logical_occurrence"),
            )
            result = _record_suppression(spec, duplicate, rendered=rendered)
            return MessagingEmitResult(
                status=result.status,
                mel_id=result.mel_id,
                occurrence_id=occurrence_id,
                suppression_reason=SuppressionReason.DUPLICATE_EVENT,
            )
    elif (
        not spec.bypass_dedupe
        and is_duplicate_event(
            spec.event_name,
            recipient_user_id,
            entity_type,
            entity_id,
        )
    ):
        duplicate = MessagingSafetyDecision(
            False,
            spec.event_name,
            occurrence_id,
            recipient_user_id,
            actor_user_id,
            entity_type,
            entity_id,
            Channel.PUSH,
            Provider.ONESIGNAL,
            SuppressionReason.DUPLICATE_EVENT,
            _audit_metadata(source_route, "legacy_window"),
        )
        return _record_suppression(spec, duplicate, rendered=rendered)

    # 3. Send — opt-out filter (push_notifications_enabled) is handled inside.
    try:
        result = send_onesignal_push(
            user_ids=[recipient_user_id],
            title=title,
            body=body,
            data=push_data or None,
        )
    except Exception:
        current_app.logger.warning(
            "[MessageDispatch] _dispatch_immediate_push: provider send raised"
        )
        result = {"success": False, "provider_message_id": None,
                  "skipped": False, "error": "provider_send_raised"}

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
            else SuppressionReason.NO_DEVICE_TOKEN
            if result.get("skipped_reason") == "no_device_token"
            else SuppressionReason.RECIPIENT_INELIGIBLE
            if result.get("skipped_reason") == "eligibility_error"
            else SuppressionReason.USER_OPTED_OUT
        )
        _error               = None
        _provider_message_id = None
        _sent_at             = None
    else:
        _status              = DeliveryStatus.FAILED
        _suppression         = None
        _error               = "provider_error"
        _provider_message_id = None
        _sent_at             = None

    try:
        if claim_row is not None:
            row = finalize_message_event(
                claim_row,
                delivery_status=_status,
                suppression_reason=_suppression,
                error_message=_error,
                provider_message_id=_provider_message_id,
                sent_at=_sent_at,
            )
        else:
            row = create_message_event(
                event_name=spec.event_name,
                category=spec.category,
                actor_user_id=actor_user_id,
                recipient_user_id=recipient_user_id,
                object_type=entity_type,
                object_id=entity_id,
                channel=Channel.PUSH,
                provider=Provider.ONESIGNAL,
                payload_json={
                    **decision.audit_metadata,
                    "event": spec.event_name,
                },
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
        return MessagingEmitResult(
            status=_status,
            occurrence_id=occurrence_id,
            suppression_reason=_suppression,
            provider_message_id=_provider_message_id,
            error="audit_write_failed",
        )
    return MessagingEmitResult(
        status=_status,
        mel_id=row.id,
        occurrence_id=occurrence_id,
        suppression_reason=_suppression,
        provider_message_id=_provider_message_id,
        error=_error,
    )


def _dispatch_automation_event(spec, actor_user_id, recipient_user_id,
                               entity_type, entity_id, metadata, source_route,
                               occurrence_id=None):
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
        return MessagingEmitResult(
            status=DeliveryStatus.SKIPPED,
            occurrence_id=occurrence_id,
            suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
        )

    decision = evaluate_message_safety(
        spec,
        actor_user_id,
        recipient_user_id,
        entity_type,
        entity_id,
        metadata,
        source_route,
        occurrence_id,
    )
    if not decision.allowed:
        return _record_suppression(spec, decision)

    # Build properties forwarded to the automation platform.
    meta       = metadata or {}
    properties = {k: v for k, v in meta.items() if k in (spec.data_keys or [])}
    if actor_user_id:
        properties.setdefault("actor_user_id", actor_user_id)
    if source_route:
        properties["source_route"] = source_route

    claim_row = None
    if occurrence_id and not spec.bypass_dedupe:
        claim_row, claimed = claim_message_event(
            event_name=spec.event_name,
            category=spec.category,
            actor_user_id=actor_user_id,
            recipient_user_id=recipient_user_id,
            object_type=entity_type,
            object_id=entity_id,
            channel=Channel.PUSH,
            provider=Provider.ONESIGNAL_JOURNEY,
            payload_json={
                **decision.audit_metadata,
                "automation_event_name": spec.automation_event_name,
            },
            occurrence_id=occurrence_id,
        )
        if not claimed:
            duplicate = MessagingSafetyDecision(
                False,
                spec.event_name,
                occurrence_id,
                recipient_user_id,
                actor_user_id,
                entity_type,
                entity_id,
                Channel.PUSH,
                Provider.ONESIGNAL_JOURNEY,
                SuppressionReason.DUPLICATE_EVENT,
                _audit_metadata(source_route, "logical_occurrence"),
            )
            return _record_suppression(spec, duplicate)
    elif (
        not spec.bypass_dedupe
        and is_duplicate_event(
            spec.event_name,
            recipient_user_id,
            entity_type,
            entity_id,
        )
    ):
        duplicate = MessagingSafetyDecision(
            False,
            spec.event_name,
            occurrence_id,
            recipient_user_id,
            actor_user_id,
            entity_type,
            entity_id,
            Channel.PUSH,
            Provider.ONESIGNAL_JOURNEY,
            SuppressionReason.DUPLICATE_EVENT,
            _audit_metadata(source_route, "legacy_window"),
        )
        return _record_suppression(spec, duplicate)

    try:
        result = send_onesignal_custom_event(
            user_ids=[recipient_user_id],
            event_name=spec.automation_event_name,
            properties=properties,
        )
    except Exception:
        current_app.logger.warning(
            "[MessageDispatch] automation_event: provider send raised"
        )
        result = {"success": False, "sent": 0, "failed": 1}

    # Map result → delivery status and write MEL audit row.
    # Reminder: sent = signal emitted, NOT notification delivered.
    _success = result.get("success", False)
    _status = DeliveryStatus.SENT if _success else DeliveryStatus.FAILED
    _error = None if _success else "automation_provider_error"

    try:
        if claim_row is not None:
            row = finalize_message_event(
                claim_row,
                delivery_status=_status,
                error_message=_error,
                sent_at=datetime.utcnow() if _success else None,
            )
        else:
            row = create_message_event(
                event_name=spec.event_name,
                category=spec.category,
                actor_user_id=actor_user_id,
                recipient_user_id=recipient_user_id,
                object_type=entity_type,
                object_id=entity_id,
                channel=Channel.PUSH,
                provider=Provider.ONESIGNAL_JOURNEY,
                payload_json={
                    **decision.audit_metadata,
                    "automation_event_name": spec.automation_event_name,
                },
                delivery_status=_status,
                error_message=_error,
                sent_at=datetime.utcnow() if _success else None,
            )
    except Exception as _mel_err:
        current_app.logger.warning(
            "[MessageDispatch] automation_event MEL write failed: %s", _mel_err,
        )
        return MessagingEmitResult(
            status=_status,
            occurrence_id=occurrence_id,
            error="audit_write_failed",
        )
    return MessagingEmitResult(
        status=_status,
        mel_id=row.id,
        occurrence_id=occurrence_id,
        error=_error,
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
    occurrence_id=None,
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
            return MessagingEmitResult(
                status=DeliveryStatus.SKIPPED,
                suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
            )

        occurrence_id = _normalized_occurrence_id(
            occurrence_id
            or _derive_occurrence_id(
                spec,
                actor_user_id,
                recipient_user_id,
                entity_type,
                entity_id,
                metadata,
            )
        )

        current_app.logger.debug(
            "[MESSAGE_DISPATCH] event=%s strategy=%s actor=%s recipient=%s",
            event_name, spec.delivery_strategy, actor_user_id, recipient_user_id,
        )

        if is_opportunity_event(spec.event_name):
            _dispatch_not_implemented(
                event_name, actor_user_id, recipient_user_id,
                entity_type, entity_id, source_route,
            )
            return MessagingEmitResult(
                status=DeliveryStatus.SKIPPED,
                occurrence_id=occurrence_id,
                suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
            )

        if spec.delivery_strategy == DeliveryStrategy.IMMEDIATE_PUSH:
            return _dispatch_immediate_push(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route, occurrence_id,
            )

        elif spec.delivery_strategy == DeliveryStrategy.AUTOMATION_EVENT:
            return _dispatch_automation_event(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route, occurrence_id,
            )

        elif spec.delivery_strategy == DeliveryStrategy.IMMEDIATE_PUSH_AND_AUTOMATION:
            # Phase C: produces two MEL rows (one per channel/provider).
            # Not active in Phase A/B — no EventSpec uses this strategy yet.
            push_result = _dispatch_immediate_push(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route, occurrence_id,
            )
            automation_result = _dispatch_automation_event(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route, occurrence_id,
            )
            return (push_result, automation_result)

        elif spec.delivery_strategy == DeliveryStrategy.SILENT:
            _dispatch_silent(
                spec, actor_user_id, recipient_user_id,
                entity_type, entity_id, metadata, source_route,
            )
            return MessagingEmitResult(status=DeliveryStatus.SKIPPED)

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
            return MessagingEmitResult(
                status=DeliveryStatus.SKIPPED,
                suppression_reason=SuppressionReason.NOT_IMPLEMENTED,
            )

    except Exception as _top_err:
        # Absolute safety net — emit_messaging_event must never raise.
        current_app.logger.warning(
            "[MessageDispatch] emit_messaging_event: unhandled exception for "
            "event=%s: %s", event_name, _top_err,
        )
        return MessagingEmitResult(
            status=DeliveryStatus.FAILED,
            occurrence_id=occurrence_id,
            error="internal_dispatch_error",
        )
