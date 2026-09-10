const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  require.resolve('../../static/analytics.js'),
  'utf8'
);

function runAnalytics({ user = {}, storedUserId = null, reset = false } = {}) {
  const calls = [];
  const storage = new Map();
  if (storedUserId !== null) {
    storage.set('baselodge_posthog_authenticated_user_id', storedUserId);
  }
  const ph = {
    __SV: 1,
    init(key, options) {
      calls.push(['init', key, options]);
      options.loaded(ph);
    },
    reset() {
      calls.push(['reset']);
    },
    identify(id, properties) {
      calls.push(['identify', id, properties]);
    },
    capture(event, properties) {
      calls.push(['capture', event, properties]);
    }
  };
  const localStorage = {
    getItem(key) {
      return storage.has(key) ? storage.get(key) : null;
    },
    setItem(key, value) {
      storage.set(key, value);
    },
    removeItem(key) {
      storage.delete(key);
    }
  };
  const window = {
    __POSTHOG_KEY__: 'test-key',
    __POSTHOG_HOST__: 'https://example.test',
    __POSTHOG_RESET__: reset,
    __USER__: user,
    localStorage,
    posthog: ph
  };
  vm.runInNewContext(source, { window, posthog: ph, document: {} });
  return { calls, storage };
}

test('authenticated users are identified with numeric ID and internal flag', () => {
  const { calls, storage } = runAnalytics({
    user: { id: 42, is_internal: true }
  });
  const identify = calls.find((call) => call[0] === 'identify');
  assert.equal(identify[1], '42');
  assert.equal(identify[2].is_internal, true);
  assert.deepEqual(Object.keys(identify[2]), ['is_internal']);
  assert.equal(
    storage.get('baselodge_posthog_authenticated_user_id'),
    '42'
  );
  const options = calls.find((call) => call[0] === 'init')[2];
  assert.equal(options.autocapture, false);
  assert.equal(options.capture_pageview, false);
  assert.equal(options.disable_session_recording, true);
});

test('anonymous page after authenticated page resets and clears marker', () => {
  const { calls, storage } = runAnalytics({ storedUserId: '42' });
  assert.equal(calls.filter((call) => call[0] === 'reset').length, 1);
  assert.equal(
    storage.has('baselodge_posthog_authenticated_user_id'),
    false
  );
});

test('account switch resets before identifying the new user', () => {
  const { calls, storage } = runAnalytics({
    user: { id: 84, is_internal: false },
    storedUserId: '42'
  });
  assert.ok(
    calls.findIndex((call) => call[0] === 'reset')
      < calls.findIndex((call) => call[0] === 'identify')
  );
  assert.equal(
    storage.get('baselodge_posthog_authenticated_user_id'),
    '84'
  );
});

test('same authenticated user does not reset unnecessarily', () => {
  const { calls } = runAnalytics({
    user: { id: 42, is_internal: false },
    storedUserId: '42'
  });
  assert.equal(calls.some((call) => call[0] === 'reset'), false);
});

test('server reset flag resets once before identify', () => {
  const { calls } = runAnalytics({
    user: { id: 42, is_internal: false },
    storedUserId: '42',
    reset: true
  });
  assert.equal(calls.filter((call) => call[0] === 'reset').length, 1);
  assert.ok(
    calls.findIndex((call) => call[0] === 'reset')
      < calls.findIndex((call) => call[0] === 'identify')
  );
});

test('malformed authenticated marker is removed without resetting', () => {
  const { calls, storage } = runAnalytics({ storedUserId: 'user@example.com' });
  assert.equal(calls.some((call) => call[0] === 'reset'), false);
  assert.equal(
    storage.has('baselodge_posthog_authenticated_user_id'),
    false
  );
});