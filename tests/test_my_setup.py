"""
#242 — My Setup isolation tests (spec section 4).

Verifies that pass_type is stored per-participant (not on the SkiTrip row)
and that one user's update never changes another's.

Setup context is CLOSED before yield; assertions use their own
`with app.app_context():` blocks.
"""
import pytest
from app import app
from models import db, SkiTripParticipant, SkiTrip, GuestStatus, ParticipantRole
from tests.conftest import (
    _make_user, _make_resort, _make_trip, _add_participant,
    _login, json_post,
)


@pytest.fixture
def setup(client):
    with app.app_context():
        resort = _make_resort()
        owner  = _make_user("owner")
        part   = _make_user("participant")
        trip   = _make_trip(owner, resort=resort)
        _add_participant(trip, part, GuestStatus.INTERESTED)
        db.session.commit()
        data = {
            "owner_id": owner.id,
            "part_id":  part.id,
            "trip_id":  trip.id,
        }
    yield data


def test_owner_and_participant_pass_types_are_independent(client, setup):
    owner_id = setup["owner_id"]
    part_id  = setup["part_id"]
    trip_id  = setup["trip_id"]

    _login(client, owner_id)
    rv = json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "epic"})
    assert rv.status_code == 200

    _login(client, part_id)
    rv = json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "ikon"})
    assert rv.status_code == 200

    with app.app_context():
        owner_row = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).first()
        part_row = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=part_id
        ).first()
        assert owner_row is not None
        assert part_row is not None
        assert "epic" in (owner_row.pass_type or ""), (
            f"Owner row should have 'epic', got {owner_row.pass_type!r}"
        )
        assert "ikon" in (part_row.pass_type or ""), (
            f"Part row should have 'ikon', got {part_row.pass_type!r}"
        )
        assert "ikon" not in (owner_row.pass_type or "")
        assert "epic" not in (part_row.pass_type or "")


def test_participant_update_does_not_affect_owner(client, setup):
    owner_id = setup["owner_id"]
    part_id  = setup["part_id"]
    trip_id  = setup["trip_id"]

    _login(client, owner_id)
    json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "epic"})

    with app.app_context():
        before_pass = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).first().pass_type

    _login(client, part_id)
    json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "ikon"})

    with app.app_context():
        after_pass = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).first().pass_type
    assert after_pass == before_pass, (
        f"Owner pass changed from {before_pass!r} to {after_pass!r} after participant update"
    )


def test_skitrip_pass_type_not_written_by_update_pass(client, setup):
    """SkiTrip.pass_type (legacy field) is NOT updated by update-pass."""
    owner_id = setup["owner_id"]
    trip_id  = setup["trip_id"]

    with app.app_context():
        original = SkiTrip.query.get(trip_id).pass_type

    _login(client, owner_id)
    json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "ikon"})

    with app.app_context():
        after = SkiTrip.query.get(trip_id).pass_type
    assert after == original, (
        f"SkiTrip.pass_type changed from {original!r} to {after!r} — update-pass must not touch it"
    )


def test_only_accepted_participant_can_update_pass(client, setup):
    """INVITED participant is blocked from updating their pass."""
    trip_id = setup["trip_id"]

    with app.app_context():
        invited = _make_user("invited")
        db.session.add(SkiTripParticipant(
            trip_id=trip_id, user_id=invited.id,
            status=GuestStatus.PENDING, role=ParticipantRole.GUEST,
        ))
        db.session.commit()
        invited_id = invited.id

    _login(client, invited_id)
    rv = json_post(client, f"/api/trip/{trip_id}/update-pass", {"pass_type": "ikon"})
    assert rv.status_code == 403


def test_each_participant_can_have_multiple_passes(client, setup):
    """Pass selection accepts comma-separated multi-value strings."""
    owner_id = setup["owner_id"]
    trip_id  = setup["trip_id"]

    _login(client, owner_id)
    rv = json_post(client, f"/api/trip/{trip_id}/update-pass",
                   {"pass_type": "epic,ikon"})
    assert rv.status_code == 200

    with app.app_context():
        row = SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).first()
        assert row.pass_type is not None
        assert "epic" in row.pass_type
        assert "ikon" in row.pass_type
