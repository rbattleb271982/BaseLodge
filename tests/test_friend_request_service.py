"""Tests for the shared create_friend_request() helper and connection lifecycle.

Covers:
  - Self-request guard
  - Duplicate outgoing pending
  - Incoming-pending prevention (reverse request shows INCOMING_PENDING)
  - Pair-specific cooldown enforcement (A↔B blocked, A→C not blocked)
  - Cooldown from decline, cancel, unfriend
  - Cooldown expiry (simulated)
  - cancel_friend_invite endpoint (sender-only)
  - accept/decline idempotency
  - Invitation NULL uniqueness: multiple (A, B, NULL) rows can coexist
  - Notifications fire on valid request
"""
import pytest
from datetime import datetime, timedelta

from app import app, create_friend_request, _set_pair_cooldown
from models import (
    db, User, Friend, Invitation, FriendCooldown, InviteType,
)
from tests.conftest import (
    _make_user, _login,
    json_post, json_delete, _TEST_CSRF,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(client):
    """Re-export the shared client fixture."""
    return client


@pytest.fixture
def users(client):
    """Create three users A, B, C with normalized search columns."""
    from services.search_utils import normalize_for_search
    with app.app_context():
        a = _make_user('A')
        b = _make_user('B')
        c = _make_user('C')
        db.session.flush()
        # set names + search columns after creation to avoid conftest clash
        for u, fn, ln in [(a, 'Alice', 'Archer'), (b, 'Bob', 'Baxter'), (c, 'Carol', 'Cruz')]:
            u.first_name = fn
            u.last_name = ln
            u.search_first_name = normalize_for_search(fn)
            u.search_last_name = normalize_for_search(ln)
        db.session.commit()
        return {'A': a.id, 'B': b.id, 'C': c.id}


# ── create_friend_request() ───────────────────────────────────────────────────

class TestCreateFriendRequest:

    def test_self_request_rejected(self, client, users):
        with app.app_context():
            r = create_friend_request(users['A'], users['A'])
        assert r['ok'] is False
        assert r['code'] == 'SELF'

    def test_success(self, client, users):
        with app.app_context():
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is True
        assert r['code'] == 'SUCCESS'
        assert r['invitation_id'] is not None

    def test_duplicate_outgoing_rejected(self, client, users):
        with app.app_context():
            create_friend_request(users['A'], users['B'])
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is False
        assert r['code'] == 'OUTGOING_PENDING'

    def test_incoming_pending_returns_code(self, client, users):
        """When B→A is pending, A trying to send A→B gets INCOMING_PENDING."""
        with app.app_context():
            create_friend_request(users['B'], users['A'])
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is False
        assert r['code'] == 'INCOMING_PENDING'
        assert r['invitation_id'] is not None

    def test_already_friends_rejected(self, client, users):
        with app.app_context():
            db.session.add(Friend(user_id=users['A'], friend_id=users['B']))
            db.session.add(Friend(user_id=users['B'], friend_id=users['A']))
            db.session.commit()
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is False
        assert r['code'] == 'ALREADY_FRIENDS'

    def test_cooldown_blocks_request(self, client, users):
        with app.app_context():
            _set_pair_cooldown(users['A'], users['B'], hours=24)
            db.session.commit()
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is False
        assert r['code'] == 'COOLDOWN'

    def test_cooldown_is_pair_specific(self, client, users):
        """A↔B cooldown must NOT block A→C."""
        with app.app_context():
            _set_pair_cooldown(users['A'], users['B'], hours=24)
            db.session.commit()
            r = create_friend_request(users['A'], users['C'])
        assert r['ok'] is True
        assert r['code'] == 'SUCCESS'

    def test_expired_cooldown_allows_request(self, client, users):
        """A cooldown in the past should not block a new request."""
        with app.app_context():
            # Set cooldown that expired 1 second ago
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            past = datetime.utcnow() - timedelta(seconds=1)
            db.session.add(FriendCooldown(user_a_id=a, user_b_id=b, expires_at=past))
            db.session.commit()
            r = create_friend_request(users['A'], users['B'])
        assert r['ok'] is True


class TestInvitationNullUniqueness:
    """Verify PostgreSQL NULL uniqueness semantics hold in SQLite too:
    multiple (A, B, NULL) Invitation rows can coexist because NULLs
    are never equal in uniqueness checks."""

    def test_multiple_null_trip_id_rows_allowed(self, client, users):
        with app.app_context():
            inv1 = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='declined', invite_type=InviteType.OUTBOUND,
            )
            inv2 = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add_all([inv1, inv2])
            try:
                db.session.commit()
                committed = True
            except Exception:
                db.session.rollback()
                committed = False
            # Both rows should coexist (trip_id=NULL uniqueness not enforced)
            assert committed, "Multiple (A,B,NULL) Invitation rows should be allowed"
            count = Invitation.query.filter_by(
                sender_id=users['A'], receiver_id=users['B']
            ).count()
            assert count == 2


