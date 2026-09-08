const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function harness() {
  const listeners = {};
  const assigned = [];
  const current = {};
  let incoming = {};
  const document = {
    activeElement: null,
    addEventListener(type, handler) { listeners[type] = handler; },
    querySelector(selector) { return current[selector] || null; },
  };
  class Parser {
    parseFromString() {
      return { querySelector(selector) { return incoming[selector] || null; } };
    }
  }
  const window = {
    CSS: { escape(value) { return value; } },
    location: {
      href: 'https://example.test/friends?tab=friends',
      origin: 'https://example.test',
      pathname: '/friends',
      search: '?tab=friends',
      assign(url) { assigned.push(url); },
    },
    scrollX: 4,
    scrollY: 9,
    scrollTo() {},
  };
  const context = {
    Array,
    DOMParser: Parser,
    Error,
    FormData: class FormData {},
    Promise,
    Set,
    String,
    URL,
    document,
    fetch: null,
    window,
  };
  vm.runInNewContext(
    fs.readFileSync('static/js/bl-targeted-refresh.js', 'utf8'),
    context
  );
  return {
    assigned,
    context,
    current,
    listeners,
    setIncoming(value) { incoming = value; },
    window,
  };
}

function response({ ok = true, status = 200, url, html = '<html></html>' } = {}) {
  return {
    ok,
    status,
    url: url || 'https://example.test/friends?tab=friends',
    headers: { get() { return 'text/html; charset=utf-8'; } },
    async text() { return html; },
  };
}

function jsonResponse(data) {
  return {
    ok: true,
    status: 200,
    url: 'https://example.test/friends',
    headers: { get() { return 'application/json'; } },
    async json() { return data; },
  };
}

test('older region response cannot replace newer content', async () => {
  const h = harness();
  const selector = '[data-test-region="directory"]';
  const replacements = [];
  h.current[selector] = { replaceWith(node) { replacements.push(node.value); } };
  const controller = h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
  });
  const oldTicket = controller.beginRefresh(['directory']);
  const newTicket = controller.beginRefresh(['directory']);
  h.setIncoming({ [selector]: { value: 'new' } });
  await controller.applyResponse(response(), ['directory'], newTicket);
  h.setIncoming({ [selector]: { value: 'old' } });
  await controller.applyResponse(response(), ['directory'], oldTicket);
  assert.deepEqual(replacements, ['new']);
});

test('429 is rejected without navigation or retry', async () => {
  const h = harness();
  const controller = h.window.BLTargetedRefresh.create({});
  const ticket = controller.beginRefresh(['directory']);
  await assert.rejects(
    controller.applyResponse(
      response({ ok: false, status: 429 }),
      ['directory'],
      ticket
    ),
    error => error.status === 429
  );
  assert.deepEqual(h.assigned, []);
});

test('redirect away uses normal navigation', async () => {
  const h = harness();
  const controller = h.window.BLTargetedRefresh.create({});
  const ticket = controller.beginRefresh(['directory']);
  await controller.applyResponse(
    response({ url: 'https://example.test/home' }),
    ['directory'],
    ticket
  );
  assert.deepEqual(h.assigned, ['https://example.test/home']);
});

test('missing region falls back once without throwing', async () => {
  const h = harness();
  const present = '[data-test-region="present"]';
  h.current[present] = { replaceWith() {} };
  h.setIncoming({ [present]: { value: 'present' } });
  const controller = h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
  });
  const ticket = controller.beginRefresh(['missing', 'present']);
  await controller.applyResponse(
    response(),
    ['missing', 'present'],
    ticket
  );
  assert.deepEqual(h.assigned, ['https://example.test/friends?tab=friends']);
});

test('asynchronous state hook completes before scroll restoration', async () => {
  const h = harness();
  const selector = '[data-test-region="directory"]';
  const order = [];
  h.current[selector] = { replaceWith() { order.push('replace'); } };
  h.setIncoming({ [selector]: { value: 'new' } });
  h.window.scrollTo = function() { order.push('scroll'); };
  const controller = h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
    async afterReplace() {
      await Promise.resolve();
      order.push('hook');
    },
  });
  const ticket = controller.beginRefresh(['directory']);
  await controller.applyResponse(response(), ['directory'], ticket);
  assert.deepEqual(order, ['replace', 'hook', 'scroll']);
});

