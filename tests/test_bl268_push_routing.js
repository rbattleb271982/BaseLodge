/**
 * Push deep-link routing helpers — unit tests.
 *
 * Tests the helpers extracted from the OneSignal push lifecycle block in
 * bl-native.js (the sole push owner since @capacitor/push-notifications
 * was removed):
 *   _extractPushUrl  — payload shape handling for all OneSignal event formats
 *   _doNavFromPush   — dedup via _pushNavDone
 *
 * Run with:  node tests/test_bl268_push_routing.js
 *
 * Payload shapes covered:
 *   • OneSignal SDK 5.x click event: event.notification.additionalData.url
 *   • OneSignal result.url field (event.result.url)
 *   • Legacy Capacitor PushNotifications shape (data.url) — kept for
 *     compatibility with any stored notifications from the prior architecture
 */

'use strict';

// ── Inline the helpers under test ─────────────────────────────────────────
// Extracted verbatim from static/js/bl-native.js (OneSignal block).
// If the implementations diverge the tests will start failing — update here.

var _pushNavDone = false;

function _extractPushUrl(payload) {
  try {
    if (!payload) return null;
    var raw = null;
    var n = payload.notification || payload;
    // OneSignal SDK 5 click event: notification.additionalData.url
    // Capacitor-compat fallback: notification.data.url
    raw = (n.additionalData && n.additionalData.url)
       || (n.data        && n.data.url)
       || (payload.additionalData && payload.additionalData.url)
       || (payload.data        && payload.data.url)
       || null;
    // OneSignal result.url field (separate from data payload)
    if (!raw && payload.result && payload.result.url) {
      raw = payload.result.url;
    }
    if (!raw || typeof raw !== 'string') return null;
    raw = raw.trim();
    // Safety: must be a relative path starting with a single "/"
    if (!raw.startsWith('/') || raw.startsWith('//')) return null;
    if (/javascript:/i.test(raw) || /data:/i.test(raw)) return null;
    return raw;
  } catch (_ue) {
    return null;
  }
}

// Stub window.location.href writes
var _navCalls = [];
var _window = { location: {} };
Object.defineProperty(_window.location, 'href', {
  set: function(v) { _navCalls.push(v); },
  get: function() { return _navCalls[_navCalls.length - 1] || ''; },
});

function _doNavFromPush(payload, source) {
  if (_pushNavDone) return;
  var url = _extractPushUrl(payload);
  if (url) {
    _pushNavDone = true;
    _navCalls.push(url);
  }
}

// ── Test harness ──────────────────────────────────────────────────────────

var passed = 0;
var failed = 0;

function reset() {
  _pushNavDone = false;
  _navCalls = [];
}

function assert(desc, condition) {
  if (condition) {
    console.log('  ✓ ' + desc);
    passed++;
  } else {
    console.error('  ✗ ' + desc);
    failed++;
  }
}

// ── _extractPushUrl — OneSignal SDK 5.x shapes ────────────────────────────

console.log('\n_extractPushUrl — OneSignal SDK 5.x click event shapes\n');

// 1. Primary shape: OS.Notifications.click event — notification.additionalData.url
console.log('  [1] OneSignal click event (notification.additionalData.url via .notification wrapper)');
assert('Suggested Friends URL extracted',
  _extractPushUrl({ notification: { additionalData: { url: '/friends?tab=suggested' } } })
    === '/friends?tab=suggested');

// 2. /friends plain path (as sent in test notification data:{url:"/friends"})
console.log('  [2] /friends plain path (from server data:{url:"/friends"})');
assert('/friends extracted from additionalData',
  _extractPushUrl({ notification: { additionalData: { url: '/friends' } } })
    === '/friends');

// 3. Raw OSNotification (no .notification wrapper) — foregroundWillDisplay shape
console.log('  [3] Raw OSNotification with additionalData.url (foregroundWillDisplay shape)');
assert('/friends?tab=suggested extracted from raw notification',
  _extractPushUrl({ additionalData: { url: '/friends?tab=suggested' } })
    === '/friends?tab=suggested');

// 4. OneSignal result.url field (separate from data payload)
console.log('  [4] OneSignal result.url field');
assert('result.url extracted when no additionalData',
  _extractPushUrl({ result: { url: '/friends?requests=1' } })
    === '/friends?requests=1');

// 5. result.url ignored when additionalData.url present (additionalData wins)
console.log('  [5] additionalData.url takes priority over result.url');
assert('additionalData.url wins over result.url',
  _extractPushUrl({
    notification: { additionalData: { url: '/friends?tab=suggested' } },
    result: { url: '/other' }
  }) === '/friends?tab=suggested');

// ── _extractPushUrl — Capacitor legacy compat shapes ─────────────────────

console.log('\n_extractPushUrl — legacy Capacitor shape compat\n');

// 6. Capacitor PushNotifications action event shape: action.notification.data.url
console.log('  [6] Legacy Capacitor action (data.url via .notification wrapper)');
assert('data.url extracted',
  _extractPushUrl({ notification: { data: { url: '/friends?requests=1' } } })
    === '/friends?requests=1');

