"""BL-109 derived Suggested Connection Happening regressions."""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from flask import render_template
from sqlalchemy.dialects import postgresql

from app import app
from models import (
    DismissedInsightCard,
    Friend,
    FriendConnectionEvent,
    FriendSuggestion,
    db,
)
from services.happening import (
    _build_suggested_connection_candidates_statement,
    get_suggested_connection_candidates,
)
from tests.conftest import _login, _make_user


BASE = datetime(2026, 8, 1, 12, 0, 0)


def _connect_live(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


def _disconnect_live(first, second):
    Friend.query.filter(
        sa.or_(
            sa.and_(
                Friend.user_id == first.id,
                Friend.friend_id == second.id,
            ),
            sa.and_(
                Friend.user_id == second.id,
                Friend.friend_id == first.id,
            ),
        )
    ).delete(synchronize_session=False)


def _lifecycle(first, second, event_type, occurred_at, *, actor=None):
    user_a_id, user_b_id = sorted((first.id, second.id))
    event = FriendConnectionEvent(
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        event_type=event_type,
        occurred_at=occurred_at,
        actor_user_id=(actor or first).id,
        source="qr_connect" if event_type == "formed" else "api_unfriend",
    )
    db.session.add(event)
    db.session.flush()
    return event


def _suggest(
    introducer,
    recipient,
    suggested,
    created_at,
    *,
    expires_at=None,
    dismissed_at=None,
):
    row = FriendSuggestion(
        suggester_id=introducer.id,
        recipient_id=recipient.id,
        suggested_user_id=suggested.id,
        created_at=created_at,
        expires_at=expires_at or created_at + timedelta(days=30),
        dismissed_at=dismissed_at,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _triangle(*, second_introducer=False):
    introducer = _make_user("bl109-introducer")
    recipient = _make_user("bl109-recipient")
    suggested = _make_user("bl109-suggested")
    _connect_live(introducer, recipient)
    _connect_live(introducer, suggested)
    other = None
    if second_introducer:
        other = _make_user("bl109-other-introducer")
        _connect_live(other, recipient)
        _connect_live(other, suggested)
    return introducer, recipient, suggested, other


def _form_pair(recipient, suggested, occurred_at):
    _connect_live(recipient, suggested)
    return _lifecycle(recipient, suggested, "formed", occurred_at)


def test_suggestion_before_connection_yields_one_first_name_only_candidate(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        suggestion = _suggest(
            introducer, recipient, suggested, BASE,
        )
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.commit()

        rows = get_suggested_connection_candidates(user_id=introducer.id)

        assert len(rows) == 1
        assert rows[0].suggestion_id == suggestion.id
        assert rows[0].formation_event_id == formation.id
        assert rows[0].recipient_first_name == recipient.first_name
        assert rows[0].suggested_first_name == suggested.first_name
        assert rows[0].card_key == (
            f"happening:suggested-connection:{formation.id}"
        )


def test_reversed_pair_and_repeated_suggestions_collapse_per_formation(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        first = _suggest(introducer, recipient, suggested, BASE)
        _suggest(
            introducer,
            suggested,
            recipient,
            BASE + timedelta(minutes=10),
        )
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.commit()

        rows = get_suggested_connection_candidates(user_id=introducer.id)

        assert len(rows) == 1
        assert rows[0].suggestion_id == first.id
        assert rows[0].formation_event_id == formation.id


def test_multiple_suggesters_each_receive_their_own_candidate(client):
    with app.app_context():
        introducer, recipient, suggested, other = _triangle(
            second_introducer=True
        )
        _suggest(introducer, recipient, suggested, BASE)
        _suggest(
            other,
            recipient,
            suggested,
            BASE + timedelta(minutes=5),
        )
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.commit()

        first_rows = get_suggested_connection_candidates(
            user_id=introducer.id
        )
        other_rows = get_suggested_connection_candidates(user_id=other.id)

        assert [row.formation_event_id for row in first_rows] == [formation.id]
        assert [row.formation_event_id for row in other_rows] == [formation.id]


def test_non_suggester_and_unrelated_connection_receive_nothing(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        observer = _make_user("bl109-observer")
        unrelated = _make_user("bl109-unrelated")
        _connect_live(observer, recipient)
        _connect_live(observer, suggested)
        _connect_live(introducer, unrelated)
        _suggest(introducer, recipient, suggested, BASE)
        _form_pair(recipient, unrelated, BASE + timedelta(hours=1))
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []
        assert get_suggested_connection_candidates(user_id=observer.id) == []


def test_suggestion_while_pair_connected_never_qualifies(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _connect_live(recipient, suggested)
        _lifecycle(recipient, suggested, "formed", BASE)
        _suggest(
            introducer,
            recipient,
            suggested,
            BASE + timedelta(hours=1),
        )
        _lifecycle(
            recipient,
            suggested,
            "formed",
            BASE + timedelta(hours=2),
        )
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []


def test_formation_at_same_timestamp_is_not_after_suggestion(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _suggest(introducer, recipient, suggested, BASE)
        _form_pair(recipient, suggested, BASE)
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []


@pytest.mark.parametrize("removed_edge", ("introducer_recipient",
                                           "introducer_suggested",
                                           "recipient_suggested"))
def test_current_reciprocal_privacy_suppresses_removed_edges(
    client, removed_edge
):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _suggest(introducer, recipient, suggested, BASE)
        _form_pair(recipient, suggested, BASE + timedelta(hours=1))
        edges = {
            "introducer_recipient": (introducer, recipient),
            "introducer_suggested": (introducer, suggested),
            "recipient_suggested": (recipient, suggested),
        }
        _disconnect_live(*edges[removed_edge])
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []


def test_old_suggestion_does_not_rematch_reconnection_and_new_one_can(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        old = _suggest(introducer, recipient, suggested, BASE)
        first_formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        _disconnect_live(recipient, suggested)
        _lifecycle(
            recipient,
            suggested,
            "removed",
            BASE + timedelta(hours=2),
        )
        new = _suggest(
            introducer,
            recipient,
            suggested,
            BASE + timedelta(hours=3),
            dismissed_at=BASE + timedelta(hours=3, minutes=5),
        )
        second_formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=4),
        )
        db.session.commit()

        rows = get_suggested_connection_candidates(user_id=introducer.id)
        matches = {
            row.suggestion_id: row.formation_event_id for row in rows
        }

        assert matches == {
            old.id: first_formation.id,
            new.id: second_formation.id,
        }


def test_pre_history_suggestion_does_not_match_after_removal_and_reconnect(
    client,
):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _suggest(introducer, recipient, suggested, BASE)
        # The original formation predates lifecycle history and is absent. A
        # later recorded removal is enough to prevent attribution to reconnect.
        _lifecycle(
            recipient,
            suggested,
            "removed",
            BASE + timedelta(hours=1),
        )
        _connect_live(recipient, suggested)
        _lifecycle(
            recipient,
            suggested,
            "formed",
            BASE + timedelta(hours=2),
        )
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []


@pytest.mark.parametrize("historical_state", ("expired", "dismissed"))
def test_expired_and_dismissed_suggestions_remain_historical_evidence(
    client, historical_state
):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        kwargs = {}
        if historical_state == "expired":
            kwargs["expires_at"] = BASE + timedelta(minutes=5)
        else:
            kwargs["dismissed_at"] = BASE + timedelta(minutes=5)
        _suggest(introducer, recipient, suggested, BASE, **kwargs)
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.commit()

        rows = get_suggested_connection_candidates(user_id=introducer.id)

        assert [row.formation_event_id for row in rows] == [formation.id]


def test_dismissed_confirmation_is_recipient_specific_and_does_not_return(
    client,
):
    with app.app_context():
        introducer, recipient, suggested, other = _triangle(
            second_introducer=True
        )
        _suggest(introducer, recipient, suggested, BASE)
        _suggest(other, recipient, suggested, BASE)
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.add(DismissedInsightCard(
            user_id=introducer.id,
            card_type="happening",
            card_key=f"happening:suggested-connection:{formation.id}",
        ))
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []
        assert len(get_suggested_connection_candidates(user_id=other.id)) == 1


@pytest.mark.parametrize("removed_direction", ("forward", "reverse"))
def test_one_way_friendship_drift_does_not_authorize_visibility(
    client, removed_direction
):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _suggest(introducer, recipient, suggested, BASE)
        _form_pair(recipient, suggested, BASE + timedelta(hours=1))
        if removed_direction == "forward":
            Friend.query.filter_by(
                user_id=introducer.id,
                friend_id=recipient.id,
            ).delete()
        else:
            Friend.query.filter_by(
                user_id=recipient.id,
                friend_id=introducer.id,
            ).delete()
        db.session.commit()

        assert get_suggested_connection_candidates(
            user_id=introducer.id
        ) == []


def test_real_dismissal_post_is_idempotent_for_confirmation(client):
    with app.app_context():
        introducer, recipient, suggested, _ = _triangle()
        _suggest(introducer, recipient, suggested, BASE)
        formation = _form_pair(
            recipient, suggested, BASE + timedelta(hours=1),
        )
        db.session.commit()
        introducer_id = introducer.id
        card_key = f"happening:suggested-connection:{formation.id}"

    _login(client, introducer_id)
    for _ in range(2):
        response = client.post(
            "/dismiss-insight-card",
            data={
                "card_type": "happening",
                "card_key": card_key,
                "csrf_token": "test-csrf-fixed-value-baselodge-regression",
            },
        )
        assert response.status_code == 204

    with app.app_context():
        assert DismissedInsightCard.query.filter_by(
            user_id=introducer_id,
            card_type="happening",
            card_key=card_key,
        ).count() == 1
        assert get_suggested_connection_candidates(
            user_id=introducer_id
        ) == []


def test_query_is_bounded_single_select_and_compiles_for_postgresql(client):
    with app.app_context():
        introducer = _make_user("bl109-bounded-introducer")
        for index in range(7):
            recipient = _make_user(f"bl109-bounded-recipient-{index}")
            suggested = _make_user(f"bl109-bounded-suggested-{index}")
            _connect_live(introducer, recipient)
            _connect_live(introducer, suggested)
            _suggest(
                introducer,
                recipient,
                suggested,
                BASE + timedelta(minutes=index),
            )
            _form_pair(
                recipient,
                suggested,
                BASE + timedelta(hours=1, minutes=index),
            )
        introducer_id = introducer.id
        db.session.commit()
        statements = []

        def capture(_conn, _cursor, statement, parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement, parameters))

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            rows = get_suggested_connection_candidates(
                user_id=introducer_id,
                limit=5,
            )
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)

        statement = _build_suggested_connection_candidates_statement(
            user_id=introducer_id,
            limit=5,
        )
        postgres_sql = str(statement.compile(dialect=postgresql.dialect()))

        assert len(rows) == 5
        assert len(statements) == 1
        assert "row_number() OVER" in postgres_sql
        assert "LIMIT" in postgres_sql
        assert "NULLS LAST" in postgres_sql


def test_template_renders_approved_non_causal_copy_without_private_metadata(
    client,
):
    signal = {
        "kind": "suggested_connection",
        "headline": "John and Sarah connected",
        "detail": "You suggested they knew each other.",
        "_card_key": "happening:suggested-connection:42",
    }
    with app.test_request_context("/home"):
        html = render_template(
            "partials/home/_section_happening.html",
            happening_signals=[signal],
        )

    assert "John and Sarah connected" in html
    assert "You suggested they knew each other." in html
    assert "introduced" not in html
    assert "caused" not in html
    assert "source" not in html
    assert "actor" not in html
    assert "happening:suggested-connection:42" in html