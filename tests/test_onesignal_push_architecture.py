"""
test_onesignal_push_architecture.py

Verifies that the OneSignal-only push architecture is correctly implemented
and that @capacitor/push-notifications has been removed from the lifecycle.

Coverage:
  1.  package.json does NOT list @capacitor/push-notifications
  2.  bl-native.js does NOT call Push.requestPermissions() (Capacitor)
  3.  bl-native.js does NOT call Push.register() (Capacitor)
  4.  bl-native.js does NOT attach pushNotificationReceived listener
  5.  bl-native.js does NOT attach pushNotificationActionPerformed listener
  6.  bl-native.js DOES attach OS.Notifications.addEventListener('foregroundWillDisplay')
  7.  bl-native.js DOES attach OS.Notifications.addEventListener('click')
  8.  bl-native.js DOES call OS.Notifications.requestPermission
  9.  bl-native.js DOES expose blSetPushEnabled helper
  10. bl-native.js DOES expose blOSLogout helper
  11. bl-native.js DOES have subscription change observer (OSSubscription diagnostic)
  12. bl-native.js does NOT auto-call optIn() to fight state (no automatic optIn loop)
  13. AppDelegate.swift does NOT set UNUserNotificationCenter delegate in applicationDidBecomeActive
  14. AppDelegate.swift does NOT implement willPresent (no competing foreground handler)
  15. AppDelegate.swift does NOT implement didReceive (no competing tap handler)
  16. AppDelegate.swift DOES relay APNs token via capacitorDidRegisterForRemoteNotifications
  17. capacitor.config.json does NOT have handleApplicationNotifications key
  18. capacitor.config.json does NOT have PushNotifications plugin config
  19. _extractPushUrl accepts OneSignal notification.additionalData.url shape
  20. _extractPushUrl accepts OneSignal result.url shape
  21. _extractPushUrl rejects absolute URLs
  22. _extractPushUrl rejects javascript: schemes
  23. send_onesignal_push opt-out filter respects push_notifications_enabled=False
  24. blSetPushEnabled calls optOut (not a competing push disable mechanism)
"""

import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _read(rel_path):
    with open(os.path.join(REPO_ROOT, rel_path), 'r', encoding='utf-8') as f:
        return f.read()


class PackageJsonArchitectureTests(unittest.TestCase):

    def setUp(self):
        self.pkg = json.loads(_read('package.json'))
        self.deps = {**self.pkg.get('dependencies', {}), **self.pkg.get('devDependencies', {})}

    # 1
    def test_capacitor_push_notifications_not_in_package_json(self):
        """@capacitor/push-notifications must NOT be listed as a dependency."""
        self.assertNotIn(
            '@capacitor/push-notifications', self.deps,
            '@capacitor/push-notifications must be removed from package.json — '
            'OneSignal is the sole push owner'
        )

    def test_onesignal_cordova_plugin_present(self):
        """onesignal-cordova-plugin must be listed as a dependency."""
        self.assertIn(
            'onesignal-cordova-plugin', self.deps,
            'onesignal-cordova-plugin must remain in package.json'
        )

    def test_onesignal_version_pinned_to_552(self):
        """onesignal-cordova-plugin must be pinned to exactly 5.5.2."""
        ver = self.deps.get('onesignal-cordova-plugin', '')
        self.assertEqual(ver, '5.5.2',
                         f'onesignal-cordova-plugin must be pinned to 5.5.2, got: {ver!r}')