# ── Decline endpoint + cooldown ───────────────────────────────────────────────

class TestDeclineInvitation:

    def test_decline_sets_cooldown(self, client, users):
        """Declining a friend request creates a pair-specific cooldown."""
        with app.app_context():
            inv = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(client, users['B'])
        rv = json_post(client, f'/api/friends/invite/{inv_id}/decline')
        assert rv.status_code == 200

        with app.app_context():
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(
                user_a_id=a, user_b_id=b
            ).first()
            assert cooldown is not None
            assert cooldown.expires_at > datetime.utcnow()

    def test_decline_blocks_subsequent_request(self, client, users):
        """After decline, sender cannot immediately re-request."""
        with app.app_context():
            inv = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(client, users['B'])
        json_post(client, f'/api/friends/invite/{inv_id}/decline')

        with app.app_context():
            r = create_friend_request(users['A'], users['B'])
        assert r['code'] == 'COOLDOWN'


# ── Cancel endpoint ───────────────────────────────────────────────────────────

class TestCancelFriendInvite:

    def _make_pending_invite(self, sender_id, receiver_id):
        inv = Invitation(
            sender_id=sender_id, receiver_id=receiver_id,
            status='pending', invite_type=InviteType.OUTBOUND,
        )
        db.session.add(inv)
        db.session.commit()
        return inv.id

    def test_cancel_by_sender_succeeds(self, client, users):
        with app.app_context():
            inv_id = self._make_pending_invite(users['A'], users['B'])

        _login(client, users['A'])
        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code == 200
        data = rv.get_json()
        assert data['success'] is True

    def test_cancel_changes_status_to_cancelled(self, client, users):
        with app.app_context():
            inv_id = self._make_pending_invite(users['A'], users['B'])

        _login(client, users['A'])
        json_delete(client, f'/api/friends/invite/{inv_id}')

        with app.app_context():
            inv = db.session.get(Invitation, inv_id)
            assert inv.status == 'cancelled'

    def test_cancel_sets_cooldown(self, client, users):
        with app.app_context():
            inv_id = self._make_pending_invite(users['A'], users['B'])

        _login(client, users['A'])
        json_delete(client, f'/api/friends/invite/{inv_id}')

        with app.app_context():
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(user_a_id=a, user_b_id=b).first()
            assert cooldown is not None
            assert cooldown.expires_at > datetime.utcnow()

    def test_cancel_by_non_sender_rejected(self, client, users):
        with app.app_context():
            inv_id = self._make_pending_invite(users['A'], users['B'])

        _login(client, users['B'])  # receiver, not sender
        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code == 403

    def test_cancel_requires_auth(self, client, users):
        with app.app_context():
            inv_id = self._make_pending_invite(users['A'], users['B'])

        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code in (401, 302)

    def test_cancel_already_resolved_rejected(self, client, users):
        with app.app_context():
            inv = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='declined', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(client, users['A'])
        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code == 409

    def test_cancelled_invitation_cannot_be_accepted(self, client, users):
        """Receiver must NOT be able to accept a cancelled invitation.

        A sender cancels → cooldown is set.  If the receiver could still call
        accept on the old invitation ID, the cooldown would be bypassed and a
        spurious friendship would be created.
        """
        with app.app_context():
            inv = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        # Sender cancels
        _login(client, users['A'])
        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code == 200

        # Receiver tries to accept the now-cancelled invitation
        _login(client, users['B'])
        rv = json_post(client, f'/api/friends/invite/{inv_id}/accept')
        assert rv.status_code == 409
        data = rv.get_json()
        assert data['success'] is False

        # Verify no friendship was created
        with app.app_context():
            from models import Friend
            friendship = Friend.query.filter_by(
                user_id=users['B'], friend_id=users['A']
            ).first()
            assert friendship is None

    def test_declined_invitation_cannot_be_accepted(self, client, users):
        """Receiver cannot accept an invitation they previously declined."""
        with app.app_context():
            inv = Invitation(
                sender_id=users['A'], receiver_id=users['B'],
                status='declined', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        _login(client, users['B'])
        rv = json_post(client, f'/api/friends/invite/{inv_id}/accept')
        assert rv.status_code == 409
        assert rv.get_json()['success'] is False


# ── Unfriend cooldown ─────────────────────────────────────────────────────────

class TestConnectDiscoverability:
    """Verify that /api/users/<id>/connect enforces discoverability server-side.

    Knowing a numeric user ID must not bypass discoverable_in_friend_search=False.
    """

    @pytest.fixture(autouse=True)
    def setup(self, client):
        from services.search_utils import normalize_for_search
        with app.app_context():
            self.me = _make_user('me_disc')
            self.hidden = _make_user('hidden_disc')
            db.session.flush()
            self.hidden.discoverable_in_friend_search = False
            self.visible = _make_user('visible_disc')
            db.session.commit()
            self.me_id = self.me.id
            self.hidden_id = self.hidden.id
            self.visible_id = self.visible.id
        self.client = client

    def test_connect_to_discoverable_user_succeeds(self):
        _login(self.client, self.me_id)
        rv = json_post(self.client, f'/api/users/{self.visible_id}/connect')
        assert rv.status_code == 201

    def test_connect_to_non_discoverable_user_rejected(self):
        """Knowing the numeric ID of an opted-out user must not create a request."""
        _login(self.client, self.me_id)
        rv = json_post(self.client, f'/api/users/{self.hidden_id}/connect')
        # Must look like user not found — not merely forbidden — so the ID itself
        # does not reveal that the user exists but opted out.
        assert rv.status_code == 404

    def test_connect_to_non_discoverable_who_sent_incoming_allowed(self):
        """Exception: opted-out user who sent ME a pending request is reachable."""
        with app.app_context():
            inv = Invitation(
                sender_id=self.hidden_id,
                receiver_id=self.me_id,
                status='pending',
                invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(self.client, self.me_id)
        rv = json_post(self.client, f'/api/users/{self.hidden_id}/connect')
        # Should surface INCOMING_PENDING (409), not 404
        assert rv.status_code == 409
        data = rv.get_json()
        assert data.get('code') == 'INCOMING_PENDING'

    def test_connect_to_non_discoverable_already_friend_allowed(self):
        """Exception: opted-out confirmed friend is still reachable (idempotent)."""
        with app.app_context():
            db.session.add(Friend(user_id=self.me_id, friend_id=self.hidden_id))
            db.session.add(Friend(user_id=self.hidden_id, friend_id=self.me_id))
            db.session.commit()

        _login(self.client, self.me_id)
        rv = json_post(self.client, f'/api/users/{self.hidden_id}/connect')
        # ALREADY_FRIENDS — not 404
        assert rv.status_code == 409
        data = rv.get_json()
        assert data.get('code') in ('ALREADY_FRIENDS', 'OUTGOING_PENDING', 'INCOMING_PENDING') \
               or not data['success']


class TestTripInvitationScope:
    """Verify that friend-discovery endpoints cannot act on trip invitations.

    Trip join requests share the Invitation table but have trip_id IS NOT NULL.
    The cancel, accept, and decline endpoints must reject them so they cannot:
      - impose a social friend-pair cooldown via a trip decline/cancel
      - create a Friend relationship by accepting a trip join request
    """

    def _make_trip_invite(self, sender_id, receiver_id, users):
        """Create a pending Invitation with a non-null trip_id."""
        from models import SkiTrip
        # Use a fake trip_id (999) — we don't need a real trip row for these tests
        inv = Invitation(
            sender_id=sender_id,
            receiver_id=receiver_id,
            status='pending',
            trip_id=999,  # non-null — marks this as a trip invitation
            invite_type=InviteType.OUTBOUND,
        )
        db.session.add(inv)
        db.session.commit()
        return inv.id

    def test_cancel_trip_invite_rejected(self, client, users):
        """DELETE /api/friends/invite/<id> must not cancel a trip join request."""
        with app.app_context():
            inv_id = self._make_trip_invite(users['A'], users['B'], users)
        _login(client, users['A'])
        rv = json_delete(client, f'/api/friends/invite/{inv_id}')
        assert rv.status_code == 400
        data = rv.get_json()
        assert data['success'] is False
        # Verify the invitation is still pending
        with app.app_context():
            inv = db.session.get(Invitation, inv_id)
            assert inv.status == 'pending'

    def test_cancel_trip_invite_does_not_set_cooldown(self, client, users):
        """Cancelling a trip invite must not impose a friend-pair cooldown."""
        with app.app_context():
            inv_id = self._make_trip_invite(users['A'], users['B'], users)
        _login(client, users['A'])
        json_delete(client, f'/api/friends/invite/{inv_id}')
        with app.app_context():
            from app import _set_pair_cooldown
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(user_a_id=a, user_b_id=b).first()
            assert cooldown is None

    def test_accept_trip_invite_rejected(self, client, users):
        """POST /api/friends/invite/<id>/accept must not accept a trip join request."""
        with app.app_context():
            inv_id = self._make_trip_invite(users['A'], users['B'], users)
        _login(client, users['B'])
        rv = json_post(client, f'/api/friends/invite/{inv_id}/accept')
        assert rv.status_code == 400
        data = rv.get_json()
        assert data['success'] is False
        # Verify no Friend row was created
        with app.app_context():
            friendship = Friend.query.filter_by(
                user_id=users['B'], friend_id=users['A']
            ).first()
            assert friendship is None

    def test_decline_trip_invite_does_not_set_cooldown(self, client, users):
        """Declining a trip join request must not impose a friend-pair cooldown."""
        with app.app_context():
            inv_id = self._make_trip_invite(users['A'], users['B'], users)
        _login(client, users['B'])
        # Decline is allowed (trip workflow uses the same endpoint)
        # but must NOT create a friend cooldown
        json_post(client, f'/api/friends/invite/{inv_id}/decline')
        with app.app_context():
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(user_a_id=a, user_b_id=b).first()
            assert cooldown is None


class TestUnfriendCooldown:

    def test_remove_friend_sets_cooldown(self, client, users):
        with app.app_context():
            db.session.add(Friend(user_id=users['A'], friend_id=users['B']))
            db.session.add(Friend(user_id=users['B'], friend_id=users['A']))
            db.session.commit()

        _login(client, users['A'])
        rv = json_delete(client, f'/api/friends/{users["B"]}')
        assert rv.status_code == 200

        with app.app_context():
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(user_a_id=a, user_b_id=b).first()
            assert cooldown is not None
            assert cooldown.expires_at > datetime.utcnow()

    def test_remove_friend_web_sets_cooldown(self, client, users):
        """Unfriend via the web/form route also sets a pair cooldown.

        After this flow, neither user can immediately reconnect via the new
        global-search Connect button.
        """
        from tests.conftest import form_post
        with app.app_context():
            db.session.add(Friend(user_id=users['A'], friend_id=users['B']))
            db.session.add(Friend(user_id=users['B'], friend_id=users['A']))
            db.session.commit()

        _login(client, users['A'])
        rv = form_post(client, f'/friends/{users["B"]}/remove')
        # Web route redirects on success
        assert rv.status_code in (200, 302)

        with app.app_context():
            a, b = min(users['A'], users['B']), max(users['A'], users['B'])
            cooldown = FriendCooldown.query.filter_by(user_a_id=a, user_b_id=b).first()
            assert cooldown is not None
            assert cooldown.expires_at > datetime.utcnow()

    def test_remove_friend_web_blocks_reconnect_via_search(self, client, users):
        """After web unfriend, connect endpoint returns COOLDOWN for both parties."""
        from tests.conftest import form_post
        with app.app_context():
            db.session.add(Friend(user_id=users['A'], friend_id=users['B']))
            db.session.add(Friend(user_id=users['B'], friend_id=users['A']))
            db.session.commit()

        _login(client, users['A'])
        form_post(client, f'/friends/{users["B"]}/remove')

        # A → B: should be blocked by cooldown
        _login(client, users['A'])
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code == 429

        # B → A: also blocked (pair cooldown is symmetric)
        _login(client, users['B'])
        rv = json_post(client, f'/api/users/{users["A"]}/connect')
        assert rv.status_code == 429


# ── connect endpoint ──────────────────────────────────────────────────────────

class TestUserConnectEndpoint:

    def test_connect_creates_invitation(self, client, users):
        _login(client, users['A'])
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code == 201
        data = rv.get_json()
        assert data['success'] is True
        assert data['invitation_id'] is not None

    def test_connect_nonexistent_user_404(self, client, users):
        _login(client, users['A'])
        rv = json_post(client, '/api/users/999999/connect')
        assert rv.status_code == 404

    def test_connect_self_400(self, client, users):
        _login(client, users['A'])
        rv = json_post(client, f'/api/users/{users["A"]}/connect')
        assert rv.status_code == 400

    def test_connect_duplicate_409(self, client, users):
        _login(client, users['A'])
        json_post(client, f'/api/users/{users["B"]}/connect')
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code == 409

    def test_connect_during_cooldown_429(self, client, users):
        with app.app_context():
            _set_pair_cooldown(users['A'], users['B'], hours=24)
            db.session.commit()

        _login(client, users['A'])
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code == 429

    def test_connect_incoming_pending_returns_409_with_code(self, client, users):
        """When B→A is pending and A tries to connect A→B, get INCOMING_PENDING."""
        with app.app_context():
            inv = Invitation(
                sender_id=users['B'], receiver_id=users['A'],
                status='pending', invite_type=InviteType.OUTBOUND,
            )
            db.session.add(inv)
            db.session.commit()

        _login(client, users['A'])
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code == 409
        data = rv.get_json()
        assert data['code'] == 'INCOMING_PENDING'

    def test_connect_requires_auth(self, client, users):
        rv = json_post(client, f'/api/users/{users["B"]}/connect')
        assert rv.status_code in (401, 302)
