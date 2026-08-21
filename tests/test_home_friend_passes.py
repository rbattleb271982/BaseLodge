"""Tests for the Home Friends' Passes card and shared pass-group counting."""

from types import SimpleNamespace

from app import app
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


def test_home_always_renders_zero_count_card(client):
    with app.app_context():
        me = _make_user("home-zero-passes")
        db.session.commit()
        me_id = me.id

    _login(client, me_id)
    response = client.get("/home")

    assert response.status_code == 200
    html = response.data.decode()
    assert "Friends' Passes" in html
    assert "Friends' Passes · 0 friends" in html
    assert html.count('class="fp-card-count">0</span>') == 3
    assert html.index(">Epic</span>") < html.index(">Ikon</span>") < html.index(">Other</span>")


def test_home_renders_singular_friend_total(client):
    with app.app_context():
        me = _make_user("home-one-friend")
        friend = _make_user("home-one-friend-target")
        db.session.add(Friend(user_id=me.id, friend_id=friend.id))
        db.session.commit()
        me_id = me.id

    _login(client, me_id)
    response = client.get("/home")

    assert response.status_code == 200
    assert "Friends' Passes · 1 friend" in response.data.decode()


def test_home_renders_multi_pass_counts_and_filter_links(client):
    with app.app_context():
        me = _make_user("home-pass-owner")
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
    assert "pass=indy%2Cmountain_collective%2Cpowder_alliance%2Cfreedom%2Cski_california%2Cother" in html
    assert 'aria-label="Show 2 Epic pass friends"' in html
    assert 'aria-label="Show 1 Ikon pass friends"' in html
    assert 'aria-label="Show 2 friends with other passes"' in html
    assert "Friends' Passes · 3 friends" in html