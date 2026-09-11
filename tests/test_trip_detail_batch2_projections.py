"""Trip Detail Batch 2 People and mountain-social projection coverage."""

from datetime import date, timedelta

from sqlalchemy import event

from app import app
from models import (
    Friend,
    GuestStatus,
    Invitation,
    InviteType,
    SkiTripParticipant,
    db,
)
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
)


def _link_friends(left, right):
    db.session.add_all([
        Friend(user_id=left.id, friend_id=right.id),
        Friend(user_id=right.id, friend_id=left.id),
    ])


def _named_user(label, first, last):
    user = _make_user(label)
    user.first_name = first
    user.last_name = last
    return user


def _trip_html(client, viewer_id, trip_id):
    _login(client, viewer_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_people_projection_counts_owner_once_and_normalizes_passes(client):
    with app.app_context():
        resort = _make_resort("Northstar")
        owner = _named_user("batch2-owner", "Owner", "Organizer")
        owner.pass_type = "epic"
        trip = _make_trip(owner, resort=resort)
        owner_participant = SkiTripParticipant.query.filter_by(
            trip_id=trip.id,
            user_id=owner.id,
        ).one()
        owner_participant.pass_type = "Ikon"

        going = _named_user("batch2-going", "Going", "Epic")
        going.pass_type = "Epic"
        _add_participant(trip, going, GuestStatus.GOING)

        interested = _named_user("batch2-interested", "Interested", "Multi")
        interested.pass_type = "IKON, indy"
        _add_participant(trip, interested, GuestStatus.INTERESTED)

        invited = _named_user("batch2-invited", "Invited", "NoPass")
        invited.pass_type = "No Pass"
        _add_participant(trip, invited, GuestStatus.PENDING)

        declined = _named_user("batch2-declined", "Declined", "Excluded")
        _add_participant(trip, declined, GuestStatus.DECLINED)
        removed = _named_user("batch2-removed", "Removed", "Excluded")
        _add_participant(trip, removed, GuestStatus.REMOVED)
        db.session.commit()
        owner_id, trip_id = owner.id, trip.id

    html = _trip_html(client, owner_id, trip_id)
    people_panel = html.split('id="td-panel-people"', 1)[1].split(
        "</section><!-- /td-hub-people -->", 1
    )[0]

    assert 'data-people-total="4"' in html
    assert "People <span class=\"td-detail-tab-count\">4</span>" in html
    assert "The group <span>4 people</span>" in people_panel
    assert (
        'aria-label="1 organizing, 1 going, 1 interested, 1 invited"'
        in people_panel
    )
    assert "Declined Excluded" not in people_panel
    assert "Removed Excluded" not in people_panel

    # Snapshot wins over the organizer's current profile value. A multi-pass
    # participant contributes once to each real-pass bucket, but all bars use
    # the four-person People denominator.
    assert 'data-pass-bucket="epic" data-pass-count="1" data-pass-share="25.0"' in people_panel
    assert 'data-pass-bucket="ikon" data-pass-count="2" data-pass-share="50.0"' in people_panel
    assert 'data-pass-bucket="indy" data-pass-count="1" data-pass-share="25.0"' in people_panel
    assert 'data-pass-bucket="no_pass" data-pass-count="1" data-pass-share="25.0"' in people_panel
    assert "have access" not in people_panel
    assert "Buddy Pass" not in people_panel


def test_people_request_badge_is_owner_only_and_terminal_safe(client):
    with app.app_context():
        owner = _make_user("batch2-request-owner")
        trip = _make_trip(owner, resort=_make_resort())
        guest = _make_user("batch2-request-guest")
        _add_participant(trip, guest, GuestStatus.GOING)
        for index in range(3):
            requester = _make_user(f"batch2-requester-{index}")
            db.session.add(Invitation(
                sender_id=requester.id,
                receiver_id=owner.id,
                trip_id=trip.id,
                invite_type=InviteType.REQUEST,
                status="pending",
            ))
        db.session.commit()
        owner_id, guest_id, trip_id = owner.id, guest.id, trip.id

    owner_html = _trip_html(client, owner_id, trip_id)
    assert '<span class="td-detail-tab-attention" aria-hidden="true">3</span>' in owner_html
    assert 'id="td-join-requests">Requests <span>3 asked to join</span>' in owner_html
    assert 'class="td-join-request-list" data-presentation="flat-ledger"' in owner_html
    assert owner_html.count('class="td-person-row td-join-request-row"') == 3

    guest_html = _trip_html(client, guest_id, trip_id)
    assert '<span class="td-detail-tab-attention"' not in guest_html
    assert 'id="td-join-requests"' not in guest_html

    with app.app_context():
        trip = db.session.get(type(trip), trip_id)
        trip.lifecycle_state = "completed"
        db.session.commit()

    terminal_html = _trip_html(client, owner_id, trip_id)
    assert '<span class="td-detail-tab-attention"' not in terminal_html
    assert 'id="td-join-requests"' not in terminal_html


def test_mountain_social_counts_and_destinations_share_scoped_populations(client):
    today = date.today()
    with app.app_context():
        resort = _make_resort("Northstar")
        other_resort = _make_resort("Elsewhere")
        viewer = _named_user("batch2-viewer", "Viewer", "Owner")
        trip = _make_trip(
            viewer,
            resort=resort,
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=4),
        )

        future_owner = _named_user("batch2-future-owner", "Future", "Owner")
        _link_friends(viewer, future_owner)
        _make_trip(
            future_owner,
            resort=resort,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=12),
        )

        future_guest = _named_user("batch2-future-guest", "Future", "Guest")
        host = _make_user("batch2-public-host")
        _link_friends(viewer, future_guest)
        host_trip = _make_trip(
            host,
            resort=resort,
            start_date=today + timedelta(days=11),
            end_date=today + timedelta(days=12),
        )
        _add_participant(host_trip, future_guest, GuestStatus.GOING)

        multi_trip_friend = _named_user("batch2-multi-trip", "Multi", "Trip")
        _link_friends(viewer, multi_trip_friend)
        _make_trip(multi_trip_friend, resort=resort)
        _make_trip(
            multi_trip_friend,
            resort=resort,
            start_date=today + timedelta(days=14),
            end_date=today + timedelta(days=15),
        )

        private_friend = _named_user("batch2-private", "Private", "Friend")
        _link_friends(viewer, private_friend)
        _make_trip(private_friend, resort=resort, is_public=False)

        terminal_friend = _named_user("batch2-terminal", "Terminal", "Friend")
        _link_friends(viewer, terminal_friend)
        terminal_trip = _make_trip(terminal_friend, resort=resort)
        terminal_trip.lifecycle_state = "completed"

        other_resort_friend = _named_user("batch2-other", "Other", "Resort")
        _link_friends(viewer, other_resort_friend)
        _make_trip(other_resort_friend, resort=other_resort)

        one_way_friend = _named_user("batch2-one-way", "OneWay", "Friend")
        db.session.add(Friend(user_id=viewer.id, friend_id=one_way_friend.id))
        _make_trip(one_way_friend, resort=resort)

        normalized_visited = _named_user("batch2-visited-normal", "Visited", "Normalized")
        normalized_visited.visited_resort_ids = [resort.id, resort.id]
        _link_friends(viewer, normalized_visited)
        legacy_visited = _named_user("batch2-visited-legacy", "Visited", "Legacy")
        legacy_visited.visited_resort_ids = []
        legacy_visited.mountains_visited = [resort.name]
        _link_friends(viewer, legacy_visited)

        wishlist_a = _named_user("batch2-wishlist-a", "Wishlist", "Alpha")
        wishlist_a.wish_list_resorts = [resort.id, resort.id]
        _link_friends(viewer, wishlist_a)
        wishlist_b = _named_user("batch2-wishlist-b", "Wishlist", "Beta")
        wishlist_b.wish_list_resorts = [resort.id]
        _link_friends(viewer, wishlist_b)
        db.session.commit()
        viewer_id, trip_id = viewer.id, trip.id

    detail_html = _trip_html(client, viewer_id, trip_id)
    assert 'data-mountain-signal="upcoming"' in detail_html
    assert "3 friends have Northstar trips planned" in detail_html
    assert "Dates that could overlap with yours" in detail_html
    assert "2 friends have visited Northstar" in detail_html
    assert "People to ask about the mountain" in detail_html
    assert "2 friends want to ski Northstar" in detail_html
    assert "People worth inviting" in detail_html
    assert "skied Northstar" not in detail_html

    expected = {
        "upcoming": ["Future Owner", "Future Guest", "Multi Trip"],
        "visited": ["Visited Legacy", "Visited Normalized"],
        "wishlist": ["Wishlist Alpha", "Wishlist Beta"],
    }
    for signal, names in expected.items():
        response = client.get(f"/trips/{trip_id}/mountain-friends/{signal}")
        assert response.status_code == 200
        destination_html = response.get_data(as_text=True)
        assert (
            f'data-mountain-signal="{signal}" '
            f'data-matching-count="{len(names)}" data-presentation="flat-ledger"'
            in destination_html
        )
        assert destination_html.count('class="tmf-info"') == len(names)
        assert destination_html.count('class="tmf-name"') == len(names)
        assert destination_html.count('class="tmf-meta"') == len(names)
        for name in names:
            assert name in destination_html
        for excluded_name in (
            "Private Friend",
            "Terminal Friend",
            "Other Resort",
            "OneWay Friend",
        ):
            assert excluded_name not in destination_html


