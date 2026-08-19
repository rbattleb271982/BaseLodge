from datetime import date, timedelta

from app import app, run_trip_rsvp_migration
from conftest import _login, _make_trip, _make_user, json_post
from models import GroupTrip, GuestStatus, SkiTripParticipant, TripGuest, db


def test_owner_going_rsvp_survives_repeat_migration(client):
    """Startup migration must preserve a canonical organizer RSVP on rerun."""
    with app.app_context():
        owner = _make_user("rsvp-owner")
        trip = _make_trip(owner)
        participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id, user_id=owner.id
        ).one()
        participant.status = GuestStatus.GOING
        db.session.commit()

        run_trip_rsvp_migration()
        db.session.expire_all()
        assert SkiTripParticipant.query.filter_by(
            trip_id=trip.id, user_id=owner.id
        ).one().status == GuestStatus.GOING

        run_trip_rsvp_migration()
        db.session.expire_all()
        assert SkiTripParticipant.query.filter_by(
            trip_id=trip.id, user_id=owner.id
        ).one().status == GuestStatus.GOING


def test_organizer_cannot_decline_own_trip(client):
    with app.app_context():
        owner = _make_user("organizer-rsvp")
        trip = _make_trip(owner)
        db.session.commit()
        owner_id, trip_id = owner.id, trip.id

    _login(client, owner_id)
    response = json_post(client, f"/trips/{trip_id}/rsvp", {"response": "declined"})
    assert response.status_code == 400

    with app.app_context():
        assert SkiTripParticipant.query.filter_by(
            trip_id=trip_id, user_id=owner_id
        ).one().status == GuestStatus.INTERESTED


def test_legacy_accepted_trip_guest_starts_planning_but_pending_does_not(client):
    with app.app_context():
        host = _make_user("legacy-host")
        accepted_user = _make_user("legacy-accepted")
        pending_user = _make_user("legacy-pending")
        legacy_trip = GroupTrip(
            host_id=host.id,
            title="Legacy group trip",
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=12),
        )
        db.session.add(legacy_trip)
        db.session.flush()
        db.session.add_all([
            TripGuest(
                trip_id=legacy_trip.id,
                user_id=accepted_user.id,
                status=GuestStatus.ACCEPTED,
            ),
            TripGuest(
                trip_id=legacy_trip.id,
                user_id=pending_user.id,
                status=GuestStatus.INVITED,
            ),
        ])
        db.session.commit()

        assert accepted_user.has_started_planning is True
        assert pending_user.has_started_planning is False