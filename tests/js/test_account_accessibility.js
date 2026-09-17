const fs = require('node:fs');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const source = fs.readFileSync('templates/account.html', 'utf8');
const script = source.slice(source.indexOf('(function(){'), source.lastIndexOf('</script>'));

function element(id, type = '') {
  return {
    id, hidden: false, disabled: false, textContent: '', value: '',
    attributes: new Map(type ? [['type', type]] : []),
    listeners: new Map(),
    classList: {
      values: new Set(),
      add(value) { this.values.add(value); },
      remove(value) { this.values.delete(value); },
      contains(value) { return this.values.has(value); },
    },
    addEventListener(name, fn) { this.listeners.set(name, fn); },
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; },
    hasAttribute(name) { return this.attributes.has(name); },
    removeAttribute(name) { this.attributes.delete(name); },
    getClientRects() { return this.hidden ? [] : [{}]; },
    focus() { this.ownerDocument.activeElement = this; },
  };
}

function harness(withPassword = true) {
  const nodes = {
    modal: element('account-modal'), open: element('account-open', 'button'),
    cancel: element('account-cancel', 'button'), email: element('delete-confirm-email', 'email'),
    csrf: element('csrf', 'hidden'), password: element('delete-current-password', 'password'),
    submit: element('delete-confirm-btn', 'submit'), form: element('delete-account-form'),
    background: element('background'),
  };
  nodes.email.dataset = { expected: 'skier@example.com' };
  nodes.modal.setAttribute('aria-hidden', 'true');
  nodes.form.checkValidity = () => true;
  nodes.form.removeAttribute = nodes.form.removeAttribute.bind(nodes.form);
  const controls = [nodes.csrf, nodes.email];
  if (withPassword) controls.push(nodes.password);
  controls.push(nodes.submit, nodes.cancel);
  nodes.modal.querySelectorAll = () => controls;
  nodes.modal.contains = (node) => controls.includes(node) || node === nodes.modal;
  const parent = { children: [nodes.background, nodes.modal] };
  nodes.modal.parentNode = parent;
  const document = {
    activeElement: null, body: { style: {} }, listeners: new Map(),
    getElementById(id) {
      return Object.values(nodes).find((node) => node.id === id) || null;
    },
    addEventListener(name, fn) { this.listeners.set(name, fn); },
  };
  Object.values(nodes).forEach((node) => { node.ownerDocument = document; });
  let popstate;
  const history = { pushes: 0, backs: 0, pushState() { this.pushes += 1; }, back() { this.backs += 1; } };
  const window = {
    history,
    location: { href: 'https://example.test/account' },
    requestAnimationFrame(fn) { fn(); },
    addEventListener(name, fn) { if (name === 'popstate') popstate = fn; },
  };
  vm.runInNewContext(script, { document, window, Array });
  return { nodes, document, history, popstate: () => popstate() };
}

function event(extra = {}) {
  return { prevented: false, preventDefault() { this.prevented = true; }, ...extra };
}

test('dialog has a stable accessible name and destructive description', () => {
  assert.match(source, /role="dialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description"/);
  assert.match(source, /id="delete-title">Delete account\?<\/h2>/);
  assert.match(source, /id="delete-description"/);
  assert.match(source, /type="hidden" name="csrf_token"/);
});

test('opening isolates background and focuses safe Cancel control', () => {
  const { nodes, document } = harness();
  nodes.open.listeners.get('click')({ currentTarget: nodes.open });
  assert.equal(document.activeElement, nodes.cancel);
  assert.equal(nodes.modal.getAttribute('aria-hidden'), 'false');
  assert.equal(nodes.background.hasAttribute('inert'), true);
  assert.equal(nodes.background.getAttribute('aria-hidden'), 'true');
});

test('focus trap skips hidden CSRF and cycles through conditional password', () => {
  const { nodes, document } = harness(true);
  nodes.open.listeners.get('click')({ currentTarget: nodes.open });
  const keydown = document.listeners.get('keydown');
  nodes.cancel.focus();
  const forward = event({ key: 'Tab', shiftKey: false });
  keydown(forward);
  assert.equal(forward.prevented, true);
  assert.equal(document.activeElement, nodes.email);
  nodes.email.focus();
  const reverse = event({ key: 'Tab', shiftKey: true });
  keydown(reverse);
  assert.equal(document.activeElement, nodes.cancel);
  nodes.password.focus();
  assert.equal(document.activeElement, nodes.password);
});

test('Escape, Cancel, backdrop, and history close restore opener and background', () => {
  for (const mode of ['escape', 'cancel', 'backdrop', 'history']) {
    const h = harness();
    h.nodes.open.listeners.get('click')({ currentTarget: h.nodes.open });
    if (mode === 'escape') h.document.listeners.get('keydown')(event({ key: 'Escape' }));
    if (mode === 'cancel') h.nodes.cancel.listeners.get('click')();
    if (mode === 'backdrop') h.nodes.modal.listeners.get('click')({ target: h.nodes.modal });
    if (mode === 'history') h.popstate();
    assert.equal(h.document.activeElement, h.nodes.open);
    assert.equal(h.nodes.background.hasAttribute('inert'), false);
    assert.equal(h.nodes.modal.getAttribute('aria-hidden'), 'true');
  }
});

test('first valid submission exposes loading state and blocks duplicates', () => {
  const { nodes } = harness();
  nodes.email.value = 'skier@example.com';
  nodes.email.listeners.get('input')();
  const submit = nodes.form.listeners.get('submit');
  const first = event();
  submit(first);
  assert.equal(first.prevented, false);
  assert.equal(nodes.form.getAttribute('aria-busy'), 'true');
  assert.equal(nodes.submit.disabled, true);
  assert.equal(nodes.submit.textContent, 'Deleting account…');
  const duplicate = event();
  submit(duplicate);
  assert.equal(duplicate.prevented, true);
});