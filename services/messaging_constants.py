"""
Canonical constants for the BaseLodge MessageEventLog v1 system.

No project imports — safe to import from models, services, or app without
circular-import risk.
"""


class EventName:
    TRIP_INVITE_CREATED     = "trip.invite.created"
    TRIP_INVITE_ACCEPTED    = "trip.invite.accepted"
    TRIP_INVITE_DECLINED    = "trip.invite.declined"

    FRIEND_REQUEST_CREATED  = "friend.request.created"
    FRIEND_REQUEST_ACCEPTED = "friend.request.accepted"

    OVERLAP_DETECTED        = "overlap.detected"

    FRIEND_TRIP_CREATED     = "friend.trip.created"
    FRIEND_TRIP_UPDATED     = "friend.trip.updated"

    WISHLIST_MATCH_DETECTED = "wishlist.match.detected"

    DIGEST_WEEKLY_GENERATED = "digest.weekly.generated"

    PUSH_TEST_SENT          = "push.test.sent"
    PUSH_BROADCAST_SENT     = "push.broadcast.sent"


class Category:
    TRIP      = "trip"
    FRIEND    = "friend"
    OVERLAP   = "overlap"
    WISHLIST  = "wishlist"
    DIGEST    = "digest"
    SYSTEM    = "system"
    MARKETING = "marketing"


class DeliveryStatus:
    PENDING = "pending"
    SENT    = "sent"
    SKIPPED = "skipped"
    FAILED  = "failed"


class SuppressionReason:
    USER_OPTED_OUT          = "user_opted_out"
    CHANNEL_UNAVAILABLE     = "channel_unavailable"
    SENDER_IS_RECIPIENT     = "sender_is_recipient"
    DUPLICATE_EVENT         = "duplicate_event"
    DIGEST_ONLY             = "digest_only"
    QUIET_HOURS             = "quiet_hours"
    MISSING_REQUIRED_PAYLOAD = "missing_required_payload"
    RECIPIENT_INELIGIBLE    = "recipient_ineligible"
    TEST_ONLY               = "test_only"
    PROVIDER_ERROR          = "provider_error"
    NOT_IMPLEMENTED         = "not_implemented"
    SILENT_BY_DESIGN        = "silent_by_design"


class Channel:
    PUSH   = "push"
    EMAIL  = "email"
    IN_APP = "in_app"
    DIGEST = "digest"


class Provider:
    ONESIGNAL = "onesignal"
    SENDGRID  = "sendgrid"
    APNS      = "apns"
    FCM       = "fcm"
    INTERNAL  = "internal"


# Suppression reasons that make a failed event non-retryable.
# Provider/network failures are NOT in this set — those may be retried.
RETRYABLE_STATUSES = frozenset({
    SuppressionReason.DUPLICATE_EVENT,
    SuppressionReason.USER_OPTED_OUT,
    SuppressionReason.CHANNEL_UNAVAILABLE,
    SuppressionReason.MISSING_REQUIRED_PAYLOAD,
    SuppressionReason.RECIPIENT_INELIGIBLE,
})

# Maximum number of retry attempts before a failed event is abandoned.
MAX_RETRY_COUNT = 3

# Default dedupe window — events with the same (name, recipient, object)
# within this window are considered duplicates.
DEDUPE_WINDOW_SECONDS = 3600  # 1 hour

# Events that always bypass dedupe (e.g. explicit admin/test pushes).
BYPASS_DEDUPE_EVENTS = frozenset({
    EventName.PUSH_TEST_SENT,
    EventName.PUSH_BROADCAST_SENT,
})
