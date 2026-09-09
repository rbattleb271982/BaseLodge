'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
  ALLOWED_PATHS,
  installIntentPrefetch,
} = require('../../static/js/bl-intent-prefetch.js');

const ROOT = path.resolve(__dirname, '../..');

function anchor(href, options = {}) {
  return {
    href,
    target: options.target || '',
    closest(selector) {
      return selector === 'a[href]' ? this : null;
    },
    getAttribute(name) {
      if (name === 'href') return href;
      if (name === 'target') return this.target;
      return null;
    },
    hasAttribute(name) {
      return name === 'download' && options.download === true;
    },
  };
}

function harness(pathname = '/home') {
  const listeners = new Map();
  const hints = [];
  const document = {
    head: {
      appendChild(element) {
        hints.push(element);
      },
    },
    addEventListener(type, listener, capture) {
      listeners.set(type, { listener, capture });
    },
    createElement(tag) {
      assert.equal(tag, 'link');
      return {};
    },
  };
  installIntentPrefetch(document, {
    href: `https://app.baselodgeapp.com${pathname}`,
    origin: 'https://app.baselodgeapp.com',
  });
  return {
    hints,
    listeners,
    fire(type, target) {
      let prevented = false;
      listeners.get(type).listener({
        target,
        preventDefault() {
          prevented = true;
        },
      });
      return prevented;
    },
  };
}

test('initialization creates no hints and registers no viewport observer', () => {
  const state = harness();
  assert.equal(state.hints.length, 0);
  assert.deepEqual([...state.listeners.keys()].sort(), [
    'focusin',
    'pointerdown',
    'pointerenter',
  ]);
  assert.equal(
    fs.readFileSync(
      path.join(ROOT, 'static/js/bl-intent-prefetch.js'),
      'utf8',
    ).includes('IntersectionObserver'),
    false,
  );
});

for (const eventName of ['pointerenter', 'focusin', 'pointerdown']) {
  test(`${eventName} creates one native prefetch hint`, () => {
    const state = harness('/home');
    const prevented = state.fire(
      eventName,
      anchor('/friends?tab=requests'),
    );
    assert.equal(prevented, false);
    assert.equal(state.hints.length, 1);
    assert.equal(state.hints[0].rel, 'prefetch');
    assert.equal(
      state.hints[0].href,
      'https://app.baselodgeapp.com/friends?tab=requests',
    );
  });
}

test('repeated and mixed intent deduplicates the normalized destination', () => {
  const state = harness();
  const link = anchor('/mountains');
  state.fire('pointerenter', link);
  state.fire('pointerenter', link);
  state.fire('focusin', link);
  state.fire('pointerdown', link);
  assert.equal(state.hints.length, 1);
});

test('only the five exact paths are allowed', () => {
  assert.deepEqual([...ALLOWED_PATHS].sort(), [
    '/friends',
    '/home',
    '/mountains',
    '/my-trips',
    '/profile',
  ]);
});

test('unsafe and unapproved destinations never create hints', () => {
  const cases = [
    anchor('https://example.com/home'),
    anchor('#section'),
    anchor('/friends#requests'),
    anchor('mailto:test@example.com'),
    anchor('tel:5551234567'),
    anchor('sms:5551234567'),
    anchor('/home', { target: '_blank' }),
    anchor('/home', { download: true }),
    anchor('/api/mountains-data'),
    anchor('/api/friends'),
    anchor('/auth'),
    anchor('/trips/12'),
    anchor('/mountain/alta'),
    anchor('/friends/12'),
    anchor('/edit-profile'),
    anchor('/settings/equipment'),
    anchor('/logout'),
    anchor('/health'),
    anchor('/admin'),
    anchor('/profile/settings'),
    anchor('/unknown'),
  ];
  for (const link of cases) {
    const state = harness();
    state.fire('pointerenter', link);
    assert.equal(state.hints.length, 0, link.href);
  }
});

test('current page and targets without an anchor create no hint', () => {
  const state = harness('/profile?section=passes');
  state.fire('focusin', anchor('/profile?section=passes'));
  state.fire('pointerdown', {
    closest() {
      return null;
    },
  });
  assert.equal(state.hints.length, 0);
});

test('broad static hints are gone while required loading remains', () => {
  const broadTemplates = [
    'templates/home.html',
    'templates/friends.html',
    'templates/my_trips.html',
    'templates/mountains_tab.html',
    'templates/profile.html',
    'templates/trip_ideas.html',
  ];
  for (const filename of broadTemplates) {
    const source = fs.readFileSync(path.join(ROOT, filename), 'utf8');
    assert.equal(source.includes('rel="prefetch"'), false, filename);
  }

  const base = fs.readFileSync(
    path.join(ROOT, 'templates/base_app.html'),
    'utf8',
  );
  assert.equal(
    (base.match(/bl-intent-prefetch\.js/g) || []).length,
    1,
  );

  const auth = fs.readFileSync(
    path.join(ROOT, 'templates/auth.html'),
    'utf8',
  );
  assert.match(auth, /rel="preconnect"/);
  assert.match(auth, /rel="preload" as="style"/);

  const mountains = fs.readFileSync(
    path.join(ROOT, 'templates/mountains_tab.html'),
    'utf8',
  );
  assert.match(
    mountains,
    /fetch\('\/api\/mountains-data', \{ cache: 'no-store' \}\)/,
  );
  assert.match(mountains, /loadMountainsData\(\)/);
});