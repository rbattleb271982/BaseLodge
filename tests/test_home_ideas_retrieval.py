"""BL-176 exact bounded Home Ideas retrieval regressions."""

from datetime import date, timedelta

import sqlalchemy as sa
import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app import app
from models import (
    DismissedInsightCard,
    Friend,
    GuestStatus,
    SkiTripParticipant,
    UserAvailability,
    db,
)
from services.ideas_engine import build_destination_feed
from services.skills.trip_overlap import trip_overlap_skill
from services.ideas_retrieval import (
    _build_home_ideas_statement,
    get_home_ideas,
)
from tests.conftest import _make_resort, _make_trip, _make_user


TODAY = date(2026, 9, 1)


def _connect(viewer, friend):
    db.session.add(Friend(user_id=viewer.id, friend_id=friend.id))


@pytest.mark.parametrize("lifecycle_state", ["completed", "cancelled"])
def test_trip_overlap_skill_ignores_terminal_future_friend_trip(
    client, lifecycle_state
):
    with app.app_context():
        resort = _make_resort()
        viewer = _make_user(
            f"skill-terminal-viewer-{lifecycle_state}",
            wish_list_resorts=[resort.id],
        )
        friend = _make_user(f"skill-terminal-friend-{lifecycle_state}")
        trip = _make_trip(
            friend,
            resort=resort,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=7),
        )
        trip.lifecycle_state = lifecycle_state
        db.session.commit()

        with app.test_request_context():
            assert trip_overlap_skill(viewer, [friend]) == []


def test_statement_compiles_json_expansion_and_final_limit_for_both_dialects():
    statement = _build_home_ideas_statement(
        user_id=7, today=TODAY, limit=5
    )
    sqlite_sql = str(
        statement.compile(
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    postgres_sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "json_each(" in sqlite_sql
    assert "json_valid(" in sqlite_sql
    assert "json_type(" in sqlite_sql
    assert "jsonb_array_elements_text(" in postgres_sql
    assert "jsonb_typeof(" in postgres_sql
    assert "BETWEEN 1 AND 9999" in postgres_sql
    assert "IN (4, 6, 9, 11)" in postgres_sql
    assert "THEN CAST(" in postgres_sql
    assert "row_number() OVER" in sqlite_sql
    assert "dismissed_insight_card" in sqlite_sql
    assert sqlite_sql.upper().count(" LIMIT ") == 1
    assert postgres_sql.upper().count("\n LIMIT ") == 1


def test_dismissal_backfills_and_large_population_uses_one_bounded_query(client):
    with app.app_context():
        viewer = _make_user("ideas-bound-viewer")
        resort_ids = []
        for index in range(8):
            friend = _make_user(f"ideas-bound-friend-{index}")
            resort = _make_resort(f"Ideas Bound {index}")
            _connect(viewer, friend)
            _make_trip(
                friend,
                resort,
                start_date=TODAY + timedelta(days=index),
                end_date=TODAY + timedelta(days=index + 2),
            )
            resort_ids.append(resort.id)
        db.session.flush()
        db.session.add(
            DismissedInsightCard(
                user_id=viewer.id,
                card_type="opportunity",
                card_key=f"friend_trip:{resort_ids[0]}",
            )
        )
        db.session.commit()
        viewer_id = viewer.id

        selects = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                selects.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            rows = get_home_ideas(
                user_id=viewer_id, today=TODAY, limit=50
            )
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)

        assert len(rows) == 5
        assert resort_ids[0] not in {row["resort_id"] for row in rows}
        assert len(selects) == 1
        assert " LIMIT " in selects[0].upper()


def test_normalized_availability_overrides_legacy_and_merges_windows(client):
    with app.app_context():
        viewer = _make_user(
            "ideas-avail-viewer",
            open_dates=[
                (TODAY + timedelta(days=1)).isoformat(),
                (TODAY + timedelta(days=2)).isoformat(),
            ],
        )
        friend = _make_user(
            "ideas-avail-friend",
            open_dates=[
                (TODAY + timedelta(days=1)).isoformat(),
                (TODAY + timedelta(days=2)).isoformat(),
            ],
        )
        _connect(viewer, friend)
        # One normalized row suppresses each user's complete legacy list.
        normalized_day = TODAY + timedelta(days=4)
        db.session.add_all(
            [
                UserAvailability(
                    user_id=viewer.id,
                    date=normalized_day,
                    is_available=True,
                ),
                UserAvailability(
                    user_id=friend.id,
                    date=normalized_day,
                    is_available=True,
                ),
            ]
        )
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)

        assert len(rows) == 1
        assert rows[0]["idea_type"] == "availability_overlap"
        assert rows[0]["start_date"] == normalized_day
        assert rows[0]["end_date"] == normalized_day
        assert rows[0]["resort"] is None


