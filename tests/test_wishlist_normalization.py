from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app import app
from conftest import _login, _make_resort, _make_user, json_post
from models import Friend, User, WishlistResortEvent, db
from services.ideas_retrieval import get_home_ideas
from services.wishlist import (
    WISHLIST_LIMIT,
    WishlistValidationError,
    normalize_wishlist_resort_ids,
    validate_wishlist_resort_ids,
)


def _connect(first, second):
    db.session.add_all([
        Friend(user_id=first.id, friend_id=second.id),
        Friend(user_id=second.id, friend_id=first.id),
    ])


@pytest.mark.parametrize("value", ["bad", True, False, None, 1.0, {}, []])
def test_normalization_rejects_malformed_ids(value):
    with pytest.raises(WishlistValidationError):
        normalize_wishlist_resort_ids([value])


def test_normalization_coerces_numeric_strings_and_preserves_first_seen_order():
    assert normalize_wishlist_resort_ids([4, "2", 4, "7", "2"]) == [4, 2, 7]


def test_bulk_validation_uses_one_resort_query(client):
    with app.app_context():
        resorts = [_make_resort(f"Bounded Wishlist {index}") for index in range(3)]
        ids = [resort.id for resort in resorts]
        db.session.commit()
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if "from resort" in " ".join(statement.lower().split()):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            assert validate_wishlist_resort_ids(ids) == ids
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert len(statements) == 1


def test_bulk_save_dedupes_before_limit_and_preserves_order(client):
    with app.app_context():
        user = _make_user("wishlist-bulk")
        resorts = [_make_resort(f"Bulk Resort {index}") for index in range(15)]
        ids = [resort.id for resort in resorts]
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    payload = [str(ids[0]), ids[1], ids[0], *ids[2:], str(ids[-1])]
    response = json_post(
        client, "/settings/wish-list/save", {"resort_ids": payload}
    )

    assert response.status_code == 200
    assert response.get_json()["count"] == 15
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == ids


@pytest.mark.parametrize("invalid_kind", ["inactive", "region", "nonexistent", "malformed"])
def test_bulk_save_rejects_invalid_destination_atomically(client, invalid_kind):
    with app.app_context():
        user = _make_user("wishlist-atomic")
        original = _make_resort("Original Wishlist")
        valid = _make_resort("Valid Wishlist")
        invalid = _make_resort("Invalid Wishlist")
        if invalid_kind == "inactive":
            invalid.is_active = False
            invalid_value = invalid.id
        elif invalid_kind == "region":
            invalid.is_region = True
            invalid_value = invalid.id
        elif invalid_kind == "nonexistent":
            invalid_value = 999999999
        else:
            invalid_value = "not-a-resort"
        user.wish_list_resorts = [original.id]
        user_id, original_id, valid_id = user.id, original.id, valid.id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client,
        "/settings/wish-list/save",
        {"resort_ids": [valid_id, invalid_value]},
    )

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == [original_id]


def test_bulk_save_rejects_sixteenth_unique_resort(client):
    with app.app_context():
        user = _make_user("wishlist-over-limit")
        original = _make_resort("Over Limit Original")
        resorts = [_make_resort(f"Over Limit {index}") for index in range(16)]
        user.wish_list_resorts = [original.id]
        user_id, original_id = user.id, original.id
        ids = [resort.id for resort in resorts]
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client, "/settings/wish-list/save", {"resort_ids": ids}
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "wishlist_limit"
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == [original_id]


def test_duplicate_add_at_limit_is_successful_noop_and_repairs_storage(client):
    with app.app_context():
        user = _make_user("wishlist-add-duplicate")
        resorts = [_make_resort(f"Add Limit {index}") for index in range(15)]
        ids = [resort.id for resort in resorts]
        user.wish_list_resorts = [str(ids[0]), ids[0], *ids[1:]]
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client, "/api/wishlist/add", {"resort_id": str(ids[0])}
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": 15,
        "at_limit": True,
    }
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == ids


