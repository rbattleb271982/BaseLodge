/* Open to Ski deterministic PNG capture and delivery. */
(function (root, factory) {
    'use strict';
    var api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.OpenToSkiExport = api;
}(typeof window !== 'undefined' ? window : null, function () {
    'use strict';

    var WIDTH = 1080;
    var HEIGHT = 1350;
    var MIME = 'image/png';
    var FILENAME = 'baselodge-open-to-ski.png';
    var ALLOWED_ANALYTICS = {
        availability_share_opened: [],
        availability_share_generated: ['format'],
        availability_share_started: ['format', 'delivery'],
        availability_share_succeeded: ['format', 'delivery'],
        availability_share_cancelled: ['format', 'delivery'],
        availability_share_failed: ['format', 'delivery', 'error_code']
    };

    function analytics(track, eventName, properties) {
        var allowed = ALLOWED_ANALYTICS[eventName];
        if (!allowed || typeof track !== 'function') return;
        var safe = {};
        allowed.forEach(function (key) {
            if (Object.prototype.hasOwnProperty.call(properties || {}, key)) {
                safe[key] = properties[key];
            }
        });
        track(eventName, safe);
    }

    function waitForFonts(documentObject, timeoutMs) {
        if (!documentObject.fonts || !documentObject.fonts.ready) {
            return Promise.resolve();
        }
        return Promise.race([
            documentObject.fonts.ready,
            new Promise(function (_, reject) {
                setTimeout(function () { reject(new Error('fonts_timeout')); }, timeoutMs);
            })
        ]);
    }

    function canvasToPngBlob(canvas) {
        return new Promise(function (resolve, reject) {
            if (canvas.width !== WIDTH || canvas.height !== HEIGHT) {
                reject(new Error('wrong_dimensions'));
                return;
            }
            canvas.toBlob(function (blob) {
                if (!blob) reject(new Error('null_blob'));
                else if (!blob.size) reject(new Error('empty_blob'));
                else if (blob.type !== MIME) reject(new Error('wrong_mime'));
                else resolve(blob);
            }, MIME);
        });
    }

    function downloadBlob(blob, documentObject, urlApi) {
        var url = urlApi.createObjectURL(blob);
        var anchor = documentObject.createElement('a');
        try {
            anchor.href = url;
            anchor.download = FILENAME;
            anchor.hidden = true;
            documentObject.body.appendChild(anchor);
            anchor.click();
        } finally {
            setTimeout(function () {
                try { anchor.remove(); } finally { urlApi.revokeObjectURL(url); }
            }, 1000);
        }
    }

    function canShareFiles(navigatorObject, file) {
        try {
            return Boolean(
                navigatorObject &&
                typeof navigatorObject.share === 'function' &&
                typeof navigatorObject.canShare === 'function' &&
                navigatorObject.canShare({ files: [file] })
            );
        } catch (_) {
            return false;
        }
    }

    function errorCode(error) {
        var allowed = [
            'fonts_timeout', 'capture_unavailable', 'invalid_source',
            'wrong_dimensions', 'null_blob', 'empty_blob', 'wrong_mime',
            'capture_failed', 'share_failed', 'download_failed'
        ];
        return error && allowed.indexOf(error.message) !== -1
            ? error.message
            : 'capture_failed';
    }

    function createController(options) {
        var busy = false;
        var doc = options.document;
        var nav = options.navigator || {};
        var urlApi = options.URL;
        var track = options.track;
        var card = options.card;
        var status = options.status;
        var buttons = options.buttons || [];

        function setBusy(value) {
            busy = value;
            buttons.forEach(function (button) {
                button.disabled = value;
                button.setAttribute('aria-busy', value ? 'true' : 'false');
            });
        }

        function setStatus(message, assertive) {
            status.textContent = message;
            status.setAttribute('aria-live', assertive ? 'assertive' : 'polite');
        }

        function generate() {
            if (busy) return Promise.reject(new Error('capture_in_progress'));
            setBusy(true);
            setStatus('Preparing image…', false);
            return waitForFonts(doc, 5000).then(function () {
                if (!options.html2canvas) throw new Error('capture_unavailable');
                if (!card.offsetWidth || !card.offsetHeight) {
                    throw new Error('invalid_source');
                }
                var wrapper = doc.createElement('div');
                var source = card.cloneNode(true);
                wrapper.setAttribute('aria-hidden', 'true');
                wrapper.style.cssText = 'position:fixed;left:-12000px;top:0;width:1080px;height:1350px;overflow:hidden;pointer-events:none;';
                source.style.width = WIDTH + 'px';
                source.style.height = HEIGHT + 'px';
                source.style.maxHeight = 'none';
                source.style.boxShadow = 'none';
                wrapper.appendChild(source);
                doc.body.appendChild(wrapper);
                return Promise.resolve().then(function () {
                    return options.html2canvas(source, {
                        scale: 1,
                        width: WIDTH,
                        height: HEIGHT,
                        windowWidth: WIDTH,
                        windowHeight: HEIGHT,
                        useCORS: true,
                        allowTaint: false,
                        backgroundColor: '#fbf7ee',
                        logging: false,
                        scrollX: 0,
                        scrollY: 0
                    });
                }).finally(function () { wrapper.remove(); });
            }).then(canvasToPngBlob).then(function (blob) {
                analytics(track, 'availability_share_generated', { format: 'png' });
                return blob;
            });
        }

        function finish() { setBusy(false); }

        function deliver(delivery) {
            if (busy) return Promise.resolve(false);
            analytics(track, 'availability_share_started', {
                format: 'png', delivery: delivery
            });
            return generate().then(function (blob) {
                var file = null;
                if (delivery === 'share') {
                    try {
                        file = new options.File([blob], FILENAME, { type: MIME });
                    } catch (_) {
                        file = null;
                    }
                }
                if (file && canShareFiles(nav, file)) {
                    return nav.share({ files: [file], title: 'Open to Ski' })
                        .then(function () {
                            analytics(track, 'availability_share_succeeded', {
                                format: 'png', delivery: 'share'
                            });
                            setStatus('Image shared.', false);
                            return true;
                        }).catch(function (error) {
                            if (error && error.name === 'AbortError') {
                                analytics(track, 'availability_share_cancelled', {
                                    format: 'png', delivery: 'share'
                                });
                                setStatus('Share cancelled. Your preview is still ready.', false);
                                return false;
                            }
                            throw new Error('share_failed');
                        });
                }
                delivery = 'download';
                try {
                    downloadBlob(blob, doc, urlApi);
                } catch (_) {
                    throw new Error('download_failed');
                }
                analytics(track, 'availability_share_succeeded', {
                    format: 'png', delivery: 'download'
                });
                setStatus('Image downloaded.', false);
                return true;
            }).catch(function (error) {
                var code = errorCode(error);
                analytics(track, 'availability_share_failed', {
                    format: 'png', delivery: delivery, error_code: code
                });
                setStatus('We could not prepare the image. Please try again.', true);
                return false;
            }).finally(finish);
        }

        analytics(track, 'availability_share_opened', {});
        return {
            deliver: deliver,
            isBusy: function () { return busy; }
        };
    }

    function init(windowObject) {
        var doc = windowObject.document;
        var card = doc.querySelector('.ots-card[data-export-width="1080"][data-export-height="1350"]');
        var share = doc.getElementById('ots-share-image');
        var download = doc.getElementById('ots-download-image');
        var status = doc.getElementById('ots-export-status');
        if (!card || !share || !download || !status) return null;
        var csrf = doc.querySelector('meta[name="csrf-token"]');
        function pageTrack(eventName, properties) {
            if (!csrf || typeof windowObject.fetch !== 'function') return;
            windowObject.fetch('/api/open-to-ski/analytics', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrf.content
                },
                body: JSON.stringify({ event: eventName, properties: properties })
            }).catch(function () { /* Analytics never interrupts export. */ });
        }
        var controller = createController({
            document: doc,
            navigator: windowObject.navigator,
            URL: windowObject.URL,
            File: windowObject.File,
            html2canvas: windowObject.html2canvas,
            track: pageTrack,
            card: card,
            status: status,
            buttons: [share, download]
        });
        share.addEventListener('click', function () { controller.deliver('share'); });
        download.addEventListener('click', function () { controller.deliver('download'); });
        return controller;
    }

    if (typeof window !== 'undefined' && window.document) {
        if (window.document.readyState === 'loading') {
            window.document.addEventListener('DOMContentLoaded', function () { init(window); });
        } else {
            init(window);
        }
    }

    return {
        WIDTH: WIDTH,
        HEIGHT: HEIGHT,
        MIME: MIME,
        FILENAME: FILENAME,
        analytics: analytics,
        waitForFonts: waitForFonts,
        canvasToPngBlob: canvasToPngBlob,
        downloadBlob: downloadBlob,
        canShareFiles: canShareFiles,
        createController: createController,
        init: init
    };
}));