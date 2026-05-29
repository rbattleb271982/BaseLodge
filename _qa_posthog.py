"""QA script for PostHog activation instrumentation (#164)."""
import os, json
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
# Use testuser@baselodge.com (id=3, lifecycle_stage=active) as our test subject
os.environ['ALLOWED_ADMIN_EMAILS'] = 'testuser@baselodge.com'

import analytics as ph_analytics
_fired = []
def _mock_track(user_id, event, props=None, **kw):
    _fired.append({'user_id': user_id, 'event': event, 'props': props or {}})
ph_analytics.track = _mock_track

from app import app, db
from datetime import date, timedelta

def reset():
    _fired.clear()

def fired(event):
    return [e for e in _fired if e['event'] == event]

def cnt(event):
    return len(fired(event))

results = []
def check(label, ok):
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] {label}')
    results.append(ok)

with app.test_client() as c:
    with app.app_context():
        from app import User, Friend, InviteToken, SkiTrip, GroupTrip, Resort, SkiTripParticipant

        user = User.query.get(3)   # testuser@baselodge.com — active, non-seeded
        u_id = user.id

        def sess():
            with c.session_transaction() as s:
                s['_user_id'] = str(u_id)
                s['_fresh'] = True

        today = date.today()

        # ── invite_generated ──────────────────────────────────────────────────
        print('\n--- invite_generated ---')
        InviteToken.query.filter_by(inviter_id=u_id).delete()
        db.session.commit()
        reset(); sess()
        r = c.get('/invite', follow_redirects=False)
        check('new token: status 200', r.status_code == 200)
        check('new token fires', cnt('invite_generated') == 1)
        e0 = fired('invite_generated')
        check('source=invite_page', bool(e0) and e0[0]['props'].get('source') == 'invite_page')
        reset(); sess()
        r = c.get('/invite', follow_redirects=False)
        check('reused token: does NOT fire', cnt('invite_generated') == 0)

        # ── pass_added — select-pass ──────────────────────────────────────────
        print('\n--- pass_added (select-pass) ---')
        reset(); sess()
        r = c.post('/select-pass', data={'pass_type': 'Epic'}, follow_redirects=False)
        check('real pass: status 302 (redirect to profile)', r.status_code == 302)
        check('real pass fires', cnt('pass_added') == 1)
        e0 = fired('pass_added')
        check('source=select_pass', bool(e0) and e0[0]['props'].get('source') == 'select_pass')
        reset(); sess()
        r = c.post('/select-pass', data={'pass_type': 'no_pass'}, follow_redirects=False)
        check('no_pass does NOT fire', cnt('pass_added') == 0)
        reset(); sess()
        r = c.post('/select-pass', data={'pass_type': 'no_pass_yet'}, follow_redirects=False)
        check('no_pass_yet does NOT fire', cnt('pass_added') == 0)

        # ── pass_added — edit_profile ─────────────────────────────────────────
        print('\n--- pass_added (edit_profile) ---')
        reset(); sess()
        r = c.post('/edit_profile', data={
            'first_name':  user.first_name or 'Test',
            'last_name':   user.last_name  or 'User',
            'pass_type':   'Ikon',
            'rider_types': 'Skier',
            'skill_level': 'Intermediate',
            'home_state':  user.home_state or 'Colorado',
        }, follow_redirects=False)
        check('real pass: status 302', r.status_code == 302)
        check('real pass fires', cnt('pass_added') >= 1)
        e0 = fired('pass_added')
        check('source=settings', bool(e0) and e0[0]['props'].get('source') == 'settings')
        reset(); sess()
        r = c.post('/edit_profile', data={
            'first_name':  user.first_name or 'Test',
            'last_name':   user.last_name  or 'User',
            'pass_type':   'no_pass',
            'rider_types': 'Skier',
            'skill_level': 'Intermediate',
            'home_state':  user.home_state or 'Colorado',
        }, follow_redirects=False)
        check('no_pass does NOT fire', cnt('pass_added') == 0)

        # ── availability_added ────────────────────────────────────────────────
        print('\n--- availability_added ---')
        d1 = (today + timedelta(days=10)).strftime('%Y-%m-%d')
        d2 = (today + timedelta(days=11)).strftime('%Y-%m-%d')
        reset(); sess()
        r = c.post('/add-open-dates', data={'selected_dates': f'{d1},{d2}'}, follow_redirects=False)
        check('dates added: status 302', r.status_code == 302)
        check('fires', cnt('availability_added') == 1)
        e0 = fired('availability_added')
        check('date_count=2', bool(e0) and e0[0]['props'].get('date_count') == 2)
        reset(); sess()
        r = c.post('/add-open-dates', data={'selected_dates': ''}, follow_redirects=False)
        check('empty does NOT fire', cnt('availability_added') == 0)

        # ── wishlist_added — mountain_page ────────────────────────────────────
        print('\n--- wishlist_added (mountain_page) ---')
        resort = Resort.query.filter_by(is_active=True).first()
        if resort:
            cur_wl = [i for i in (user.wish_list_resorts or []) if i != resort.id]
            user.wish_list_resorts = cur_wl; db.session.commit()
            reset(); sess()
            r = c.post('/api/wishlist/add',
                       data=json.dumps({'resort_id': resort.id}),
                       content_type='application/json')
            check('fires on new add', cnt('wishlist_added') == 1)
            e0 = fired('wishlist_added')
            check('source=mountain_page', bool(e0) and e0[0]['props'].get('source') == 'mountain_page')
            reset(); sess()
            r = c.post('/api/wishlist/add',
                       data=json.dumps({'resort_id': resort.id}),
                       content_type='application/json')
            check('duplicate does NOT fire', cnt('wishlist_added') == 0)
        else:
            for lbl in ('fires on new add', 'source=mountain_page', 'duplicate does NOT fire'):
                check(lbl, False)

        # ── wishlist_added — settings ─────────────────────────────────────────
        print('\n--- wishlist_added (settings) ---')
        resort2 = Resort.query.filter_by(is_active=True).offset(2).first()
        if resort and resort2:
            base_wl = [i for i in (user.wish_list_resorts or []) if i != resort2.id]
            user.wish_list_resorts = base_wl; db.session.commit()
            reset(); sess()
            r = c.post('/settings/wish-list/save',
                       data=json.dumps({'resort_ids': base_wl + [resort2.id]}),
                       content_type='application/json')
            check('status 200', r.status_code == 200)
            check('add fires', cnt('wishlist_added') == 1)
            e0 = fired('wishlist_added')
            check('source=settings', bool(e0) and e0[0]['props'].get('source') == 'settings')
            reset(); sess()
            r = c.post('/settings/wish-list/save',
                       data=json.dumps({'resort_ids': base_wl}),
                       content_type='application/json')
            check('removal does NOT fire', cnt('wishlist_added') == 0)
        else:
            for lbl in ('status 200', 'add fires', 'source=settings', 'removal does NOT fire'):
                check(lbl, False)

        # ── trip_created — standard ───────────────────────────────────────────
        print('\n--- trip_created (standard) ---')
        if resort:
            start = (today + timedelta(days=120)).strftime('%Y-%m-%d')
            end   = (today + timedelta(days=122)).strftime('%Y-%m-%d')
            reset(); sess()
            r = c.post('/api/trip/create',
                       data=json.dumps({'resort_id': resort.id, 'start_date': start, 'end_date': end}),
                       content_type='application/json')
            rdata = json.loads(r.data)
            check('status 200', r.status_code == 200)
            check('fires', cnt('trip_created') == 1)
            e0 = fired('trip_created')
            check('source=create_trip_api', bool(e0) and e0[0]['props'].get('source') == 'create_trip_api')
            check('days=3', bool(e0) and e0[0]['props'].get('days') == 3)
            # cleanup
            if rdata.get('success') and rdata.get('trip', {}).get('id'):
                tid = rdata['trip']['id']
                SkiTripParticipant.query.filter_by(trip_id=tid).delete()
                SkiTrip.query.filter_by(id=tid).delete()
                db.session.commit()

        # ── trip_created — group ──────────────────────────────────────────────
        print('\n--- trip_created (group) ---')
        gstart = (today + timedelta(days=130)).strftime('%Y-%m-%d')
        gend   = (today + timedelta(days=132)).strftime('%Y-%m-%d')
        reset(); sess()
        r = c.post('/api/group-trip/create',
                   data=json.dumps({'start_date': gstart, 'end_date': gend}),
                   content_type='application/json')
        check('status 200', r.status_code == 200)
        check('fires', cnt('trip_created') == 1)
        e0 = fired('trip_created')
        check('source=create_group_trip_api', bool(e0) and e0[0]['props'].get('source') == 'create_group_trip_api')

        # ── friend_connected — invitation_accept ──────────────────────────────
        print('\n--- friend_connected (invitation_accept) ---')
        # Create a scratch user and invitation for testing
        from app import Invitation
        scratch = User(
            email=f'_qa_scratch_{u_id}@test.invalid',
            username=f'_qa_scratch_{u_id}',
            is_seeded=True,
        )
        db.session.add(scratch); db.session.flush()
        inv = Invitation(sender_id=scratch.id, receiver_id=u_id, status='pending')
        db.session.add(inv); db.session.commit()
        # Remove any existing friend relationship
        Friend.query.filter_by(user_id=u_id, friend_id=scratch.id).delete()
        Friend.query.filter_by(user_id=scratch.id, friend_id=u_id).delete()
        db.session.commit()
        reset(); sess()
        r = c.post(f'/api/friends/invite/{inv.id}/accept',
                   content_type='application/json')
        check('status 200', r.status_code == 200)
        check('fires', cnt('friend_connected') == 1)
        e0 = fired('friend_connected')
        check('source=invitation_accept', bool(e0) and e0[0]['props'].get('source') == 'invitation_accept')
        # already-friends path does NOT fire again
        reset(); sess()
        r = c.post(f'/api/friends/invite/{inv.id}/accept',
                   content_type='application/json')
        check('already-friends does NOT fire', cnt('friend_connected') == 0)
        # cleanup
        Friend.query.filter_by(user_id=u_id, friend_id=scratch.id).delete()
        Friend.query.filter_by(user_id=scratch.id, friend_id=u_id).delete()
        Invitation.query.filter_by(id=inv.id).delete()
        db.session.delete(scratch); db.session.commit()

        # ── friend_connected — qr_scan ────────────────────────────────────────
        print('\n--- friend_connected (qr_scan) ---')
        scratch2 = User(
            email=f'_qa_scratch2_{u_id}@test.invalid',
            username=f'_qa_scratch2_{u_id}',
            is_seeded=True,
        )
        db.session.add(scratch2); db.session.flush()
        Friend.query.filter_by(user_id=u_id, friend_id=scratch2.id).delete()
        Friend.query.filter_by(user_id=scratch2.id, friend_id=u_id).delete()
        db.session.commit()
        reset(); sess()
        r = c.post(f'/connect/{scratch2.id}/add', follow_redirects=False)
        check('status 200', r.status_code == 200)
        check('fires', cnt('friend_connected') == 1)
        e0 = fired('friend_connected')
        check('source=qr_scan', bool(e0) and e0[0]['props'].get('source') == 'qr_scan')
        # cleanup
        Friend.query.filter_by(user_id=u_id, friend_id=scratch2.id).delete()
        Friend.query.filter_by(user_id=scratch2.id, friend_id=u_id).delete()
        db.session.delete(scratch2); db.session.commit()

print()
total  = len(results)
passed = sum(results)
print(f'=== {passed}/{total} PASS ===')
if passed < total:
    print(f'{total - passed} FAILURES above')