def test_mountain_social_destination_requires_current_trip_access(client):
    with app.app_context():
        owner = _make_user("batch2-route-owner")
        outsider = _make_user("batch2-route-outsider")
        trip = _make_trip(owner, resort=_make_resort())
        db.session.commit()
        outsider_id, trip_id = outsider.id, trip.id

    _login(client, outsider_id)
    assert client.get(f"/trips/{trip_id}/mountain-friends/upcoming").status_code == 404


def test_mountain_social_queries_do_not_grow_with_matching_friend_count(client):
    def measured_get(path):
        statements = []
        with app.app_context():
            engine = db.engine

        def record(_connection, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            response = client.get(path)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200
        return len(statements)

    with app.app_context():
        sparse_resort = _make_resort("Sparse Query Ridge")
        sparse_owner = _make_user("batch2-query-sparse-owner")
        sparse_trip = _make_trip(sparse_owner, resort=sparse_resort)
        sparse_friend = _make_user("batch2-query-sparse-friend")
        _link_friends(sparse_owner, sparse_friend)
        _make_trip(sparse_friend, resort=sparse_resort)

        dense_resort = _make_resort("Dense Query Ridge")
        dense_owner = _make_user("batch2-query-dense-owner")
        dense_trip = _make_trip(dense_owner, resort=dense_resort)
        for index in range(20):
            friend = _make_user(f"batch2-query-friend-{index}")
            _link_friends(dense_owner, friend)
            _make_trip(friend, resort=dense_resort)
        db.session.commit()
        sparse_owner_id, sparse_trip_id = sparse_owner.id, sparse_trip.id
        dense_owner_id, dense_trip_id = dense_owner.id, dense_trip.id

    _login(client, sparse_owner_id)
    sparse_query_count = measured_get(f"/trips/{sparse_trip_id}")
    _login(client, dense_owner_id)
    dense_query_count = measured_get(f"/trips/{dense_trip_id}")

    # Population size may affect returned rows, but should never add one query
    # per matching friend.
    assert dense_query_count <= sparse_query_count + 1