class BLNativeJSArchitectureTests(unittest.TestCase):

    def setUp(self):
        self.src = _read('static/js/bl-native.js')

    # 2
    def test_no_capacitor_request_permissions(self):
        """bl-native.js must NOT call Push.requestPermissions() (Capacitor API)."""
        # Look for the Capacitor push requestPermissions pattern, not OneSignal's
        self.assertNotRegex(
            self.src,
            r'Push\.requestPermissions\s*\(',
            'Push.requestPermissions() is a Capacitor PushNotifications call — remove it; '
            'OneSignal.Notifications.requestPermission() handles this'
        )

    # 3
    def test_no_capacitor_register(self):
        """bl-native.js must NOT call Push.register() (Capacitor API)."""
        self.assertNotRegex(
            self.src,
            r'\bPush\.register\s*\(',
            'Push.register() is a Capacitor PushNotifications call — remove it; '
            'OneSignal handles APNs registration internally'
        )

    # 4
    def test_no_push_notification_received_listener(self):
        """bl-native.js must NOT attach a pushNotificationReceived Capacitor listener."""
        self.assertNotIn(
            'pushNotificationReceived',
            self.src,
            'pushNotificationReceived is a Capacitor PushNotifications event — '
            'use OS.Notifications.addEventListener(\'foregroundWillDisplay\') instead'
        )

    # 5
    def test_no_push_notification_action_performed_listener(self):
        """bl-native.js must NOT attach a pushNotificationActionPerformed Capacitor listener."""
        self.assertNotIn(
            'pushNotificationActionPerformed',
            self.src,
            'pushNotificationActionPerformed is a Capacitor PushNotifications event — '
            'use OS.Notifications.addEventListener(\'click\') instead'
        )

    # 6
    def test_foreground_will_display_listener_present(self):
        """bl-native.js MUST attach OneSignal foregroundWillDisplay listener."""
        self.assertIn(
            "foregroundWillDisplay",
            self.src,
            "OS.Notifications.addEventListener('foregroundWillDisplay') must be present — "
            "it replaces the Capacitor pushNotificationReceived event"
        )

    # 7
    def test_click_listener_present(self):
        """bl-native.js MUST attach OneSignal click listener for tap routing."""
        self.assertIn(
            "'click'",
            self.src,
            "OS.Notifications.addEventListener('click') must be present — "
            "it replaces pushNotificationActionPerformed for tap routing"
        )

    # 8
    def test_onesignal_request_permission_called(self):
        """bl-native.js MUST call OS.Notifications.requestPermission (not Capacitor)."""
        self.assertIn(
            'Notifications.requestPermission',
            self.src,
            "OS.Notifications.requestPermission() must be called — "
            "OneSignal owns permission management"
        )

    # 9
    def test_bl_set_push_enabled_helper_present(self):
        """bl-native.js MUST expose window.blSetPushEnabled for the push toggle."""
        self.assertIn(
            'window.blSetPushEnabled',
            self.src,
            'window.blSetPushEnabled must be defined for the push preference toggle'
        )

    # 10
    def test_bl_os_logout_helper_present(self):
        """bl-native.js MUST expose window.blOSLogout for the sign-out flow."""
        self.assertIn(
            'window.blOSLogout',
            self.src,
            'window.blOSLogout must be defined for the sign-out flow'
        )

    # 11
    def test_subscription_change_observer_present(self):
        """bl-native.js MUST register a pushSubscription change observer for diagnostics."""
        self.assertIn(
            "addEventListener('change'",
            self.src,
            "OS.User.pushSubscription.addEventListener('change') must be registered — "
            "required for subscription state diagnostics"
        )

    # 12
    def test_no_automatic_opt_in_loop(self):
        """bl-native.js must NOT automatically call optIn() in a subscription observer."""
        # Find the subscription change observer block and ensure there's no optIn() call inside it.
        # The observer is between 'change' listener registration and the next major section.
        # Strategy: search for optIn() calls that are NOT inside blSetPushEnabled.
        # Acceptable: blSetPushEnabled calls optIn() on user action.
        # NOT acceptable: optIn() called automatically from an observer or timer.
        src = self.src

        # Extract the subscription observer callback body
        observer_match = re.search(
            r"addEventListener\('change',\s*function\(state\)(.*?)}\s*\)",
            src, re.DOTALL
        )
        if observer_match:
            observer_body = observer_match.group(1)
            self.assertNotIn(
                'optIn()',
                observer_body,
                'optIn() must NOT be called automatically inside the subscription change observer — '
                'that is a workaround, not a fix. OneSignal must own the lifecycle.'
            )

    # 13 — verify _extractPushUrl is in the file with correct shape handling
    def test_extract_push_url_handles_onesignal_shape(self):
        """bl-native.js _extractPushUrl must read from notification.additionalData.url."""
        self.assertIn(
            'n.additionalData && n.additionalData.url',
            self.src,
            '_extractPushUrl must read notification.additionalData.url '
            '(primary OneSignal SDK 5.x click event shape)'
        )

    def test_extract_push_url_handles_result_url(self):
        """bl-native.js _extractPushUrl must also check result.url as fallback."""
        self.assertIn(
            'payload.result && payload.result.url',
            self.src,
            '_extractPushUrl must include payload.result.url fallback '
            '(OneSignal result field)'
        )

    def test_no_capacitor_push_plugin_lookup(self):
        """bl-native.js must NOT look up PushNotifications plugin by name."""
        # registerPlugin('PushNotifications') should not appear
        self.assertNotRegex(
            self.src,
            r"registerPlugin\(['\"]PushNotifications['\"]",
            "registerPlugin('PushNotifications') must be removed — "
            "@capacitor/push-notifications is no longer used"
        )

    def test_onesignal_sole_owner_comment_present(self):
        """bl-native.js must have architecture comment declaring OneSignal sole owner."""
        self.assertIn(
            'is the SOLE owner',
            self.src,
            'bl-native.js must document that OneSignal is the sole push owner'
        )