test('stale asynchronous hook cannot restore old scroll position', async () => {
  const h = harness();
  const selector = '[data-test-region="directory"]';
  const order = [];
  h.current[selector] = { replaceWith() { order.push('replace'); } };
  h.setIncoming({ [selector]: { value: 'new' } });
  h.window.scrollTo = function() { order.push('scroll'); };
  let controller;
  controller = h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
    async afterReplace() {
      controller.beginRefresh(['directory']);
      await Promise.resolve();
      order.push('hook');
    },
  });
  const ticket = controller.beginRefresh(['directory']);
  await controller.applyResponse(response(), ['directory'], ticket);
  assert.deepEqual(order, ['replace', 'hook']);
});

test('pending duplicate submit is prevented and not fetched twice', async () => {
  const h = harness();
  let resolveFetch;
  let fetchCount = 0;
  h.context.fetch = function() {
    fetchCount += 1;
    return new Promise(resolve => { resolveFetch = resolve; });
  };
  h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
    formAttribute: 'data-test-form',
  });

  const attributes = { 'data-test-form': 'directory' };
  const form = {
    action: 'https://example.test/friends/accept',
    method: 'POST',
    isConnected: true,
    getAttribute(name) { return attributes[name] || null; },
    setAttribute(name, value) { attributes[name] = value; },
    removeAttribute(name) { delete attributes[name]; },
  };
  const target = { closest() { return form; } };
  let prevented = 0;
  const event = {
    target,
    submitter: null,
    preventDefault() { prevented += 1; },
  };

  const first = h.listeners.submit(event);
  const second = h.listeners.submit(event);
  assert.equal(prevented, 2);
  assert.equal(fetchCount, 1);

  resolveFetch(response({ ok: false, status: 429 }));
  await Promise.all([first, second]);
  assert.equal(fetchCount, 1);
});

test('JSON form success refreshes canonical regions and shows message', async () => {
  const h = harness();
  const selector = '[data-test-region="directory"]';
  const replacements = [];
  const toasts = [];
  h.current[selector] = { replaceWith(node) { replacements.push(node.value); } };
  h.setIncoming({ [selector]: { value: 'canonical' } });
  h.window.blToast = message => toasts.push(message);
  let fetchCount = 0;
  h.context.fetch = async function() {
    fetchCount += 1;
    return fetchCount === 1
      ? jsonResponse({ success: true, message: 'Saved' })
      : response();
  };
  h.window.BLTargetedRefresh.create({
    regionAttribute: 'data-test-region',
    formAttribute: 'data-test-form',
  });
  const attributes = { 'data-test-form': 'directory' };
  const form = {
    action: '/save', method: 'POST', isConnected: true,
    getAttribute(name) { return attributes[name] || null; },
    setAttribute(name, value) { attributes[name] = value; },
    removeAttribute(name) { delete attributes[name]; },
  };
  await h.listeners.submit({
    target: { closest() { return form; } },
    submitter: null,
    preventDefault() {},
  });
  assert.equal(fetchCount, 2);
  assert.deepEqual(replacements, ['canonical']);
  assert.deepEqual(toasts, ['Saved']);
});

function inviteLoaderHarness() {
  const states = {
    loading: { hidden: true },
    empty: { hidden: true },
    error: { hidden: true },
  };
  const attributes = {};
  const results = {
    innerHTML: '',
    setAttribute(name, value) { attributes[name] = value; },
    removeAttribute(name) { delete attributes[name]; },
  };
  const window = {};
  const context = { Error, Number, Promise, window };
  vm.runInNewContext(
    fs.readFileSync('static/js/trip-detail-invite-loader.js', 'utf8'),
    context
  );
  return {
    results,
    states,
    create(options) {
      return window.TripDetailInviteLoader.create({
        url: '/trips/1/invite-candidates',
        fetchImpl: options.fetchImpl,
        getResults() { return results; },
        getState(name) { return states[name]; },
        onLoaded: options.onLoaded,
      });
    },
  };
}

