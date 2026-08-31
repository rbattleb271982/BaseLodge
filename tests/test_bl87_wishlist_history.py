"""Focused behavior coverage for BL-87 wishlist transition history."""

from unittest.mock import patch

import pytest

from app import app
from conftest import _login, _make_resort, _make_user, json_post
from models import User, WishlistResortEvent, db
from services.wishlist import (
    add_wishlist_resort,
    remove_wishlist_resort,
    replace_wishlist,
)


def _events():
    return WishlistResortEvent.query.order_by(WishlistResortEvent.id).all()


def test_add_remove_add_records_three_distinct_ordered_events(client):
    with app.app_context():
        user = _make_user("wishlist-cycle")
        resort = _make_resort("Wishlist Cycle")
        user_id, resort_id = user.id, resort.id
        db.session.commit()

    _login(client, user_id)
    for path in (
        "/api/wishlist/add",
        "/api/wishlist/remove",
        "/api/wishlist/add",
    ):
        response = json_post(client, path, {"resort_id": resort_id})
        assert response.status_code == 200

    with app.app_context():
        events = _events()
        assert [event.event_type for event in events] == [
            "added",
            "removed",
            "added",
        ]
        assert {event.resort_id for event in events} == {resort_id}
        assert {event.user_id for event in events} == {user_id}
        assert {event.actor_user_id for event in events} == {user_id}
        assert {event.source for event in events} == {"mountain_detail"}
        assert all(event.occurred_at is not None for event in events)


def test_duplicate_add_absent_remove_and_retry_emit_no_events(client):
    with app.app_context():
        user = _make_user("wishlist-noops")
        present = _make_resort("Wishlist Present")
        absent = _make_resort("Wishlist Absent")
        user.wish_list_resorts = [present.id]
        user_id, present_id, absent_id = user.id, present.id, absent.id
        db.session.commit()

    _login(client, user_id)
    with patch("app.ph_analytics.track") as track:
        assert json_post(
            client, "/api/wishlist/add", {"resort_id": present_id}
        ).status_code == 200
        assert json_post(
            client, "/api/wishlist/remove", {"resort_id": absent_id}
        ).status_code == 200
        track.assert_not_called()

    with app.app_context():
        assert WishlistResortEvent.query.count() == 0
        assert db.session.get(User, user_id).wish_list_resorts == [present_id]


def test_settings_replacement_uses_deterministic_membership_diff(client):
    with app.app_context():
        user = _make_user("wishlist-diff")
        old = [_make_resort(f"Wishlist Old {index}") for index in range(3)]
        added = [_make_resort(f"Wishlist Added {index}") for index in range(3)]
        user.wish_list_resorts = [resort.id for resort in old]
        user_id = user.id
        old_ids = [resort.id for resort in old]
        added_ids = [resort.id for resort in added]
        db.session.commit()

    requested = [old_ids[1], *added_ids]
    _login(client, user_id)
    response = json_post(
        client, "/settings/wish-list/save", {"resort_ids": requested}
    )
    assert response.status_code == 200

    with app.app_context():
        events = _events()
        assert [(event.event_type, event.resort_id) for event in events] == [
            ("removed", old_ids[0]),
            ("removed", old_ids[2]),
            ("added", added_ids[0]),
            ("added", added_ids[1]),
            ("added", added_ids[2]),
        ]
        assert {event.source for event in events} == {"settings"}
        assert db.session.get(User, user_id).wish_list_resorts == requested


def test_reorder_identical_and_normalization_only_changes_emit_no_events(client):
    with app.app_context():
        user = _make_user("wishlist-nonmembership")
        first = _make_resort("Wishlist First")
        second = _make_resort("Wishlist Second")
        user.wish_list_resorts = [str(first.id), first.id, second.id, "bad"]
        user_id, first_id, second_id = user.id, first.id, second.id
        db.session.commit()

    _login(client, user_id)
    for requested in (
        [first_id, second_id],
        [second_id, first_id],
        [second_id, first_id],
    ):
        response = json_post(
            client, "/settings/wish-list/save", {"resort_ids": requested}
        )
        assert response.status_code == 200

    with app.app_context():
        assert WishlistResortEvent.query.count() == 0
        assert db.session.get(User, user_id).wish_list_resorts == [
            second_id,
            first_id,
        ]


def test_service_flushes_without_committing_and_rollback_is_atomic(client):
    with app.app_context():
        user = _make_user("wishlist-rollback")
        resort = _make_resort("Wishlist Rollback")
        user_id, resort_id = user.id, resort.id
        db.session.commit()

        change = add_wishlist_resort(
            db.session,
            user_id=user_id,
            resort_id=resort_id,
            actor_user_id=user_id,
        )
        assert change.added_ids == [resort_id]
        assert WishlistResortEvent.query.count() == 1
        db.session.rollback()
        db.session.expire_all()
        assert db.session.get(User, user_id).wish_list_resorts == []
        assert WishlistResortEvent.query.count() == 0


