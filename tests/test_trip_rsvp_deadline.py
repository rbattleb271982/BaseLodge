"""Focused BL-83 RSVP deadline coverage."""

from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest

from app import app
from models import db, GuestStatus, SkiTrip, SkiTripParticipant
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    form_post,
    json_post,
)


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "bl83_rsvp_deadline.py"
)


@pytest.fixture
def setup(client):
    with app.app_context():
        owner = _make_user("deadline_owner")
        going = _make_user("deadline_going")
        interested = _make_user("deadline_interested")
        pending = _make_user("deadline_pending")
        declined = _make_user("deadline_declined")
        removed = _make_user("deadline_removed")
        outsider = _make_user("deadline_outsider")
        trip = _make_trip(owner, resort=_make_resort())
        participants = {
            going.id: _add_participant(trip, going, GuestStatus.GOING),
            interested.id: _add_participant(
                trip, interested, GuestStatus.INTERESTED
            ),
            pending.id: _add_participant(trip, pending, GuestStatus.PENDING),
            declined.id: _add_participant(
                trip, declined, GuestStatus.DECLINED
            ),
            removed.id: _add_participant(trip, removed, GuestStatus.REMOVED),
        }
        db.session.commit()
        data = {
            "trip_id": trip.id,
            "start_date": trip.start_date,
            "owner_id": owner.id,
            "going_id": going.id,
            "interested_id": interested.id,
            "pending_id": pending.id,
            "declined_id": declined.id,
            "removed_id": removed.id,
            "outsider_id": outsider.id,
            "participant_ids": {
                user_id: participant.id
                for user_id, participant in participants.items()
            },
        }
    return data


def _update(client, trip_id, payload):
    return json_post(
        client,
        f"/api/trip/{trip_id}/update-rsvp-deadline",
        payload,
    )


def test_deadline_defaults_to_null(client, setup):
    with app.app_context():
        assert db.session.get(SkiTrip, setup["trip_id"]).rsvp_deadline is None


def test_organizer_can_add_edit_remove_and_repeat_deadline(client, setup):
    _login(client, setup["owner_id"])
    for value in ("2020-01-02", setup["start_date"].isoformat(), "2099-12-31"):
        response = _update(
            client, setup["trip_id"], {"rsvp_deadline": value}
        )
        assert response.status_code == 200
        assert response.get_json()["rsvp_deadline"] == value

    repeated = _update(
        client, setup["trip_id"], {"rsvp_deadline": "2099-12-31"}
    )
    assert repeated.status_code == 200

    removed = _update(
        client, setup["trip_id"], {"rsvp_deadline": None}
    )
    assert removed.status_code == 200
    assert removed.get_json()["rsvp_deadline"] is None
    with app.app_context():
        assert db.session.get(SkiTrip, setup["trip_id"]).rsvp_deadline is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"rsvp_deadline": 20270101},
        {"rsvp_deadline": True},
        {"rsvp_deadline": "01/02/2027"},
        {"rsvp_deadline": "2027-02-30"},
        {"rsvp_deadline": "2027-1-02"},
    ],
)
def test_invalid_deadline_payloads_are_rejected(client, setup, payload):
    _login(client, setup["owner_id"])
    assert _update(client, setup["trip_id"], payload).status_code == 400


@pytest.mark.parametrize(
    "user_key",
    ["going_id", "interested_id", "pending_id", "outsider_id"],
)
def test_non_organizers_cannot_mutate_deadline(client, setup, user_key):
    _login(client, setup[user_key])
    response = _update(
        client, setup["trip_id"], {"rsvp_deadline": "2027-01-02"}
    )
    assert response.status_code == 403


def test_terminal_trip_deadline_mutation_is_rejected(client, setup):
    with app.app_context():
        trip = db.session.get(SkiTrip, setup["trip_id"])
        trip.lifecycle_state = "completed"
        db.session.commit()
    _login(client, setup["owner_id"])
    assert _update(
        client, setup["trip_id"], {"rsvp_deadline": "2027-01-02"}
    ).status_code == 409


@pytest.mark.parametrize(
    "user_key",
    ["owner_id", "going_id", "interested_id", "pending_id"],
)
def test_authorized_trip_detail_viewers_see_deadline(client, setup, user_key):
    with app.app_context():
        trip = db.session.get(SkiTrip, setup["trip_id"])
        trip.rsvp_deadline = date(2027, 3, 15)
        db.session.commit()
    _login(client, setup[user_key])
    response = client.get(f"/trips/{setup['trip_id']}")
    assert response.status_code == 200
    assert b"RSVP by Mar 15, 2027" in response.data


def test_null_deadline_renders_no_deadline_copy(client, setup):
    _login(client, setup["owner_id"])
    response = client.get(f"/trips/{setup['trip_id']}")
    assert response.status_code == 200
    assert b'id="td-rsvp-deadline-text"' not in response.data


@pytest.mark.parametrize("user_key", ["declined_id", "removed_id", "outsider_id"])
def test_deadline_does_not_broaden_trip_detail_access(client, setup, user_key):
    with app.app_context():
        trip = db.session.get(SkiTrip, setup["trip_id"])
        trip.rsvp_deadline = date(2027, 3, 15)
        db.session.commit()
    _login(client, setup[user_key])
    assert client.get(f"/trips/{setup['trip_id']}").status_code == 404


def test_past_deadline_does_not_block_participant_rsvp(client, setup):
    with app.app_context():
        trip = db.session.get(SkiTrip, setup["trip_id"])
        trip.rsvp_deadline = date.today() - timedelta(days=1)
        db.session.commit()
    _login(client, setup["interested_id"])
    response = form_post(
        client,
        f"/trips/{setup['trip_id']}/rsvp",
        {"status": "going"},
    )
    assert response.status_code in (200, 302)
    with app.app_context():
        participant = db.session.get(
            SkiTripParticipant,
            setup["participant_ids"][setup["interested_id"]],
        )
        assert participant.status == GuestStatus.GOING


def _migration():
    spec = spec_from_file_location("bl83_rsvp_deadline", MIGRATION_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_nullable_date_without_backfill_and_downgrades():
    migration = _migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        sa.Table(
            "ski_trip",
            metadata,
            sa.Column("id", sa.Integer(), primary_key=True),
        )
        metadata.create_all(connection)
        connection.execute(sa.text("INSERT INTO ski_trip (id) VALUES (1)"))
        operations = Operations(MigrationContext.configure(connection))
        original = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            column = {
                item["name"]: item
                for item in sa.inspect(connection).get_columns("ski_trip")
            }["rsvp_deadline"]
            assert isinstance(column["type"], sa.Date)
            assert column["nullable"] is True
            assert connection.execute(
                sa.text("SELECT rsvp_deadline FROM ski_trip WHERE id = 1")
            ).scalar_one() is None
            migration.downgrade()
        finally:
            migration.op = original
        assert "rsvp_deadline" not in {
            item["name"]
            for item in sa.inspect(connection).get_columns("ski_trip")
        }