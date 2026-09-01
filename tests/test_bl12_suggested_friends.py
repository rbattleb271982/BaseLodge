"""BL-12: Suggested Friends — test suite.

Covers:
  1.  Authorization — non-friends and logged-out users blocked
  2.  Selector eligibility — already-connected, pending, already-suggested excluded
  3.  Submission — valid batch insert with savepoints
  4.  Re-suggestion after dismiss
  5.  Re-suggestion after expiry (lazy closure)
  6.  Aggregation and attribution (Python grouping)
  7.  Accept vs Connect detection via inbound Invitation
  8.  Dismiss endpoint
  9.  Expiration — expired rows absent from suggestions tab
  10. Push cooldown — second batch same day skips push
  11. Activity record created on submit
  12. Privacy regression — non-discoverable user still connectable via suggestions
  13. Selector excludes self
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import app as _app
from models import (
    db as _db,
    User, Friend, Invitation, Activity,
    FriendSuggestion, SuggestionPushCooldown,
)
from tests.conftest import _login, _TEST_CSRF, form_post, json_post

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(first_name, email=None, discoverable=True):
    """Create a full User inside an active app context (matches conftest conventions)."""
    import secrets
    tag = f"bl12_{secrets.token_hex(4)}"
    u = User(
        email=email or f"{tag}@bl12test.example",
        first_name=first_name,
        last_name='Test',
        rider_types=['Skier'],
        pass_type='epic',
        skill_level='Intermediate',
        lifecycle_stage='active',
        onboarding_completed_at=datetime.utcnow(),
        is_seeded=True,
        discoverable_in_friend_search=discoverable,
        home_state='CO',
    )
    u.set_password('TestPass1!')
    _db.session.add(u)
    _db.session.flush()
    return u


def _prime_csrf(client):
    with client.session_transaction() as session:
        session["_csrf_token"] = _TEST_CSRF


def _make_friend(user_id, friend_id):
    """Insert mirrored Friend rows (bidirectional friendship)."""
    _db.session.add(Friend(user_id=user_id, friend_id=friend_id))
    _db.session.add(Friend(user_id=friend_id, friend_id=user_id))
    _db.session.flush()


def _make_suggestion(*, suggester_id, recipient_id, suggested_user_id,
                      dismissed_at=None, expires_days=30):
    row = FriendSuggestion(
        suggester_id=suggester_id,
        recipient_id=recipient_id,
        suggested_user_id=suggested_user_id,
        expires_at=datetime.utcnow() + timedelta(days=expires_days),
        dismissed_at=dismissed_at,
    )
    _db.session.add(row)
    _db.session.flush()
    return row


def _mock_user(uid, first_name):
    """Minimal in-memory User stand-in for tests that don't need persistence."""
    return type('MockUser', (), {'id': uid, 'first_name': first_name})()


# ---------------------------------------------------------------------------
# 1. Authorization
# ---------------------------------------------------------------------------

