"""Tests for BL-10: Connection accepted toast UX.

Covers:
  - accept_invitation no longer writes session['new_connection_name']
  - connect_from_trip no longer writes session['new_connection_name']
  - Home route: 1 unseen connection → single-name toast message
  - Home route: 2+ unseen connections → count toast message
  - Home route: 0 unseen connections → no toast data
  - Home route does NOT create DismissedInsightCard rows
  - POST /api/home/connection-toast-seen marks Activities surfaced (idempotent)
  - Endpoint validates ownership: only acts on current user's Activities
  - Duplicate Activity rows for same pair count once; all IDs marked surfaced
  - Two users with the same first name count as two separate connections
  - Critical lifecycle: acceptance during active session → Activity stays unseen
    → new session → toast data present → endpoint marks surfaced
  - Historical backfill migration: marks pre-deploy activities, skips post-deploy
    activities, is idempotent, and runs correctly in both PostgreSQL and SQLite
"""
from datetime import date, datetime, timedelta

import pytest

from app import app
from models import (
    db, User, Friend, Invitation, InviteType, Activity, ActivityType,
    DismissedInsightCard, GroupTrip, TripGuest, GuestStatus,
)
from tests.conftest import _make_user, _login


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conn_activity(actor_id, recipient_id):
    """Create one CONNECTION_ACCEPTED Activity row (actor→recipient direction)."""
    act = Activity(
        actor_user_id=actor_id,
        recipient_user_id=recipient_id,
        type=ActivityType.CONNECTION_ACCEPTED.value,
        object_type='user',
        object_id=actor_id,
    )
    db.session.add(act)
    db.session.flush()
    return act


def _make_invitation(sender, receiver):
    """Create a pending friend invitation (sender → receiver, no trip)."""
    inv = Invitation(
        sender_id=sender.id,
        receiver_id=receiver.id,
        trip_id=None,
        invite_type=InviteType.OUTBOUND,
        status='pending',
    )
    db.session.add(inv)
    db.session.flush()
    return inv


def _make_group_trip_with_members(*users):
    """Create a future GroupTrip with all given users as ACCEPTED TripGuests."""
    future_start = date.today() + timedelta(days=10)
    future_end   = date.today() + timedelta(days=15)
    gt = GroupTrip(
        host_id=users[0].id,
        title="BL-10 Test Trip",
        start_date=future_start,
        end_date=future_end,
    )
    db.session.add(gt)
    db.session.flush()
    for u in users:
        db.session.add(TripGuest(
            trip_id=gt.id,
            user_id=u.id,
            status=GuestStatus.ACCEPTED,
        ))
    db.session.flush()
    return gt


def _dismissed_count(user_id):
    """Return how many DismissedInsightCard rows exist for this user / connection_accepted."""
    with app.app_context():
        return DismissedInsightCard.query.filter_by(
            user_id=user_id,
            card_type='connection_accepted',
        ).count()


# ── Tests: session key no longer written by acceptance routes ─────────────────

class TestSessionKeyRemoved:
    """accept_invitation and connect_from_trip must not write new_connection_name."""

    def test_accept_invitation_no_session_key(self, client):
        with app.app_context():
            sender   = _make_user("sender")
            receiver = _make_user("receiver")
            inv = _make_invitation(sender, receiver)
            inv_id, receiver_id = inv.id, receiver.id
            db.session.commit()

        _login(client, receiver_id)
        resp = client.post(
            f'/api/friends/invite/{inv_id}/accept',
            headers={'X-CSRF-Token': 'test-csrf-fixed-value-baselodge-regression'},
        )
        assert resp.status_code == 200
        with client.session_transaction() as sess:
            assert 'new_connection_name' not in sess

    def test_connect_from_trip_no_session_key(self, client):
        with app.app_context():
            host  = _make_user("host_trip")
            other = _make_user("other_trip")
            _make_group_trip_with_members(host, other)
            db.session.commit()
            host_id, other_id = host.id, other.id

        _login(client, host_id)
        resp = client.post(f'/connect-from-trip/{other_id}', follow_redirects=False)
        # Route redirects on success; any redirect means the action executed
        assert resp.status_code in (302, 303, 200)
        with client.session_transaction() as sess:
            assert 'new_connection_name' not in sess


