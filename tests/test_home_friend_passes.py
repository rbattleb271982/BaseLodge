"""Tests for the Home Friends' Passes card and shared pass-group counting."""

from types import SimpleNamespace

from app import _build_home_pass_rows, app
from models import db, Friend
from services.pass_utils import (
    CANONICAL_PASS_ORDER,
    OTHER_PASS_SLUGS_URL,
    _NON_REAL_PASSES,
    _OTHER_PASS_SLUGS,
    _VALID_PASS_SLUGS,
    count_friends_by_pass_group,
)
from tests.conftest import _login, _make_user


def _friends(*pass_types):
    return [SimpleNamespace(pass_type=pass_type) for pass_type in pass_types]


def test_no_friends_returns_zero_counts():
    assert count_friends_by_pass_group([]) == {"epic": 0, "ikon": 0, "other": 0}


def test_epic_and_ikon_are_counted_independently():
    assert count_friends_by_pass_group(_friends("epic", "ikon", "epic,ikon")) == {
        "epic": 2,
        "ikon": 2,
        "other": 0,
    }


def test_every_current_non_epic_ikon_real_pass_counts_as_other():
    for slug in _OTHER_PASS_SLUGS:
        assert count_friends_by_pass_group(_friends(slug))["other"] == 1


def test_multi_other_pass_friend_is_deduplicated():
    assert count_friends_by_pass_group(
        _friends("indy,mountain_collective,powder_alliance")
    ) == {"epic": 0, "ikon": 0, "other": 1}


def test_epic_plus_other_counts_in_both_groups():
    assert count_friends_by_pass_group(_friends("epic,indy")) == {
        "epic": 1,
        "ikon": 0,
        "other": 1,
    }


def test_empty_and_non_real_passes_do_not_count():
    assert count_friends_by_pass_group(
        _friends(None, "", "no_pass", "no_pass_yet")
    ) == {"epic": 0, "ikon": 0, "other": 0}


def test_other_group_is_derived_from_canonical_passes():
    expected = _VALID_PASS_SLUGS - {"epic", "ikon"} - _NON_REAL_PASSES
    assert _OTHER_PASS_SLUGS == expected
    assert OTHER_PASS_SLUGS_URL.split(",") == [
        slug for slug in CANONICAL_PASS_ORDER if slug in expected
    ]


def test_exact_home_pass_rows_count_each_pass_independently():
    rows, friends_with_pass = _build_home_pass_rows(
        "epic,indy,mountain_collective",
        _friends(
            "epic,indy",
            "epic,mountain_collective",
            "mountain_collective",
            "no_pass",
        ),
    )

    assert rows == [
        {"slug": "epic", "label": "Epic", "friend_count": 2},
        {"slug": "indy", "label": "Indy Pass", "friend_count": 1},
        {
            "slug": "mountain_collective",
            "label": "Mountain Collective",
            "friend_count": 2,
        },
    ]
    assert friends_with_pass == 3


def test_home_no_pass_state_renders_zero_friend_context(client):
    with app.app_context():
        me = _make_user("home-zero-passes")
        me.pass_type = "no_pass"
        db.session.commit()
        me_id = me.id

    _login(client, me_id)
    response = client.get("/home")

    assert response.status_code == 200
    html = response.data.decode()
    assert "PASSES" in html
    assert "No pass added" in html
    assert "0 friends have one" in html
    assert 'href="/friends"' in html
    assert 'href="/select-pass"' in html
    assert "0 <span>on BaseLodge</span>" in html


def test_home_no_pass_state_counts_friends_who_have_a_real_pass(client):
    with app.app_context():
        me = _make_user("home-one-friend")
        me.pass_type = "no_pass"
        friend = _make_user("home-one-friend-target")
        friend.pass_type = "epic"
        db.session.add_all([
            Friend(user_id=me.id, friend_id=friend.id),
            Friend(user_id=friend.id, friend_id=me.id),
        ])
        db.session.commit()
        me_id = me.id

    _login(client, me_id)
    response = client.get("/home")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'href="/friends"' in html
    assert "No pass added" in html
    assert "1 friend has one" in html
    assert "1 <span>on BaseLodge</span>" in html


def test_home_renders_multi_pass_counts_and_filter_links(client):
    with app.app_context():
        me = _make_user("home-pass-owner")
        me.pass_type = "epic,ikon,indy"
        epic_ikon = _make_user("home-pass-epic-ikon")
        epic_ikon.pass_type = "epic,ikon"
        epic_indy = _make_user("home-pass-epic-indy")
        epic_indy.pass_type = "epic,indy"
        multi_other = _make_user("home-pass-multi-other")
        multi_other.pass_type = "indy,mountain_collective"
        for friend in (epic_ikon, epic_indy, multi_other):
            db.session.add(Friend(user_id=me.id, friend_id=friend.id))
            db.session.add(Friend(user_id=friend.id, friend_id=me.id))
        db.session.commit()
        me_id = me.id

    _login(client, me_id)
    response = client.get("/home")

    assert response.status_code == 200
    html = response.data.decode()
    assert 'href="/friends?pass=epic"' in html
    assert 'href="/friends?pass=ikon"' in html
    assert 'href="/friends?pass=indy"' in html
    assert "Epic" in html
    assert "Ikon" in html
    assert "Indy Pass" in html
    assert "2 friends" in html
    assert "1 friend" in html
    assert 'href="/friends"' in html
    assert "3 <span>on BaseLodge</span>" in html