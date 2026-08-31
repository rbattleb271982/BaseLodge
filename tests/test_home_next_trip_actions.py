"""BL-189 canonical Home Next Trip action contract regressions."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from app import (
    HOME_NEXT_TRIP_ACTION_PRIORITIES,
    _build_home_next_trip_actions,
    _canonicalize_home_next_trip_actions,
    app,
)
from models import GuestStatus, Invitation, InviteType, db
from tests.conftest import (
    _add_participant,
    _login,
    _make_trip,
    _make_user,
)


def _capture_selects(call):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = db.engine
    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    return result, statements


def _build(*, trip, user_id, participant=None):
    with app.test_request_context():
        return _build_home_next_trip_actions(
            next_trip=trip,
            current_user_id=user_id,
            participant=participant,
        )


def _home_context(client, user_id):
    captured = {}

    def capture_render(template_name, **context):
        assert template_name == "home.html"
        captured.update(context)
        return "rendered"

    _login(client, user_id)
    with patch(
        "services.open_dates.get_available_dates_for_user",
        return_value=[],
    ), patch(
        "services.ideas_retrieval.get_home_ideas",
        return_value=[],
    ), patch(
        "services.happening.get_happening_candidates",
        return_value=[],
    ), patch(
        "app.get_all_active_resorts_map",
        return_value={},
    ), patch(
        "app.render_template",
        side_effect=capture_render,
    ):
        response = client.get("/home")

    assert response.status_code == 200
    return captured


def test_interested_guest_receives_review_rsvp_without_action_query(client):
    with app.app_context():
        owner = _make_user("actions-interested-owner")
        guest = _make_user("actions-interested-guest")
        trip = _make_trip(owner, is_public=False)
        participant = _add_participant(trip, guest, GuestStatus.INTERESTED)
        trip_ref = SimpleNamespace(id=trip.id, user_id=owner.id)

        actions, statements = _capture_selects(
            lambda: _build(
                trip=trip_ref,
                user_id=guest.id,
                participant=participant,
            )
        )

        assert actions == [{
            "key": f"next_trip:review_rsvp:{trip.id}",
            "type": "review_rsvp",
            "label": "Review RSVP",
            "destination": f"/trips/{trip.id}#td-self-rsvp",
            "priority": HOME_NEXT_TRIP_ACTION_PRIORITIES["review_rsvp"],
        }]
        assert statements == []


@pytest.mark.parametrize(
    "status",
    [
        GuestStatus.GOING,
        GuestStatus.PENDING,
        GuestStatus.DECLINED,
        GuestStatus.REMOVED,
    ],
)
def test_non_interested_guest_states_receive_no_action_or_query(client, status):
    with app.app_context():
        owner = _make_user(f"actions-{status.value}-owner")
        guest = _make_user(f"actions-{status.value}-guest")
        trip = _make_trip(owner, is_public=False)
        participant = _add_participant(trip, guest, status)
        trip_ref = SimpleNamespace(id=trip.id, user_id=owner.id)

        actions, statements = _capture_selects(
            lambda: _build(
                trip=trip_ref,
                user_id=guest.id,
                participant=participant,
            )
        )

        assert actions == []
        assert statements == []


def test_owner_pending_join_request_uses_one_bounded_query(client):
    with app.app_context():
        owner = _make_user("actions-request-owner")
        requester = _make_user("actions-requester")
        trip = _make_trip(owner, is_public=False)
        db.session.add(Invitation(
            sender_id=requester.id,
            receiver_id=owner.id,
            trip_id=trip.id,
            invite_type=InviteType.REQUEST,
            status="pending",
        ))
        db.session.flush()
        trip_ref = SimpleNamespace(id=trip.id, user_id=owner.id)

        actions, statements = _capture_selects(
            lambda: _build(trip=trip_ref, user_id=owner.id)
        )

        assert actions == [{
            "key": f"next_trip:review_join_requests:{trip.id}",
            "type": "review_join_requests",
            "label": "Review join requests",
            "destination": f"/trips/{trip.id}#td-join-requests",
            "priority": HOME_NEXT_TRIP_ACTION_PRIORITIES[
                "review_join_requests"
            ],
        }]
        assert len(statements) == 1
        assert "invitation" in statements[0].lower()
        assert "exists" in statements[0].lower()
        assert " join " not in f" {statements[0].lower()} "


def test_owner_without_pending_requests_has_zero_actions_with_one_query(client):
    with app.app_context():
        owner = _make_user("actions-no-request-owner")
        trip = _make_trip(owner)
        trip_ref = SimpleNamespace(id=trip.id, user_id=owner.id)

        actions, statements = _capture_selects(
            lambda: _build(trip=trip_ref, user_id=owner.id)
        )

        assert actions == []
        assert len(statements) == 1


def test_no_next_trip_has_zero_actions_without_query(client):
    with app.app_context():
        actions, statements = _capture_selects(
            lambda: _build(trip=None, user_id=123)
        )

        assert actions == []
        assert statements == []


def test_contract_ordering_and_deduplication_are_deterministic():
    review_requests = {
        "key": "next_trip:review_join_requests:7",
        "type": "review_join_requests",
        "label": "Review join requests",
        "destination": "/trips/7#td-join-requests",
        "priority": HOME_NEXT_TRIP_ACTION_PRIORITIES["review_join_requests"],
    }
    review_rsvp = {
        "key": "next_trip:review_rsvp:7",
        "type": "review_rsvp",
        "label": "Review RSVP",
        "destination": "/trips/7#td-self-rsvp",
        "priority": HOME_NEXT_TRIP_ACTION_PRIORITIES["review_rsvp"],
    }

    actions = _canonicalize_home_next_trip_actions([
        review_requests,
        review_rsvp,
        dict(review_rsvp),
    ])

    assert actions == [review_rsvp, review_requests]
    assert len({action["key"] for action in actions}) == len(actions)
    assert {
        action["type"] for action in actions
    } == {"review_rsvp", "review_join_requests"}
    excluded_types = {
        "view_trip",
        "edit_trip",
        "add_pass",
        "add_gear",
        "profile_completion",
    }
    assert not excluded_types.intersection(
        action["type"] for action in actions
    )


def test_private_interested_guest_home_summary_exposes_action_contract(client):
    with app.app_context():
        owner = _make_user("actions-private-owner")
        guest = _make_user("actions-private-guest")
        trip = _make_trip(owner, is_public=False)
        _add_participant(trip, guest, GuestStatus.INTERESTED)
        db.session.commit()
        guest_id = guest.id
        trip_id = trip.id

    next_trip_summary = _home_context(client, guest_id)["home_summary"][
        "next_trip"
    ]

    assert next_trip_summary["trip"].id == trip_id
    assert next_trip_summary["is_owner"] is False
    assert next_trip_summary["action_count"] == 1
    assert next_trip_summary["action_count"] == len(
        next_trip_summary["actions"]
    )
    assert next_trip_summary["actions"][0]["type"] == "review_rsvp"


def test_owner_pending_request_home_summary_exposes_action_contract(client):
    with app.app_context():
        owner = _make_user("actions-summary-owner")
        requester = _make_user("actions-summary-requester")
        trip = _make_trip(owner, is_public=False)
        db.session.add(Invitation(
            sender_id=requester.id,
            receiver_id=owner.id,
            trip_id=trip.id,
            invite_type=InviteType.REQUEST,
            status="pending",
        ))
        db.session.commit()
        owner_id = owner.id
        trip_id = trip.id

    next_trip_summary = _home_context(client, owner_id)["home_summary"][
        "next_trip"
    ]

    assert next_trip_summary["trip"].id == trip_id
    assert next_trip_summary["is_owner"] is True
    assert next_trip_summary["action_count"] == 1
    assert next_trip_summary["action_count"] == len(
        next_trip_summary["actions"]
    )
    assert next_trip_summary["actions"][0]["type"] == "review_join_requests"


@pytest.mark.parametrize(
    "status",
    [
        GuestStatus.PENDING,
        GuestStatus.DECLINED,
        GuestStatus.REMOVED,
    ],
)
def test_inactive_private_guest_has_no_next_trip_action_exposure(client, status):
    with app.app_context():
        owner = _make_user(f"actions-private-{status.value}-owner")
        guest = _make_user(f"actions-private-{status.value}-guest")
        trip = _make_trip(owner, is_public=False)
        _add_participant(trip, guest, status)
        db.session.commit()
        guest_id = guest.id

    assert _home_context(client, guest_id)["home_summary"]["next_trip"] is None


def test_private_trip_stranger_has_no_next_trip_action_exposure(client):
    with app.app_context():
        owner = _make_user("actions-private-owner-only")
        stranger = _make_user("actions-private-stranger")
        _make_trip(owner, is_public=False)
        db.session.commit()
        stranger_id = stranger.id

    assert _home_context(client, stranger_id)["home_summary"]["next_trip"] is None