function inviteResponse(data, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async json() { return data; },
  };
}

test('invite loader deduplicates concurrent retrieval and caches success', async () => {
  const h = inviteLoaderHarness();
  let resolveFetch;
  let fetchCount = 0;
  const loader = h.create({
    fetchImpl() {
      fetchCount += 1;
      return new Promise(resolve => { resolveFetch = resolve; });
    },
  });

  const first = loader.load();
  const second = loader.load();
  assert.equal(fetchCount, 1);
  assert.equal(loader.isLoading(), true);
  assert.equal(h.states.loading.hidden, false);

  resolveFetch(inviteResponse({ html: '<div class="friend-select-row"></div>', count: 1 }));
  await Promise.all([first, second]);
  assert.equal(loader.isLoaded(), true);
  assert.equal(h.results.innerHTML, '<div class="friend-select-row"></div>');

  await loader.load();
  assert.equal(fetchCount, 1);
});

test('invite loader exposes empty state and supports invalidation', async () => {
  const h = inviteLoaderHarness();
  let fetchCount = 0;
  const loader = h.create({
    async fetchImpl() {
      fetchCount += 1;
      return inviteResponse({ html: '', count: 0 });
    },
  });

  await loader.load();
  assert.equal(h.states.empty.hidden, false);
  loader.invalidate();
  assert.equal(loader.isLoaded(), false);
  assert.equal(h.results.innerHTML, '');
  await loader.load();
  assert.equal(fetchCount, 2);
});

test('invite loader clears stale rows on failure and allows retry', async () => {
  const h = inviteLoaderHarness();
  let fetchCount = 0;
  const loader = h.create({
    async fetchImpl() {
      fetchCount += 1;
      return fetchCount === 1
        ? inviteResponse({ error: 'Nope' }, { ok: false, status: 500 })
        : inviteResponse({ html: '<div>Recovered</div>', count: 1 });
    },
  });

  await assert.rejects(loader.load(), error => error.status === 500);
  assert.equal(h.states.error.hidden, false);
  assert.equal(h.results.innerHTML, '');
  await loader.load();
  assert.equal(h.results.innerHTML, '<div>Recovered</div>');
  assert.equal(fetchCount, 2);
});

test('invite loader ignores a response invalidated during retrieval', async () => {
  const h = inviteLoaderHarness();
  const resolvers = [];
  const loader = h.create({
    fetchImpl() {
      return new Promise(resolve => { resolvers.push(resolve); });
    },
  });

  const oldRequest = loader.load();
  loader.invalidate();
  const newRequest = loader.load();
  assert.equal(resolvers.length, 2);

  resolvers[0](inviteResponse({ html: '<div>Stale</div>', count: 1 }));
  const staleResult = await oldRequest;
  assert.equal(staleResult.loaded, false);
  assert.equal(staleResult.stale, true);
  assert.equal(h.results.innerHTML, '');
  assert.equal(loader.isLoading(), true);

  resolvers[1](inviteResponse({ html: '<div>Current</div>', count: 1 }));
  await newRequest;
  assert.equal(h.results.innerHTML, '<div>Current</div>');
  assert.equal(loader.isLoaded(), true);
  assert.equal(loader.isLoading(), false);
});

test('modal focuses search on open and never from late loader completion', () => {
  const template = fs.readFileSync('templates/trip_detail.html', 'utf8');
  const openHandler = template.slice(
    template.indexOf('window.openInviteModal = function'),
    template.indexOf('window.closeInviteModal = function')
  );
  const onLoaded = template.slice(
    template.indexOf('onLoaded: function()'),
    template.indexOf('});', template.indexOf('onLoaded: function()'))
  );
  assert.match(openHandler, /search\.focus\(\)/);
  assert.doesNotMatch(onLoaded, /\.focus\(/);
});