def test_legacy_malformed_values_and_missing_wishlist_resorts_are_ignored(client):
    with app.app_context():
        viewer = _make_user(
            "ideas-malformed-viewer",
            open_dates=["not-a-date", "2026-99-99", TODAY.isoformat()],
            wish_list_resorts=["bad", 999999],
        )
        friend = _make_user(
            "ideas-malformed-friend",
            open_dates=["abcdefghij", TODAY.isoformat()],
            wish_list_resorts=["also-bad", 999999],
        )
        _connect(viewer, friend)
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)

        # The valid shared legacy date remains, while malformed dates and the
        # nonexistent shared wishlist destination cannot manufacture a card.
        assert [(row["idea_type"], row["resort_id"]) for row in rows] == [
            ("availability_overlap", None)
        ]


def test_invalid_and_non_array_json_containers_are_treated_as_empty(client):
    with app.app_context():
        viewer = _make_user("ideas-invalid-json-viewer")
        friend = _make_user("ideas-invalid-json-friend")
        _connect(viewer, friend)
        db.session.flush()
        viewer_id = viewer.id
        db.session.execute(
            sa.text(
                'UPDATE "user" '
                "SET open_dates = :open_dates, wish_list_resorts = :wishlist "
                "WHERE id = :user_id"
            ),
            {
                "open_dates": "not-json",
                "wishlist": '{"resort": 123}',
                "user_id": viewer.id,
            },
        )
        db.session.execute(
            sa.text(
                'UPDATE "user" '
                "SET open_dates = :open_dates, wish_list_resorts = :wishlist "
                "WHERE id = :user_id"
            ),
            {
                "open_dates": f'"{TODAY.isoformat()}"',
                "wishlist": '"not-an-array"',
                "user_id": friend.id,
            },
        )
        db.session.commit()

        assert get_home_ideas(user_id=viewer_id, today=TODAY) == []


def test_legacy_global_999_day_sort_and_duplicate_trip_identity_key(client):
    with app.app_context():
        viewer = _make_user(
            "ideas-ranking-viewer", wish_list_resorts=[]
        )
        friend = _make_user(
            "ideas-ranking-friend", wish_list_resorts=[]
        )
        wishlist_friend = _make_user(
            "ideas-ranking-wishlist", wish_list_resorts=[]
        )
        near_resort = _make_resort("Ideas Near")
        far_resort = _make_resort("Ideas Far")
        wishlist_resort = _make_resort("Ideas Wishlist")
        viewer.wish_list_resorts = [wishlist_resort.id]
        wishlist_friend.wish_list_resorts = [wishlist_resort.id]
        _connect(viewer, friend)
        _connect(viewer, wishlist_friend)
        first = _make_trip(
            friend,
            near_resort,
            start_date=TODAY + timedelta(days=2),
            end_date=TODAY + timedelta(days=3),
        )
        # A second occurrence for the same person/window keeps group count 2
        # but must not duplicate the canonical card identity.
        _make_trip(
            friend,
            near_resort,
            start_date=first.start_date,
            end_date=first.end_date,
        )
        _make_trip(
            friend,
            far_resort,
            start_date=TODAY + timedelta(days=1200),
            end_date=TODAY + timedelta(days=1201),
        )
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)
        by_resort = {row["resort_id"]: row for row in rows}

        assert by_resort[near_resort.id]["friend_count"] == 2
        assert by_resort[near_resort.id]["friend_ids"] == [friend.id]
        assert by_resort[near_resort.id]["_card_key"] == (
            f"friend_trip:{near_resort.id}"
        )
        # An undated wishlist scores at the historical 999-day sentinel and
        # therefore precedes the otherwise equal far-dated trip.
        ids = [row["resort_id"] for row in rows]
        assert ids.index(wishlist_resort.id) < ids.index(far_resort.id)


def test_booked_window_suppression_and_three_friend_override(client):
    with app.app_context():
        viewer = _make_user("ideas-booking-viewer")
        resort = _make_resort("Ideas Booking")
        viewer_trip = _make_trip(
            viewer,
            resort,
            start_date=TODAY + timedelta(days=10),
            end_date=TODAY + timedelta(days=12),
        )
        friends = []
        for index in range(3):
            friend = _make_user(f"ideas-booking-friend-{index}")
            _connect(viewer, friend)
            friends.append(friend)
        # One friend is suppressed inside the seven-day buffer; the three
        # simultaneous friends survive under the legacy high-social rule.
        _make_trip(
            friends[0],
            resort,
            start_date=viewer_trip.start_date,
            end_date=viewer_trip.end_date,
        )
        db.session.commit()
        assert get_home_ideas(user_id=viewer.id, today=TODAY) == []

        for friend in friends[1:]:
            _make_trip(
                friend,
                resort,
                start_date=viewer_trip.start_date,
                end_date=viewer_trip.end_date,
            )
        db.session.commit()
        rows = get_home_ideas(user_id=viewer.id, today=TODAY)
        assert len(rows) == 1
        assert rows[0]["friend_count"] == 3


