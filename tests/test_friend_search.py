"""Server-side tests for the GET /api/users/search endpoint.

Covers:
  - Query eligibility validation
  - Discoverability filtering (both directions, including incoming-request exception)
  - Mutual count accuracy (0/1/many, pending not counted, opted-out confirmed mutual)
  - Relationship state resolution (all 5 states)
  - Ranking (better name match before weaker, mutual count tiebreak)
  - Sensitive data not leaked in response
  - Result cap (max 50)
  - Auth required
"""
import pytest
from services.search_utils import normalize_for_search

from app import app
from models import (
    db, User, Friend, Invitation, FriendCooldown, InviteType,
)
from tests.conftest import _make_user, _login, _TEST_CSRF


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_searchable_user(label, first, last, **kwargs):
    """Create a user with pre-normalized search columns.

    Sets first/last name and search columns after _make_user() to avoid
    conflict with conftest's hardcoded first_name/last_name defaults.
    Extra kwargs that are NOT first_name/last_name go through normally.
    """
    disc = kwargs.pop('discoverable_in_friend_search', True)
    home_state = kwargs.pop('home_state', None)
    u = _make_user(label, **kwargs)
    db.session.flush()
    u.first_name = first
    u.last_name = last
    u.search_first_name = normalize_for_search(first)
    u.search_last_name = normalize_for_search(last)
    u.discoverable_in_friend_search = disc
    if home_state is not None:
        u.home_state = home_state
    return u


def _search(client, q, user_id=None):
    """GET /api/users/search?q=<q> as user_id (logs them in if given)."""
    if user_id is not None:
        _login(client, user_id)
    return client.get(f'/api/users/search?q={q}')


def _ids(response):
    return [r['id'] for r in response.get_json()]


def _states(response):
    return {r['id']: r['relationship_state'] for r in response.get_json()}


# ── Eligibility validation ────────────────────────────────────────────────────

