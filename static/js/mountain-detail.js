(function(window, document) {
    'use strict';

    var region = document.getElementById('md-social-region');
    if (!region) return;

    var socialUrl = region.getAttribute('data-social-url');
    if (!socialUrl) return;

    var generation = 0;
    var pending = null;

    function showLoading() {
        region.hidden = false;
        region.setAttribute('aria-busy', 'true');
        region.innerHTML = '<p class="md-social-loading">Loading mountain community…</p>';
    }

    function showFailure() {
        region.hidden = false;
        region.setAttribute('aria-busy', 'false');
        region.innerHTML = (
            '<div class="md-social-load-failure">' +
                '<span>Social details couldn’t load. </span>' +
                '<button type="button" class="md-social-retry">Try again.</button>' +
            '</div>'
        );
        var retry = region.querySelector('.md-social-retry');
        if (retry) {
            retry.addEventListener('click', function() {
                loadSocial(true);
            });
        }
    }

    function isValidPayload(payload) {
        if (
            !payload
            || typeof payload !== 'object'
            || typeof payload.has_content !== 'boolean'
            || typeof payload.html !== 'string'
        ) {
            return false;
        }
        return payload.has_content
            ? payload.html.trim().length > 0
            : payload.html === '';
    }

    function loadSocial(force) {
        if (pending && !force) return pending;

        var requestGeneration = ++generation;
        showLoading();
        pending = window.fetch(socialUrl, {
            method: 'GET',
            credentials: 'same-origin',
            cache: 'no-store',
            headers: {
                'Accept': 'application/json'
            }
        }).then(function(response) {
            if (!response.ok || response.redirected) {
                throw new Error('Social request failed');
            }
            var contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                throw new Error('Unexpected social response');
            }
            return response.json();
        }).then(function(payload) {
            if (requestGeneration !== generation) return;
            if (!isValidPayload(payload)) {
                throw new Error('Invalid social response');
            }
            region.setAttribute('aria-busy', 'false');
            if (!payload.has_content) {
                region.innerHTML = '';
                region.hidden = true;
                return;
            }
            region.hidden = false;
            region.innerHTML = payload.html;
        }).catch(function() {
            if (requestGeneration === generation) {
                showFailure();
            }
        }).finally(function() {
            if (requestGeneration === generation) {
                pending = null;
            }
        });
        return pending;
    }

    window.BLLoadMountainSocial = loadSocial;
    var captureControl = window.__BASELODGE_CAPTURE_MOUNTAIN_SOCIAL__;
    if (captureControl === 'loading') {
        showLoading();
        return;
    }
    if (captureControl === 'error') {
        showFailure();
        return;
    }
    loadSocial();
})(window, document);