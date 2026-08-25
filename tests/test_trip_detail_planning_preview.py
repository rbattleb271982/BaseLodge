"""BL-53 — canonical Plan Together preview on Trip Detail."""

from datetime import date, datetime, timedelta

import pytest

from app import app
from models import db, GuestStatus, SkiTrip, SkiTripParticipant, SkiTripPlanningPost
from tests.conftest import (
    _add_participant,
    _login,
    _make_resort,
    _make_trip,
    _make_user,
    json_post,
)


@pytest.fixture
def preview_setup(client):
    with app.app_context():
        resort = _make_resort()
        owner = _make_user("preview-owner")
        going = _make_user("preview-going")
        interested = _make_user("preview-interested")
        pending = _make_user("preview-pending")
        outsider = _make_user("preview-outsider")
        trip = _make_trip(owner, resort=resort)
        _add_participant(trip, going, GuestStatus.GOING)
        _add_participant(trip, interested, GuestStatus.INTERESTED)
        _add_participant(trip, pending, GuestStatus.PENDING)
        db.session.commit()
        return {
            "trip_id": trip.id,
            "owner_id": owner.id,
            "going_id": going.id,
            "interested_id": interested.id,
            "pending_id": pending.id,
            "outsider_id": outsider.id,
        }


def _detail_html(client, user_id, trip_id):
    _login(client, user_id)
    response = client.get(f"/trips/{trip_id}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("viewer_key", ["owner_id", "going_id", "interested_id"])
def test_active_planning_viewers_see_preview_and_composer(client, preview_setup, viewer_key):
    html = _detail_html(
        client, preview_setup[viewer_key], preview_setup["trip_id"]
    )

    assert 'class="td-hub-planning td-hub-section"' in html
    assert "Share an idea or link" in html
    assert 'id="td-planning-sheet"' in html
    assert "View all posts" in html


def test_pending_and_nonmembers_do_not_receive_planning_preview(client, preview_setup):
    pending_html = _detail_html(
        client, preview_setup["pending_id"], preview_setup["trip_id"]
    )
    assert 'class="td-hub-planning td-hub-section"' not in pending_html
    assert 'id="td-planning-sheet"' not in pending_html
    assert "View all posts" not in pending_html

    _login(client, preview_setup["outsider_id"])
    assert client.get(f"/trips/{preview_setup['trip_id']}").status_code == 404


def test_preview_is_newest_first_limited_to_three_and_keeps_total_count(
    client, preview_setup
):
    with app.app_context():
        now = datetime.utcnow()
        for index, label in enumerate(["oldest", "older", "middle", "newest"]):
            db.session.add(
                SkiTripPlanningPost(
                    trip_id=preview_setup["trip_id"],
                    user_id=preview_setup["owner_id"],
                    category="Other",
                    body=label,
                    created_at=now - timedelta(minutes=3 - index),
                )
            )
        db.session.commit()

    html = _detail_html(
        client, preview_setup["owner_id"], preview_setup["trip_id"]
    )

    assert "4 posts" in html
    assert "oldest" not in html
    assert html.index(">newest</p>") < html.index(">middle</p>") < html.index(
        ">older</p>"
    )


def test_preview_truncates_body_without_changing_canonical_post_and_uses_safe_link(
    client, preview_setup
):
    long_body = "x" * 180
    with app.app_context():
        post = SkiTripPlanningPost(
            trip_id=preview_setup["trip_id"],
            user_id=preview_setup["owner_id"],
            category="Lodging",
            body=long_body,
            link_url="https://example.com/stay",
        )
        db.session.add(post)
        db.session.commit()
        post_id = post.id

    html = _detail_html(
        client, preview_setup["owner_id"], preview_setup["trip_id"]
    )

    assert ("x" * 160) + "…" in html
    assert long_body not in html
    assert "Lodging" in html
    assert "Posted by" in html
    assert 'href="https://example.com/stay"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html

    with app.app_context():
        assert SkiTripPlanningPost.query.get(post_id).body == long_body


def test_empty_preview_keeps_compose_entry_and_full_board_link(client, preview_setup):
    html = _detail_html(
        client, preview_setup["owner_id"], preview_setup["trip_id"]
    )

    assert "No posts yet" in html
    assert "Share ideas and links with everyone going." in html
    assert "View all posts" in html
    assert 'href="/trips/{}/planning"'.format(preview_setup["trip_id"]) in html


def test_trip_detail_and_full_board_read_the_same_canonical_post_records(
    client, preview_setup
):
    _login(client, preview_setup["going_id"])
    response = json_post(
        client,
        f"/api/trip/{preview_setup['trip_id']}/planning-posts",
        {
            "category": "Transportation",
            "body": "Carpool from Denver",
            "link_url": "https://example.com/carpool",
        },
    )
    assert response.status_code == 201

    detail_html = client.get(f"/trips/{preview_setup['trip_id']}").get_data(
        as_text=True
    )
    board_html = client.get(f"/trips/{preview_setup['trip_id']}/planning").get_data(
        as_text=True
    )
    assert "Carpool from Denver" in detail_html
    assert "Carpool from Denver" in board_html

    with app.app_context():
        post = SkiTripPlanningPost.query.filter_by(
            trip_id=preview_setup["trip_id"], body="Carpool from Denver"
        ).one()
        assert post.category == "Transportation"
        assert post.link_url == "https://example.com/carpool"


def test_composer_exposes_all_existing_canonical_categories(client, preview_setup):
    html = _detail_html(
        client, preview_setup["owner_id"], preview_setup["trip_id"]
    )

    for category in (
        "Lodging",
        "Transportation",
        "Activities",
        "Food &amp; Drink",
        "Lessons",
        "Other",
    ):
        assert category in html


def test_historical_active_trip_keeps_current_planning_access_rule(client):
    with app.app_context():
        owner = _make_user("historical-owner")
        trip = _make_trip(
            owner,
            start_date=date.today() - timedelta(days=8),
            end_date=date.today() - timedelta(days=4),
        )
        db.session.commit()
        owner_id, trip_id = owner.id, trip.id

    _login(client, owner_id)
    assert client.get(f"/trips/{trip_id}").status_code == 200
    assert client.get(f"/trips/{trip_id}/planning").status_code == 200