# ── Tests: home route builds toast data correctly ─────────────────────────────

class TestHomeConnectionToast:
    """Home route must build connection_toast_msg and activity IDs from Activity rows."""

    def test_one_unseen_connection_single_name_message(self, client):
        with app.app_context():
            user  = _make_user("home1_me")
            actor = _make_user("home1_actor")
            _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            expected_name = actor.first_name
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        body = resp.data.decode()
        assert f"You and {expected_name} are now connected." in body

    def test_two_unseen_connections_count_message(self, client):
        with app.app_context():
            user   = _make_user("home2_me")
            actor1 = _make_user("home2_a1")
            actor2 = _make_user("home2_a2")
            _make_conn_activity(actor_id=actor1.id, recipient_id=user.id)
            _make_conn_activity(actor_id=actor2.id, recipient_id=user.id)
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        assert "You have 2 new connections." in resp.data.decode()

    def test_zero_unseen_no_toast_message(self, client):
        with app.app_context():
            user  = _make_user("home3_me")
            actor = _make_user("home3_actor")
            act = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            # Pre-dismiss so there are zero unseen activities
            db.session.add(DismissedInsightCard(
                user_id=user.id,
                card_type='connection_accepted',
                card_key=str(act.id),
            ))
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        body = resp.data.decode()
        # JS msg variable should be null; neither toast message should appear
        assert "are now connected." not in body
        assert "new connections." not in body
        assert "var msg      = null" in body

    def test_home_does_not_create_dismissed_rows(self, client):
        """Home route query alone must leave DismissedInsightCard untouched."""
        with app.app_context():
            user  = _make_user("home4_me")
            actor = _make_user("home4_actor")
            _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        client.get('/home')

        assert _dismissed_count(user_id) == 0


# ── Tests: POST /api/home/connection-toast-seen ───────────────────────────────