def test_subject_account_deletion_erases_history_and_actor_only_is_anonymized(client):
    with app.app_context():
        subject = _make_user("wishlist-delete-subject")
        actor = _make_user("wishlist-delete-actor")
        other = _make_user("wishlist-delete-other")
        resort = _make_resort("Wishlist Privacy")
        db.session.add_all([
            WishlistResortEvent(
                user_id=actor.id,
                resort_id=resort.id,
                actor_user_id=actor.id,
                event_type="added",
                source="mountain_detail",
            ),
            WishlistResortEvent(
                user_id=other.id,
                resort_id=resort.id,
                actor_user_id=subject.id,
                event_type="added",
                source="settings",
            ),
            WishlistResortEvent(
                user_id=subject.id,
                resort_id=resort.id,
                actor_user_id=subject.id,
                event_type="added",
                source="settings",
            ),
        ])
        db.session.commit()
        subject_id, subject_email = subject.id, subject.email
        other_id = other.id

    _login(client, subject_id)
    response = client.post(
        "/delete-account",
        data={
            "confirm_email": subject_email,
            "csrf_token": "test-csrf-fixed-value-baselodge-regression",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        assert WishlistResortEvent.query.filter_by(
            user_id=subject_id
        ).count() == 0
        surviving = WishlistResortEvent.query.filter_by(user_id=other_id).one()
        assert surviving.actor_user_id is None
        assert WishlistResortEvent.query.filter_by(
            event_type="removed"
        ).count() == 0


def test_inactivation_preserves_history(client):
    with app.app_context():
        user = _make_user("wishlist-inactive")
        resort = _make_resort("Wishlist Inactivation")
        event = WishlistResortEvent(
            user_id=user.id,
            resort_id=resort.id,
            actor_user_id=user.id,
            event_type="added",
            source="mountain_detail",
        )
        db.session.add(event)
        db.session.commit()
        event_id, resort_id = event.id, resort.id
        resort.is_active = False
        db.session.commit()
        assert db.session.get(WishlistResortEvent, event_id) is not None
        assert db.session.get(WishlistResortEvent, event_id).resort_id == resort_id


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/admin/resorts/delete", lambda resort_id: {"resort_id": resort_id}),
        ("/api/admin/resorts/bulk-delete", lambda resort_id: {"ids": [resort_id]}),
    ],
)
def test_numeric_string_wishlist_reference_blocks_hard_delete(
    client, path, payload
):
    with app.app_context():
        admin = _make_user("wishlist-delete-guard")
        resort = _make_resort("Wishlist Delete Guard")
        admin.wish_list_resorts = [str(resort.id), "bad"]
        admin_id, admin_email, resort_id = admin.id, admin.email, resort.id
        db.session.commit()

    _login(client, admin_id)
    with patch.dict("os.environ", {"ALLOWED_ADMIN_EMAILS": admin_email}):
        response = json_post(client, path, payload(resort_id))

    assert response.status_code in (200, 400)
    body = response.get_json()
    if path.endswith("bulk-delete"):
        assert body["deleted"] == []
        assert body["blocked"][0]["id"] == resort_id
    else:
        assert response.status_code == 400
    with app.app_context():
        assert db.session.get(User, admin_id) is not None
        assert db.session.get(WishlistResortEvent, 999999) is None


def test_numeric_string_wishlist_reference_blocks_rest_hard_delete(client):
    with app.app_context():
        admin = _make_user("wishlist-rest-delete-guard")
        resort = _make_resort("Wishlist REST Delete Guard")
        admin.wish_list_resorts = [str(resort.id)]
        admin_id, admin_email, resort_id = admin.id, admin.email, resort.id
        db.session.commit()

    _login(client, admin_id)
    with patch.dict("os.environ", {"ALLOWED_ADMIN_EMAILS": admin_email}):
        response = client.delete(
            f"/api/admin/resorts/{resort_id}",
            headers={"X-CSRFToken": "test-csrf-fixed-value-baselodge-regression"},
        )

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(User, admin_id).wish_list_resorts == [
            str(resort_id)
        ]


def test_direct_service_replace_and_remove_return_structured_change(client):
    with app.app_context():
        user = _make_user("wishlist-result")
        first = _make_resort("Wishlist Result First")
        second = _make_resort("Wishlist Result Second")
        user.wish_list_resorts = [first.id]
        user_id, first_id, second_id = user.id, first.id, second.id
        db.session.commit()

        changed = replace_wishlist(
            db.session,
            user_id=user_id,
            requested_ids=[second_id],
            actor_user_id=user_id,
        )
        assert changed.old_ids == [first_id]
        assert changed.new_ids == [second_id]
        assert changed.removed_ids == [first_id]
        assert changed.added_ids == [second_id]
        db.session.commit()

        removed = remove_wishlist_resort(
            db.session,
            user_id=user_id,
            resort_id=second_id,
            actor_user_id=user_id,
        )
        assert removed.removed_ids == [second_id]
        assert removed.count == 0