const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..', '..');
const template = fs.readFileSync(
  path.join(root, 'templates', 'friends.html'),
  'utf8',
);
const region = fs.readFileSync(
  path.join(root, 'templates', 'partials', 'friends_directory_region.html'),
  'utf8',
);

test('directory paging uses an explicit monotonic request generation', () => {
  assert.match(template, /var _frDirectoryGeneration = 0;/);
  assert.match(template, /_frDirectoryGeneration \+= 1;/);
  assert.match(
    template,
    /if \(generation !== _frDirectoryGeneration\) return false;/,
  );
  assert.match(template, /_frStartDirectoryGeneration\(\);/);
});

test('search resets paging before its debounced server request', () => {
  const search = template.slice(
    template.indexOf('function searchFriends'),
    template.indexOf('// ── Global member search'),
  );
  assert.match(search, /var generation = _frStartDirectoryGeneration\(\);/);
  assert.match(
    search,
    /_frFetchDirectory\(true, 'search', generation\)/,
  );
});

test('incremental loads share one guarded path for observer and button', () => {
  assert.match(template, /var _frDirectoryInFlight = false;/);
  assert.match(
    template,
    /generation !== _frDirectoryGeneration \|\| _frDirectoryInFlight/,
  );
  assert.match(template, /function _frLoadNext\(source\)/);
  assert.match(template, /_frLoadNext\('automatic'\)/);
  assert.match(template, /_frLoadNext\('manual'\)/);
});

test('observer is progressive enhancement with a manual fallback', () => {
  assert.match(region, /id="fr-load-more"/);
  assert.match(region, /id="fr-directory-sentinel"/);
  assert.match(template, /!\('IntersectionObserver' in window\)/);
  assert.match(template, /rootMargin: '0px 0px 320px 0px'/);
});

test('friend IDs remain a second deduplication layer', () => {
  assert.match(template, /var existingIds = new Set/);
  assert.match(template, /existingIds\.has\(id\)/);
  assert.match(template, /existingIds\.add\(id\)/);
});

test('automatic loading pauses after failure and manual retry remains available', () => {
  assert.match(template, /_frDirectoryAutoPaused = true;/);
  assert.match(
    template,
    /_frDirectoryAutoPaused && source !== 'manual'/,
  );
  assert.match(template, /button\.textContent = 'Try again';/);
  assert.match(template, /data-retry-reset/);
});

test('final page clears its cursor and exposes an accessible completion state', () => {
  assert.match(region, /role="status"/);
  assert.match(region, /aria-live="polite"/);
  assert.match(template, /button\.setAttribute\('data-cursor', ''\)/);
  assert.match(template, /'All friends loaded\.'/);
});

test('automatic appends do not move keyboard focus', () => {
  assert.match(
    template,
    /if \(!reset && firstAdded && source === 'manual'\)/,
  );
});