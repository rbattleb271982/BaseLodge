(function (root, factory) {
  'use strict';

  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root && root.document && root.location) {
    api.installIntentPrefetch(root.document, root.location);
  }
}(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  var ALLOWED_PATHS = new Set([
    '/home',
    '/my-trips',
    '/friends',
    '/mountains',
    '/profile',
  ]);

  function eligibleDestination(anchor, locationLike) {
    if (!anchor || anchor.hasAttribute('download')) return null;
    if ((anchor.getAttribute('target') || '').toLowerCase() === '_blank') {
      return null;
    }

    var rawHref = (anchor.getAttribute('href') || '').trim();
    if (!rawHref || rawHref.charAt(0) === '#') return null;

    var destination;
    try {
      destination = new URL(rawHref, locationLike.href);
    } catch (_error) {
      return null;
    }

    if (
      (destination.protocol !== 'http:' && destination.protocol !== 'https:')
      || destination.origin !== locationLike.origin
      || destination.hash
      || destination.username
      || destination.password
      || !ALLOWED_PATHS.has(destination.pathname)
      || destination.href === locationLike.href
    ) {
      return null;
    }

    return destination.href;
  }

  function installIntentPrefetch(documentLike, locationLike) {
    var prefetched = new Set();

    function onIntent(event) {
      var target = event.target;
      if (target && target.nodeType === 3) target = target.parentElement;
      var anchor = target && target.closest
        ? target.closest('a[href]')
        : null;
      var destination = eligibleDestination(anchor, locationLike);
      if (!destination || prefetched.has(destination)) return;

      prefetched.add(destination);
      var hint = documentLike.createElement('link');
      hint.rel = 'prefetch';
      hint.href = destination;
      documentLike.head.appendChild(hint);
    }

    documentLike.addEventListener('pointerenter', onIntent, true);
    documentLike.addEventListener('focusin', onIntent, false);
    documentLike.addEventListener('pointerdown', onIntent, false);

    return prefetched;
  }

  return {
    ALLOWED_PATHS: ALLOWED_PATHS,
    eligibleDestination: eligibleDestination,
    installIntentPrefetch: installIntentPrefetch,
  };
}));