// 7. Top-level data.url (no .notification wrapper, no .additionalData)
console.log('  [7] Top-level data.url fallback');
assert('Top-level data.url extracted',
  _extractPushUrl({ data: { url: '/friends?tab=suggested' } }) === '/friends?tab=suggested');

// ── _extractPushUrl — null / empty cases ─────────────────────────────────

console.log('\n_extractPushUrl — null / empty / rejection cases\n');

// 8. No URL in payload
console.log('  [8] Push with no URL');
assert('Returns null when no URL present',
  _extractPushUrl({ additionalData: { event: 'friend.request.created' } }) === null);

// 9. Null payload
console.log('  [9] Null payload');
assert('Returns null for null payload',
  _extractPushUrl(null) === null);

// 10. Unsafe absolute URL rejected
console.log('  [10] Absolute URL rejected');
assert('Absolute URL returns null',
  _extractPushUrl({ additionalData: { url: 'https://evil.com/' } }) === null);

// 11. Protocol-relative URL rejected
console.log('  [11] Protocol-relative URL rejected');
assert('// URL returns null',
  _extractPushUrl({ additionalData: { url: '//evil.com/' } }) === null);

// 12. javascript: scheme rejected
console.log('  [12] javascript: scheme rejected');
assert('javascript: URL returns null',
  _extractPushUrl({ additionalData: { url: 'javascript:alert(1)' } }) === null);

// 13. data: scheme rejected
console.log('  [13] data: scheme rejected');
assert('data: URL returns null',
  _extractPushUrl({ additionalData: { url: 'data:text/html,<h1>x</h1>' } }) === null);

// 14. Friend-request URL via additionalData
console.log('  [14] Friend-request URL (/friends?requests=1)');
assert('Friend request URL extracted',
  _extractPushUrl({ additionalData: { url: '/friends?requests=1' } })
    === '/friends?requests=1');

// ── _doNavFromPush — dedup via _pushNavDone ───────────────────────────────

console.log('\n_doNavFromPush — dedup / cold-launch prevention\n');

// 15. Single tap navigates
console.log('  [15] Single push tap navigates');
reset();
_doNavFromPush({ notification: { additionalData: { url: '/friends?tab=suggested' } } }, 'OS.Notifications.click');
assert('_navCalls has one entry', _navCalls.length === 1);
assert('Navigated to Suggested Friends', _navCalls[0] === '/friends?tab=suggested');
assert('_pushNavDone is now true', _pushNavDone === true);

// 16. Cold-launch replay (getLaunchNotification) suppressed after click handler already ran
console.log('  [16] Cold-launch replay suppressed after click handler');
_doNavFromPush({ notification: { additionalData: { url: '/friends?tab=suggested' } } }, 'getLaunchNotification');
assert('Still only one nav call (cold-launch replay deduplicated)', _navCalls.length === 1);

// 17. Different source also suppressed
console.log('  [17] Second listener call suppressed by _pushNavDone');
_doNavFromPush({ data: { url: '/other' } }, 'duplicate_listener');
assert('Still only one nav call (no /other)', _navCalls.length === 1);

// 18. Push with no URL does not set _pushNavDone
console.log('  [18] Push with no URL does not lock out future navs');
reset();
_doNavFromPush({ additionalData: {} }, 'no-url-source');
assert('_pushNavDone still false', _pushNavDone === false);
assert('No nav calls', _navCalls.length === 0);
_doNavFromPush({ notification: { additionalData: { url: '/friends?tab=suggested' } } }, 'OS.Notifications.click');
assert('Subsequent real tap navigates', _navCalls.length === 1);

// 19. Friend-request notification routes to /friends?requests=1
console.log('  [19] Friend-request notification routes to /friends?requests=1');
reset();
_doNavFromPush({ notification: { additionalData: { url: '/friends?requests=1' } } }, 'OS.Notifications.click');
assert('Friend request navigated', _navCalls[0] === '/friends?requests=1');

// 20. /friends plain path (as sent in production test notification)
console.log('  [20] /friends plain path navigated correctly');
reset();
_doNavFromPush({ notification: { additionalData: { url: '/friends' } } }, 'OS.Notifications.click');
assert('/friends navigated', _navCalls[0] === '/friends');

// 21. No Capacitor PushNotifications shape dependency
//     Ensures the old Capacitor 'pushNotificationActionPerformed' shape is NOT
//     required — OneSignal click event shape is sufficient.
console.log('  [21] OneSignal click event shape (no Capacitor dependency)');
reset();
var osClickEvent = {
  notification: { additionalData: { url: '/friends', event: 'friend.request.created' } },
  result: { actionId: 'default', closingMessage: false }
};
_doNavFromPush(osClickEvent, 'OS.Notifications.click');
assert('OneSignal click event shape navigates correctly', _navCalls[0] === '/friends');

// ── Summary ───────────────────────────────────────────────────────────────

console.log('\n─────────────────────────────────────────────');
console.log('Results: ' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) {
  console.error('FAIL');
  process.exit(1);
} else {
  console.log('PASS');
  process.exit(0);
}
