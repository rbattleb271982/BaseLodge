"""Backend contract tests for the Trips Both projection."""

from datetime import date, timedelta

import sqlalchemy as sa

from app import app
from models import (
    DismissedInsightCard,
    Friend,
    GuestStatus,
    SkiTripParticipant,
    db,
)
from services.both_trips import load_both_trips
from services.ideas_retrieval import get_home_idea_candidates
from services.ski_seasons import get_ski_season_window
from tests.conftest import _login, _make_resort, _make_trip, _make_user


def _connect(viewer, *friends):
    for friend in friends:
        db.session.add_all([
            Friend(user_id=viewer.id, friend_id=friend.id),
            Friend(user_id=friend.id, friend_id=viewer.id),
        ])


def _participant(trip, user, status, **dates):
    value = SkiTripParticipant(
        trip_id=trip.id, user_id=user.id, status=status, role="guest"
    )
    for key, value_date in dates.items():
        setattr(value, key, value_date)
    db.session.add(value)
    return value


def test_both_includes_organizer_going_and_interested_rows(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-base-viewer")
        organizer = _make_user("both-base-organizer")
        resort = _make_resort("Both Base Peak")
        _connect(viewer, organizer)
        owned = _make_trip(viewer, resort, start_date=today + timedelta(1),
                           end_date=today + timedelta(2))
        going = _make_trip(organizer, resort, start_date=today + timedelta(3),
                           end_date=today + timedelta(4))
        interested = _make_trip(organizer, resort, start_date=today + timedelta(5),
                                end_date=today + timedelta(6))
        _participant(going, viewer, GuestStatus.GOING)
        _participant(interested, viewer, GuestStatus.INTERESTED)
        db.session.commit()
        rows = load_both_trips(viewer.id, today=today)
        assert {row.trip.id for row in rows} >= {owned.id, going.id, interested.id}
        assert len([row for row in rows if row.trip.id == owned.id]) == 1


def test_both_excludes_pending_declined_removed_terminal_and_history(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-state-viewer")
        organizer = _make_user("both-state-organizer")
        resort = _make_resort("Both State Peak")
        _connect(viewer, organizer)
        excluded = []
        for index, status in enumerate((
            GuestStatus.PENDING, GuestStatus.DECLINED, GuestStatus.REMOVED
        )):
            trip = _make_trip(organizer, resort, start_date=today + timedelta(5 + index * 2),
                              end_date=today + timedelta(6 + index * 2))
            _participant(trip, viewer, status)
            excluded.append(trip.id)
        terminal = _make_trip(organizer, resort, start_date=today + timedelta(20),
                              end_date=today + timedelta(21))
        terminal.lifecycle_state = "completed"
        history = _make_trip(organizer, resort, start_date=today - timedelta(5),
                             end_date=today - timedelta(4))
        _participant(history, viewer, GuestStatus.GOING)
        db.session.commit()
        ids = {row.trip.id for row in load_both_trips(viewer.id, today=today)}
        assert not (set(excluded) | {terminal.id, history.id}) & ids


def test_overlap_names_are_going_only_deduped_and_use_effective_dates(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-names-viewer")
        first = _make_user("both-names-first")
        second = _make_user("both-names-second")
        disjoint = _make_user("both-names-disjoint")
        first.first_name = "Dana"
        second.first_name = "Nora"
        disjoint.first_name = "Theo"
        _connect(viewer, first, second, disjoint)
        resort = _make_resort("Both Names Peak")
        mine = _make_trip(viewer, resort, start_date=today + timedelta(10),
                          end_date=today + timedelta(15))
        shared = _make_trip(
            first,
            resort,
            trip_status="going",
            start_date=today + timedelta(1),
            end_date=today + timedelta(20),
        )
        _participant(shared, second, GuestStatus.GOING,
                     start_date=today + timedelta(12),
                     end_date=today + timedelta(13))
        _participant(shared, disjoint, GuestStatus.GOING,
                     start_date=today + timedelta(2),
                     end_date=today + timedelta(3))
        # A second eligible record for the same friend must not repeat them.
        second_shared = _make_trip(
            first,
            resort,
            trip_status="going",
            start_date=today + timedelta(11),
            end_date=today + timedelta(14),
        )
        db.session.commit()
        rows = load_both_trips(viewer.id, today=today)
        mine_row = next(row for row in rows if row.trip.id == mine.id)
        assert mine_row.overlap_names == sorted(
            {first.first_name, second.first_name}, key=str.casefold
        )
        assert disjoint.first_name not in mine_row.overlap_names
        assert len(mine_row.overlap_names) == len(set(mine_row.overlap_names))
        assert len([row for row in rows if row.trip.id == shared.id]) <= 1
        assert len([row for row in rows if row.trip.id == second_shared.id]) <= 1


def test_people_on_the_same_trip_are_not_reported_as_overlap(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-same-trip-viewer")
        friends = [
            _make_user(f"both-same-trip-friend-{index}")
            for index in range(3)
        ]
        friends[0].first_name = "Dana"
        _connect(viewer, *friends)
        resort = _make_resort("Both Same Trip Peak")
        viewer.wish_list_resorts = [resort.id]
        mine = _make_trip(
            viewer,
            resort,
            start_date=today + timedelta(4),
            end_date=today + timedelta(6),
        )
        for friend in friends:
            _participant(mine, friend, GuestStatus.GOING)
        db.session.commit()

        rows = load_both_trips(viewer.id, today=today)
        matching = [item for item in rows if item.trip.id == mine.id]
        assert len(matching) == 1
        row = matching[0]
        assert row.overlap_names == []
        assert not row.is_opportunity


def test_planning_friend_organizer_is_not_presented_as_going(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-planning-owner-viewer")
        friend = _make_user("both-planning-owner-friend")
        friend.first_name = "Dana"
        _connect(viewer, friend)
        overlap_resort = _make_resort("Both Planning Owner Overlap")
        wishlist_resort = _make_resort("Both Planning Owner Wishlist")
        viewer.wish_list_resorts = [wishlist_resort.id]
        friend.wish_list_resorts = [wishlist_resort.id]
        mine = _make_trip(
            viewer,
            overlap_resort,
            start_date=today + timedelta(4),
            end_date=today + timedelta(6),
        )
        _make_trip(
            friend,
            overlap_resort,
            trip_status="planning",
            start_date=today + timedelta(4),
            end_date=today + timedelta(6),
        )
        planning_opportunity = _make_trip(
            friend,
            wishlist_resort,
            trip_status="planning",
            start_date=today + timedelta(10),
            end_date=today + timedelta(12),
        )
        db.session.commit()

        rows = load_both_trips(viewer.id, today=today)
        mine_row = next(row for row in rows if row.trip.id == mine.id)
        opportunity_row = next(
            row for row in rows if row.trip.id == planning_opportunity.id
        )
        assert mine_row.overlap_names == []
        assert opportunity_row.standalone_reason == "On your wishlist"
        assert opportunity_row.friend_names == []


def test_both_loads_the_complete_active_season_beyond_mine_page_size(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-complete-season-viewer")
        resort = _make_resort("Both Complete Season Peak")
        trips = [
            _make_trip(
                viewer,
                resort,
                start_date=today + timedelta(index + 1),
                end_date=today + timedelta(index + 1),
            )
            for index in range(25)
        ]
        db.session.flush()
        expected_ids = {trip.id for trip in trips}
        db.session.commit()

        rows = load_both_trips(viewer.id, today=today)
        actual_ids = {row.trip.id for row in rows if not row.is_opportunity}
        assert actual_ids == expected_ids


def test_both_excludes_viewer_and_friend_trips_beyond_current_season(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-season-bound-viewer")
        friend = _make_user("both-season-bound-friend")
        _connect(viewer, friend)
        resort = _make_resort("Both Season Bound Peak")
        _season_start, season_end = get_ski_season_window(today)
        viewer_trip = _make_trip(
            viewer,
            resort,
            start_date=season_end + timedelta(1),
            end_date=season_end + timedelta(2),
        )
        friend_trip = _make_trip(
            friend,
            resort,
            trip_status="going",
            start_date=season_end + timedelta(1),
            end_date=season_end + timedelta(2),
        )
        db.session.commit()

        ids = {row.trip.id for row in load_both_trips(viewer.id, today=today)}
        assert viewer_trip.id not in ids
        assert friend_trip.id not in ids


def test_interested_friend_is_not_an_overlap_and_private_nonreciprocal_terminal_hidden(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-privacy-viewer")
        friend = _make_user("both-privacy-friend")
        stranger = _make_user("both-privacy-stranger")
        organizer = _make_user("both-privacy-organizer")
        resort = _make_resort("Both Privacy Peak")
        _connect(viewer, friend)
        mine = _make_trip(viewer, resort, start_date=today + timedelta(2),
                          end_date=today + timedelta(4))
        interested = _make_trip(organizer, resort, start_date=today + timedelta(2),
                                end_date=today + timedelta(4))
        _participant(interested, friend, GuestStatus.INTERESTED)
        private = _make_trip(friend, resort, is_public=False,
                             start_date=today + timedelta(2),
                             end_date=today + timedelta(4))
        terminal = _make_trip(friend, resort, start_date=today + timedelta(2),
                              end_date=today + timedelta(4))
        terminal.lifecycle_state = "cancelled"
        stranger_trip = _make_trip(stranger, resort, start_date=today + timedelta(2),
                                   end_date=today + timedelta(4))
        db.session.commit()
        rows = load_both_trips(viewer.id, today=today)
        mine_row = next(row for row in rows if row.trip.id == mine.id)
        assert mine_row.overlap_names == []
        ids = {row.trip.id for row in rows}
        assert not {private.id, terminal.id, stranger_trip.id} & ids


def test_resort_id_not_name_is_overlap_identity(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-resort-viewer")
        friend = _make_user("both-resort-friend")
        _connect(viewer, friend)
        first_resort = _make_resort("Same Name")
        second_resort = _make_resort("Same Name")
        mine = _make_trip(viewer, first_resort, start_date=today + timedelta(2),
                          end_date=today + timedelta(4))
        _make_trip(friend, second_resort, start_date=today + timedelta(2),
                   end_date=today + timedelta(4))
        db.session.commit()
        row = next(row for row in load_both_trips(viewer.id, today=today)
                   if row.trip.id == mine.id)
        assert row.overlap_names == []


def test_standalone_wishlist_and_three_friend_reason_are_sorted_and_not_duplicates(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-opportunity-viewer")
        friends = [_make_user(f"both-opportunity-friend-{i}") for i in range(3)]
        _connect(viewer, *friends)
        wishlist_resort = _make_resort("Both Wishlist Peak")
        viewer.wish_list_resorts = [wishlist_resort.id]
        friends[0].wish_list_resorts = [wishlist_resort.id]
        wishlist_trip = _make_trip(friends[0], wishlist_resort,
                                   start_date=today + timedelta(12),
                                   end_date=today + timedelta(14))
        group_resort = _make_resort("Both Group Peak")
        group_trip = _make_trip(_make_user("both-group-organizer"), group_resort,
                                start_date=today + timedelta(5),
                                end_date=today + timedelta(7))
        for friend in friends:
            _participant(group_trip, friend, GuestStatus.GOING)
        db.session.commit()
        rows = load_both_trips(viewer.id, today=today)
        opportunities = [row for row in rows if row.is_opportunity]
        by_trip = {row.trip.id: row for row in opportunities}
        assert by_trip[wishlist_trip.id].standalone_reason == "On your wishlist"
        assert "3 friends going" == by_trip[group_trip.id].standalone_reason
        assert [row.attendance_start_date for row in rows] == sorted(
            row.attendance_start_date for row in rows
        )


def test_availability_only_and_one_friend_reason_do_not_emit_opportunity(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-no-reason-viewer",
                            open_dates=[(today + timedelta(2)).isoformat()])
        friend = _make_user("both-no-reason-friend",
                            open_dates=[(today + timedelta(2)).isoformat()])
        _connect(viewer, friend)
        resort = _make_resort("Both No Reason Peak")
        trip = _make_trip(friend, resort, start_date=today + timedelta(2),
                          end_date=today + timedelta(3))
        db.session.commit()
        rows = load_both_trips(viewer.id, today=today)
        assert not [row for row in rows if row.trip.id == trip.id and row.is_opportunity]


def test_raw_candidate_and_both_ignore_home_dismissal_and_overlap_booking_suppression(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-dismissal-viewer")
        friends = [_make_user(f"both-dismissal-friend-{i}") for i in range(3)]
        for index, friend in enumerate(friends):
            friend.first_name = f"Friend{index}"
        _connect(viewer, *friends)
        resort = _make_resort("Both Dismissal Peak")
        own = _make_trip(viewer, resort, start_date=today + timedelta(10),
                         end_date=today + timedelta(12))
        opportunity = _make_trip(_make_user("both-dismissal-organizer"), resort,
                                 start_date=today + timedelta(10),
                                 end_date=today + timedelta(12))
        for friend in friends:
            _participant(opportunity, friend, GuestStatus.GOING)
        db.session.add(DismissedInsightCard(
            user_id=viewer.id, card_type="opportunity",
            card_key=f"friend_trip:{resort.id}",
        ))
        db.session.commit()
        raw = get_home_idea_candidates(user_id=viewer.id, today=today)
        assert any(row["resort_id"] == resort.id for row in raw)
        own_row = next(row for row in load_both_trips(viewer.id, today=today)
                       if row.trip.id == own.id)
        assert own_row.overlap_names == ["Friend0", "Friend1", "Friend2"]
        assert not [row for row in load_both_trips(viewer.id, today=today)
                    if row.trip.id == opportunity.id and row.is_opportunity]


def test_both_route_renders_grouped_overlaps_opportunities_and_no_invitations(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-render-viewer")
        dana = _make_user("both-render-dana")
        nora = _make_user("both-render-nora")
        theo = _make_user("both-render-theo")
        dana.first_name = "Dana"
        nora.first_name = "Nora"
        theo.first_name = "Theo"
        _connect(viewer, dana, nora, theo)
        overlap_resort = _make_resort("Both Render Overlap")
        opportunity_resort = _make_resort("Both Render Opportunity")
        mine = _make_trip(
            viewer,
            overlap_resort,
            start_date=today + timedelta(5),
            end_date=today + timedelta(8),
        )
        friend_overlap = _make_trip(
            dana,
            overlap_resort,
            trip_status="going",
            start_date=today + timedelta(6),
            end_date=today + timedelta(7),
        )
        _participant(friend_overlap, nora, GuestStatus.GOING)
        opportunity = _make_trip(
            theo,
            opportunity_resort,
            trip_status="going",
            start_date=today + timedelta(10),
            end_date=today + timedelta(12),
        )
        _participant(opportunity, dana, GuestStatus.GOING)
        _participant(opportunity, nora, GuestStatus.GOING)
        invitation = _make_trip(
            theo,
            opportunity_resort,
            start_date=today + timedelta(14),
            end_date=today + timedelta(15),
        )
        _participant(invitation, viewer, GuestStatus.PENDING)
        db.session.commit()
        viewer_id = viewer.id
        mine_id = mine.id
        opportunity_id = opportunity.id
        invitation_id = invitation.id

    _login(client, viewer_id)
    html = client.get("/my-trips?tab=both").get_data(as_text=True)

    assert 'class="view-tab active" href="/my-trips?tab=both"' in html
    assert "2 entries" in html
    assert "Dana + 1 other overlap your dates" in html
    assert "FRIEND TRIP" in html
    assert "3 friends going" in html
    assert f'data-trip-id="{mine_id}"' in html
    assert f'data-trip-id="{opportunity_id}"' in html
    assert f'data-trip-id="{invitation_id}"' not in html
    assert 'class="ledger-invite"' not in html

    mine_html = client.get("/my-trips").get_data(as_text=True)
    assert f'data-trip-id="{invitation_id}"' in mine_html
    assert 'class="view-tab active" href="/my-trips"' in mine_html


def test_both_route_keeps_viewer_rows_with_quiet_no_relevance_copy(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-render-quiet-viewer")
        resort = _make_resort("Both Render Quiet")
        trip = _make_trip(
            viewer,
            resort,
            start_date=today + timedelta(3),
            end_date=today + timedelta(4),
        )
        db.session.commit()
        viewer_id = viewer.id
        trip_id = trip.id

    _login(client, viewer_id)
    html = client.get("/my-trips?tab=both").get_data(as_text=True)

    assert "Nothing of yours overlaps a friend's trip yet." in html
    assert f'data-trip-id="{trip_id}"' in html
    assert "1 entry" in html


def test_both_query_count_is_bounded_and_route_context_smoke(client):
    today = date.today()
    with app.app_context():
        viewer = _make_user("both-query-viewer")
        resort = _make_resort("Both Query Peak")
        for index in range(20):
            _make_trip(viewer, resort, start_date=today + timedelta(index + 1),
                       end_date=today + timedelta(index + 2))
        db.session.commit()
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            load_both_trips(viewer.id, today=today)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)
        assert len(statements) <= 9
        viewer_id = viewer.id
    _login(client, viewer_id)
    assert client.get("/my-trips?tab=both").status_code == 200