def test_friend_trip_owner_and_participant_eligibility_and_effective_dates(client):
    with app.app_context():
        viewer = _make_user("ideas-trip-viewer")
        owner_friend = _make_user("ideas-trip-owner")
        interested_friend = _make_user("ideas-trip-interested")
        going_friend = _make_user("ideas-trip-going")
        pending_friend = _make_user("ideas-trip-pending")
        declined_friend = _make_user("ideas-trip-declined")
        removed_friend = _make_user("ideas-trip-removed")
        nonfriend = _make_user("ideas-trip-nonfriend")
        organizer = _make_user("ideas-trip-organizer")
        resort = _make_resort("Ideas Attendance")
        interested_resort = _make_resort("Ideas Interested Attendance")
        going_resort = _make_resort("Ideas Going Attendance")
        for friend in (
            owner_friend,
            interested_friend,
            going_friend,
            pending_friend,
            declined_friend,
            removed_friend,
        ):
            _connect(viewer, friend)
        _make_trip(
            owner_friend,
            resort,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=2),
        )
        shared = _make_trip(
            organizer,
            interested_resort,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=10),
        )
        going_shared = _make_trip(
            organizer,
            going_resort,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=10),
        )
        for friend, status in (
            (interested_friend, GuestStatus.INTERESTED),
            (going_friend, GuestStatus.GOING),
            (pending_friend, GuestStatus.PENDING),
            (declined_friend, GuestStatus.DECLINED),
            (removed_friend, GuestStatus.REMOVED),
            (nonfriend, GuestStatus.GOING),
        ):
            participant = SkiTripParticipant(
                trip_id=(going_shared.id if friend is going_friend else shared.id),
                user_id=friend.id,
                status=status,
                role="guest",
            )
            if friend is going_friend:
                participant.start_date = TODAY + timedelta(days=3)
                participant.end_date = TODAY + timedelta(days=4)
            db.session.add(participant)
        private = _make_trip(
            owner_friend,
            resort,
            start_date=TODAY + timedelta(days=20),
            end_date=TODAY + timedelta(days=21),
            is_public=False,
        )
        _make_trip(
            owner_friend,
            None,
            start_date=TODAY + timedelta(days=30),
            end_date=TODAY + timedelta(days=31),
        )
        expired_shared = _make_trip(
            organizer,
            resort,
            start_date=TODAY - timedelta(days=10),
            end_date=TODAY + timedelta(days=5),
        )
        expired = SkiTripParticipant(
            trip_id=expired_shared.id,
            user_id=going_friend.id,
            status=GuestStatus.GOING,
            role="guest",
            start_date=TODAY - timedelta(days=4),
            end_date=TODAY - timedelta(days=1),
        )
        db.session.add(expired)
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)
        trip_rows = [row for row in rows if row["idea_type"] == "friend_trip"]
        identities = {
            (row["start_date"], tuple(row["friend_ids"])) for row in trip_rows
        }

        assert (TODAY, (owner_friend.id,)) in identities
        assert (TODAY, (interested_friend.id,)) in identities
        assert (
            TODAY + timedelta(days=3),
            (going_friend.id,),
        ) in identities
        surfaced = {friend_id for row in trip_rows for friend_id in row["friend_ids"]}
        assert pending_friend.id not in surfaced
        assert declined_friend.id not in surfaced
        assert removed_friend.id not in surfaced
        assert nonfriend.id not in surfaced
        assert TODAY + timedelta(days=20) not in {
            row["start_date"] for row in trip_rows
        }
        assert TODAY + timedelta(days=30) not in {
            row["start_date"] for row in trip_rows
        }
        assert all(row["end_date"] >= TODAY for row in trip_rows)
        assert {row["resort_id"] for row in trip_rows} == {
            resort.id,
            interested_resort.id,
            going_resort.id,
        }


