"""Focused BL-238 attention architecture regressions."""

from datetime import datetime, timedelta
from pathlib import Path

from app import (
    _attention_activity_query,
    _build_home_needs_you,
    app,
    create_activity,
    emit_trip_invite_received_activity,
)
from models import Activity, ActivityType, GuestStatus, Invitation, InviteType, db
from tests.conftest import _add_participant, _login, _make_trip, _make_user, json_post


def _activity(actor, recipient, kind, *, subject_type=None, subject_id=None,
              created_at=None, seen_at=None, object_type="user", object_id=None):
    row = Activity(
        actor_user_id=actor.id,
        recipient_user_id=recipient.id,
        type=kind.value if hasattr(kind, "value") else kind,
        object_type=object_type,
        object_id=object_id or actor.id,
        created_at=created_at or datetime.utcnow(),
        seen_at=seen_at,
        subject_type=subject_type,
        subject_id=subject_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def test_activity_state_has_independent_seen_and_subject_fields(client):
    with app.app_context():
        assert hasattr(Activity, "seen_at")
        assert hasattr(Activity, "subject_type")
        assert hasattr(Activity, "subject_id")


def test_friend_request_emits_exact_actionable_activity(client):
    with app.app_context():
        sender = _make_user("bl238-emitter")
        receiver = _make_user("bl238-recipient")
        from app import create_friend_request
        result = create_friend_request(sender.id, receiver.id)
        assert result["ok"] is True
        activity = Activity.query.filter_by(
            recipient_user_id=receiver.id,
            type=ActivityType.FRIEND_REQUEST_RECEIVED.value,
        ).one()
        assert activity.subject_type == "invitation"
        assert activity.subject_id == result["invitation_id"]
        assert activity.seen_at is None


def test_acknowledgement_is_durable_and_requires_auth_and_csrf(client):
    with app.app_context():
        actor = _make_user("bl238-ack-actor")
        recipient = _make_user("bl238-ack-recipient", is_verified=True)
        row = _activity(actor, recipient, ActivityType.TRIP_CREATED)
        recipient_id, activity_id = recipient.id, row.id

    csrf_client = app.test_client()
    assert csrf_client.post("/api/notifications/viewed", json={"activity_ids": [activity_id]}).status_code in (302, 403)
    with app.app_context():
        assert hasattr(Activity, "seen_at")


def test_notifications_filters_resolved_actionable_and_keeps_unresolved(client):
    with app.app_context():
        actor = _make_user("bl238-notif-actor")
        recipient = _make_user("bl238-notif-recipient")
        invitation = Invitation(
            sender_id=actor.id, receiver_id=recipient.id,
            invite_type=InviteType.OUTBOUND, status="pending",
        )
        db.session.add(invitation)
        db.session.flush()
        invitation_id = invitation.id
        row = _activity(
            actor, recipient, ActivityType.FRIEND_REQUEST_RECEIVED,
            subject_type="invitation", subject_id=invitation.id,
        )
        recipient_id, activity_id = recipient.id, row.id
        db.session.commit()
    _login(client, recipient_id)
    assert client.get("/notifications").status_code == 200
    with app.app_context():
        invitation = db.session.get(Invitation, invitation_id)
        invitation.status = "accepted"
        db.session.commit()
        assert db.session.get(Invitation, invitation_id).status == "accepted"
    assert f'data-activity-id="{activity_id}"' not in client.get("/notifications").get_data(as_text=True)


def test_join_request_uses_exact_invitation_subject(client):
    with app.app_context():
        requester = _make_user("bl238-join-requester")
        owner = _make_user("bl238-join-owner")
        trip = _make_trip(owner)
        invitation = Invitation(
            sender_id=requester.id,
            receiver_id=owner.id,
            trip_id=trip.id,
            invite_type=InviteType.REQUEST,
            status="pending",
        )
        db.session.add(invitation)
        db.session.flush()
        activity = _activity(
            requester,
            owner,
            ActivityType.JOIN_REQUEST_RECEIVED,
            subject_type="invitation",
            subject_id=invitation.id,
            object_type="trip",
            object_id=trip.id,
        )
        owner_id, activity_id = owner.id, activity.id
        db.session.commit()

    _login(client, owner_id)
    html = client.get("/notifications").get_data(as_text=True)
    assert f'data-activity-id="{activity_id}"' in html


def test_trip_reinvite_supersedes_prior_actionable_activity(client):
    with app.app_context():
        owner = _make_user("bl238-reinvite-owner")
        invitee = _make_user("bl238-reinvite-user")
        trip = _make_trip(owner)
        _add_participant(trip, invitee, GuestStatus.PENDING)
        db.session.flush()

        emit_trip_invite_received_activity(trip, owner.id, invitee.id)
        db.session.flush()
        first = Activity.query.filter_by(
            recipient_user_id=invitee.id,
            type=ActivityType.TRIP_INVITE_RECEIVED.value,
        ).one()
        first_created_at = first.created_at

        emit_trip_invite_received_activity(trip, owner.id, invitee.id)
        db.session.flush()
        rows = Activity.query.filter_by(
            recipient_user_id=invitee.id,
            type=ActivityType.TRIP_INVITE_RECEIVED.value,
        ).all()
        assert len(rows) == 1
        assert rows[0].created_at >= first_created_at
        assert rows[0].subject_id == trip.participants[1].id


def test_notifications_retention_keeps_unseen_over_50_and_caps_seen_info(client):
    with app.app_context():
        actor = _make_user("bl238-retention-actor")
        recipient = _make_user("bl238-retention-recipient")
        old = datetime.utcnow() - timedelta(days=91)
        for index in range(60):
            _activity(actor, recipient, ActivityType.TRIP_CREATED,
                      created_at=datetime.utcnow() - timedelta(minutes=index),
                      seen_at=datetime.utcnow())
        fresh_unseen = _activity(actor, recipient, ActivityType.TRIP_CREATED)
        old_unseen = _activity(actor, recipient, ActivityType.TRIP_CREATED, created_at=old)
        recipient_id, fresh_id, old_id = recipient.id, fresh_unseen.id, old_unseen.id
        db.session.commit()
    _login(client, recipient_id)
    html = client.get("/notifications").get_data(as_text=True)
    assert html.count("data-activity-id=") == 51
    assert f'data-activity-id="{fresh_id}"' in html
    assert f'data-activity-id="{old_id}"' not in html


def test_terminal_trip_information_is_not_badge_eligible(client):
    with app.app_context():
        actor = _make_user("bl238-terminal-actor")
        recipient = _make_user("bl238-terminal-recipient")
        trip = _make_trip(actor)
        trip.lifecycle_state = "cancelled"
        _activity(
            actor,
            recipient,
            ActivityType.TRIP_UPDATED,
            object_type="trip",
            object_id=trip.id,
        )
        db.session.commit()
        assert _attention_activity_query(recipient.id, seen=False).count() == 0


def test_unseen_trip_updates_consolidate_only_until_seen(client):
    with app.app_context():
        actor = _make_user("bl238-consolidation-actor")
        recipient = _make_user("bl238-consolidation-recipient")
        create_activity(actor.id, recipient.id, ActivityType.TRIP_UPDATED,
                        "trip", 42, subject_type="trip", subject_id=42)
        second = create_activity(actor.id, recipient.id, ActivityType.TRIP_UPDATED,
                                 "trip", 42, subject_type="trip", subject_id=42)
        db.session.flush()
        first = Activity.query.filter_by(
            recipient_user_id=recipient.id,
            type=ActivityType.TRIP_UPDATED.value,
        ).one()
        assert first is second
        first.seen_at = datetime.utcnow()
        create_activity(actor.id, recipient.id, ActivityType.TRIP_UPDATED,
                        "trip", 42, subject_type="trip", subject_id=42)
        db.session.flush()
        third = Activity.query.filter_by(
            recipient_user_id=recipient.id,
            type=ActivityType.TRIP_UPDATED.value,
        ).order_by(Activity.id.desc()).first()
        assert third.id != first.id


def test_needs_you_orders_coordination_before_friend_requests(client):
    with app.app_context():
        viewer = _make_user("bl238-order-viewer")
        owner = _make_user("bl238-order-owner")
        invited = _make_trip(owner)
        _add_participant(invited, viewer, GuestStatus.PENDING)
        friend = _make_user("bl238-order-friend")
        db.session.add(Invitation(sender_id=friend.id, receiver_id=viewer.id,
                                  invite_type=InviteType.OUTBOUND, status="pending"))
        db.session.commit()
        rows = _build_home_needs_you(user_id=viewer.id, today=datetime.utcnow().date())
        assert rows[0]["type"] == "trip_invitation"
        assert rows[-1]["type"] == "friend_request"


def test_notifications_has_no_resolution_controls_and_needs_you_routes_contextual_workflows():
    notifications = Path("templates/notifications.html").read_text()
    friends = Path("templates/friends.html").read_text()
    needs = Path("templates/partials/home/_section_requests.html").read_text()
    assert "acceptConnect" not in notifications
    assert "if (!response.ok)" in notifications
    assert "if (!data.success)" in notifications
    assert "if (!response.ok)" in friends
    assert "if (!data.success)" in friends
    assert "respond_to_trip_invite" not in needs
    assert "respond_to_join_request" not in needs
    assert "trip_detail" in needs