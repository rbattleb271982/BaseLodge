"""Focused coverage for BL-225 sender-facing pending friend requests."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from itsdangerous import URLSafeSerializer

from app import app
from models import FriendSuggestion, Invitation, InviteType, db
from services.outgoing_friend_requests import (
    OUTGOING_REQUESTS_PAGE_SIZE,
    OutgoingRequestCursor,
    OutgoingRequestsCursorError,
    decode_outgoing_requests_cursor,
    encode_outgoing_requests_cursor,
    load_outgoing_requests_page,
)
from tests.conftest import _login, _make_user, json_delete, json_post


def _pending(sender, receiver, *, created_at=None, trip_id=None, status="pending"):
    invitation = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        trip_id=trip_id,
        status=status,
        invite_type=InviteType.OUTBOUND,
        created_at=created_at or datetime.utcnow(),
    )
    db.session.add(invitation)
    db.session.flush()
    return invitation


def _persist_null_created_at(*invitation_ids):
    Invitation.query.filter(Invitation.id.in_(invitation_ids)).update(
        {Invitation.created_at: None},
        synchronize_session=False,
    )
    db.session.flush()


def _traverse(viewer_id):
    rows = []
    cursors = []
    cursor = None
    while True:
        page = load_outgoing_requests_page(viewer_id, cursor)
        rows.extend(page.rows)
        if not page.has_more:
            return rows, cursors, page.total_count
        assert page.next_cursor
        cursors.append(
            decode_outgoing_requests_cursor(page.next_cursor, viewer_id=viewer_id)
        )
        cursor = page.next_cursor


def test_retrieval_is_sender_scoped_pending_social_and_minimal(client):
    with app.app_context():
        viewer = _make_user("outgoing-viewer")
        visible = _make_user("outgoing-visible")
        visible.first_name = "Hidden"
        visible.last_name = "Recipient"
        visible.discoverable_in_friend_search = False
        other_sender = _make_user("outgoing-other")
        resolved = _make_user("outgoing-resolved")
        trip_target = _make_user("outgoing-trip")
        null_trip_request_target = _make_user("outgoing-null-trip-request")
        included = _pending(viewer, visible)
        _pending(other_sender, visible)
        _pending(viewer, resolved, status="accepted")
        _pending(viewer, trip_target, trip_id=999)
        null_trip_request = _pending(viewer, null_trip_request_target)
        null_trip_request.invite_type = InviteType.REQUEST
        db.session.commit()

        page = load_outgoing_requests_page(viewer.id)

        assert page.total_count == 1
        assert [row.invitation_id for row in page.rows] == [included.id]
        assert page.rows[0].recipient_name == "Hidden Recipient"
        assert set(page.rows[0].__dataclass_fields__) == {
            "invitation_id",
            "recipient_id",
            "recipient_first_name",
            "recipient_last_name",
            "created_at",
        }


@pytest.mark.parametrize("source_count", [0, 1, 20, 21, 41])
def test_boundaries_order_and_complete_keyset_paging(client, source_count):
    with app.app_context():
        viewer = _make_user(f"outgoing-boundary-{source_count}")
        tied_at = datetime(2026, 1, 15, 12, 0, 0)
        invitation_ids = []
        for index in range(source_count):
            recipient = _make_user(f"outgoing-recipient-{source_count}-{index}")
            invitation_ids.append(
                _pending(viewer, recipient, created_at=tied_at).id
            )
        db.session.commit()

        rows = []
        cursor = None
        while True:
            page = load_outgoing_requests_page(viewer.id, cursor)
            rows.extend(page.rows)
            assert page.total_count == source_count
            if not page.has_more:
                break
            assert page.next_cursor
            cursor = page.next_cursor

        assert len(rows) == source_count
        assert len({row.invitation_id for row in rows}) == source_count
        assert [row.invitation_id for row in rows] == sorted(
            invitation_ids, reverse=True
        )
        assert len(rows[:OUTGOING_REQUESTS_PAGE_SIZE]) == min(source_count, 20)


def test_cursor_is_signed_and_bound_to_viewer(client):
    with app.app_context():
        viewer = _make_user("outgoing-cursor-viewer")
        other = _make_user("outgoing-cursor-other")
        for index in range(OUTGOING_REQUESTS_PAGE_SIZE + 1):
            _pending(viewer, _make_user(f"outgoing-cursor-{index}"))
        db.session.commit()
        cursor = load_outgoing_requests_page(viewer.id).next_cursor
        assert cursor

        with pytest.raises(OutgoingRequestsCursorError):
            load_outgoing_requests_page(other.id, cursor)
        with pytest.raises(OutgoingRequestsCursorError):
            load_outgoing_requests_page(viewer.id, "not-a-cursor")
        token, signature = cursor.rsplit(".", 1)
        replacement = "a" if signature[0] != "a" else "b"
        tampered_cursor = f"{token}.{replacement}{signature[1:]}"
        with pytest.raises(OutgoingRequestsCursorError):
            load_outgoing_requests_page(viewer.id, tampered_cursor)


def test_cursor_contract_accepts_only_consistent_rank_timestamp_pairs(client):
    with app.app_context():
        viewer = _make_user("outgoing-cursor-contract")
        db.session.commit()
        tied_at = datetime(2026, 1, 15, 12, 0, 0)

        timestamp_cursor = OutgoingRequestCursor(
            viewer_id=viewer.id,
            null_rank=0,
            created_at=tied_at,
            invitation_id=10,
        )
        timestamp_value = encode_outgoing_requests_cursor(timestamp_cursor)
        assert decode_outgoing_requests_cursor(
            timestamp_value, viewer_id=viewer.id
        ) == timestamp_cursor

        null_cursor = OutgoingRequestCursor(
            viewer_id=viewer.id,
            null_rank=1,
            created_at=None,
            invitation_id=9,
        )
        null_value = encode_outgoing_requests_cursor(null_cursor)
        assert decode_outgoing_requests_cursor(
            null_value, viewer_id=viewer.id
        ) == null_cursor

        for invalid in (
            OutgoingRequestCursor(viewer.id, 0, None, 8),
            OutgoingRequestCursor(viewer.id, 1, tied_at, 7),
        ):
            with pytest.raises(OutgoingRequestsCursorError):
                encode_outgoing_requests_cursor(invalid)


def test_signed_cursor_rejects_inconsistent_rank_timestamp_payloads(client):
    with app.app_context():
        viewer = _make_user("outgoing-cursor-malformed")
        db.session.commit()
        serializer = URLSafeSerializer(
            app.config["SECRET_KEY"],
            salt="outgoing-friend-requests-page",
        )
        base = {
            "v": 2,
            "t": "outgoing-friend-requests",
            "u": viewer.id,
            "i": 10,
        }
        inconsistent_payloads = (
            {**base, "n": 0, "d": None},
            {**base, "n": 1, "d": datetime(2026, 1, 15).isoformat()},
        )

        for payload in inconsistent_payloads:
            signed = serializer.dumps(payload)
            with pytest.raises(OutgoingRequestsCursorError):
                decode_outgoing_requests_cursor(signed, viewer_id=viewer.id)


def test_mixed_nullable_rows_traverse_timestamp_then_null_phases(client):
    with app.app_context():
        viewer = _make_user("outgoing-null-mixed-viewer")
        timestamped_ids = []
        tied_at = datetime(2026, 1, 15, 12, 0, 0)
        for index in range(25):
            recipient = _make_user(f"outgoing-null-dated-{index}")
            timestamped_ids.append(
                _pending(viewer, recipient, created_at=tied_at).id
            )
        null_ids = []
        for index in range(22):
            recipient = _make_user(f"outgoing-null-legacy-{index}")
            null_ids.append(_pending(viewer, recipient).id)
        _persist_null_created_at(*null_ids)
        db.session.commit()

        rows, cursors, total_count = _traverse(viewer.id)
        actual_ids = [row.invitation_id for row in rows]

        assert total_count == 47
        assert len(actual_ids) == total_count
        assert len(actual_ids) == len(set(actual_ids))
        assert actual_ids == (
            sorted(timestamped_ids, reverse=True)
            + sorted(null_ids, reverse=True)
        )
        assert [row.created_at is None for row in rows] == (
            [False] * 25 + [True] * 22
        )
        assert [(cursor.null_rank, cursor.created_at is None) for cursor in cursors] == [
            (0, False),
            (1, True),
        ]


def test_more_than_twenty_null_rows_page_by_id_desc(client):
    with app.app_context():
        viewer = _make_user("outgoing-null-only-viewer")
        null_ids = [
            _pending(
                viewer,
                _make_user(f"outgoing-null-only-{index}"),
            ).id
            for index in range(41)
        ]
        _persist_null_created_at(*null_ids)
        db.session.commit()

        rows, cursors, total_count = _traverse(viewer.id)

        assert total_count == 41
        assert [row.invitation_id for row in rows] == sorted(
            null_ids, reverse=True
        )
        assert all(row.created_at is None for row in rows)
        assert len({row.invitation_id for row in rows}) == 41
        assert [(cursor.null_rank, cursor.created_at) for cursor in cursors] == [
            (1, None),
            (1, None),
        ]


def test_service_statement_budget_is_fixed(client):
    with app.app_context():
        viewer = _make_user("outgoing-budget-viewer")
        for index in range(41):
            _pending(viewer, _make_user(f"outgoing-budget-{index}"))
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine
        statements = []

        def record(_connection, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            page = load_outgoing_requests_page(viewer_id)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        assert len(page.rows) == 20
        assert page.total_count == 41
        assert len(statements) == 2


def test_nullable_paging_keeps_two_statements_per_page(client):
    with app.app_context():
        viewer = _make_user("outgoing-null-budget-viewer")
        invitation_ids = [
            _pending(
                viewer,
                _make_user(f"outgoing-null-budget-{index}"),
            ).id
            for index in range(41)
        ]
        _persist_null_created_at(*invitation_ids)
        db.session.commit()
        viewer_id = viewer.id
        engine = db.engine
        cursor = None
        page_sizes = []

        while True:
            statements = []

            def record(_connection, _cursor, statement, _params, _context, _many):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                page = load_outgoing_requests_page(viewer_id, cursor)
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert len(statements) == 2
            page_sizes.append(len(page.rows))
            if not page.has_more:
                break
            cursor = page.next_cursor

        assert page_sizes == [20, 20, 1]


def test_route_is_authenticated_and_renders_collapsed_disclosure(client):
    assert client.get("/api/friends/outgoing/page").status_code in (302, 401, 403)

    with app.app_context():
        viewer = _make_user("outgoing-route-viewer")
        target = _make_user("outgoing-route-target")
        invitation = _pending(viewer, target)
        db.session.commit()
        viewer_id = viewer.id
        invitation_id = invitation.id

    _login(client, viewer_id)
    response = client.get("/friends")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<details class="fr-sent-disclosure" id="fr-sent-disclosure">' in html
    assert "Sent requests" in html
    assert 'id="fr-sent-count">1</span>' in html
    assert f'data-outgoing-invitation-id="{invitation_id}"' in html
    assert "open>" not in html

    endpoint = client.get("/api/friends/outgoing/page")
    assert endpoint.status_code == 200
    assert (
        f'data-outgoing-invitation-id="{invitation_id}"'
        in endpoint.get_json()["html"]
    )
    assert "invitation_ids" not in endpoint.get_json()


def test_disclosure_is_absent_at_zero(client):
    with app.app_context():
        viewer = _make_user("outgoing-empty-viewer")
        db.session.commit()
        viewer_id = viewer.id
    _login(client, viewer_id)
    html = client.get("/friends").get_data(as_text=True)
    assert '<details class="fr-sent-disclosure"' not in html
    assert "<span>Sent requests</span>" not in html


def test_all_three_request_creation_paths_appear(client):
    with app.app_context():
        viewer = _make_user("outgoing-path-viewer")
        global_target = _make_user("outgoing-global")
        suggested_target = _make_user("outgoing-suggested")
        email_target = _make_user(
            "outgoing-email", email="outgoing-email-target@example.test"
        )
        suggestion = FriendSuggestion(
            suggester_id=global_target.id,
            recipient_id=viewer.id,
            suggested_user_id=suggested_target.id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.session.add(suggestion)
        db.session.commit()
        viewer_id = viewer.id
        global_id = global_target.id
        suggested_id = suggested_target.id

    _login(client, viewer_id)
    assert json_post(
        client, f"/api/users/{global_id}/connect"
    ).status_code == 201
    assert json_post(
        client,
        "/api/friends/suggestions/connect",
        {"user_id": suggested_id},
    ).status_code == 201
    assert json_post(
        client,
        "/api/friends/invite",
        {"friend_email": "outgoing-email-target@example.test"},
    ).status_code == 201

    payload = client.get("/api/friends/outgoing/page").get_json()
    assert payload["total_count"] == 3
    assert payload["html"].count("data-outgoing-invitation-id=") == 3


def test_suggested_request_is_canonical_and_suggestion_survives_withdrawal(client):
    with app.app_context():
        viewer = _make_user("outgoing-sugg-viewer")
        suggester = _make_user("outgoing-sugg-suggester")
        target = _make_user("outgoing-sugg-target")
        suggestion = FriendSuggestion(
            suggester_id=suggester.id,
            recipient_id=viewer.id,
            suggested_user_id=target.id,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.session.add(suggestion)
        db.session.commit()
        viewer_id = viewer.id
        target_id = target.id
        suggestion_id = suggestion.id

    _login(client, viewer_id)
    created = json_post(
        client,
        "/api/friends/suggestions/connect",
        {"user_id": target_id},
    )
    invitation_id = created.get_json()["invitation_id"]
    outgoing = client.get("/api/friends/outgoing/page").get_json()
    suggested = client.get("/api/friends/suggestions/page").get_json()["html"]
    assert (
        f'data-outgoing-invitation-id="{invitation_id}"'
        in outgoing["html"]
    )
    assert f'data-sugg-invitation-id="{invitation_id}"' in suggested
    assert ">Requested</button>" in suggested

    assert json_delete(
        client, f"/api/friends/invite/{invitation_id}"
    ).status_code == 200
    assert client.get(
        "/api/friends/outgoing/page"
    ).get_json()["total_count"] == 0
    refreshed = client.get("/api/friends/suggestions/page").get_json()["html"]
    assert ">Request withdrawn</button>" in refreshed
    with app.app_context():
        assert db.session.get(FriendSuggestion, suggestion_id).dismissed_at is None


def test_resolved_requests_disappear_and_stale_withdrawal_remains_safe(client):
    with app.app_context():
        viewer = _make_user("outgoing-lifecycle-viewer")
        accepted_target = _make_user("outgoing-accepted")
        declined_target = _make_user("outgoing-declined")
        stale_target = _make_user("outgoing-stale")
        accepted = _pending(viewer, accepted_target)
        declined = _pending(viewer, declined_target)
        stale = _pending(viewer, stale_target)
        db.session.commit()
        viewer_id = viewer.id
        accepted_id, declined_id, stale_id = accepted.id, declined.id, stale.id

    with app.app_context():
        db.session.get(Invitation, accepted_id).status = "accepted"
        db.session.get(Invitation, declined_id).status = "declined"
        db.session.commit()

    _login(client, viewer_id)
    payload = client.get("/api/friends/outgoing/page").get_json()
    assert f'data-outgoing-invitation-id="{stale_id}"' in payload["html"]
    assert f'data-outgoing-invitation-id="{accepted_id}"' not in payload["html"]
    assert f'data-outgoing-invitation-id="{declined_id}"' not in payload["html"]
    assert json_delete(
        client, f"/api/friends/invite/{stale_id}"
    ).status_code == 200
    assert json_delete(
        client, f"/api/friends/invite/{stale_id}"
    ).status_code == 409
    assert client.get(
        "/api/friends/outgoing/page"
    ).get_json()["total_count"] == 0


def test_ui_reuses_canonical_mutation_and_targeted_refresh():
    source = Path("templates/friends.html").read_text()
    start = source.index("function frCancelSentRequest")
    handler = source[
        start:source.index(
            "// ── Accept / Decline friend requests",
            start,
        )
    ]
    assert "DELETE" in handler
    assert "'/api/friends/invite/' + invitationId" in handler
    assert "result.status === 404 || result.status === 409" in handler
    assert "frRefreshRegions(['requests', 'suggestions'])" in handler
    assert "btn.textContent = 'Refresh needed'" in handler
    assert "Request status changed. Pull to refresh." in handler
    assert "location.reload" not in handler
    assert "document.addEventListener('visibilitychange'" in source
    assert "window.addEventListener('pageshow'" in source
    assert ".fr-load-more[hidden] { display: none; }" in source