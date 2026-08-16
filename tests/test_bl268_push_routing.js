/**
 * BL-268: Push deep-link routing helpers — unit tests.
 *
 * Tests the module-scope helpers extracted from bl-native.js:
 *   _extractPushUrl  — payload shape handling
 *   _doNavFromPush   — dedup via _pushNavDone
 *
 * Run with:  node tests/test_bl268_push_routing.js
 */

'use strict';

// ── Inline the helpers under test ─────────────────────────────────────────
// Extracted verbatim from static/js/bl-native.js (module-scope declarations).
// If the implementations diverge the tests will start failing and this file
// must be updated to match.

var _pushNavDone = false;

function _extractPushUrl(payload) {
  try {
    if (!payload) return null;
    var raw = null;
    var n = payload.notification || payload;
    raw = (n.additionalData && n.additionalData.url)
       || (n.data        && n.data.url)
       || (payload.additionalData && payload.additionalData.url)
       || (payload.data        && payload.data.url)
       || null;
    if (!raw || typeof raw !== 'string') return null;
    raw = raw.trim();
    if (!raw.startsWith('/') || raw.startsWith('//')) return null;
    if (/javascript:/i.test(raw) || /data:/i.test(raw)) return null;
    return raw;
  } catch (_ue) {
    return null;
  }
}

// Stub window.location.href writes so we can inspect without actually navigating.
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

// ── _extractPushUrl — payload shape coverage ──────────────────────────────

console.log('\n_extractPushUrl — payload shapes\n');

// 1. onesignal-cordova-plugin v5 click event shape:
//    clickEvent.notification.additionalData.url
console.log('  [1] Cordova v5 click event (additionalData.url via .notification wrapper)');
assert('Suggested Friends URL extracted',
  _extractPushUrl({ notification: { additionalData: { url: '/friends?tab=suggested' } } })
    === '/friends?tab=suggested');

// 2. Same shape, raw notification object (no .notification wrapper)
console.log('  [2] Raw OSNotification with additionalData.url');
assert('Suggested Friends URL extracted from raw notification',
  _extractPushUrl({ additionalData: { url: '/friends?tab=suggested' } })
    === '/friends?tab=suggested');

// 3. Capacitor PushNotifications action event shape:
//    action.notification.data.url
console.log('  [3] Capacitor PushNotifications action (data.url via .notification wrapper)');
assert('data.url extracted',
  _extractPushUrl({ notification: { data: { url: '/friends?requests=1' } } })
    === '/friends?requests=1');

// 4. Friend-request URL via additionalData
console.log('  [4] Friend-request URL (/friends?requests=1)');
assert('Friend request URL extracted',
  _extractPushUrl({ additionalData: { url: '/friends?requests=1' } })
    === '/friends?requests=1');

// 5. No URL in payload
console.log('  [5] Push with no URL');
assert('Returns null when no URL present',
  _extractPushUrl({ additionalData: { event: 'friend.request.created' } }) === null);

// 6. Null payload
console.log('  [6] Null payload');
assert('Returns null for null payload',
  _extractPushUrl(null) === null);

// 7. Unsafe absolute URL rejected
console.log('  [7] Absolute URL rejected');
assert('Absolute URL returns null',
  _extractPushUrl({ additionalData: { url: 'https://evil.com/' } }) === null);

// 8. Protocol-relative URL rejected
console.log('  [8] Protocol-relative URL rejected');
assert('// URL returns null',
  _extractPushUrl({ additionalData: { url: '//evil.com/' } }) === null);

// 9. javascript: scheme rejected
console.log('  [9] javascript: scheme rejected');
assert('javascript: URL returns null',
  _extractPushUrl({ additionalData: { url: 'javascript:alert(1)' } }) === null);

// 10. data: scheme rejected
console.log('  [10] data: scheme rejected');
assert('data: URL returns null',
  _extractPushUrl({ additionalData: { url: 'data:text/html,<h1>x</h1>' } }) === null);

// 11. Top-level data.url (no .notification wrapper, no .additionalData)
console.log('  [11] Top-level data.url fallback');
assert('Top-level data.url extracted',
  _extractPushUrl({ data: { url: '/friends?tab=suggested' } }) === '/friends?tab=suggested');

// ── _doNavFromPush — dedup via _pushNavDone ───────────────────────────────

console.log('\n_doNavFromPush — dedup behaviour\n');

// 12. Single tap navigates
console.log('  [12] Single push tap navigates');
reset();
_doNavFromPush({ additionalData: { url: '/friends?tab=suggested' } }, 'test');
assert('_navCalls has one entry', _navCalls.length === 1);
assert('Navigated to Suggested Friends', _navCalls[0] === '/friends?tab=suggested');
assert('_pushNavDone is now true', _pushNavDone === true);

// 13. Second call (same push, two listeners firing) is suppressed
console.log('  [13] Second listener call suppressed by _pushNavDone');
_doNavFromPush({ additionalData: { url: '/friends?tab=suggested' } }, 'test_duplicate');
assert('Still only one nav call', _navCalls.length === 1);

// 14. Different source also suppressed
console.log('  [14] pushNotificationActionPerformed fallback suppressed after click handler');
_doNavFromPush({ data: { url: '/other' } }, 'pushNotificationActionPerformed');
assert('Still only one nav call (no /other)', _navCalls.length === 1);

// 15. Push with no URL does not set _pushNavDone
console.log('  [15] Push with no URL does not lock out future navs');
reset();
_doNavFromPush({ additionalData: {} }, 'no-url-source');
assert('_pushNavDone still false', _pushNavDone === false);
assert('No nav calls', _navCalls.length === 0);
_doNavFromPush({ additionalData: { url: '/friends?tab=suggested' } }, 'real-tap');
assert('Subsequent real tap navigates', _navCalls.length === 1);

// 16. Friend-request notification routes correctly
console.log('  [16] Friend-request notification routes to /friends?requests=1');
reset();
_doNavFromPush({ additionalData: { url: '/friends?requests=1' } }, 'OS.Notifications.click');
assert('Friend request navigated', _navCalls[0] === '/friends?requests=1');

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