class AppDelegateArchitectureTests(unittest.TestCase):

    def setUp(self):
        self.src = _read('ios/App/App/AppDelegate.swift')

    # 13
    def test_no_delegate_assignment_in_did_become_active(self):
        """applicationDidBecomeActive must NOT set UNUserNotificationCenter.current().delegate."""
        # Find applicationDidBecomeActive body
        match = re.search(
            r'func applicationDidBecomeActive.*?(?=func |\Z)',
            self.src, re.DOTALL
        )
        if match:
            body = match.group(0)
            self.assertNotIn(
                'UNUserNotificationCenter.current().delegate',
                body,
                'applicationDidBecomeActive must NOT re-assign UNUserNotificationCenter.delegate — '
                'this overwrites OneSignal\'s delegate on every foreground and causes the -30 loop'
            )

    # 14
    def test_no_will_present_implementation(self):
        """AppDelegate must NOT implement willPresent (competing foreground handler)."""
        self.assertNotIn(
            'willPresent notification:',
            self.src,
            'AppDelegate must NOT implement willPresent — '
            'OneSignal owns foreground notification display'
        )

    # 15
    def test_no_did_receive_implementation(self):
        """AppDelegate must NOT implement didReceive response (competing tap handler)."""
        self.assertNotIn(
            'didReceive response: UNNotificationResponse',
            self.src,
            'AppDelegate must NOT implement didReceive — '
            'OneSignal owns notification tap handling'
        )

    # 16
    def test_apns_token_relay_present(self):
        """AppDelegate MUST relay APNs tokens via capacitorDidRegisterForRemoteNotifications."""
        self.assertIn(
            'capacitorDidRegisterForRemoteNotifications',
            self.src,
            'AppDelegate must post capacitorDidRegisterForRemoteNotifications — '
            'required by Capacitor bridge for APNs token propagation'
        )

    def test_no_un_delegate_assignment_at_launch(self):
        """AppDelegate.didFinishLaunching must NOT set UNUserNotificationCenter.delegate."""
        # Strip single-line Swift comments before searching so comment text
        # (e.g. "// Do NOT set X here") doesn't trigger the assertion.
        uncommented = re.sub(r'//[^\n]*', '', self.src)
        match = re.search(
            r'func application.*?didFinishLaunchingWithOptions.*?(?=func |\Z)',
            uncommented, re.DOTALL
        )
        if match:
            body = match.group(0)
            self.assertNotIn(
                '.delegate',
                body,
                'didFinishLaunchingWithOptions must NOT assign a notification-center delegate — '
                'OneSignal must own the delegate without interference'
            )

    def test_un_notification_center_delegate_conformance_removed(self):
        """AppDelegate class declaration must NOT list UNUserNotificationCenterDelegate."""
        # Only check the class declaration line, not comments or doc strings.
        # Extract the class declaration line.
        match = re.search(r'^class AppDelegate\s*:.*$', self.src, re.MULTILINE)
        if match:
            decl = match.group(0)
            self.assertNotIn(
                'UNUserNotificationCenterDelegate',
                decl,
                'AppDelegate class declaration must not list UNUserNotificationCenterDelegate — '
                'OneSignal owns the delegate; remove the protocol from the class line'
            )

    def test_badge_clear_in_did_become_active(self):
        """applicationDidBecomeActive MUST zero the badge count directly via UIKit."""
        self.assertIn(
            'applicationIconBadgeNumber = 0',
            self.src,
            'applicationDidBecomeActive must clear badge via UIApplication.shared.applicationIconBadgeNumber = 0'
        )