class TestAuthorization:

    def test_get_selector_requires_friendship(self, client):
        """Non-friends get 404 to avoid disclosing user existence."""
        with _app.app_context():
            richard = _make_user('Richard')
            stranger = _make_user('Stranger')
            _db.session.commit()
            rid, strid = richard.id, stranger.id

        _login(client, rid)
        resp = client.get(f'/friends/{strid}/suggest')
        assert resp.status_code == 404

    def test_get_selector_requires_login(self, client):
        with _app.app_context():
            target = _make_user('Target')
            _db.session.commit()
            tid = target.id

        resp = client.get(f'/friends/{tid}/suggest', follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_post_submit_requires_friendship(self, client):
        with _app.app_context():
            richard = _make_user('RichardAuthP')
            stranger = _make_user('StrangerAuthP')
            _db.session.commit()
            rid, strid = richard.id, stranger.id

        _login(client, rid)
        resp = form_post(client, f'/friends/{strid}/suggest',
                         {'suggested_user_ids': 999})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Selector eligibility
# ---------------------------------------------------------------------------

class TestSelectorEligibility:

    def test_jon_excluded_from_selector(self, client):
        """Jon (the recipient) must not appear as a selectable candidate."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('JonExcluded')
            _make_friend(richard.id, jon.id)
            _db.session.commit()
            rid, jid = richard.id, jon.id

        _login(client, rid)
        resp = client.get(f'/friends/{jid}/suggest')
        assert resp.status_code == 200
        assert b'JonExcluded' not in resp.data

    def test_already_connected_to_jon_hidden(self, client):
        """Users already connected to Jon are excluded from candidates."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('JonCn')
            alice = _make_user('AliceConnected')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_friend(jon.id, alice.id)   # Alice already knows Jon
            _db.session.commit()
            rid, jid = richard.id, jon.id

        _login(client, rid)
        resp = client.get(f'/friends/{jid}/suggest')
        assert resp.status_code == 200
        assert b'AliceConnected' not in resp.data

    def test_already_suggested_shown_disabled(self, client):
        """An active suggestion for Bob renders as disabled (status label shown)."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('JonDs')
            bob = _make_user('BobAlreadySugg')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, bob.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=bob.id)
            _db.session.commit()
            rid, jid = richard.id, jon.id

        _login(client, rid)
        resp = client.get(f'/friends/{jid}/suggest')
        assert resp.status_code == 200
        assert b'Already suggested' in resp.data


# ---------------------------------------------------------------------------
# 3. Submission — valid batch insert
# ---------------------------------------------------------------------------

class TestSubmission:

    def test_valid_submission_creates_rows(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('Alice')
            bob = _make_user('Bob')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_friend(richard.id, bob.id)
            _db.session.commit()
            rid, jid, aid, bid = richard.id, jon.id, alice.id, bob.id

        _login(client, rid)
        with patch('app.send_onesignal_push', return_value={'success': True}):
            resp = form_post(client, f'/friends/{jid}/suggest',
                             {'suggested_user_ids': [aid, bid]})
        assert resp.status_code == 302

        with _app.app_context():
            rows = FriendSuggestion.query.filter_by(
                suggester_id=rid, recipient_id=jid
            ).all()
            assert len(rows) == 2
            assert {r.suggested_user_id for r in rows} == {aid, bid}

    def test_non_connection_rejected_server_side(self, client):
        """Cannot suggest users who are not Richard's own connections."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            stranger = _make_user('StrangerNotFr')
            _make_friend(richard.id, jon.id)
            _db.session.commit()
            rid, jid, strid = richard.id, jon.id, stranger.id

        _login(client, rid)
        with patch('app.send_onesignal_push', return_value={'success': True}):
            resp = form_post(client, f'/friends/{jid}/suggest',
                             {'suggested_user_ids': strid})
        assert resp.status_code == 302

        with _app.app_context():
            count = FriendSuggestion.query.filter_by(
                suggester_id=rid, recipient_id=jid
            ).count()
            assert count == 0

    def test_empty_submission_redirects_to_selector(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            _make_friend(richard.id, jon.id)
            _db.session.commit()
            rid, jid = richard.id, jon.id

        _login(client, rid)
        resp = form_post(client, f'/friends/{jid}/suggest', {})
        assert resp.status_code == 302
        assert f'/friends/{jid}/suggest' in resp.headers['Location']


# ---------------------------------------------------------------------------
# 4. Re-suggestion after dismiss
# ---------------------------------------------------------------------------

class TestResuggestionAfterDismiss:

    def test_re_suggest_after_dismiss_succeeds(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceRedisSug')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            # Dismissed row
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id,
                             dismissed_at=datetime.utcnow())
            _db.session.commit()
            rid, jid, aid = richard.id, jon.id, alice.id

        _login(client, rid)
        with patch('app.send_onesignal_push', return_value={'success': True}):
            resp = form_post(client, f'/friends/{jid}/suggest',
                             {'suggested_user_ids': aid})
        assert resp.status_code == 302

        with _app.app_context():
            active = FriendSuggestion.query.filter(
                FriendSuggestion.suggester_id == rid,
                FriendSuggestion.recipient_id == jid,
                FriendSuggestion.suggested_user_id == aid,
                FriendSuggestion.dismissed_at.is_(None),
            ).first()
            assert active is not None


# ---------------------------------------------------------------------------
# 5. Re-suggestion after expiry (lazy closure)
# ---------------------------------------------------------------------------

class TestResuggestionAfterExpiry:

    def test_expired_row_closed_and_fresh_row_inserted(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceExpLazy')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            expired = FriendSuggestion(
                suggester_id=richard.id,
                recipient_id=jon.id,
                suggested_user_id=alice.id,
                expires_at=datetime.utcnow() - timedelta(days=1),
            )
            _db.session.add(expired)
            _db.session.commit()
            rid, jid, aid = richard.id, jon.id, alice.id

        _login(client, rid)
        with patch('app.send_onesignal_push', return_value={'success': True}):
            resp = form_post(client, f'/friends/{jid}/suggest',
                             {'suggested_user_ids': aid})
        assert resp.status_code == 302

        with _app.app_context():
            rows = FriendSuggestion.query.filter(
                FriendSuggestion.suggester_id == rid,
                FriendSuggestion.recipient_id == jid,
                FriendSuggestion.suggested_user_id == aid,
            ).all()
            now = datetime.utcnow()
            active = [r for r in rows if r.dismissed_at is None and r.expires_at > now]
            assert len(active) == 1
            # The old expired row should now be closed
            old = [r for r in rows if r.expires_at < now]
            assert all(r.dismissed_at is not None for r in old)


# ---------------------------------------------------------------------------
# 6. Aggregation and attribution (no DB needed — tests the pure function)
# ---------------------------------------------------------------------------

class TestAggregationAndAttribution:

    def test_two_suggesters_attribution_names_both(self):
        from app import _build_suggestion_attribution
        sr_map = {1: _mock_user(1, 'Richard'), 2: _mock_user(2, 'Kate')}
        attr = _build_suggestion_attribution([1, 2], sr_map)
        assert 'Richard' in attr
        assert 'Kate' in attr

    def test_single_suggester_attribution(self):
        from app import _build_suggestion_attribution
        sr_map = {1: _mock_user(1, 'Richard')}
        attr = _build_suggestion_attribution([1], sr_map)
        assert 'Richard' in attr
        assert 'by' in attr.lower()

    def test_three_suggesters_plus_abbreviation(self):
        from app import _build_suggestion_attribution
        sr_map = {
            1: _mock_user(1, 'Alice'),
            2: _mock_user(2, 'Bob'),
            3: _mock_user(3, 'Carol'),
        }
        attr = _build_suggestion_attribution([1, 2, 3], sr_map)
        assert '+1' in attr

    def test_latest_at_determines_order(self, client):
        """Rows grouped by suggested_user_id; group with latest created_at ranks first."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceOld')
            bob = _make_user('BobNew')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_friend(richard.id, bob.id)
            # Alice suggested earlier, Bob suggested later
            old_sugg = FriendSuggestion(
                suggester_id=richard.id,
                recipient_id=jon.id,
                suggested_user_id=alice.id,
                expires_at=datetime.utcnow() + timedelta(days=30),
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
            new_sugg = FriendSuggestion(
                suggester_id=richard.id,
                recipient_id=jon.id,
                suggested_user_id=bob.id,
                expires_at=datetime.utcnow() + timedelta(days=30),
                created_at=datetime.utcnow() - timedelta(minutes=5),
            )
            _db.session.add(old_sugg)
            _db.session.add(new_sugg)
            _db.session.commit()
            jid = jon.id

        _login(client, jid)
        resp = client.get('/api/friends/suggestions/page')
        assert resp.status_code == 200
        # format_name capitalizes first letter only — 'BobNew' → 'Bobnew'
        body = resp.get_json()['html']
        bob_pos = body.find('Bobnew')
        alice_pos = body.find('Aliceold')
        assert bob_pos != -1 and alice_pos != -1
        assert bob_pos < alice_pos


# ---------------------------------------------------------------------------
# 7. Accept vs Connect — inbound pending shows Accept
# ---------------------------------------------------------------------------

class TestAcceptVsConnect:

    def test_inbound_pending_shows_accept_button(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceAccept')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id)
            # Alice has already sent Jon a request
            inv = Invitation(
                sender_id=alice.id,
                receiver_id=jon.id,
                status='pending',
            )
            _db.session.add(inv)
            _db.session.commit()
            jid = jon.id

        _login(client, jid)
        resp = client.get('/friends?tab=suggested')
        assert resp.status_code == 200
        assert b'Accept' in resp.data

    def test_no_inbound_shows_connect_button(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceConnect')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id)
            _db.session.commit()
            jid = jon.id

        _login(client, jid)
        resp = client.get('/friends?tab=suggested')
        assert resp.status_code == 200
        assert b'Connect' in resp.data


# ---------------------------------------------------------------------------
# 7b. Suggested Friend preview — safe client-side data contract
# ---------------------------------------------------------------------------

class TestSuggestedFriendPreview:

    def test_preview_markup_uses_only_suggested_friend_fields(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AlicePreview')
            alice.rider_types = ['private-preview-rider']
            alice.pass_type = 'private_preview_pass'
            alice.skill_level = 'private_preview_skill'
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_suggestion(
                suggester_id=richard.id,
                recipient_id=jon.id,
                suggested_user_id=alice.id,
            )
            _db.session.commit()
            jid, aid = jon.id, alice.id

        _login(client, jid)
        body = client.get('/api/friends/suggestions/page').get_json()['html']

        assert f'id="fr-sugg-row-{aid}"' in body
        assert 'data-suggested-name=' in body
        assert 'data-suggested-state="Colorado"' in body
        assert 'data-suggested-attribution=' in body
        assert 'frSuggOpenPreview(this)' in body
        assert f'href="/friends/{aid}"' not in body
        assert 'private-preview-rider' not in body
        assert 'private_preview_pass' not in body
        assert 'private_preview_skill' not in body

    def test_preview_template_has_required_dismissal_and_action_hooks(self):
        html = Path('templates/friends.html').read_text()

        assert 'id="fr-sugg-preview-overlay"' in html
        assert 'frSuggClosePreview()' in html
        assert "event.key === 'Escape'" in html
        assert "window.addEventListener('popstate'" in html
        assert 'window.history.pushState' in html
        assert 'frSuggSetActionState(userId, ' in html
        assert 'data-sugg-action-for=' in html
        assert "data.code === 'OUTGOING_PENDING'" in html
        assert "frSuggSetActionState(userId, 'requested')" in html


# ---------------------------------------------------------------------------
# 8. Dismiss endpoint
# ---------------------------------------------------------------------------

class TestDismiss:

    def test_dismiss_sets_dismissed_at(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceDismissRow')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id)
            _db.session.commit()
            jid, aid = jon.id, alice.id

        _login(client, jid)
        resp = json_post(client, '/api/friends/suggestions/dismiss',
                         {'suggested_user_id': aid})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        with _app.app_context():
            row = FriendSuggestion.query.filter(
                FriendSuggestion.recipient_id == jid,
                FriendSuggestion.suggested_user_id == aid,
            ).first()
            assert row.dismissed_at is not None

    def test_dismiss_requires_login(self, client):
        _prime_csrf(client)
        resp = client.post(
            '/api/friends/suggestions/dismiss',
            json={'suggested_user_id': 1},
            headers={'X-CSRF-Token': _TEST_CSRF},
            content_type='application/json',
        )
        assert resp.status_code in (302, 401)

    def test_dismiss_missing_param_returns_400(self, client):
        with _app.app_context():
            u = _make_user('Jon')
            _db.session.commit()
            uid = u.id

        _login(client, uid)
        resp = json_post(client, '/api/friends/suggestions/dismiss', {})
        assert resp.status_code == 400

    def test_dismiss_only_affects_recipient_rows(self, client):
        """Jon's dismiss must not touch Kate's suggestion for the same person."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            kate = _make_user('Kate')
            alice = _make_user('AlicePrivTwo')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, kate.id)
            _make_friend(richard.id, alice.id)
            _make_friend(kate.id, alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=kate.id,
                             suggested_user_id=alice.id)
            _db.session.commit()
            jid, kid, aid = jon.id, kate.id, alice.id

        _login(client, jid)
        json_post(client, '/api/friends/suggestions/dismiss',
                  {'suggested_user_id': aid})

        with _app.app_context():
            kate_row = FriendSuggestion.query.filter(
                FriendSuggestion.recipient_id == kid,
                FriendSuggestion.suggested_user_id == aid,
                FriendSuggestion.dismissed_at.is_(None),
            ).first()
            assert kate_row is not None


# ---------------------------------------------------------------------------
# 9. Expiration — expired rows must not appear in the suggestions tab
# ---------------------------------------------------------------------------

class TestExpiration:

    def test_expired_rows_not_shown_in_tab(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceExpShow')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            expired = FriendSuggestion(
                suggester_id=richard.id,
                recipient_id=jon.id,
                suggested_user_id=alice.id,
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
            _db.session.add(expired)
            _db.session.commit()
            jid = jon.id

        _login(client, jid)
        resp = client.get('/friends?tab=suggested')
        assert resp.status_code == 200
        assert b'AliceExpShow' not in resp.data


# ---------------------------------------------------------------------------
# 10. Push cooldown
# ---------------------------------------------------------------------------

class TestPushCooldown:

    def test_push_not_sent_within_cooldown_window(self, client):
        """Second batch within 12-hour cooldown must not fire push."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            bob = _make_user('BobPush')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, bob.id)
            # Cooldown exists — last_sent 1 hour ago (within 12-hr window)
            cooldown = SuggestionPushCooldown(
                suggester_id=richard.id,
                recipient_id=jon.id,
                last_sent_at=datetime.utcnow() - timedelta(hours=1),
            )
            _db.session.add(cooldown)
            _db.session.commit()
            rid, jid, bid = richard.id, jon.id, bob.id

        _login(client, rid)
        with patch('app.send_onesignal_push') as mock_push:
            form_post(client, f'/friends/{jid}/suggest',
                      {'suggested_user_ids': bid})
            mock_push.assert_not_called()

    def test_push_sent_after_cooldown_expires(self, client):
        """After the 12-hour cooldown window, push is sent on next batch."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AlicePushCool')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            # Cooldown expired 13 hours ago
            cooldown = SuggestionPushCooldown(
                suggester_id=richard.id,
                recipient_id=jon.id,
                last_sent_at=datetime.utcnow() - timedelta(hours=13),
            )
            _db.session.add(cooldown)
            _db.session.commit()
            rid, jid, aid = richard.id, jon.id, alice.id

        _login(client, rid)
        with patch('app.send_onesignal_push',
                   return_value={'success': True}) as mock_push:
            form_post(client, f'/friends/{jid}/suggest',
                      {'suggested_user_ids': aid})
            mock_push.assert_called_once()

    def test_push_sent_on_first_batch(self, client):
        """No cooldown row → push is sent on the first batch."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceFirstPush')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _db.session.commit()
            rid, jid, aid = richard.id, jon.id, alice.id

        _login(client, rid)
        with patch('app.send_onesignal_push',
                   return_value={'success': True}) as mock_push:
            form_post(client, f'/friends/{jid}/suggest',
                      {'suggested_user_ids': aid})
            mock_push.assert_called_once()


# ---------------------------------------------------------------------------
# 11. Activity record created on submit
# ---------------------------------------------------------------------------

class TestActivityCreated:

    def test_activity_created_with_correct_type(self, client):
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AliceAct')
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _db.session.commit()
            rid, jid, aid = richard.id, jon.id, alice.id

        _login(client, rid)
        with patch('app.send_onesignal_push', return_value={'success': True}):
            form_post(client, f'/friends/{jid}/suggest',
                      {'suggested_user_ids': aid})

        with _app.app_context():
            # Activity model uses column 'type', not 'activity_type'
            act = Activity.query.filter_by(
                actor_user_id=rid,
                recipient_user_id=jid,
                type='friend_suggestions_received',
            ).first()
            assert act is not None
            assert act.extra_data['count'] == 1


# ---------------------------------------------------------------------------
# 12. Privacy regression — non-discoverable user connectable via suggestions
# ---------------------------------------------------------------------------

class TestPrivacyRegression:

    def test_non_discoverable_user_connectable_via_suggestions(self, client):
        """discoverable_in_friend_search=False must not block the suggestions_connect endpoint."""
        with _app.app_context():
            richard = _make_user('Richard')
            jon = _make_user('Jon')
            alice = _make_user('AlicePriv', discoverable=False)
            _make_friend(richard.id, jon.id)
            _make_friend(richard.id, alice.id)
            _make_suggestion(suggester_id=richard.id, recipient_id=jon.id,
                             suggested_user_id=alice.id)
            _db.session.commit()
            jid, aid = jon.id, alice.id

        _login(client, jid)
        with patch('app.create_friend_request',
                   return_value={'ok': True, 'code': 'CREATED', 'invitation_id': 99}):
            resp = json_post(client, '/api/friends/suggestions/connect',
                             {'user_id': aid})
        assert resp.status_code == 201
        assert resp.get_json()['success'] is True

    def test_suggestions_endpoint_requires_login(self, client):
        _prime_csrf(client)
        resp = json_post(client, '/api/friends/suggestions/connect', {'user_id': 1})
        assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# 13. Self-exclusion from selector
# ---------------------------------------------------------------------------

class TestSelfExclusion:

    def test_richard_not_in_his_own_selector(self, client):
        with _app.app_context():
            richard = _make_user('RichardSelfX')
            jon = _make_user('Jon')
            _make_friend(richard.id, jon.id)
            _db.session.commit()
            rid, jid = richard.id, jon.id

        _login(client, rid)
        resp = client.get(f'/friends/{jid}/suggest')
        assert resp.status_code == 200
        assert b'RichardSelfX' not in resp.data
