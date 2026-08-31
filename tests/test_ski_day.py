"""Persistence and foreign-key coverage for the canonical SkiDay foundation."""

from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest.mock

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from app import app
from models import GuestStatus, SkiDay, SkiTripParticipant, db
from tests.conftest import (
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


def _ski_day(user, resort, ski_date, **kwargs):
    return SkiDay(
        user_id=user.id,
        resort_id=resort.id,
        ski_date=ski_date,
        source=kwargs.pop("source", "user_confirmation"),
        **kwargs,
    )


def _enable_sqlite_foreign_keys():
    db.session.commit()
    db.session.connection().exec_driver_sql("PRAGMA foreign_keys = ON")
    assert db.session.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1


def test_ski_day_persists_required_confirmation_fields(client):
    with app.app_context():
        user = _make_user("ski-day")
        resort = _make_resort()
        day = _ski_day(user, resort, date(2026, 1, 10))
        db.session.add(day)
        db.session.commit()

        stored = db.session.get(SkiDay, day.id)
        assert stored.user_id == user.id
        assert stored.resort_id == resort.id
        assert stored.ski_date == date(2026, 1, 10)
        assert stored.source == "user_confirmation"
        assert stored.trip_id is None
        assert stored.confirmed_at is not None
        assert stored.created_at is not None
        assert stored.updated_at is not None


def test_first_ski_day_adds_its_resort_to_canonical_visited_ids(client):
    with app.app_context():
        user = _make_user("sync-first")
        resort = _make_resort()
        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        db.session.commit()
        db.session.refresh(user)

        assert user.visited_resort_ids == [resort.id]
        assert user.mountains_visited == []


def test_additional_ski_days_at_same_resort_do_not_duplicate_visited_id(client):
    with app.app_context():
        user = _make_user("sync-repeat")
        resort = _make_resort()
        db.session.add_all([
            _ski_day(user, resort, date(2026, 1, 10)),
            _ski_day(user, resort, date(2026, 1, 11)),
        ])
        db.session.commit()
        db.session.refresh(user)

        assert user.visited_resort_ids == [resort.id]


def test_ski_day_sync_preserves_existing_manual_and_legacy_visit_data(client):
    with app.app_context():
        user = _make_user("sync-manual")
        resort = _make_resort()
        user.visited_resort_ids = [resort.id]
        user.mountains_visited = ["Manual Mountain"]
        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        db.session.commit()
        db.session.refresh(user)

        assert user.visited_resort_ids == [resort.id]
        assert user.mountains_visited == ["Manual Mountain"]


def test_ski_days_sync_distinct_resorts_without_touching_another_user(client):
    with app.app_context():
        user = _make_user("sync-owner")
        other = _make_user("sync-other")
        first_resort = _make_resort()
        second_resort = _make_resort()
        db.session.add_all([
            _ski_day(user, first_resort, date(2026, 1, 10)),
            _ski_day(user, second_resort, date(2026, 1, 11)),
            _ski_day(other, first_resort, date(2026, 1, 10)),
        ])
        db.session.commit()
        db.session.refresh(user)
        db.session.refresh(other)

        assert user.visited_resort_ids == [first_resort.id, second_resort.id]
        assert other.visited_resort_ids == [first_resort.id]


def test_ski_day_source_uses_controlled_vocabulary(client):
    with app.app_context():
        user = _make_user("source")
        resort = _make_resort()
        with pytest.raises(ValueError, match="Unsupported SkiDay source"):
            _ski_day(user, resort, date(2026, 1, 10), source="guessed_profile")


def test_ski_day_unique_per_user_resort_and_date(client):
    with app.app_context():
        user = _make_user("duplicate")
        resort = _make_resort()
        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        db.session.commit()

        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_ski_day_allows_distinct_dates_resorts_and_users(client):
    with app.app_context():
        user = _make_user("owner")
        other = _make_user("other")
        first_resort = _make_resort()
        second_resort = _make_resort()
        same_day = date(2026, 1, 10)
        db.session.add_all([
            _ski_day(user, first_resort, same_day),
            _ski_day(user, first_resort, same_day + timedelta(days=1)),
            _ski_day(user, second_resort, same_day),
            _ski_day(other, first_resort, same_day),
        ])
        db.session.commit()

        assert SkiDay.query.count() == 4


def test_ski_day_stays_independent_when_trip_changes(client):
    with app.app_context():
        user = _make_user("trip-edit")
        resort = _make_resort()
        replacement_resort = _make_resort()
        trip = _make_trip(user, resort=resort)
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=user.id,
        ).one()
        day = _ski_day(
            user,
            resort,
            date(2026, 1, 10),
            trip_id=trip.id,
            source="trip_confirmation",
        )
        db.session.add(day)
        db.session.commit()

        trip.start_date = date(2026, 2, 1)
        trip.end_date = date(2026, 2, 4)
        trip.resort_id = replacement_resort.id
        trip.is_public = False
        participant.status = GuestStatus.DECLINED
        db.session.commit()
        db.session.refresh(day)

        assert day.resort_id == resort.id
        assert day.ski_date == date(2026, 1, 10)
        assert day.trip_id == trip.id