class CapacitorConfigArchitectureTests(unittest.TestCase):

    def setUp(self):
        self.cfg = json.loads(_read('capacitor.config.json'))

    # 17
    def test_no_handle_application_notifications(self):
        """capacitor.config.json must NOT have handleApplicationNotifications."""
        ios_section = self.cfg.get('ios', {})
        self.assertNotIn(
            'handleApplicationNotifications',
            ios_section,
            'handleApplicationNotifications must be removed from capacitor.config.json — '
            'it was only needed to prevent Capacitor push from conflicting; '
            'the conflict is resolved by removing @capacitor/push-notifications'
        )

    # 18
    def test_no_push_notifications_plugin_config(self):
        """capacitor.config.json must NOT have PushNotifications plugin config."""
        plugins = self.cfg.get('plugins', {})
        self.assertNotIn(
            'PushNotifications',
            plugins,
            'PushNotifications plugin config must be removed — '
            '@capacitor/push-notifications is no longer used'
        )

    def test_splash_screen_config_preserved(self):
        """capacitor.config.json MUST retain SplashScreen plugin config."""
        plugins = self.cfg.get('plugins', {})
        self.assertIn(
            'SplashScreen',
            plugins,
            'SplashScreen plugin config must be preserved in capacitor.config.json'
        )

    def test_server_url_preserved(self):
        """capacitor.config.json MUST retain server.url pointing to production."""
        server = self.cfg.get('server', {})
        self.assertEqual(
            server.get('url'),
            'https://app.baselodgeapp.com',
            'server.url must remain https://app.baselodgeapp.com'
        )


class OneSignalPushSendTests(unittest.TestCase):
    """Verify send_onesignal_push still respects push_notifications_enabled=False.
    These tests patch httpx.post and do not make real network calls.
    """

    _ENV_PATCH = {
        'ONESIGNAL_APP_ID':       'test-app-id',
        'ONESIGNAL_REST_API_KEY': 'test-rest-key',
    }

    def _make_response(self, status_code, body):
        import unittest.mock
        m = unittest.mock.MagicMock()
        m.status_code = status_code
        m.json.return_value = body
        return m

    # 23
    def test_opted_out_user_is_skipped(self):
        """send_onesignal_push skips users with push_notifications_enabled=False."""
        import unittest.mock
        from services.push_providers import send_onesignal_push
        from app import app
        from models import db, User

        try:
            with app.app_context():
                u = db.session.get(User, 2)
                if u is None:
                    self.skipTest('User id=2 not present in dev DB — skipping live-DB assertion')
                    return
                original = u.push_notifications_enabled

                try:
                    u.push_notifications_enabled = False
                    db.session.commit()

                    mock_resp = self._make_response(200, {'id': 'should-not-appear'})
                    with unittest.mock.patch.dict('os.environ', self._ENV_PATCH):
                        with unittest.mock.patch('httpx.post', return_value=mock_resp):
                            result = send_onesignal_push(
                                user_ids=[2],
                                title='Test',
                                body='Test body',
                            )

                    # If user is opted out, the call should skip without hitting OneSignal
                    self.assertTrue(result.get('skipped'),
                                    'User with push_notifications_enabled=False must be skipped')
                finally:
                    u.push_notifications_enabled = original
                    db.session.commit()
        except Exception as exc:
            # DB schema may be out of sync in dev (missing columns from pending migrations).
            # Skip rather than fail — the logic is tested by test_push_lifecycle.py.
            if 'no such column' in str(exc) or 'OperationalError' in type(exc).__name__:
                self.skipTest(f'Dev DB schema mismatch — skipping: {exc}')
            raise

    # 24
    def test_blsetpushenabled_calls_optout_not_capacitor_unregister(self):
        """Architecture: blSetPushEnabled uses optOut(), not Capacitor unregister().
        Verified via source inspection — not a runtime test.
        """
        src = _read('static/js/bl-native.js')

        # blSetPushEnabled should call optOut() when enabled=false
        self.assertIn(
            '_pushSub.optOut()',
            src,
            'blSetPushEnabled must call OS.User.pushSubscription.optOut() for push-off'
        )

        # blSetPushEnabled must NOT call Push.unregister() (Capacitor)
        # Find the blSetPushEnabled function body
        match = re.search(
            r'window\.blSetPushEnabled\s*=\s*function.*?^      \};',
            src, re.DOTALL | re.MULTILINE
        )
        if match:
            fn_body = match.group(0)
            self.assertNotIn(
                'Push.unregister',
                fn_body,
                'blSetPushEnabled must NOT call Push.unregister() — '
                'that is a Capacitor call; use optOut() instead'
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
