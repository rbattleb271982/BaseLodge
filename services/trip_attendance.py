"""Status-aware attendance windows for shared trips.

Trip dates remain the organizer's planning window.  A Going guest may narrow
their own physical attendance with a complete participant date range.
"""

from models import GuestStatus


def participant_is_going(participant):
    """Return whether a participant has the explicit Going RSVP."""
    if participant is None:
        return False
    status = getattr(participant, "status", None)
    return getattr(status, "value", status) == GuestStatus.GOING.value


def effective_attendance_dates(trip, participant=None):
    """Return the physical attendance range represented by ``trip``.

    Only a non-owner Going participant with both override dates can narrow a
    range.  Partial legacy values and all non-Going states intentionally fall
    back to the organizer's core dates.
    """
    if (
        participant is not None
        and getattr(participant, "user_id", None) != getattr(trip, "user_id", None)
        and participant_is_going(participant)
        and getattr(participant, "start_date", None)
        and getattr(participant, "end_date", None)
    ):
        return participant.start_date, participant.end_date
    return trip.start_date, trip.end_date


def set_effective_attendance_dates(trip, participant=None):
    """Attach presentation-only effective dates to an existing trip instance."""
    start_date, end_date = effective_attendance_dates(trip, participant)
    trip.attendance_start_date = start_date
    trip.attendance_end_date = end_date
    trip._attendance_participant = participant
    return trip