def test_availability_merging_dedupe_casing_and_inactive_wishlist_behavior(client):
    with app.app_context():
        days = [TODAY + timedelta(days=n) for n in (1, 2, 3)]
        inactive = _make_resort("Ideas Inactive")
        inactive.is_active = False
        viewer = _make_user(
            "ideas-open-viewer",
            open_dates=[day.isoformat() for day in days],
            wish_list_resorts=[inactive.id],
        )
        first = _make_user(
            "ideas-open-first",
            open_dates=[days[0].isoformat(), days[1].isoformat()],
            wish_list_resorts=[inactive.id],
        )
        first.first_name = "aLEX"
        second = _make_user(
            "ideas-open-second",
            open_dates=[days[1].isoformat(), days[2].isoformat()],
        )
        _connect(viewer, first)
        _connect(viewer, second)
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)

        assert len(rows) == 1
        row = rows[0]
        assert row["start_date"] == days[0]
        assert row["end_date"] == days[2]
        assert row["friend_count"] == 2
        assert row["friend_ids"] == sorted([first.id, second.id])
        assert row["resort_id"] is None
        assert row["anchor_friend_name"] == "Alex"
        assert row["line2"].startswith("Alex overlaps")

        # An inactive shared wishlist alone is not an Ideas destination.
        viewer.open_dates = []
        first.open_dates = []
        second.open_dates = []
        db.session.commit()
        assert get_home_ideas(user_id=viewer.id, today=TODAY) == []


def test_wishlist_multiple_friends_source_competition_and_both_dismissal_keys(client):
    with app.app_context():
        viewer = _make_user("ideas-concept-viewer")
        first = _make_user("ideas-concept-first")
        second = _make_user("ideas-concept-second")
        resort = _make_resort("Ideas Concept")
        viewer.wish_list_resorts = [resort.id]
        first.wish_list_resorts = [resort.id]
        second.wish_list_resorts = [resort.id]
        shared_day = TODAY + timedelta(days=5)
        viewer.open_dates = [shared_day.isoformat()]
        first.open_dates = [shared_day.isoformat()]
        second.open_dates = [shared_day.isoformat()]
        _connect(viewer, first)
        _connect(viewer, second)
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=TODAY)
        assert len(rows) == 1
        assert rows[0]["idea_type"] == "availability_overlap"
        assert rows[0]["friend_count"] == 2
        resort_key = f"availability_overlap:{resort.id}"
        db.session.add(
            DismissedInsightCard(
                user_id=viewer.id,
                card_type="opportunity",
                card_key=resort_key,
            )
        )
        db.session.commit()
        assert get_home_ideas(user_id=viewer.id, today=TODAY) == []

        # Mountainless canonical keys include sorted, deduplicated friend IDs.
        viewer.wish_list_resorts = []
        first.wish_list_resorts = []
        second.wish_list_resorts = []
        db.session.query(DismissedInsightCard).delete()
        db.session.commit()
        no_resort = get_home_ideas(user_id=viewer.id, today=TODAY)[0]
        expected_key = (
            "availability_overlap:"
            f"{min(first.id, second.id)}_{max(first.id, second.id)}:"
            f"{shared_day.isoformat()}"
        )
        assert no_resort["_card_key"] == expected_key
        db.session.add(
            DismissedInsightCard(
                user_id=viewer.id,
                card_type="opportunity",
                card_key=expected_key,
            )
        )
        db.session.commit()
        assert get_home_ideas(user_id=viewer.id, today=TODAY) == []


def test_deterministic_oracle_equivalence_and_new_service_query_count(client):
    real_today = date.today()
    with app.app_context():
        viewer = _make_user("ideas-oracle-viewer")
        friend = _make_user("ideas-oracle-friend")
        trip_resort = _make_resort("Ideas Oracle Trip")
        wish_resort = _make_resort("Ideas Oracle Wish")
        viewer.wish_list_resorts = [wish_resort.id]
        friend.wish_list_resorts = [wish_resort.id]
        _connect(viewer, friend)
        _make_trip(
            friend,
            trip_resort,
            start_date=real_today + timedelta(days=10),
            end_date=real_today + timedelta(days=12),
            trip_status="going",
        )
        db.session.commit()
        old_rows, _diag, _trips = build_destination_feed(
            viewer,
            [friend],
            user_avail_dates=set(),
            user_trips=[],
            resort_map={
                trip_resort.id: trip_resort,
                wish_resort.id: wish_resort,
            },
        )

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                statements.append(statement)

        viewer_id = viewer.id
        sa.event.listen(db.engine, "before_cursor_execute", capture)
        try:
            new_rows = get_home_ideas(user_id=viewer_id, today=real_today)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", capture)

        def semantic(rows):
            return [
                (
                    row["resort_id"],
                    row["start_date"],
                    row["end_date"],
                    row["friend_count"],
                    row["going_count"],
                    row["considering_count"],
                    row["line2"],
                    row["signal_type"],
                    row["idea_type"],
                    tuple(sorted(set(row["friend_ids"]))),
                )
                for row in rows
            ]

        assert semantic(new_rows) == semantic(old_rows)
        assert len(statements) == 1