def test_trip_cancellation_preserves_ski_day_and_trip_reference(client):
    with app.app_context():
        _enable_sqlite_foreign_keys()
        owner = _make_user("trip-delete")
        resort = _make_resort()
        trip = _make_trip(owner, resort=resort)
        day = _ski_day(
            owner,
            resort,
            date(2026, 1, 10),
            trip_id=trip.id,
            source="trip_confirmation",
        )
        db.session.add(day)
        db.session.commit()
        owner_id = owner.id
        trip_id = trip.id
        day_id = day.id

    _login(client, owner_id)
    with unittest.mock.patch("app.delete_availability_overlap_activities_for_trip"):
        response = json_post(client, f"/api/trip/{trip_id}/delete")
    assert response.status_code == 200

    with app.app_context():
        stored = db.session.get(SkiDay, day_id)
        assert stored is not None
        assert stored.trip_id == trip_id


def test_ski_day_resort_fk_restricts_history_destroying_delete(client):
    with app.app_context():
        _enable_sqlite_foreign_keys()
        user = _make_user("resort-delete")
        resort = _make_resort()
        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        db.session.commit()

        with pytest.raises(IntegrityError):
            db.session.execute(sa.delete(type(resort)).where(type(resort).id == resort.id))
            db.session.commit()
        db.session.rollback()

        assert db.session.get(type(resort), resort.id) is not None
        assert SkiDay.query.count() == 1


def test_ski_day_hard_delete_allows_a_corrected_replacement(client):
    with app.app_context():
        user = _make_user("correct")
        resort = _make_resort()
        day = _ski_day(user, resort, date(2026, 1, 10))
        db.session.add(day)
        db.session.commit()

        db.session.delete(day)
        db.session.commit()
        db.session.add(_ski_day(user, resort, date(2026, 1, 10)))
        db.session.commit()

        assert SkiDay.query.filter_by(
            user_id=user.id,
            resort_id=resort.id,
            ski_date=date(2026, 1, 10),
        ).count() == 1


def test_deleting_ski_day_does_not_remove_visited_resort(client):
    with app.app_context():
        user = _make_user("sync-delete")
        resort = _make_resort()
        day = _ski_day(user, resort, date(2026, 1, 10))
        db.session.add(day)
        db.session.commit()
        day_id = day.id
        user_id = user.id

        db.session.delete(day)
        db.session.commit()
        stored_user = db.session.get(type(user), user_id)

        assert db.session.get(SkiDay, day_id) is None
        assert stored_user.visited_resort_ids == [resort.id]


def test_correcting_ski_day_adds_new_resort_and_retains_old_visit(client):
    with app.app_context():
        user = _make_user("sync-correct")
        old_resort = _make_resort()
        new_resort = _make_resort()
        day = _ski_day(user, old_resort, date(2026, 1, 10))
        db.session.add(day)
        db.session.commit()

        day.resort_id = new_resort.id
        db.session.commit()
        db.session.refresh(user)

        assert user.visited_resort_ids == [old_resort.id, new_resort.id]


def test_existing_manual_mountains_visited_add_and_remove_still_work(client):
    with app.app_context():
        user = _make_user("manual-api")
        first_resort = _make_resort()
        second_resort = _make_resort()
        first_resort_id = first_resort.id
        second_resort_id = second_resort.id
        db.session.commit()
        user_id = user.id

    _login(client, user_id)
    assert json_post(
        client,
        "/api/mountains-visited/add",
        {"resort_id": first_resort_id},
    ).status_code == 200
    assert json_post(
        client,
        "/api/mountains-visited/add",
        {"resort_id": second_resort_id},
    ).status_code == 200
    assert json_post(
        client,
        "/api/mountains-visited/remove",
        {"resort_id": first_resort_id},
    ).status_code == 200

    with app.app_context():
        user = db.session.get(type(user), user_id)
        assert user.visited_resort_ids == [second_resort_id]


def test_ski_day_supports_future_per_resort_day_aggregation(client):
    with app.app_context():
        user = _make_user("aggregate")
        resort = _make_resort()
        other_resort = _make_resort()
        db.session.add_all([
            _ski_day(user, resort, date(2026, 1, 10)),
            _ski_day(user, resort, date(2026, 1, 11)),
            _ski_day(user, other_resort, date(2026, 1, 10)),
        ])
        db.session.commit()

        totals = dict(
            db.session.query(SkiDay.resort_id, sa.func.count(SkiDay.id))
            .filter(SkiDay.user_id == user.id)
            .group_by(SkiDay.resort_id)
            .all()
        )
        assert totals == {resort.id: 2, other_resort.id: 1}


def test_ski_day_migration_upgrades_and_downgrades_with_expected_fk_actions():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "bl305_ski_day_foundation.py"
    )
    spec = spec_from_file_location("bl305_ski_day_foundation", migration_path)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("resort", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("ski_trip", metadata, sa.Column("id", sa.Integer, primary_key=True))

    with engine.begin() as connection:
        metadata.create_all(connection)
        operations = Operations(MigrationContext.configure(connection))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            inspector = sa.inspect(connection)
            assert "ski_day" in inspector.get_table_names()
            assert {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("ski_day")
            } == {"uq_ski_day_user_resort_date"}
            fk_actions = {
                fk["referred_table"]: fk["options"].get("ondelete")
                for fk in inspector.get_foreign_keys("ski_day")
            }
            assert fk_actions == {
                "user": "CASCADE",
                "resort": "RESTRICT",
                "ski_trip": "SET NULL",
            }
            assert {
                index["name"]
                for index in inspector.get_indexes("ski_day")
            } == {
                "ix_ski_day_user_id",
                "ix_ski_day_resort_id",
                "ix_ski_day_trip_id",
            }
            migration.downgrade()
            assert "ski_day" not in sa.inspect(connection).get_table_names()
        finally:
            migration.op = original_op
