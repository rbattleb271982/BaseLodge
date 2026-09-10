const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  require.resolve('../../static/js/mountain-detail.js'),
  'utf8'
);

function response({
  ok = true,
  redirected = false,
  contentType = 'application/json',
  payload = { html: '<section>Friends</section>', has_content: true },
  jsonError = null
} = {}) {
  return {
    ok,
    redirected,
    headers: {
      get(name) {
        return name.toLowerCase() === 'content-type' ? contentType : null;
      }
    },
    json() {
      if (jsonError) return Promise.reject(jsonError);
      return Promise.resolve(payload);
    }
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createHarness({ hasRegion = true, socialUrl = '/api/mountain/test/social' } = {}) {
  const requests = [];
  const queued = [];
  const retryButton = {
    listener: null,
    addEventListener(event, callback) {
      if (event === 'click') this.listener = callback;
    },
    click() {
      if (this.listener) this.listener();
    }
  };
  let html = 'initial';
  const attributes = {
    'data-social-url': socialUrl,
    'aria-busy': 'true'
  };
  const region = {
    hidden: false,
    getAttribute(name) {
      return attributes[name] || null;
    },
    setAttribute(name, value) {
      attributes[name] = String(value);
    },
    querySelector(selector) {
      return selector === '.md-social-retry'
        && html.includes('md-social-retry')
        ? retryButton
        : null;
    },
    get innerHTML() {
      return html;
    },
    set innerHTML(value) {
      html = value;
    }
  };
  const wishlist = { dataset: { onWishlist: 'true' } };
  let wishlistCalls = 0;
  const window = {
    fetch(url, options) {
      requests.push({ url, options });
      const next = queued.shift();
      return next ? next.promise : Promise.resolve(response());
    },
    mdToggleWishlist() {
      wishlistCalls += 1;
    }
  };
  const document = {
    getElementById(id) {
      if (id === 'md-social-region') return hasRegion ? region : null;
      if (id === 'md-wishlist-btn') return wishlist;
      return null;
    }
  };

  vm.runInNewContext(source, { window, document, Promise, Error });
  return {
    window,
    region,
    requests,
    queued,
    retryButton,
    wishlist,
    getWishlistCalls: () => wishlistCalls
  };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test('initialization immediately starts one bounded same-origin GET', async () => {
  const harness = createHarness();
  assert.equal(harness.requests.length, 1);
  assert.equal(harness.requests[0].url, '/api/mountain/test/social');
  assert.equal(harness.requests[0].options.method, 'GET');
  assert.equal(harness.requests[0].options.credentials, 'same-origin');
  assert.equal(harness.requests[0].options.cache, 'no-store');
  assert.equal(harness.region.getAttribute('aria-busy'), 'true');
  await settle();
});

test('valid content inserts server HTML and clears busy state', async () => {
  const harness = createHarness();
  await settle();
  assert.equal(harness.region.innerHTML, '<section>Friends</section>');
  assert.equal(harness.region.hidden, false);
  assert.equal(harness.region.getAttribute('aria-busy'), 'false');
});

test('valid empty success hides the complete region', async () => {
  const request = deferred();
  const harness = createHarness();
  harness.queued.push(request);
  // Replace the already completed default request with an explicit reload.
  await settle();
  harness.window.BLLoadMountainSocial();
  request.resolve(response({
    payload: { html: '', has_content: false }
  }));
  await settle();
  assert.equal(harness.region.hidden, true);
  assert.equal(harness.region.innerHTML, '');
  assert.equal(harness.region.getAttribute('aria-busy'), 'false');
});

test('HTTP, malformed JSON shape, and redirected HTML show generic failure', async () => {
  for (const invalid of [
    response({ ok: false }),
    response({ payload: { html: 'missing flag' } }),
    response({
      redirected: true,
      contentType: 'text/html',
      payload: null
    })
  ]) {
    const request = deferred();
    const harness = createHarness();
    await settle();
    harness.queued.push(request);
    harness.window.BLLoadMountainSocial();
    request.resolve(invalid);
    await settle();
    assert.match(
      harness.region.innerHTML,
      /Social details couldn’t load/
    );
    assert.match(harness.region.innerHTML, /Try again\./);
    assert.equal(harness.region.getAttribute('aria-busy'), 'false');
  }
});

test('invalid JSON, non-JSON content, and inconsistent empty payload fail', async () => {
  for (const invalid of [
    response({ jsonError: new Error('invalid json') }),
    response({ contentType: 'text/html' }),
    response({
      payload: { html: '<section>Unexpected</section>', has_content: false }
    })
  ]) {
    const request = deferred();
    const harness = createHarness();
    await settle();
    harness.queued.push(request);
    harness.window.BLLoadMountainSocial();
    request.resolve(invalid);
    await settle();
    assert.match(
      harness.region.innerHTML,
      /Social details couldn’t load/
    );
    assert.equal(harness.region.hidden, false);
  }
});

test('retry restores loading and successful content replaces failure', async () => {
  const failure = deferred();
  const success = deferred();
  const harness = createHarness();
  await settle();
  harness.queued.push(failure, success);
  harness.window.BLLoadMountainSocial();
  failure.resolve(response({ ok: false }));
  await settle();

  harness.retryButton.click();
  assert.equal(harness.requests.length, 3);
  assert.match(harness.region.innerHTML, /Loading mountain community/);
  assert.equal(harness.region.getAttribute('aria-busy'), 'true');
  success.resolve(response({
    payload: { html: '<section>Retry worked</section>', has_content: true }
  }));
  await settle();
  assert.equal(harness.region.innerHTML, '<section>Retry worked</section>');
});

test('duplicate activation while pending does not duplicate request', async () => {
  const request = deferred();
  const harness = createHarness();
  await settle();
  harness.queued.push(request);
  harness.window.BLLoadMountainSocial();
  harness.window.BLLoadMountainSocial();
  assert.equal(harness.requests.length, 2);
  request.resolve(response());
  await settle();
});

test('an older response cannot overwrite a newer forced request', async () => {
  const older = deferred();
  const newer = deferred();
  const harness = createHarness();
  await settle();
  harness.queued.push(older, newer);

  harness.window.BLLoadMountainSocial();
  harness.window.BLLoadMountainSocial(true);
  newer.resolve(response({
    payload: { html: '<section>Newer</section>', has_content: true }
  }));
  await settle();
  older.resolve(response({
    payload: { html: '<section>Older</section>', has_content: true }
  }));
  await settle();

  assert.equal(harness.region.innerHTML, '<section>Newer</section>');
});

test('missing region or endpoint URL safely no-ops', () => {
  const noRegion = createHarness({ hasRegion: false });
  const noUrl = createHarness({ socialUrl: '' });
  assert.equal(noRegion.requests.length, 0);
  assert.equal(noUrl.requests.length, 0);
});

test('social loader does not call page-view or change wishlist behavior', async () => {
  const harness = createHarness();
  await settle();
  assert.equal(
    harness.requests.some((item) => item.url === '/api/mountain/track-view'),
    false
  );
  assert.equal(harness.getWishlistCalls(), 0);
  assert.equal(harness.wishlist.dataset.onWishlist, 'true');
});