def test_add_allows_fifteenth_and_rejects_sixteenth(client):
    with app.app_context():
        user = _make_user("wishlist-add-cap")
        resorts = [_make_resort(f"Add Cap {index}") for index in range(16)]
        ids = [resort.id for resort in resorts]
        user.wish_list_resorts = ids[:14]
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    fifteenth = json_post(client, "/api/wishlist/add", {"resort_id": ids[14]})
    sixteenth = json_post(client, "/api/wishlist/add", {"resort_id": ids[15]})

    assert fifteenth.get_json()["count"] == 15
    assert sixteenth.status_code == 200
    assert sixteenth.get_json()["at_limit"] is True
    assert "success" not in sixteenth.get_json()
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == ids[:15]


@pytest.mark.parametrize("kind,expected_status", [
    ("inactive", 404),
    ("region", 404),
    ("nonexistent", 404),
    ("malformed", 400),
])
def test_add_rejects_invalid_destination(client, kind, expected_status):
    with app.app_context():
        user = _make_user("wishlist-add-invalid")
        invalid = _make_resort("Add Invalid")
        if kind == "inactive":
            invalid.is_active = False
            value = invalid.id
        elif kind == "region":
            invalid.is_region = True
            value = invalid.id
        elif kind == "nonexistent":
            value = 999999999
        else:
            value = 1.5
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = json_post(client, "/api/wishlist/add", {"resort_id": value})
    assert response.status_code == expected_status


@pytest.mark.parametrize("url", ["/api/wishlist/add", "/api/wishlist/remove"])
@pytest.mark.parametrize("payload", [[], "resort", 42])
def test_single_mutations_reject_non_object_json(client, url, payload):
    with app.app_context():
        user = _make_user("wishlist-container")
        user_id = user.id
        db.session.commit()

    _login(client, user_id)
    response = client.post(
        url,
        json=payload,
        headers={"X-CSRF-Token": "test-csrf-fixed-value-baselodge-regression"},
    )
    assert response.status_code == 400


def test_remove_canonicalizes_storage_and_emits_only_real_removal(client):
    with app.app_context():
        user = _make_user("wishlist-remove")
        removed = _make_resort("Remove Wishlist")
        kept = _make_resort("Keep Wishlist")
        user.wish_list_resorts = [
            removed.id,
            "legacy-bad",
            str(kept.id),
            str(removed.id),
            kept.id,
        ]
        user_id, removed_id, kept_id = user.id, removed.id, kept.id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client, "/api/wishlist/remove", {"resort_id": str(removed_id)}
    )

    assert response.get_json() == {
        "success": True,
        "count": 1,
        "at_limit": False,
    }
    with app.app_context():
        assert db.session.get(User, user_id).wish_list_resorts == [kept_id]
        events = WishlistResortEvent.query.order_by(
            WishlistResortEvent.id
        ).all()
        assert [(event.resort_id, event.event_type) for event in events] == [
            (removed_id, "removed")
        ]


@pytest.mark.parametrize(
    ("remaining_count", "expected_at_limit"),
    [(0, False), (14, False), (WISHLIST_LIMIT, True)],
)
def test_remove_reports_canonical_limit_at_boundaries(
    client, remaining_count, expected_at_limit
):
    with app.app_context():
        user = _make_user(f"wishlist-remove-{remaining_count}")
        resorts = [
            _make_resort(f"Remove Boundary {remaining_count} {index}")
            for index in range(remaining_count + 1)
        ]
        user.wish_list_resorts = [resort.id for resort in resorts]
        user_id = user.id
        removed_id = resorts[-1].id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client, "/api/wishlist/remove", {"resort_id": removed_id}
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": remaining_count,
        "at_limit": expected_at_limit,
    }


