from datetime import date, timedelta

import pytest

from app import app, get_ski_season_window
from conftest import _add_participant, _login, _make_resort, _make_trip, _make_user
from models import Friend, GuestStatus, Invitation, SkiTripParticipant, db


def _connect(user, friend):
    """Create the bidirectional confirmed friendship used by mountain pages."""
    db.session.add_all([
        Friend(user_id=user.id, friend_id=friend.id),
        Friend(user_id=friend.id, friend_id=user.id),
    ])


def _friend(label, first_name=None):
    user = _make_user(label)
    user.first_name = first_name or label.title()
    user.last_name = "Friend"
    return user


def _page(client, resort_slug):
    return client.get(f"/mountain/{resort_slug}")


def _set_rsvp(trip, user, status):
    participant = SkiTripParticipant.query.filter_by(
        trip_id=trip.id,
        user_id=user.id,
    ).one()
    participant.status = status


def test_mountain_page_shows_been_here_only_for_canonical_visit_id(client):
    with app.app_context():
        viewer = _make_user("been-here")
        resort = _make_resort("Been Here Peak")
        resort_slug = resort.slug
        viewer.visited_resort_ids = [resort.id]
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "✓ Been here" in html
    assert "Not marked as visited" not in html


@pytest.mark.parametrize("visited_ids", [None, []])
def test_mountain_page_empty_or_null_visit_ids_are_not_been_here(client, visited_ids):
    with app.app_context():
        viewer = _make_user("not-been-here")
        resort = _make_resort("Not Been Here Peak")
        resort_slug = resort.slug
        viewer.visited_resort_ids = visited_ids
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Not marked as visited" in html
    assert "✓ Been here" not in html


