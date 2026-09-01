(function(window, document) {
    'use strict';

    function normalizeRegions(regions) {
        var values = Array.isArray(regions)
            ? regions
            : String(regions || '').split(',');
        return Array.from(new Set(values.map(function(value) {
            return String(value).trim();
        }).filter(Boolean)));
    }

    function attributeSelector(attribute, region) {
        return '[' + attribute + '="' + window.CSS.escape(region) + '"]';
    }

    function defaultCurrentPage(url) {
        var destination = new URL(url, window.location.href);
        return destination.origin === window.location.origin
            && destination.pathname === window.location.pathname;
    }

    function create(options) {
        var config = options || {};
        var regionAttribute = config.regionAttribute || 'data-bl-region';
        var formAttribute = config.formAttribute || null;
        var pendingAttribute = config.pendingAttribute || 'data-bl-pending';
        var pendingControlProperty = config.pendingControlProperty || '_blPendingControl';
        var refreshHeaderName = config.refreshHeaderName || 'X-BL-Targeted-Refresh';
        var refreshHeaderValue = config.refreshHeaderValue || 'regions';
        var regionVersions = Object.create(null);

        function beginRefresh(regions) {
            var ticket = {};
            normalizeRegions(regions).forEach(function(region) {
                regionVersions[region] = (regionVersions[region] || 0) + 1;
                ticket[region] = regionVersions[region];
            });
            return ticket;
        }

        function isTicketCurrent(regions, ticket) {
            return normalizeRegions(regions).every(function(region) {
                return ticket[region] === regionVersions[region];
            });
        }

        function navigate(url) {
            window.location.assign(url || window.location.href);
            return { navigated: true };
        }

        async function applyResponse(response, regions, ticket) {
            if (!response.ok) {
                var error = new Error(config.errorMessage || 'Page refresh failed');
                error.status = response.status;
                throw error;
            }
            var isCurrentPage = config.isCurrentPage || defaultCurrentPage;
            if (!isCurrentPage(response.url)) return navigate(response.url);

            var contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('text/html')) return navigate(window.location.href);

            var html = await response.text();
            var parsed = new DOMParser().parseFromString(html, 'text/html');
            var normalized = normalizeRegions(regions);
            var replacements = [];

            normalized.forEach(function(region) {
                if (!replacements) return;
                if (ticket[region] !== regionVersions[region]) return;
                var selector = attributeSelector(regionAttribute, region);
                var current = document.querySelector(selector);
                var incoming = parsed.querySelector(selector);
                if (!current || !incoming) {
                    replacements = null;
                    return;
                }
                replacements.push([current, incoming]);
            });

            if (!replacements) return navigate(window.location.href);

            var scrollX = window.scrollX;
            var scrollY = window.scrollY;
            var isCurrent = function() {
                return isTicketCurrent(normalized, ticket);
            };
            var state = config.beforeReplace
                ? config.beforeReplace({ regions: normalized, parsed: parsed })
                : null;
            replacements.forEach(function(pair) {
                pair[0].replaceWith(pair[1]);
            });
            if (config.afterReplace) {
                await config.afterReplace({
                    regions: normalized,
                    parsed: parsed,
                    state: state,
                    isCurrent: isCurrent
                });
            }
            if (config.preserveScroll !== false && isCurrent()) {
                window.scrollTo(scrollX, scrollY);
            }
            return { navigated: false };
        }

        async function refresh(regions) {
            var normalized = normalizeRegions(regions);
            var ticket = beginRefresh(normalized);
            var headers = {};
            headers[refreshHeaderName] = refreshHeaderValue;
            var response = await fetch(
                config.getRefreshUrl
                    ? config.getRefreshUrl()
                    : window.location.pathname + window.location.search,
                {
                    method: 'GET',
                    headers: headers,
                    cache: 'no-store',
                    credentials: 'same-origin'
                }
            );
            return applyResponse(response, normalized, ticket);
        }

        function reportError(error) {
            if (config.onError) {
                config.onError(error);
                return;
            }
            if (window.blToast) {
                window.blToast(
                    error && error.status === 429
                        ? 'Too many requests. Please try again later.'
                        : 'Something went wrong. Please try again.'
                );
            }
        }

        if (formAttribute) {
            document.addEventListener('submit', async function(event) {
                var form = event.target.closest('form[' + formAttribute + ']');
                if (!form) return;
                event.preventDefault();
                if (form.getAttribute(pendingAttribute) === 'true') return;

                var regions = normalizeRegions(form.getAttribute(formAttribute));
                var ticket = beginRefresh(regions);
                var submitter = event.submitter || form[pendingControlProperty] || null;
                var originalText = submitter ? submitter.textContent : '';
                form.setAttribute(pendingAttribute, 'true');
                if (submitter) {
                    submitter.disabled = true;
                    if (submitter.dataset.loadingText) {
                        submitter.textContent = submitter.dataset.loadingText;
                    }
                }

                try {
                    var headers = {};
                    headers[refreshHeaderName] = refreshHeaderValue;
                    var response = await fetch(form.action, {
                        method: (form.method || 'POST').toUpperCase(),
                        body: new FormData(form),
                        credentials: 'same-origin',
                        headers: headers
                    });
                    var contentType = response.headers.get('content-type') || '';
                    if (response.ok && contentType.includes('application/json')) {
                        var data = await response.json();
                        if (!data.success) {
                            throw new Error(data.error || config.errorMessage);
                        }
                        await refresh(regions);
                        if (data.message && window.blToast) {
                            window.blToast(data.message);
                        }
                    } else {
                        await applyResponse(response, regions, ticket);
                    }
                } catch (error) {
                    reportError(error);
                } finally {
                    if (form.isConnected) {
                        form.removeAttribute(pendingAttribute);
                        form[pendingControlProperty] = null;
                    }
                    if (submitter && submitter.isConnected) {
                        submitter.disabled = false;
                        submitter.textContent = originalText;
                    }
                }
            });
        }

        return {
            applyResponse: applyResponse,
            beginRefresh: beginRefresh,
            normalizeRegions: normalizeRegions,
            refresh: refresh,
            reportError: reportError
        };
    }

    window.BLTargetedRefresh = { create: create };
}(window, document));