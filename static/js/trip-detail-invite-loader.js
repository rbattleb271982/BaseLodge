(function(window) {
    'use strict';

    function create(options) {
        var config = options || {};
        var loaded = false;
        var pending = null;
        var generation = 0;

        function show(name) {
            ['loading', 'empty', 'error'].forEach(function(state) {
                var element = config.getState(state);
                if (element) element.hidden = state !== name;
            });
        }

        async function load() {
            if (loaded) return { loaded: true, cached: true };
            if (pending) return pending;
            var requestGeneration = ++generation;

            var results = config.getResults();
            if (results) {
                results.innerHTML = '';
                results.setAttribute('aria-busy', 'true');
            }
            show('loading');

            var requestPromise = (async function() {
                try {
                    var response = await config.fetchImpl(config.url, {
                        method: 'GET',
                        credentials: 'same-origin',
                        headers: { 'Accept': 'application/json' },
                    });
                    var data = await response.json().catch(function() { return {}; });
                    if (!response.ok || typeof data.html !== 'string') {
                        var error = new Error(data.error || 'Could not load friends.');
                        error.status = response.status;
                        throw error;
                    }
                    if (requestGeneration !== generation) {
                        return { loaded: false, stale: true };
                    }

                    results = config.getResults();
                    if (!results) throw new Error('Invite results are unavailable.');
                    results.innerHTML = data.html;
                    results.removeAttribute('aria-busy');
                    loaded = true;
                    show(Number(data.count) === 0 ? 'empty' : null);
                    if (config.onLoaded) config.onLoaded(data);
                    return { loaded: true, cached: false, count: Number(data.count) || 0 };
                } catch (error) {
                    if (requestGeneration !== generation) {
                        return { loaded: false, stale: true };
                    }
                    results = config.getResults();
                    if (results) {
                        results.innerHTML = '';
                        results.removeAttribute('aria-busy');
                    }
                    loaded = false;
                    show('error');
                    if (config.onError) config.onError(error);
                    throw error;
                } finally {
                    if (pending === requestPromise) pending = null;
                }
            }());
            pending = requestPromise;
            return pending;
        }

        function invalidate() {
            generation += 1;
            loaded = false;
            pending = null;
            var results = config.getResults();
            if (results) {
                results.innerHTML = '';
                results.removeAttribute('aria-busy');
            }
            show(null);
        }

        return {
            invalidate: invalidate,
            isLoaded: function() { return loaded; },
            isLoading: function() { return Boolean(pending); },
            load: load,
        };
    }

    window.TripDetailInviteLoader = { create: create };
}(window));