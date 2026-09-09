const test = require('node:test');
const assert = require('node:assert/strict');
const ots = require('../../static/js/open-to-ski-export.js');

function canvas(width = 1080, height = 1350, blob = { size: 20, type: 'image/png' }) {
  return { width, height, toBlob(callback, mime) { assert.equal(mime, 'image/png'); callback(blob); } };
}

function harness(overrides = {}) {
  const events = [];
  const revoked = [];
  const anchor = { click() {}, remove() {}, hidden: false };
  const status = { textContent: '', setAttribute() {} };
  const button = { disabled: false, setAttribute() {} };
  const document = {
    fonts: { ready: Promise.resolve() },
    body: { appendChild() {} },
    createElement(tag) {
      if (tag === 'a') return anchor;
      return {
        style: {},
        setAttribute() {},
        appendChild(child) { this.child = child; },
        remove() {},
      };
    }
  };
  const base = {
    document,
    navigator: {},
    URL: { createObjectURL() { return 'blob:test'; }, revokeObjectURL(url) { revoked.push(url); } },
    File: class File { constructor(parts, name, options) { this.parts = parts; this.name = name; this.type = options.type; } },
    html2canvas: async () => canvas(),
    track(name, properties) { events.push([name, properties]); },
    card: {
      offsetWidth: 540,
      offsetHeight: 675,
      cloneNode() { return { style: {} }; }
    },
    status,
    buttons: [button]
  };
  return { options: Object.assign(base, overrides), events, revoked, status, button };
}

test('requires exact dimensions and a non-empty PNG Blob', async () => {
  await assert.rejects(ots.canvasToPngBlob(canvas(1079)), /wrong_dimensions/);
  await assert.rejects(ots.canvasToPngBlob(canvas(1080, 1350, null)), /null_blob/);
  await assert.rejects(ots.canvasToPngBlob(canvas(1080, 1350, { size: 0, type: 'image/png' })), /empty_blob/);
  await assert.rejects(ots.canvasToPngBlob(canvas(1080, 1350, { size: 2, type: 'image/jpeg' })), /wrong_mime/);
  assert.equal((await ots.canvasToPngBlob(canvas())).type, 'image/png');
});

test('download uses safe filename, Blob URL, and immediate cleanup', async () => {
  const h = harness();
  assert.equal(await ots.createController(h.options).deliver('download'), true);
  await new Promise(resolve => setTimeout(resolve, 1100));
  assert.equal(h.revoked[0], 'blob:test');
  assert.equal(h.status.textContent, 'Image downloaded.');
  assert.equal(h.button.disabled, false);
});

test('share passes a PNG File and handles success', async () => {
  const h = harness();
  let payload;
  h.options.navigator = {
    canShare({ files }) { return files[0].type === 'image/png'; },
    share(value) { payload = value; return Promise.resolve(); }
  };
  assert.equal(await ots.createController(h.options).deliver('share'), true);
  assert.equal(payload.files[0].name, 'baselodge-open-to-ski.png');
  assert.equal(payload.files[0].type, 'image/png');
});

test('AbortError is cancellation, not failure', async () => {
  const h = harness();
  h.options.navigator = {
    canShare() { return true; },
    share() { return Promise.reject(Object.assign(new Error('cancel'), { name: 'AbortError' })); }
  };
  assert.equal(await ots.createController(h.options).deliver('share'), false);
  assert.match(h.status.textContent, /cancelled/i);
  assert.ok(h.events.some(([name]) => name === 'availability_share_cancelled'));
  assert.ok(!h.events.some(([name]) => name === 'availability_share_failed'));
});

test('duplicate activation is ignored and busy state resets after failure', async () => {
  let resolveCapture;
  const h = harness({ html2canvas: () => new Promise(resolve => { resolveCapture = resolve; }) });
  const controller = ots.createController(h.options);
  const first = controller.deliver('download');
  assert.equal(controller.isBusy(), true);
  assert.equal(await controller.deliver('download'), false);
  while (!resolveCapture) await new Promise(resolve => setImmediate(resolve));
  resolveCapture(canvas(12, 12));
  assert.equal(await first, false);
  assert.equal(controller.isBusy(), false);
  assert.equal(h.button.disabled, false);
});

test('capture waits for fonts and renders an explicit 1080 by 1350 clone', async () => {
  let fontsResolve;
  let captureOptions;
  const h = harness({
    document: Object.assign(harness().options.document, {
      fonts: { ready: new Promise(resolve => { fontsResolve = resolve; }) }
    }),
    html2canvas: async (_, options) => { captureOptions = options; return canvas(); }
  });
  const pending = ots.createController(h.options).deliver('download');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(captureOptions, undefined);
  fontsResolve();
  await pending;
  assert.equal(captureOptions.width, 1080);
  assert.equal(captureOptions.height, 1350);
  assert.equal(captureOptions.scale, 1);
});

test('canShare exceptions safely fall back to download', async () => {
  const h = harness();
  h.options.navigator = {
    canShare() { throw new Error('unsupported'); },
    share() { throw new Error('must not run'); }
  };
  assert.equal(await ots.createController(h.options).deliver('share'), true);
  assert.equal(h.status.textContent, 'Image downloaded.');
});

test('analytics uses an explicit property allowlist', () => {
  const calls = [];
  ots.analytics((name, properties) => calls.push([name, properties]), 'availability_share_failed', {
    format: 'png', delivery: 'share', error_code: 'share_failed',
    first_name: 'Private', selected_dates: ['2027-01-01'], user_id: 7
  });
  assert.deepEqual(calls[0], ['availability_share_failed', {
    format: 'png', delivery: 'share', error_code: 'share_failed'
  }]);
});

test('source contains no base64 or data URL fallback', () => {
  const source = require('node:fs').readFileSync(require.resolve('../../static/js/open-to-ski-export.js'), 'utf8');
  assert.ok(!source.includes('toDataURL'));
  assert.ok(!source.includes('data:image'));
});