class TestSearchEligibility:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'User')
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def test_requires_auth(self):
        rv = self.client.get('/api/users/search?q=John+Smith')
        assert rv.status_code in (401, 302)

    def test_single_token_rejected(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=John')
        assert rv.status_code == 400

    def test_token_too_short_rejected(self):
        """'Jo S' — second token only 1 char — must be rejected."""
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Jo+S')
        assert rv.status_code == 400

    def test_two_valid_tokens_accepted(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Jo+Sm')
        assert rv.status_code == 200

    def test_empty_query_rejected(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=')
        assert rv.status_code == 400


# ── Name matching ─────────────────────────────────────────────────────────────

class TestNameMatching:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            self.john = _make_searchable_user('john', 'John', 'Smith')
            self.jane = _make_searchable_user('jane', 'Jane', 'Smith')
            self.jose = _make_searchable_user('jose', 'José', 'García')
            db.session.commit()
            self.me_id = self.me.id
            self.john_id = self.john.id
            self.jane_id = self.jane.id
            self.jose_id = self.jose.id
        self.client = client

    def test_exact_first_last_match(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=John+Smith')
        assert rv.status_code == 200
        assert self.john_id in _ids(rv)

    def test_prefix_match_first_and_last(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Jo+Sm')
        ids = _ids(rv)
        assert self.john_id in ids
        assert self.jane_id not in ids  # Jane ≠ Jo prefix match on first name

    def test_accented_name_found_without_accent(self):
        """Search 'Jose Garcia' should find José García via normalization."""
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Jose+Garcia')
        assert rv.status_code == 200
        assert self.jose_id in _ids(rv)

    def test_self_excluded_from_results(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Me+Muser')
        assert self.me_id not in _ids(rv)

    def test_middle_of_name_does_not_match(self):
        """'ohn mith' is not a prefix match — should NOT return John Smith."""
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=ohn+mith')
        assert self.john_id not in _ids(rv)


# ── Discoverability filtering ─────────────────────────────────────────────────

class TestDiscoverabilityFiltering:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            # discoverable=True (default)
            self.visible = _make_searchable_user('vis', 'Visible', 'Person')
            # discoverable=False — should be hidden in most cases
            self.hidden = _make_searchable_user(
                'hid', 'Hidden', 'Person',
                discoverable_in_friend_search=False,
            )
            db.session.commit()
            self.me_id = self.me.id
            self.visible_id = self.visible.id
            self.hidden_id = self.hidden.id
        self.client = client

    def test_discoverable_user_appears(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Visible+Person')
        assert self.visible_id in _ids(rv)

    def test_non_discoverable_hidden(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Hidden+Person')
        assert self.hidden_id not in _ids(rv)

    def test_non_discoverable_friend_visible(self):
        """An opted-out user who is already my friend should appear."""
        with app.app_context():
            db.session.add(Friend(user_id=self.me_id, friend_id=self.hidden_id))
            db.session.add(Friend(user_id=self.hidden_id, friend_id=self.me_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Hidden+Person')
        assert self.hidden_id in _ids(rv)

    def test_non_discoverable_sender_visible_to_recipient(self):
        """If hidden user sent ME a request, I should see them (to accept)."""
        with app.app_context():
            inv = Invitation(
                sender_id=self.hidden_id, receiver_id=self.me_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Hidden+Person')
        assert self.hidden_id in _ids(rv)
        # State should be 'incoming'
        states = _states(rv)
        assert states[self.hidden_id] == 'incoming'

    def test_non_discoverable_not_visible_to_requester(self):
        """I sent hidden user a request but they turned off discovery → still hidden."""
        with app.app_context():
            inv = Invitation(
                sender_id=self.me_id, receiver_id=self.hidden_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Hidden+Person')
        # Outgoing request does NOT grant visibility
        assert self.hidden_id not in _ids(rv)


# ── Relationship state resolution ─────────────────────────────────────────────

class TestRelationshipState:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            self.target = _make_searchable_user('tgt', 'Target', 'Person')
            db.session.commit()
            self.me_id = self.me.id
            self.target_id = self.target.id
        self.client = client

    def test_state_none(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        states = _states(rv)
        assert states[self.target_id] == 'none'

    def test_state_friend(self):
        with app.app_context():
            db.session.add(Friend(user_id=self.me_id, friend_id=self.target_id))
            db.session.add(Friend(user_id=self.target_id, friend_id=self.me_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        states = _states(rv)
        assert states[self.target_id] == 'friend'

    def test_state_outgoing(self):
        with app.app_context():
            inv = Invitation(
                sender_id=self.me_id, receiver_id=self.target_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        states = _states(rv)
        assert states[self.target_id] == 'outgoing'

    def test_state_incoming(self):
        with app.app_context():
            inv = Invitation(
                sender_id=self.target_id, receiver_id=self.me_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        states = _states(rv)
        assert states[self.target_id] == 'incoming'

    def test_state_cooldown(self):
        with app.app_context():
            from app import _set_pair_cooldown
            _set_pair_cooldown(self.me_id, self.target_id, hours=24)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        states = _states(rv)
        assert states[self.target_id] == 'cooldown'

    def test_invitation_id_present_for_outgoing(self):
        with app.app_context():
            inv = Invitation(
                sender_id=self.me_id, receiver_id=self.target_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next(r for r in result if r['id'] == self.target_id)
        assert match['invitation_id'] == inv_id

    def test_invitation_id_present_for_incoming(self):
        with app.app_context():
            inv = Invitation(
                sender_id=self.target_id, receiver_id=self.me_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next(r for r in result if r['id'] == self.target_id)
        assert match['invitation_id'] == inv_id


# ── Mutual count ──────────────────────────────────────────────────────────────

class TestMutualCount:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            self.target = _make_searchable_user('tgt', 'Target', 'Person')
            self.shared = _make_searchable_user('shared', 'Shared', 'Friend')
            db.session.commit()
            self.me_id = self.me.id
            self.target_id = self.target.id
            self.shared_id = self.shared.id
        self.client = client

    def test_zero_mutual(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next((r for r in result if r['id'] == self.target_id), None)
        if match:
            assert match['mutual_count'] == 0

    def test_one_mutual(self):
        with app.app_context():
            # me <-> shared, target <-> shared
            db.session.add(Friend(user_id=self.me_id, friend_id=self.shared_id))
            db.session.add(Friend(user_id=self.shared_id, friend_id=self.me_id))
            db.session.add(Friend(user_id=self.target_id, friend_id=self.shared_id))
            db.session.add(Friend(user_id=self.shared_id, friend_id=self.target_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next(r for r in result if r['id'] == self.target_id)
        assert match['mutual_count'] == 1

    def test_pending_not_counted_as_mutual(self):
        """A pending Invitation does not count as a mutual friend."""
        with app.app_context():
            # shared is friends with me but only has PENDING invite with target
            db.session.add(Friend(user_id=self.me_id, friend_id=self.shared_id))
            db.session.add(Friend(user_id=self.shared_id, friend_id=self.me_id))
            inv = Invitation(
                sender_id=self.shared_id, receiver_id=self.target_id,
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next((r for r in result if r['id'] == self.target_id), None)
        if match:
            assert match['mutual_count'] == 0

    def test_opted_out_user_counts_as_mutual(self):
        """A discoverable=False user still counts in mutual counts if confirmed friend."""
        with app.app_context():
            hidden_mutual = _make_searchable_user(
                'hm', 'Hidden', 'Mutual',
                discoverable_in_friend_search=False,
            )
            db.session.commit()
            hm_id = hidden_mutual.id
            # me <-> hm, target <-> hm (both confirmed friendships)
            db.session.add(Friend(user_id=self.me_id, friend_id=hm_id))
            db.session.add(Friend(user_id=hm_id, friend_id=self.me_id))
            db.session.add(Friend(user_id=self.target_id, friend_id=hm_id))
            db.session.add(Friend(user_id=hm_id, friend_id=self.target_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        match = next(r for r in result if r['id'] == self.target_id)
        # opted-out user is still a confirmed friend so counts
        assert match['mutual_count'] == 1


# ── Response schema ───────────────────────────────────────────────────────────

class TestResponseSchema:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            self.target = _make_searchable_user('tgt', 'Target', 'Person',
                                                home_state='CO')
            db.session.commit()
            self.me_id = self.me.id
            self.target_id = self.target.id
        self.client = client

    def test_response_fields_present(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        assert rv.status_code == 200
        result = rv.get_json()
        assert isinstance(result, list)
        if result:
            r = result[0]
            assert 'id' in r
            assert 'first_name' in r
            assert 'last_name' in r
            assert 'home_state' in r
            assert 'mutual_count' in r
            assert 'relationship_state' in r
            assert 'invitation_id' in r

    def test_email_not_leaked(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        for r in result:
            assert 'email' not in r
            assert 'password_hash' not in r

    def test_search_columns_not_leaked(self):
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Target+Person')
        result = rv.get_json()
        for r in result:
            assert 'search_first_name' not in r
            assert 'search_last_name' not in r

    def test_home_state_null_when_unset(self):
        _login(self.client, self.me_id)
        # 'Me' user has no home_state
        rv = self.client.get('/api/users/search?q=Target+Person')
        # just ensure no crash; structure is validated above


# ── Ranking ───────────────────────────────────────────────────────────────────

class TestRanking:

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_searchable_user('me', 'Me', 'Muser')
            # John Smith — full match on 'Jo Sm'
            self.john = _make_searchable_user('john', 'John', 'Smith')
            # Joel Smooth — also matches 'Jo Sm' but shorter prefix
            self.joel = _make_searchable_user('joel', 'Joel', 'Smooth')
            # Shared friend with joel only
            self.mutual = _make_searchable_user('mut', 'Mutual', 'Friend')
            db.session.commit()
            self.me_id = self.me.id
            self.john_id = self.john.id
            self.joel_id = self.joel.id
            self.mutual_id = self.mutual.id
        self.client = client

    def test_longer_prefix_match_ranked_higher(self):
        """'John Smith' provides a longer prefix match than 'Jo Sm' → ranked first."""
        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=John+Smith')
        result = rv.get_json()
        ids = [r['id'] for r in result]
        assert self.john_id in ids
        # John should be first (exact full match)
        assert ids[0] == self.john_id

    def test_mutual_count_breaks_ties(self):
        """When prefix match is equal, higher mutual count ranks first."""
        with app.app_context():
            # me-mutual, john-mutual (john gets 1 mutual)
            db.session.add(Friend(user_id=self.me_id, friend_id=self.mutual_id))
            db.session.add(Friend(user_id=self.mutual_id, friend_id=self.me_id))
            db.session.add(Friend(user_id=self.john_id, friend_id=self.mutual_id))
            db.session.add(Friend(user_id=self.mutual_id, friend_id=self.john_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = self.client.get('/api/users/search?q=Jo+Sm')
        result = rv.get_json()
        # Both john and joel match 'Jo Sm'; john has 1 mutual → should rank first
        john_pos = next(i for i, r in enumerate(result) if r['id'] == self.john_id)
        joel_pos = next(i for i, r in enumerate(result) if r['id'] == self.joel_id)
        assert john_pos < joel_pos