def test_remove_repairs_over_limit_legacy_data_without_fabricated_event(client):
    with app.app_context():
        user = _make_user("wishlist-remove-over-limit")
        resorts = [
            _make_resort(f"Remove Over Limit {index}")
            for index in range(WISHLIST_LIMIT + 2)
        ]
        user.wish_list_resorts = [resort.id for resort in resorts]
        user_id = user.id
        removed_id = resorts[-1].id
        db.session.commit()

    _login(client, user_id)
    response = json_post(
        client, "/api/wishlist/remove", {"resort_id": removed_id}
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "count": WISHLIST_LIMIT,
        "at_limit": True,
    }
    with app.app_context():
        stored_ids = db.session.get(User, user_id).wish_list_resorts
        assert len(stored_ids) == WISHLIST_LIMIT
        assert WishlistResortEvent.query.count() == 0


def test_model_reads_ignore_bad_data_dedupe_and_preserve_valid_order(client):
    with app.app_context():
        user = _make_user("wishlist-model")
        first = _make_resort("Model First")
        second = _make_resort("Model Second")
        inactive = _make_resort("Model Inactive")
        region = _make_resort("Model Region")
        inactive.is_active = False
        region.is_region = True
        user.wish_list_resorts = [
            second.id,
            "bad",
            first.id,
            str(second.id),
            inactive.id,
            region.id,
            999999999,
        ]
        db.session.commit()

        assert [resort.id for resort in user.get_wishlist_resorts()] == [
            second.id,
            first.id,
        ]
        assert user.wishlist_resorts_count == 2


def test_home_ideas_excludes_region_wishlist_candidates(client):
    with app.app_context():
        viewer = _make_user("wishlist-ideas-viewer")
        friend = _make_user("wishlist-ideas-friend")
        region = _make_resort("Ideas Region")
        region.is_region = True
        viewer.wish_list_resorts = [region.id]
        friend.wish_list_resorts = [region.id]
        viewer.open_dates = [date.today().isoformat()]
        friend.open_dates = [date.today().isoformat()]
        _connect(viewer, friend)
        db.session.commit()

        rows = get_home_ideas(user_id=viewer.id, today=date.today())
        assert len(rows) == 1
        assert rows[0]["idea_type"] == "availability_overlap"
        assert rows[0]["resort_id"] is None


@pytest.mark.parametrize("eligibility", ["inactive", "region"])
def test_mountain_social_signal_ignores_ineligible_wishlist(client, eligibility):
    with app.app_context():
        viewer = _make_user("wishlist-social-viewer")
        friend = _make_user("wishlist-social-friend")
        resort = _make_resort("Ineligible Social Wishlist")
        if eligibility == "inactive":
            resort.is_active = False
        else:
            resort.is_region = True
        friend.wish_list_resorts = [resort.id, str(resort.id)]
        _connect(viewer, friend)
        user_id, slug = viewer.id, resort.slug
        db.session.commit()

    _login(client, user_id)
    html = client.get(f"/mountain/{slug}").get_data(as_text=True)
    assert "Want to go" not in html


def test_admin_merge_normalizes_replacement_order_and_limit(client):
    with app.app_context():
        admin = _make_user("wishlist-merge-admin")
        canonical = _make_resort("Merge Canonical")
        duplicate = _make_resort("Merge Duplicate")
        others = [_make_resort(f"Merge Other {index}") for index in range(15)]
        admin.wish_list_resorts = [
            duplicate.id,
            canonical.id,
            str(duplicate.id),
            *[resort.id for resort in others],
        ]
        admin_id, admin_email = admin.id, admin.email
        canonical_id, duplicate_id = canonical.id, duplicate.id
        other_ids = [resort.id for resort in others]
        db.session.commit()

    _login(client, admin_id)
    with patch.dict("os.environ", {"ALLOWED_ADMIN_EMAILS": admin_email}):
        response = json_post(
            client,
            "/api/admin/resorts/merge",
            {"canonical_id": canonical_id, "duplicate_ids": [duplicate_id]},
        )

    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(User, admin_id).wish_list_resorts == [
            canonical_id,
            *other_ids[:14],
        ]
        assert WishlistResortEvent.query.count() == 0