def test_mountain_page_does_not_infer_been_here_from_trips_rsvps_wishlist_or_legacy_names(client):
    with app.app_context():
        viewer = _make_user("signals-not-visit")
        host = _make_user("signals-host")
        resort = _make_resort("Signals Peak")
        resort_slug = resort.slug
        viewer.visited_resort_ids = []
        viewer.mountains_visited = [resort.name]
        viewer.wish_list_resorts = [resort.id]

        past_trip = _make_trip(
            viewer,
            resort=resort,
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() - timedelta(days=9),
        )
        _set_rsvp(past_trip, viewer, GuestStatus.GOING)

        future_trip = _make_trip(viewer, resort=resort)
        _set_rsvp(future_trip, viewer, GuestStatus.INTERESTED)

        going_trip = _make_trip(host, resort=resort)
        _add_participant(going_trip, viewer, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Not marked as visited" in html
    assert "✓ Been here" not in html


def test_mountain_page_does_not_show_pending_or_nonfriend_visited_users(client):
    with app.app_context():
        viewer = _make_user("privacy-viewer")
        pending_user = _friend("pending-visited", "Pending")
        nonfriend = _friend("nonfriend-visited", "Nonfriend")
        resort = _make_resort("Privacy Visit Peak")
        resort_slug = resort.slug
        pending_user.visited_resort_ids = [resort.id]
        nonfriend.visited_resort_ids = [resort.id]
        db.session.add(Invitation(
            sender_id=viewer.id,
            receiver_id=pending_user.id,
            status="pending",
        ))
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Pending Friend" not in html
    assert "Nonfriend Friend" not in html
    assert "recorded this mountain as visited" not in html


def test_mountain_page_does_not_show_removed_friend_visit(client):
    with app.app_context():
        viewer = _make_user("removed-viewer")
        removed_friend = _friend("removed-visited", "Removed")
        resort = _make_resort("Removed Visit Peak")
        resort_slug = resort.slug
        removed_friend.visited_resort_ids = [resort.id]
        _connect(viewer, removed_friend)
        db.session.flush()
        Friend.query.filter_by(user_id=viewer.id, friend_id=removed_friend.id).delete()
        Friend.query.filter_by(user_id=removed_friend.id, friend_id=viewer.id).delete()
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Removed Friend" not in html
    assert "recorded this mountain as visited" not in html


def test_mountain_page_multiple_recorded_visits_keep_existing_summary_behavior(client):
    with app.app_context():
        viewer = _make_user("many-visits-viewer")
        friends = []
        resort = _make_resort("Many Visits Peak")
        resort_slug = resort.slug
        for label in ["alpha", "bravo", "charlie", "delta"]:
            friend = _friend(label, label.title())
            friend.visited_resort_ids = [resort.id]
            _connect(viewer, friend)
            friends.append(friend)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "4 friends have recorded this mountain as visited" in html
    assert "Alpha Friend" in html
    assert "Bravo Friend" in html
    assert "Charlie Friend" in html
    assert "Delta Friend" not in html
    assert "+1 more" in html


def test_mountain_page_going_this_winter_filters_season_and_rsvp_state(client):
    with app.app_context():
        viewer = _make_user("winter-viewer")
        going_friend = _friend("winter-going", "Winter Going")
        boundary_friend = _friend("boundary-going", "Boundary Going")
        past_friend = _friend("past-going", "Past Going")
        next_season_friend = _friend("next-season-going", "Next Season")
        interested_friend = _friend("winter-interested", "Winter Interested")
        resort = _make_resort("Winter Intelligence Peak")
        resort_slug = resort.slug
        for friend in (
            going_friend,
            boundary_friend,
            past_friend,
            next_season_friend,
            interested_friend,
        ):
            _connect(viewer, friend)

        today = date.today()
        _, season_end = get_ski_season_window(today)

        going_trip = _make_trip(
            going_friend,
            resort=resort,
            start_date=today,
            end_date=today + timedelta(days=1),
        )
        _set_rsvp(going_trip, going_friend, GuestStatus.GOING)

        boundary_trip = _make_trip(
            boundary_friend,
            resort=resort,
            start_date=season_end,
            end_date=season_end,
        )
        _set_rsvp(boundary_trip, boundary_friend, GuestStatus.GOING)

        past_trip = _make_trip(
            past_friend,
            resort=resort,
            start_date=today - timedelta(days=2),
            end_date=today - timedelta(days=1),
        )
        _set_rsvp(past_trip, past_friend, GuestStatus.GOING)

        next_season_start = season_end + timedelta(days=1)
        next_season_trip = _make_trip(
            next_season_friend,
            resort=resort,
            start_date=next_season_start,
            end_date=next_season_start + timedelta(days=1),
        )
        _set_rsvp(next_season_trip, next_season_friend, GuestStatus.GOING)

        interested_trip = _make_trip(
            interested_friend,
            resort=resort,
            start_date=today,
            end_date=today + timedelta(days=1),
        )
        _set_rsvp(interested_trip, interested_friend, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Going This Winter · 2 friends" in html
    assert "Winter Going Friend" in html
    assert "Boundary Going Friend" in html
    assert "Past Going Friend" not in html
    assert "Next Season Friend" not in html
    assert "Friends Interested · 1 friend" in html
    assert "Winter Interested Friend" in html


def test_mountain_page_with_no_going_friends_keeps_interested_separate(client):
    with app.app_context():
        viewer = _make_user("no-going-viewer")
        interested_friend = _friend("only-interested", "Only Interested")
        resort = _make_resort("No Going Peak")
        resort_slug = resort.slug
        _connect(viewer, interested_friend)
        trip = _make_trip(
            interested_friend,
            resort=resort,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )
        _set_rsvp(trip, interested_friend, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Going This Winter" not in html
    assert "Friends Interested · 1 friend" in html


def test_mountain_page_multiple_going_friends_keep_compact_preview(client):
    with app.app_context():
        viewer = _make_user("many-going-viewer")
        resort = _make_resort("Many Going Peak")
        resort_slug = resort.slug
        for label in ["alpha", "bravo", "charlie", "delta"]:
            friend = _friend(label, label.title())
            _connect(viewer, friend)
            trip = _make_trip(
                friend,
                resort=resort,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=1),
            )
            _set_rsvp(trip, friend, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Going This Winter · 4 friends" in html
    assert "Alpha Friend" in html
    assert "Bravo Friend" in html
    assert "Charlie Friend" in html
    assert "Delta Friend" not in html
    assert "+1 more" in html


def test_mountain_page_separates_person_level_going_and_interested(client):
    with app.app_context():
        viewer = _make_user("viewer")
        going_friend = _friend("going", "Going")
        interested_friend = _friend("interested", "Interested")
        resort = _make_resort("RSVP Peak")
        resort_slug = resort.slug
        _connect(viewer, going_friend)
        _connect(viewer, interested_friend)

        # Deliberately invert the trip-level planning values. The participant RSVP
        # must determine the mountain-page grouping.
        going_trip = _make_trip(
            going_friend,
            resort=resort,
            trip_status="planning",
        )
        interested_trip = _make_trip(
            interested_friend,
            resort=resort,
            trip_status="going",
        )
        _set_rsvp(going_trip, going_friend, GuestStatus.GOING)
        _set_rsvp(interested_trip, interested_friend, GuestStatus.INTERESTED)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Going This Winter · 1 friend" in html
    assert "Friends Interested · 1 friend" in html
    assert "Going Friend" in html
    assert "Interested Friend" in html
    assert "Considering" not in html


@pytest.mark.parametrize(
    "inactive_status",
    [GuestStatus.PENDING, GuestStatus.DECLINED, GuestStatus.REMOVED],
)
def test_mountain_page_excludes_inactive_rsvps(client, inactive_status):
    with app.app_context():
        viewer = _make_user("viewer")
        friend = _friend("inactive", "Inactive")
        host = _make_user("host")
        resort = _make_resort("Inactive Peak")
        resort_slug = resort.slug
        _connect(viewer, friend)
        trip = _make_trip(host, resort=resort)
        _add_participant(trip, friend, inactive_status)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Inactive Friend" not in html
    assert "Going This Winter" not in html
    assert "Friends Interested" not in html


def test_mountain_page_excludes_private_nonfriend_friend_of_friend_and_viewer(client):
    with app.app_context():
        viewer = _make_user("viewer")
        direct_friend = _friend("direct", "Direct")
        nonfriend = _friend("nonfriend", "Nonfriend")
        friend_of_friend = _friend("fof", "Friend Of Friend")
        resort = _make_resort("Privacy Peak")
        resort_slug = resort.slug
        _connect(viewer, direct_friend)
        _connect(direct_friend, friend_of_friend)

        private_trip = _make_trip(direct_friend, resort=resort, is_public=False)
        _set_rsvp(private_trip, direct_friend, GuestStatus.GOING)
        nonfriend_trip = _make_trip(nonfriend, resort=resort)
        _set_rsvp(nonfriend_trip, nonfriend, GuestStatus.GOING)
        fof_trip = _make_trip(friend_of_friend, resort=resort)
        _set_rsvp(fof_trip, friend_of_friend, GuestStatus.GOING)
        viewer_trip = _make_trip(viewer, resort=resort)
        _set_rsvp(viewer_trip, viewer, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Direct Friend" not in html
    assert "Nonfriend Friend" not in html
    assert "Friend Of Friend Friend" not in html
    assert "Viewer Friend" not in html
    assert "Going This Winter" not in html


def test_mountain_page_deduplicates_trips_and_going_wins_over_interested(client):
    with app.app_context():
        viewer = _make_user("viewer")
        friend = _friend("multi", "Multi")
        host = _make_user("host")
        resort = _make_resort("Dedup Peak")
        resort_slug = resort.slug
        _connect(viewer, friend)

        interested_trip = _make_trip(
            friend,
            resort=resort,
            start_date=date.today() + timedelta(days=3),
            end_date=date.today() + timedelta(days=4),
        )
        first_going_trip = _make_trip(
            host,
            resort=resort,
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=11),
        )
        _add_participant(first_going_trip, friend, GuestStatus.GOING)
        later_going_trip = _make_trip(
            host,
            resort=resort,
            start_date=date.today() + timedelta(days=20),
            end_date=date.today() + timedelta(days=21),
        )
        _add_participant(later_going_trip, friend, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Going This Winter · 1 friend" in html
    assert "Friends Interested" not in html
    assert html.count("Multi Friend") == 1
    assert (date.today() + timedelta(days=10)).strftime("%b %-d") in html
    assert (date.today() + timedelta(days=20)).strftime("%b %-d") not in html


def test_mountain_page_history_is_conservative_and_suppresses_repeated_name(client):
    with app.app_context():
        viewer = _make_user("viewer")
        friend = _friend("recorded", "Recorded")
        resort = _make_resort("History Peak")
        resort_slug = resort.slug
        _connect(viewer, friend)
        friend.visited_resort_ids = [resort.id]
        trip = _make_trip(friend, resort=resort)
        _set_rsvp(trip, friend, GuestStatus.GOING)
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)
    html_lower = html.lower()

    assert "1 friend has recorded this mountain as visited" in html
    assert html.count("Recorded Friend") == 1
    assert "first time" not in html_lower
    assert "expert" not in html_lower
    assert "completed visit" not in html_lower


def test_mountain_page_wishlist_has_exact_total_truncated_names_and_tap_throughs(client):
    with app.app_context():
        viewer = _make_user("viewer")
        resort = _make_resort("Wishlist Peak")
        resort_slug = resort.slug
        friends = []
        for label in ["alpha", "bravo", "charlie", "delta"]:
            friend = _friend(label, label.title())
            friend.wish_list_resorts = [resort.id]
            _connect(viewer, friend)
            friends.append(friend)
        db.session.commit()
        viewer_id = viewer.id
        alpha_id = friends[0].id
        delta_id = friends[-1].id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "4 friends have this mountain on their wishlist" in html
    assert "Alpha Friend" in html
    assert "Bravo Friend" in html
    assert "Charlie Friend" in html
    assert "Delta Friend" not in html
    assert "+1 more" in html
    assert f'href="/friends/{alpha_id}"' in html
    assert f'href="/friends/{delta_id}"' not in html


def test_mountain_page_recorded_visit_name_links_to_visited_mountains(client):
    with app.app_context():
        viewer = _make_user("viewer")
        friend = _friend("visited", "Visited")
        resort = _make_resort("Visited Peak")
        resort_slug = resort.slug
        _connect(viewer, friend)
        friend.visited_resort_ids = [resort.id]
        db.session.commit()
        viewer_id = viewer.id
        friend_id = friend.id

    _login(client, viewer_id)
    html = _page(client, resort_slug).get_data(as_text=True)

    assert "Visited Friend" in html
    assert f'href="/mountains-visited/{friend_id}"' in html
