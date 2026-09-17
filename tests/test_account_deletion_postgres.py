"""PostgreSQL FK-enforcement coverage for account hard deletion."""

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa

from app import app, limiter
from models import (
    FriendCooldown,
    FriendSuggestion,
    Invitation,
    SkiTrip,
    SuggestionPushCooldown,
    User,
    db,
)
from test_import_reference_data_postgres import (
    _initialized_database,
    disposable_postgres,
)
from tests.conftest import (
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    _swap_engine,
    form_post,
)


@pytest.fixture
def postgres_account_deletion_client(disposable_postgres, monkeypatch):
    database_url = _initialized_database(
        disposable_postgres, monkeypatch, "account-deletion"
    )
    engine = sa.create_engine(database_url, pool_pre_ping=True)
    saved_engine = _swap_engine(engine)
    original_limiter_enabled = limiter.enabled
    limiter.enabled = False
    try:
        yield app.test_client(), engine
    finally:
        with app.app_context():
            db.session.remove()
        limiter.enabled = original_limiter_enabled
        _swap_engine(saved_engine)
        engine.dispose()


def _delete_rules(engine):
    inspector = sa.inspect(engine)
    rules = {}
    for table in (
        "friend_cooldown",
        "friend_suggestion",
        "invitation",
        "suggestion_push_cooldown",
    ):
        for foreign_key in inspector.get_foreign_keys(table):
            columns = tuple(foreign_key["constrained_columns"])
            rules[(table, columns)] = (
                foreign_key.get("options", {}).get("ondelete") or "NO ACTION"
            )
    return rules


def test_account_deletion_handles_no_action_relationships_on_postgres(
    postgres_account_deletion_client,
):
    client, engine = postgres_account_deletion_client
    with app.app_context():
        resort = _make_resort()
        doomed = _make_user("pg-delete", auth_provider="email")
        survivor_a = _make_user("pg-survivor-a")
        survivor_b = _make_user("pg-survivor-b")
        survivor_c = _make_user("pg-survivor-c")
        invited_user = _make_user(
            "pg-invited", invited_by_user_id=doomed.id
        )
        owned_trip = _make_trip(doomed, resort=resort)
        surviving_trip = _make_trip(
            survivor_a,
            resort=resort,
            created_by_user_id=doomed.id,
        )
        trip_invitation = Invitation(
            sender_id=survivor_a.id,
            receiver_id=survivor_b.id,
            trip_id=owned_trip.id,
            status="pending",
        )
        expires_at = datetime.utcnow() + timedelta(days=30)
        doomed_suggestions = [
            FriendSuggestion(
                suggester_id=doomed.id,
                recipient_id=survivor_a.id,
                suggested_user_id=survivor_b.id,
                expires_at=expires_at,
            ),
            FriendSuggestion(
                suggester_id=survivor_a.id,
                recipient_id=doomed.id,
                suggested_user_id=survivor_b.id,
                expires_at=expires_at,
            ),
            FriendSuggestion(
                suggester_id=survivor_a.id,
                recipient_id=survivor_b.id,
                suggested_user_id=doomed.id,
                expires_at=expires_at,
            ),
        ]
        unrelated_suggestion = FriendSuggestion(
            suggester_id=survivor_a.id,
            recipient_id=survivor_b.id,
            suggested_user_id=survivor_c.id,
            expires_at=expires_at,
        )
        doomed_cooldowns = [
            SuggestionPushCooldown(
                suggester_id=doomed.id,
                recipient_id=survivor_a.id,
                last_sent_at=datetime.utcnow(),
            ),
            SuggestionPushCooldown(
                suggester_id=survivor_a.id,
                recipient_id=doomed.id,
                last_sent_at=datetime.utcnow(),
            ),
        ]
        unrelated_cooldown = SuggestionPushCooldown(
            suggester_id=survivor_a.id,
            recipient_id=survivor_b.id,
            last_sent_at=datetime.utcnow(),
        )
        doomed_friend_cooldown = FriendCooldown(
            user_a_id=min(doomed.id, survivor_a.id),
            user_b_id=max(doomed.id, survivor_a.id),
            expires_at=expires_at,
        )
        unrelated_friend_cooldown = FriendCooldown(
            user_a_id=min(survivor_a.id, survivor_b.id),
            user_b_id=max(survivor_a.id, survivor_b.id),
            expires_at=expires_at,
        )
        db.session.add_all([
            trip_invitation,
            *doomed_suggestions,
            unrelated_suggestion,
            *doomed_cooldowns,
            unrelated_cooldown,
            doomed_friend_cooldown,
            unrelated_friend_cooldown,
        ])
        db.session.commit()
        ids = {
            "doomed": doomed.id,
            "email": doomed.email,
            "owned_trip": owned_trip.id,
            "surviving_trip": surviving_trip.id,
            "invited_user": invited_user.id,
            "trip_invitation": trip_invitation.id,
            "unrelated_suggestion": unrelated_suggestion.id,
            "unrelated_cooldown": unrelated_cooldown.id,
            "unrelated_friend_cooldown": unrelated_friend_cooldown.id,
            "survivors": [survivor_a.id, survivor_b.id, survivor_c.id],
        }

    rules = _delete_rules(engine)
    assert rules[("invitation", ("trip_id",))] == "NO ACTION"
    for column in ("suggester_id", "recipient_id", "suggested_user_id"):
        assert rules[("friend_suggestion", (column,))] == "NO ACTION"
    for column in ("suggester_id", "recipient_id"):
        assert rules[("suggestion_push_cooldown", (column,))] == "NO ACTION"
    for column in ("user_a_id", "user_b_id"):
        assert rules[("friend_cooldown", (column,))] == "CASCADE"

    _login(client, ids["doomed"])
    response = form_post(
        client,
        "/delete-account",
        data={"confirm_email": ids["email"]},
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(User, ids["doomed"]) is None
        assert db.session.get(SkiTrip, ids["owned_trip"]) is None
        assert db.session.get(Invitation, ids["trip_invitation"]) is None
        assert FriendSuggestion.query.filter(
            sa.or_(
                FriendSuggestion.suggester_id == ids["doomed"],
                FriendSuggestion.recipient_id == ids["doomed"],
                FriendSuggestion.suggested_user_id == ids["doomed"],
            )
        ).count() == 0
        assert SuggestionPushCooldown.query.filter(
            sa.or_(
                SuggestionPushCooldown.suggester_id == ids["doomed"],
                SuggestionPushCooldown.recipient_id == ids["doomed"],
            )
        ).count() == 0
        assert db.session.get(
            FriendSuggestion, ids["unrelated_suggestion"]
        ) is not None
        assert db.session.get(
            SuggestionPushCooldown, ids["unrelated_cooldown"]
        ) is not None
        assert db.session.get(
            FriendCooldown, ids["unrelated_friend_cooldown"]
        ) is not None
        assert all(db.session.get(User, user_id) for user_id in ids["survivors"])
        assert db.session.get(
            User, ids["invited_user"]
        ).invited_by_user_id is None
        assert db.session.get(
            SkiTrip, ids["surviving_trip"]
        ).created_by_user_id is None