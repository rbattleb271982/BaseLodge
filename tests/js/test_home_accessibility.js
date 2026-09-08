const fs = require('node:fs');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const source = fs.readFileSync('templates/home.html', 'utf8');
const start = source.indexOf('var _availSheetTrigger = null;');
const end = source.indexOf('function showAllInvites()', start);
const availabilitySource = source.slice(start, end);

function createElement(id) {
  return {
    id,
    hidden: id !== 'availability-sheet-trigger',
    inert: id === 'availSheet',
    attributes: new Map(),
    classList: {
      values: new Set(),
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
  let nextFrameId = 1;
  const frames = new Map();
  const document = {
    activeElement: null,
    listeners: new Map(),
    addEventListener(type, handler) { this.listeners.set(type, handler); },
    removeEventListener(type, handler) {
      if (this.listeners.get(type) === handler) this.listeners.delete(type);
    },
    getElementById(id) { return elements[id] || null; },
  };
  const elements = {
    availSheetBackdrop: createElement('availSheetBackdrop'),
    availSheet: createElement('availSheet'),
    'availability-sheet-trigger': createElement('availability-sheet-trigger'),
    close: createElement('close'),
    cta: createElement('cta'),
  };
  Object.values(elements).forEach((element) => { element.ownerDocument = document; });
  elements.availSheet.querySelectorAll = () => [elements.close, elements.cta];
  elements.availSheet.contains = (element) => (
    element === elements.availSheet ||
    element === elements.close ||
    element === elements.cta
  );
  elements['availability-sheet-trigger'].setAttribute('aria-expanded', 'false');
  elements.availSheet.setAttribute('aria-hidden', 'true');

  const context = {
    Array,
    document,
    requestAnimationFrame(callback) {
      const id = nextFrameId++;
      frames.set(id, callback);
      return id;
    },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout(callback) { callback(); return 1; },
    clearTimeout() {},
  };
  vm.runInNewContext(availabilitySource, context);
  return {
    context,
    document,
    elements,
    flushAnimationFrame() {
      const pending = Array.from(frames.entries());
      frames.clear();
      pending.forEach(([, callback]) => callback());
    },
  };
}

function keyEvent(key, shiftKey = false) {
  return {
    key,
    shiftKey,
    prevented: false,
    preventDefault() { this.prevented = true; },
  };
}

test('availability sheet opens with focus and exposed trigger state', () => {
  const { context, document, elements, flushAnimationFrame } = createHarness();

  context.openAvailSheet(elements['availability-sheet-trigger']);
  flushAnimationFrame();

  assert.equal(elements.availSheet.hidden, false);
  assert.equal(elements.availSheet.inert, false);
  assert.equal(elements.availSheet.getAttribute('aria-hidden'), 'false');
  assert.equal(
    elements['availability-sheet-trigger'].getAttribute('aria-expanded'),
    'true',
  );
  assert.equal(document.activeElement, elements.close);
  assert.equal(document.listeners.get('keydown'), context.handleAvailSheetKeydown);
});

test('availability sheet traps forward and reverse tab focus', () => {
  const { context, document, elements, flushAnimationFrame } = createHarness();
  context.openAvailSheet(elements['availability-sheet-trigger']);
  flushAnimationFrame();
  const handler = document.listeners.get('keydown');

  elements.cta.focus();
  const forward = keyEvent('Tab');
  handler(forward);
  assert.equal(forward.prevented, true);
  assert.equal(document.activeElement, elements.close);

  const reverse = keyEvent('Tab', true);
  handler(reverse);
  assert.equal(reverse.prevented, true);
  assert.equal(document.activeElement, elements.cta);
});

test('Escape closes the sheet and restores trigger focus', () => {
  const { context, document, elements, flushAnimationFrame } = createHarness();
  context.openAvailSheet(elements['availability-sheet-trigger']);
  flushAnimationFrame();

  const escape = keyEvent('Escape');
  document.listeners.get('keydown')(escape);

  assert.equal(escape.prevented, true);
  assert.equal(elements.availSheet.hidden, true);
  assert.equal(elements.availSheet.inert, true);
  assert.equal(elements.availSheet.getAttribute('aria-hidden'), 'true');
  assert.equal(
    elements['availability-sheet-trigger'].getAttribute('aria-expanded'),
    'false',
  );
  assert.equal(document.activeElement, elements['availability-sheet-trigger']);
  assert.equal(document.listeners.has('keydown'), false);
});

test('backdrop-style close uses the same hidden lifecycle', () => {
  const { context, document, elements, flushAnimationFrame } = createHarness();
  context.openAvailSheet(elements['availability-sheet-trigger']);
  flushAnimationFrame();

  context.closeAvailSheet();

  assert.equal(elements.availSheet.hidden, true);
  assert.equal(elements.availSheetBackdrop.hidden, true);
  assert.equal(elements.availSheet.inert, true);
  assert.equal(document.activeElement, elements['availability-sheet-trigger']);
});

test('immediate close cancels stale open frame and preserves trigger focus', () => {
  const { context, document, elements, flushAnimationFrame } = createHarness();
  context.openAvailSheet(elements['availability-sheet-trigger']);

  context.closeAvailSheet();
  flushAnimationFrame();

  assert.equal(elements.availSheet.classList.contains('open'), false);
  assert.equal(elements.availSheetBackdrop.classList.contains('open'), false);
  assert.equal(elements.availSheet.hidden, true);
  assert.equal(elements.availSheet.inert, true);
  assert.equal(elements.availSheet.getAttribute('aria-hidden'), 'true');
  assert.equal(document.activeElement, elements['availability-sheet-trigger']);
});