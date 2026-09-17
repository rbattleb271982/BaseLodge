const fs = require('node:fs');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const source = fs.readFileSync('templates/auth.html', 'utf8');
const functionStart = source.indexOf('function switchTab(mode)');
const functionEnd = source.indexOf('// Password visibility toggle', functionStart);
const switchTabSource = source.slice(functionStart, functionEnd);

function createElement(id, classes = []) {
  return {
    id,
    attributes: new Map(),
    classList: {
      values: new Set(classes),
      add(value) { this.values.add(value); },
      remove(value) { this.values.delete(value); },
      contains(value) { return this.values.has(value); },
    },
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    getAttribute(name) { return this.attributes.get(name); },
    focus() { this.ownerDocument.activeElement = this; },
  };
}

function createHarness() {
  const document = {
    activeElement: null,
    getElementById(id) { return elements[id] || null; },
  };
  const elements = {
    'form-login': createElement('form-login'),
    'form-signup': createElement('form-signup', ['hidden']),
    'forgot-wrap': createElement('forgot-wrap'),
    'tab-login': createElement('tab-login', ['active']),
    'tab-signup': createElement('tab-signup'),
  };
  Object.values(elements).forEach((element) => { element.ownerDocument = document; });
  elements['tab-login'].setAttribute('aria-pressed', 'true');
  elements['tab-signup'].setAttribute('aria-pressed', 'false');

  const context = { document };
  vm.runInNewContext(switchTabSource, context);
  return { context, document, elements };
}

test('auth mode controls are named native buttons with exposed initial state', () => {
  assert.match(
    source,
    /<button type="button" class="auth-tab active" id="tab-login"\s+aria-pressed="true" onclick="switchTab\('login'\)">Log in<\/button>/,
  );
  assert.match(
    source,
    /<button type="button" class="auth-tab" id="tab-signup"\s+aria-pressed="false" onclick="switchTab\('signup'\)">Create account<\/button>/,
  );
  assert.match(source, /\.auth-tab:focus-visible\s*\{/);
  assert.doesNotMatch(source, /<div class="auth-tab(?:\s|")/);
});

test('native controls retain browser keyboard activation without custom key handlers', () => {
  assert.doesNotMatch(switchTabSource, /keydown|keyup|keypress|preventDefault/);
  assert.match(source, /<button type="button" class="auth-tab/);
});

test('switching to signup synchronizes visibility and programmatic state', () => {
  const { context, elements } = createHarness();
  context.switchTab('signup');

  assert.equal(elements['form-signup'].classList.contains('hidden'), false);
  assert.equal(elements['form-login'].classList.contains('hidden'), true);
  assert.equal(elements['forgot-wrap'].classList.contains('hidden'), true);
  assert.equal(elements['tab-signup'].classList.contains('active'), true);
  assert.equal(elements['tab-login'].classList.contains('active'), false);
  assert.equal(elements['tab-signup'].getAttribute('aria-pressed'), 'true');
  assert.equal(elements['tab-login'].getAttribute('aria-pressed'), 'false');
});

test('switching back to login synchronizes visibility and programmatic state', () => {
  const { context, elements } = createHarness();
  context.switchTab('signup');
  context.switchTab('login');

  assert.equal(elements['form-login'].classList.contains('hidden'), false);
  assert.equal(elements['form-signup'].classList.contains('hidden'), true);
  assert.equal(elements['forgot-wrap'].classList.contains('hidden'), false);
  assert.equal(elements['tab-login'].getAttribute('aria-pressed'), 'true');
  assert.equal(elements['tab-signup'].getAttribute('aria-pressed'), 'false');
});

test('mode switching does not move focus away from the activated control', () => {
  const { context, document, elements } = createHarness();
  elements['tab-signup'].focus();
  context.switchTab('signup');

  assert.equal(document.activeElement, elements['tab-signup']);
  assert.doesNotMatch(switchTabSource, /\.focus\s*\(/);
});

test('initial server-selected signup mode uses the same synchronized switch', () => {
  assert.match(
    source,
    /if \(formType === 'signup' \|\| \(formType === '' && defaultTab === 'signup'\)\) \{\s+switchTab\('signup'\);/,
  );
});