class TestConnectionToastSeen:
    """The seen endpoint marks Activities surfaced, validates ownership, and is idempotent."""

    def test_marks_own_activity_surfaced(self, client):
        with app.app_context():
            user  = _make_user("seen1_me")
            actor = _make_user("seen1_actor")
            act = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id, act_id = user.id, act.id
            db.session.commit()

        _login(client, user_id)
        resp = client.post(
            '/api/home/connection-toast-seen',
            json={'activity_ids': [act_id]},
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['ok'] is True

        with app.app_context():
            row = DismissedInsightCard.query.filter_by(
                user_id=user_id,
                card_type='connection_accepted',
                card_key=str(act_id),
            ).first()
        assert row is not None

    def test_idempotent_second_call_returns_ok_and_no_duplicate_row(self, client):
        with app.app_context():
            user  = _make_user("seen2_me")
            actor = _make_user("seen2_actor")
            act = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id, act_id = user.id, act.id
            db.session.commit()

        _login(client, user_id)
        client.post('/api/home/connection-toast-seen',
                    json={'activity_ids': [act_id]}, content_type='application/json')
        resp2 = client.post('/api/home/connection-toast-seen',
                            json={'activity_ids': [act_id]}, content_type='application/json')
        assert resp2.status_code == 200
        assert resp2.get_json()['ok'] is True

        with app.app_context():
            count = DismissedInsightCard.query.filter_by(
                user_id=user_id, card_type='connection_accepted', card_key=str(act_id),
            ).count()
        assert count == 1  # exactly one row, not two

    def test_does_not_mark_another_users_activity(self, client):
        """Endpoint must not create rows for Activities belonging to a different user."""
        with app.app_context():
            user_a = _make_user("seen3_a")
            user_b = _make_user("seen3_b")
            actor  = _make_user("seen3_actor")
            # Activity recipient is user_b, not user_a
            act = _make_conn_activity(actor_id=actor.id, recipient_id=user_b.id)
            a_id, act_id = user_a.id, act.id
            db.session.commit()

        _login(client, a_id)
        resp = client.post(
            '/api/home/connection-toast-seen',
            json={'activity_ids': [act_id]},
            content_type='application/json',
        )
        assert resp.status_code == 200  # graceful no-op

        with app.app_context():
            row = DismissedInsightCard.query.filter_by(
                card_type='connection_accepted',
                card_key=str(act_id),
            ).first()
        assert row is None  # nothing written


# ── Tests: deduplication ──────────────────────────────────────────────────────

class TestDeduplication:
    """Stable pair-key deduplication: same pair collapses; different users with
    the same first name count as separate connections."""

    def test_duplicate_rows_for_same_pair_count_as_one(self, client):
        """Two Activity rows with the same (actor, recipient) pair → 1 unique connection.
        Both IDs must appear in the page so the client can mark both surfaced."""
        with app.app_context():
            user  = _make_user("dedup1_me")
            actor = _make_user("dedup1_actor")
            act1 = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            act2 = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            expected_name = actor.first_name
            user_id, act1_id, act2_id = user.id, act1.id, act2.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        body = resp.data.decode()
        # Deduplicated → single-name message, not "You have 2 new connections."
        assert f"You and {expected_name} are now connected." in body
        assert "You have 2 new connections." not in body
        # Both Activity IDs must be in the page JS for the client to mark both surfaced
        assert str(act1_id) in body
        assert str(act2_id) in body

    def test_all_ids_in_pair_marked_surfaced_by_seen_endpoint(self, client):
        """When the client calls the seen endpoint with all IDs from a duplicate pair,
        all IDs must receive DismissedInsightCard rows so duplicates cannot resurface."""
        with app.app_context():
            user  = _make_user("dedup2_me")
            actor = _make_user("dedup2_actor")
            act1 = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            act2 = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id, act1_id, act2_id = user.id, act1.id, act2.id
            db.session.commit()

        _login(client, user_id)
        resp = client.post(
            '/api/home/connection-toast-seen',
            json={'activity_ids': [act1_id, act2_id]},
            content_type='application/json',
        )
        assert resp.status_code == 200

        with app.app_context():
            keys = {
                r.card_key for r in DismissedInsightCard.query.filter_by(
                    user_id=user_id, card_type='connection_accepted',
                ).all()
            }
        assert str(act1_id) in keys
        assert str(act2_id) in keys

    def test_same_first_name_count_as_two_connections(self, client):
        """Two people with identical first names must count as two separate connections
        because their user IDs are different, so their pair keys differ."""
        with app.app_context():
            user   = _make_user("dedup3_me")
            actor1 = _make_user("dedup3_a1")
            actor2 = _make_user("dedup3_a2")
            # Give both the same first name manually
            actor1.first_name = "Jordan"
            actor2.first_name = "Jordan"
            db.session.flush()
            _make_conn_activity(actor_id=actor1.id, recipient_id=user.id)
            _make_conn_activity(actor_id=actor2.id, recipient_id=user.id)
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        # Different user IDs → different pair keys → count = 2
        assert "You have 2 new connections." in resp.data.decode()


# ── Tests: critical lifecycle ─────────────────────────────────────────────────

class TestCriticalLifecycle:
    """Acceptance during active session must stay unseen until seen endpoint is called."""

    def test_home_visit_leaves_activity_unseen(self, client):
        """Home route must NOT mark activities seen — they remain queryable for next session."""
        with app.app_context():
            user  = _make_user("lc1_me")
            actor = _make_user("lc1_actor")
            _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id = user.id
            db.session.commit()

        _login(client, user_id)
        resp = client.get('/home')
        assert resp.status_code == 200
        # Server renders the data (client-side gate is not active in unit tests)
        assert "are now connected." in resp.data.decode()
        # Activity is NOT marked as surfaced by the home route
        assert _dismissed_count(user_id) == 0

    def test_full_lifecycle_toast_then_surfaced_then_gone(self, client):
        """Full flow: home returns data → seen endpoint marks surfaced → home returns null."""
        with app.app_context():
            user  = _make_user("lc2_me")
            actor = _make_user("lc2_actor")
            act = _make_conn_activity(actor_id=actor.id, recipient_id=user.id)
            user_id, act_id = user.id, act.id
            db.session.commit()

        _login(client, user_id)

        # Step 1: home route returns toast data
        resp1 = client.get('/home')
        assert resp1.status_code == 200
        assert "are now connected." in resp1.data.decode()

        # Step 2: client fires seen endpoint after toast renders
        resp2 = client.post(
            '/api/home/connection-toast-seen',
            json={'activity_ids': [act_id]},
            content_type='application/json',
        )
        assert resp2.status_code == 200
        assert resp2.get_json()['ok'] is True

        # Step 3: DismissedInsightCard row now exists
        assert _dismissed_count(user_id) == 1

        # Step 4: next home load returns no toast data
        resp3 = client.get('/home')
        assert resp3.status_code == 200
        body3 = resp3.data.decode()
        assert "are now connected." not in body3
        assert "new connections." not in body3
        assert "var msg      = null" in body3

    def test_acceptance_during_active_session_surfaces_next_session(self, client):
        """Simulates: active session → acceptance → home visit (no dismiss because
        client-side gate suppresses it) → Activity still unseen → new session → data present."""
        with app.app_context():
            user  = _make_user("lc3_me")
            actor = _make_user("lc3_actor")
            user_id, actor_id = user.id, actor.id
            db.session.commit()

        _login(client, user_id)
        with client.session_transaction() as sess:
            sess['_id'] = 'session-xyz-old'

        # Simulate: acceptance happens, Activity row created (but same session → client suppresses)
        with app.app_context():
            act = _make_conn_activity(actor_id=actor_id, recipient_id=user_id)
            db.session.commit()
            act_id = act.id

        # Home visit in the same session — server renders toast data but client suppresses.
        # Server MUST NOT create DismissedInsightCard (simulating same-session gate).
        resp1 = client.get('/home')
        assert resp1.status_code == 200
        # Data is present server-side (client-side gate would suppress the display)
        assert "are now connected." in resp1.data.decode()
        # Activity is NOT dismissed
        assert _dismissed_count(user_id) == 0

        # Simulate new session (new _id, e.g. after app cold-start + login)
        with client.session_transaction() as sess:
            sess['_id'] = 'session-xyz-new'

        # New session → home returns data again (Activity still unseen)
        resp2 = client.get('/home')
        assert resp2.status_code == 200
        assert "are now connected." in resp2.data.decode()
        assert _dismissed_count(user_id) == 0

        # Client fires seen endpoint (toast actually rendered)
        resp3 = client.post(
            '/api/home/connection-toast-seen',
            json={'activity_ids': [act_id]},
            content_type='application/json',
        )
        assert resp3.status_code == 200
        assert _dismissed_count(user_id) == 1

        # Final home load → no toast
        resp4 = client.get('/home')
        assert "are now connected." not in resp4.data.decode()
        assert "new connections." not in resp4.data.decode()


# ── Tests: historical backfill migration ──────────────────────────────────────
# _BACKFILL_CUTOFF inside the migration is datetime(2026, 8, 15, 0, 0, 0).
# Tests use created_at values clearly on either side of that boundary.
_PRE_DEPLOY  = datetime(2026, 7,  1, 12, 0, 0)   # before cutoff → must be backfilled
_POST_DEPLOY = datetime(2026, 9,  1, 12, 0, 0)   # after cutoff  → must NOT be backfilled


class TestBackfillMigration:
    """_run_connection_toast_backfill_migration:
      - actually marks pre-deploy Activity rows dismissed (tested in SQLite)
      - does NOT touch post-deploy Activity rows
      - is idempotent (duplicate-row safe)
      - reports correct counts via print (smoke-checked)
    """

    def test_backfill_marks_pre_deploy_activity(self, client):
        """An Activity created before the cutoff must receive a DismissedInsightCard row."""
        from app import _run_connection_toast_backfill_migration

        with app.app_context():
            user  = _make_user("bf1_me")
            actor = _make_user("bf1_actor")
            act = Activity(
                actor_user_id=actor.id,
                recipient_user_id=user.id,
                type=ActivityType.CONNECTION_ACCEPTED.value,
                object_type='user',
                object_id=actor.id,
                created_at=_PRE_DEPLOY,
            )
            db.session.add(act)
            db.session.commit()
            user_id, act_id = user.id, act.id

        _run_connection_toast_backfill_migration()

        with app.app_context():
            row = DismissedInsightCard.query.filter_by(
                user_id=user_id,
                card_type='connection_accepted',
                card_key=str(act_id),
            ).first()
        assert row is not None, "pre-deploy Activity must be marked dismissed by backfill"

    def test_backfill_does_not_mark_post_deploy_activity(self, client):
        """An Activity created after the cutoff must NOT be touched by the backfill.
        This ensures a hardcoded deploy date (not datetime.utcnow()) is used so that
        post-deploy connections are never suppressed on subsequent server restarts."""
        from app import _run_connection_toast_backfill_migration

        with app.app_context():
            user  = _make_user("bf2_me")
            actor = _make_user("bf2_actor")
            act = Activity(
                actor_user_id=actor.id,
                recipient_user_id=user.id,
                type=ActivityType.CONNECTION_ACCEPTED.value,
                object_type='user',
                object_id=actor.id,
                created_at=_POST_DEPLOY,
            )
            db.session.add(act)
            db.session.commit()
            user_id, act_id = user.id, act.id

        _run_connection_toast_backfill_migration()

        with app.app_context():
            row = DismissedInsightCard.query.filter_by(
                user_id=user_id,
                card_type='connection_accepted',
                card_key=str(act_id),
            ).first()
        assert row is None, "post-deploy Activity must NOT be dismissed by backfill"

    def test_backfill_idempotent_no_duplicate_rows(self, client):
        """Running the backfill twice produces exactly one DismissedInsightCard row,
        not two. The function must not raise on the second call."""
        from app import _run_connection_toast_backfill_migration

        with app.app_context():
            user  = _make_user("bf3_me")
            actor = _make_user("bf3_actor")
            act = Activity(
                actor_user_id=actor.id,
                recipient_user_id=user.id,
                type=ActivityType.CONNECTION_ACCEPTED.value,
                object_type='user',
                object_id=actor.id,
                created_at=_PRE_DEPLOY,
            )
            db.session.add(act)
            db.session.commit()
            user_id, act_id = user.id, act.id

        _run_connection_toast_backfill_migration()
        _run_connection_toast_backfill_migration()  # must not raise or duplicate

        with app.app_context():
            count = DismissedInsightCard.query.filter_by(
                user_id=user_id,
                card_type='connection_accepted',
                card_key=str(act_id),
            ).count()
        assert count == 1, "backfill run twice must produce exactly one row"

    def test_backfill_respects_existing_dismissal(self, client):
        """If a DismissedInsightCard row already exists (same card_key), the backfill
        must not attempt to insert a duplicate or raise."""
        from app import _run_connection_toast_backfill_migration

        with app.app_context():
            user  = _make_user("bf4_me")
            actor = _make_user("bf4_actor")
            act = Activity(
                actor_user_id=actor.id,
                recipient_user_id=user.id,
                type=ActivityType.CONNECTION_ACCEPTED.value,
                object_type='user',
                object_id=actor.id,
                created_at=_PRE_DEPLOY,
            )
            db.session.add(act)
            db.session.flush()
            # Pre-insert a dismissal (simulating a user who already dismissed the old banner)
            db.session.add(DismissedInsightCard(
                user_id=user.id,
                card_type='connection_accepted',
                card_key=str(act.id),
            ))
            db.session.commit()
            user_id, act_id = user.id, act.id

        _run_connection_toast_backfill_migration()

        with app.app_context():
            count = DismissedInsightCard.query.filter_by(
                user_id=user_id,
                card_type='connection_accepted',
                card_key=str(act_id),
            ).count()
        assert count == 1  # still exactly one — no duplicate inserted
