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