"""
Tests for the join-request push notification (TRIP_JOIN_REQUESTED).

Covers:
  - Successful request  → emit_messaging_event called once, correct args
  - Duplicate pending   → emit not called (early-return guard)
  - Already accepted    → emit not called (is_accepted guard)
  - Owner self-request  → emit not called (owner is ACCEPTED, same guard)
  - No-resort trip      → resort="upcoming" so body reads naturally
  - EventSpec registry  → IMMEDIATE_PUSH, correct title/body/deep-link
"""
import unittest.mock
from datetime import date, timedelta

import pytest

from app import app
from models import (
    db, GuestStatus, Invitation, InviteType,
)
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post,
)
from services.messaging_constants import EventName, DeliveryStrategy
from services.message_dispatch import _EVENT_REGISTRY


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pending_invitation(owner_id, requester_id, trip_id):
    """Insert a pending join Invitation directly (bypasses the route)."""
    inv = Invitation(
        sender_id=requester_id,
        receiver_id=owner_id,
        trip_id=trip_id,
        invite_type=InviteType.REQUEST,
        status='pending',
    )
    db.session.add(inv)
    db.session.commit()


# ── EventSpec registry tests (no HTTP, no DB) ─────────────────────────────────

class TestTripJoinRequestedEventSpec:
    """Verify the EventSpec is registered correctly — no request needed."""

    def test_event_constant_value(self):
        assert EventName.TRIP_JOIN_REQUESTED == "trip.join.requested"

    def test_spec_is_registered(self):
        assert EventName.TRIP_JOIN_REQUESTED in _EVENT_REGISTRY

    def test_delivery_strategy_is_immediate_push(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert spec.delivery_strategy == DeliveryStrategy.IMMEDIATE_PUSH

    def test_title_template(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert spec.title_template == "{actor_name} wants to join your trip"

    def test_body_template(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert spec.body_template == "They've requested to join your {resort} trip."

    def test_deep_link_template(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert spec.deep_link_template == "/trips/{entity_id}"

    def test_context_keys_include_resort_and_actor(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert "actor_name" in spec.context_keys
        assert "resort" in spec.context_keys
        assert "trip_id" in spec.context_keys

    def test_not_email_eligible(self):
        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        assert spec.email_eligible is False


# ── Route-level notification tests ────────────────────────────────────────────

class TestJoinRequestNotification:

    def test_successful_request_emits_notification(self, client):
        """New successful join request → emit_messaging_event called once."""
        with app.app_context():
            owner     = _make_user("owner")
            requester = _make_user("req")
            resort    = _make_resort("Whistler Blackcomb")
            trip      = _make_trip(owner, resort=resort)
            owner_id     = owner.id
            requester_id = requester.id
            trip_id      = trip.id
            db.session.commit()

        _login(client, requester_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 200
        assert rv.get_json()["success"] is True

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs["event_name"] == EventName.TRIP_JOIN_REQUESTED
        assert call_kwargs["actor_user_id"] == requester_id
        assert call_kwargs["recipient_user_id"] == owner_id
        assert call_kwargs["entity_type"] == "trip"
        assert call_kwargs["entity_id"] == trip_id
        assert call_kwargs["metadata"]["resort"] == "Whistler Blackcomb"
        assert call_kwargs["metadata"]["trip_id"] == trip_id
        assert call_kwargs["source_route"] == "request_to_join_trip"

    def test_successful_request_deep_link_via_spec(self, client):
        """The EventSpec's deep_link_template produces /trips/{trip_id}."""
        with app.app_context():
            owner        = _make_user("owner")
            requester    = _make_user("req")
            trip         = _make_trip(owner)
            trip_id      = trip.id
            requester_id = requester.id
            db.session.commit()

        _login(client, requester_id)

        spec = _EVENT_REGISTRY[EventName.TRIP_JOIN_REQUESTED]
        rendered = spec.deep_link_template.replace("{entity_id}", str(trip_id))
        assert rendered == f"/trips/{trip_id}"

    def test_duplicate_pending_request_no_notification(self, client):
        """Second request on an already-pending Invitation → emit not called."""
        with app.app_context():
            owner     = _make_user("owner")
            requester = _make_user("req")
            trip      = _make_trip(owner)
            owner_id     = owner.id
            requester_id = requester.id
            trip_id      = trip.id
            db.session.commit()
            _pending_invitation(owner_id, requester_id, trip_id)

        _login(client, requester_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        # Route returns 200 success (no-op), but no push
        assert rv.status_code == 200
        mock_emit.assert_not_called()

    def test_already_accepted_participant_no_notification(self, client):
        """Accepted participant hitting the endpoint → emit not called (400 guard)."""
        with app.app_context():
            owner     = _make_user("owner")
            member    = _make_user("member")
            trip      = _make_trip(owner)
            _add_participant(trip, member, GuestStatus.ACCEPTED)
            member_id = member.id
            trip_id   = trip.id
            db.session.commit()

        _login(client, member_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 400
        mock_emit.assert_not_called()

    def test_owner_self_request_no_notification(self, client):
        """Trip owner is always ACCEPTED; guard blocks and emit is never reached."""
        with app.app_context():
            owner   = _make_user("owner")
            trip    = _make_trip(owner)
            owner_id = owner.id
            trip_id  = trip.id
            db.session.commit()

        _login(client, owner_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 400
        mock_emit.assert_not_called()

    def test_no_resort_uses_upcoming_fallback(self, client):
        """Trip with no resort and no mountain → resort='upcoming' in metadata."""
        with app.app_context():
            owner     = _make_user("owner")
            requester = _make_user("req")
            # Create trip with no resort FK and explicit empty mountain
            trip = _make_trip(owner, mountain="")
            # Clear mountain to simulate true no-resort trip
            trip.mountain = None
            trip.resort_id = None
            db.session.flush()
            owner_id     = owner.id
            requester_id = requester.id
            trip_id      = trip.id
            db.session.commit()

        _login(client, requester_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 200
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["metadata"]["resort"] == "upcoming"

    def test_mountain_fallback_when_no_resort_fk(self, client):
        """Trip with mountain string but no resort FK → mountain used as resort."""
        with app.app_context():
            owner     = _make_user("owner")
            requester = _make_user("req")
            trip = _make_trip(owner, mountain="Copper Mountain")
            trip.resort_id = None
            db.session.flush()
            owner_id     = owner.id
            requester_id = requester.id
            trip_id      = trip.id
            db.session.commit()

        _login(client, requester_id)

        with unittest.mock.patch("app.emit_messaging_event") as mock_emit:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 200
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["metadata"]["resort"] == "Copper Mountain"

    def test_notification_uses_dispatch_infrastructure_not_direct_call(self, client):
        """emit_messaging_event is called (not a raw OneSignal call in the route)."""
        with app.app_context():
            owner     = _make_user("owner")
            requester = _make_user("req")
            trip      = _make_trip(owner)
            requester_id = requester.id
            trip_id      = trip.id
            db.session.commit()

        _login(client, requester_id)

        # Patching app.emit_messaging_event proves the route goes through
        # the messaging service, not a one-off direct OneSignal call.
        with unittest.mock.patch("app.emit_messaging_event") as mock_emit, \
             unittest.mock.patch("app.send_onesignal_push", side_effect=AssertionError("direct call")) as _direct:
            rv = json_post(client, f"/trips/{trip_id}/request-join")

        assert rv.status_code == 200
        mock_emit.assert_called_once()
        # _direct was never called — no direct OneSignal invocation in the route
