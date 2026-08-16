/* ── BaseLodge native shell JS ─────────────────────────────────────────────
   Extracted from analytics_head.html so WKWebView can cache this file.
   All server values are read from window.__* globals set by the inline
   config block in analytics_head.html, which runs synchronously before
   this defer script executes.

   Execution order guaranteed by the browser/WKWebView spec:
     1. Inline <script> blocks run during HTML head parsing
        (sets window.__USER__, window.__POSTHOG_KEY__, etc.)
     2. <script defer> files execute after full HTML parsing, in document order
        (analytics.js first, then this file)
     3. DOMContentLoaded fires after all defer scripts have executed

   No Jinja2 syntax in this file — plain static JS, fully cacheable.

   ── Push notification architecture ──────────────────────────────────────
   OneSignal (onesignal-cordova-plugin@5.5.2) is the SOLE owner of iOS and
   Android push notifications. @capacitor/push-notifications is NOT used
   and must not be re-added to this lifecycle.

   OneSignal exclusively owns:
     • notification permission (OS.Notifications.requestPermission)
     • APNs/FCM registration (handled natively by SDK)
     • foreground display (OS.Notifications.addEventListener('foregroundWillDisplay'))
     • tap/click routing (OS.Notifications.addEventListener('click'))
     • badge clearing (OS.Notifications.clearAll)
     • subscription opt-in/out (OS.User.pushSubscription.optIn/optOut)

   Do NOT add competing Capacitor PushNotifications calls anywhere.        */

/* ── Splash screen hide — native Capacitor shell only ───────────────────────
   @capacitor/splash-screen is configured with launchAutoHide:true and
   launchShowDuration:8000, which provides a guaranteed 8-second native
   fallback at the platform level. This fires even if bl-native.js never
   executes (e.g. the remote page at app.baselodgeapp.com fails to load).

   This block provides the early hide path. The key design choice is
   triggering on window.load rather than DOMContentLoaded:

     DOMContentLoaded — HTML is parsed but images/fonts are still loading.
       Hiding here reveals the page before the wordmark image has loaded,
       causing the blank-screen flash (user sees cream background, then
       logo pops in a moment later).

     window.load — ALL resources (images, stylesheets) have finished loading.
       The login-screen wordmark is already painted when the splash fades out,
       creating the seamless "splash → login screen appears immediately" feel.

   After window.load:
     1. Confirm Capacitor bridge is ready (should already be at window.load,
        but a short retry loop handles any edge case).
     2. Two requestAnimationFrame cycles — browser has committed the frame.
     3. SplashScreen.hide({ fadeOutDuration: 300 }).

   The native 8-second auto-hide (launchAutoHide:true) ensures the splash
   never stays up indefinitely if window.load is delayed or never fires.

   Fully isolated from push-notification / OneSignal logic. No-op in
   browsers — gated on window.Capacitor.isNativePlatform().                   */
(function() {
  try {
    // Synchronous native-platform check — exits immediately in browsers.
    // webkit.messageHandlers.capacitor is the WKWebView bridge injection
    // point and is present even before Capacitor fully initializes.
    var _capSp = window.Capacitor;
    var _wkSp  = window.webkit;
    var _isNativeSp = !!(_capSp
      && typeof _capSp.isNativePlatform === 'function'
      && _capSp.isNativePlatform());
    var _hasWkSp = !!(_wkSp
      && _wkSp.messageHandlers
      && _wkSp.messageHandlers.capacitor);
    if (!_isNativeSp && !_hasWkSp) return;
  } catch (_outerE) { return; }

  // _blDoHide: called once window.load has fired (all page resources loaded).
  // Uses an async IIFE so we can await the bridge-ready check and rAF cycles.
  function _blDoHide() {
    (async function() {
      try {
        // Wait for Capacitor bridge (up to 2 s in 100 ms steps).
        // At window.load time the bridge is almost always already ready, but
        // this loop handles any race on slow devices.
        var _spDeadline = Date.now() + 2000;
        while (Date.now() < _spDeadline) {
          if (window.Capacitor
              && typeof window.Capacitor.isNativePlatform === 'function'
              && window.Capacitor.isNativePlatform()) {
            break;
          }
          await new Promise(function(r) { setTimeout(r, 100); });
        }

        var Cap = window.Capacitor;
        if (!Cap || !Cap.isNativePlatform()) return; // not native, bail

        // Two rAF cycles — browser paints the fully-loaded frame before we fade.
        await new Promise(function(r) {
          requestAnimationFrame(function() { requestAnimationFrame(r); });
        });

        // Resolve the SplashScreen plugin.
        var SplashScreen = null;
        if (Cap.Plugins && Cap.Plugins.SplashScreen) {
          SplashScreen = Cap.Plugins.SplashScreen;
        } else if (typeof Cap.registerPlugin === 'function') {
          try { SplashScreen = Cap.registerPlugin('SplashScreen'); } catch (_rpe) {}
        }
        if (!SplashScreen || typeof SplashScreen.hide !== 'function') {
          console.warn('[Splash] plugin unavailable — relying on native auto-hide');
          return;
        }

        SplashScreen.hide({ fadeOutDuration: 300 });
        console.log('[Splash] hide() called after window.load + 2rAF');

      } catch (_innerE) {
        // Swallow all errors — splash logic must never block the app
        console.warn('[Splash] hide error (non-fatal):', _innerE);
      }
    })();
  }

  // Attach to window.load. If the page has somehow already finished loading
  // (readyState === 'complete') before this script runs, fire immediately.
  if (document.readyState === 'complete') {
    _blDoHide();
  } else {
    window.addEventListener('load', _blDoHide, { once: true });
  }
})();

/* ── Form submit loader ──────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
  document.addEventListener('submit', function(e) {
    var form = e.target;
    if (form.tagName !== 'FORM') return;
    var btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (!btn || btn.dataset.noLoader === 'true') return;
    btn.disabled = true;
    if (!btn.dataset.loadingText) return;
    btn._origText = btn.textContent;
    btn.textContent = btn.dataset.loadingText;
  });
});

/* ── Keyboard-safe scroll ────────────────────────────────────────────────── */
/* When an input is focused on mobile, scroll it into view after a short
   delay so the iOS keyboard doesn't cover it. */
document.addEventListener('focusin', function(e) {
  var el = e.target;
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
    setTimeout(function() {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 320);
  }
});

/* ── Push notification lifecycle — OneSignal sole owner ─────────────────────
   OneSignal (onesignal-cordova-plugin@5.5.2 / native SDK 5.5.5) owns the
   entire iOS and Android push lifecycle. @capacitor/push-notifications is
   NOT used; do not re-add it.

   Responsibilities handled here:
     • OS notification permission (OS.Notifications.requestPermission)
     • APNs/FCM registration (SDK handles natively; no registerForRemote call)
     • Foreground display: OS.Notifications.addEventListener('foregroundWillDisplay')
       – shows in-app toast for friend.request.created events
       – passes all other events through to the system banner
     • Tap/click routing: OS.Notifications.addEventListener('click')
       – extracts data.url from notification.additionalData.url
       – deduplicates with _pushNavDone; handles cold-launch replay
     • Permission change observer (diagnostic)
     • Subscription state observer (diagnostic — NEVER auto-calls optIn to fight a state)
     • helpers: blSetPushEnabled, blOSLogout, blOnOSPermReady, blGetOSPermStatus

   APIs verified against onesignal-cordova-plugin@5.5.2 dist/index.d.ts:
     OS.initialize(appId: string): void
     OS.login(externalId: string): void
     OS.logout(): void
     OS.Notifications.requestPermission(fallbackToSettings?: boolean): Promise<boolean>
     OS.Notifications.getPermissionAsync(): Promise<boolean>
     OS.Notifications.addEventListener('foregroundWillDisplay' | 'click' | 'permissionChange', fn)
     OS.Notifications.clearAll(): void
     OS.User.pushSubscription.addEventListener('change', fn)
     OS.User.pushSubscription.optIn(): void
     OS.User.pushSubscription.optOut(): void

   Logging prefix: [OneSignal]
   Subscription diagnostic prefix: [OSSubscription]                           */
(function() {
  'use strict';

  var _osAppId = window.__ONESIGNAL_APP_ID__;
  if (!_osAppId) {
    console.log('[OneSignal] No App ID configured — init skipped');
    return;
  }

  // ── Foreground banner helper ─────────────────────────────────────────────
  // Creates a dismissible slide-down toast at the top of the webview.
  // Tapping it navigates to the provided url. Auto-dismisses after 5 s.
  // Called from the foregroundWillDisplay listener for friend.request.created.
  function _showFgBanner(title, body, url) {
    try {
      var BANNER_ID = 'bl-fg-banner';
      if (document.getElementById(BANNER_ID)) return; // de-dupe

      var banner = document.createElement('div');
      banner.id = BANNER_ID;
      banner.setAttribute('role', 'alert');
      banner.style.cssText = [
        'position:fixed',
        'top:env(safe-area-inset-top,0px)',
        'left:12px',
        'right:12px',
        'z-index:99999',
        'background:#fff',
        'border:1px solid #E5DFD0',
        'border-radius:12px',
        'padding:12px 14px',
        'box-shadow:0 4px 20px rgba(0,0,0,0.13)',
        'display:flex',
        'align-items:center',
        'gap:12px',
        'cursor:pointer',
        'transform:translateY(-120%)',
        'transition:transform 0.3s cubic-bezier(0.34,1.26,0.64,1)',
        'font-family:system-ui,-apple-system,sans-serif',
      ].join(';');

      var icon = document.createElement('div');
      icon.style.cssText = 'width:36px;height:36px;background:#5C1219;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;';
      icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M11 2L4 7V18C4 18.55 4.45 19 5 19H9V14H13V19H17C17.55 19 18 18.55 18 18V7L11 2Z" fill="#F5F1E8"/></svg>';

      var text = document.createElement('div');
      text.style.cssText = 'flex:1;min-width:0;';

      var titleEl = document.createElement('div');
      titleEl.style.cssText = 'font-size:14px;font-weight:600;color:#1A1A1A;margin:0 0 1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
      titleEl.textContent = title;

      var bodyEl = document.createElement('div');
      bodyEl.style.cssText = 'font-size:12px;color:#888;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
      bodyEl.textContent = body;

      var viewEl = document.createElement('div');
      viewEl.style.cssText = 'font-size:13px;font-weight:600;color:#5C1219;flex-shrink:0;';
      viewEl.textContent = 'View';

      text.appendChild(titleEl);
      text.appendChild(bodyEl);
      banner.appendChild(icon);
      banner.appendChild(text);
      banner.appendChild(viewEl);

      function _dismiss() {
        banner.style.transform = 'translateY(-120%)';
        setTimeout(function() {
          if (banner.parentNode) banner.parentNode.removeChild(banner);
        }, 350);
      }

      banner.addEventListener('click', function() {
        _dismiss();
        if (url) window.location.href = url;
      });

      document.body.appendChild(banner);
      // Trigger slide-in on next frame
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          banner.style.transform = 'translateY(12px)';
        });
      });
      // Auto-dismiss after 5 s
      setTimeout(_dismiss, 5000);

    } catch (_be2) {
      console.warn('[OneSignal] _showFgBanner error:', _be2);
    }
  }

  // ── Push URL extractor ───────────────────────────────────────────────────
  // Reads data.url from OneSignal click event payloads.
  // OneSignal SDK 5.x: event.notification.additionalData.url (from server data:{url:...})
  // Fallback:          event.result.url (from OneSignal URL field)
  // Safety: only allows relative paths starting with a single "/".
  function _extractPushUrl(payload) {
    try {
      if (!payload) return null;
      var raw = null;
      var n = payload.notification || payload;
      // OneSignal SDK 5 click event: notification.additionalData.url
      // Capacitor-compat fallback: notification.data.url
      raw = (n.additionalData && n.additionalData.url)
         || (n.data        && n.data.url)
         || (payload.additionalData && payload.additionalData.url)
         || (payload.data        && payload.data.url)
         || null;
      // OneSignal result.url field (separate from data payload)
      if (!raw && payload.result && payload.result.url) {
        raw = payload.result.url;
      }
      if (!raw || typeof raw !== 'string') return null;
      raw = raw.trim();
      // Safety: must be a relative path starting with a single "/"
      if (!raw.startsWith('/') || raw.startsWith('//')) {
        console.log('[PushRoute] invalid url ignored (not relative): ' + raw);
        return null;
      }
      // Block embedded dangerous content
      if (/javascript:/i.test(raw) || /data:/i.test(raw)) {
        console.log('[PushRoute] invalid url ignored (dangerous scheme): ' + raw);
        return null;
      }
      return raw;
    } catch (_ue) {
      console.warn('[PushRoute] url extraction error:', _ue);
      return null;
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    (async function() {

      var userId = window.__USER__ && window.__USER__.id;
      console.log('[OneSignal] DOMContentLoaded userId=' + userId + ' appId=' + _osAppId);

      // ── Gate: native platform only ────────────────────────────────────
      var _cap0 = window.Capacitor;
      var _wk0  = window.webkit;
      var _isNative  = !!(_cap0 && typeof _cap0.isNativePlatform === 'function' && _cap0.isNativePlatform());
      var _hasWk     = !!(_wk0 && _wk0.messageHandlers && _wk0.messageHandlers.capacitor);
      console.log('[OneSignal] native_check is_native=' + _isNative + ' has_webkit=' + _hasWk);

      if (!_isNative && !_hasWk) {
        console.log('[OneSignal] Not in native shell — init skipped');
        return;
      }

      // ── Wait for Capacitor bridge (up to 2 s, 100 ms steps) ──────────
      async function _waitCap(maxMs) {
        var deadline = Date.now() + maxMs;
        while (Date.now() < deadline) {
          if (window.Capacitor && typeof window.Capacitor.isNativePlatform === 'function') {
            return window.Capacitor;
          }
          await new Promise(function(r) { setTimeout(r, 100); });
        }
        return null;
      }

      var Cap = await _waitCap(2000);
      if (!Cap) {
        console.warn('[OneSignal] Capacitor bridge not available after 2 s — init skipped');
        return;
      }
      console.log('[OneSignal] Capacitor bridge ready');

      // ── Locate OneSignal plugin via bridge ────────────────────────────
      // Priority order:
      //   1. window.plugins.OneSignal — Cordova bridge (onesignal-cordova-plugin)
      //      This is the primary path: Cordova plugin registers under window.plugins.
      //   2. Cap.Plugins.OneSignal  — registered Capacitor-native plugin
      //   3. Cap.registerPlugin()   — Capacitor v6+ lazy-registration
      //
      // _osVia tracks the bridge type for argument-shape branching.
      // Cordova bridge: initialize(appId string), login(externalId string)
      // Capacitor native: initialize({ appId }), login({ externalId })
      var OS = null;
      var _osVia = null;
      try {
        if (window.plugins && window.plugins.OneSignal) {
          OS = window.plugins.OneSignal;
          _osVia = 'window.plugins';
          console.log('[OneSignal] plugin found via window.plugins (Cordova bridge)');
        } else if (Cap.Plugins && Cap.Plugins.OneSignal) {
          OS = Cap.Plugins.OneSignal;
          _osVia = 'Cap.Plugins';
          console.log('[OneSignal] plugin found via Cap.Plugins');
        } else if (typeof Cap.registerPlugin === 'function') {
          OS = Cap.registerPlugin('OneSignal');
          _osVia = 'registerPlugin';
          console.log('[OneSignal] plugin obtained via registerPlugin()');
        }
      } catch (_pe) {
        console.warn('[OneSignal] plugin access error:', _pe);
      }
      // Cordova bridge may initialise asynchronously — retry once after brief delay
      if (!OS) {
        await new Promise(function(r) { setTimeout(r, 300); });
        if (window.plugins && window.plugins.OneSignal) {
          OS = window.plugins.OneSignal;
          _osVia = 'window.plugins';
          console.log('[OneSignal] plugin found via window.plugins (delayed)');
        }
      }

      if (!OS) {
        console.warn('[OneSignal] plugin not available — ensure onesignal-cordova-plugin is installed and `npx cap sync` has been run');
        return;
      }

      // ── Bridge introspection ──────────────────────────────────────────
      // Logs which properties exist on the plugin object. Observational only.
      try {
        var _osMethods = [];
        ['initialize','login','logout','requestPermission','setConsentRequired','setConsentGiven'].forEach(function(k) {
          if (typeof OS[k] === 'function') _osMethods.push(k);
        });
        console.log('[OneSignal] bridge=' + _osVia + ' top-level fns:', _osMethods.join(', ') || '(none)');
        console.log('[OneSignal] has Notifications=' + !!(OS.Notifications)
          + ' has User=' + !!(OS.User)
          + ' has User.pushSubscription=' + !!(OS.User && OS.User.pushSubscription));
        if (OS.Notifications) {
          console.log('[OneSignal] Notifications fns: addEventListener=' + (typeof OS.Notifications.addEventListener)
            + ' requestPermission=' + (typeof OS.Notifications.requestPermission)
            + ' getPermissionAsync=' + (typeof OS.Notifications.getPermissionAsync)
            + ' clearAll=' + (typeof OS.Notifications.clearAll));
        }
        if (OS.User && OS.User.pushSubscription) {
          var _sub = OS.User.pushSubscription;
          console.log('[OneSignal] pushSubscription fns: optIn=' + (typeof _sub.optIn)
            + ' optOut=' + (typeof _sub.optOut)
            + ' addEventListener=' + (typeof _sub.addEventListener));
        }
      } catch (_ie) {
        console.warn('[OneSignal] introspection error:', _ie);
      }

      var _isCordovaBridge = (_osVia === 'window.plugins');

      // ── DIAGNOSTIC: Subscription state observer ───────────────────────
      // Fires whenever OneSignal changes the push subscription state.
      // OBSERVATIONAL ONLY — does not call optIn() to fight state changes.
      // This is the primary instrument for diagnosing the enabled/disabled loop.
      try {
        if (OS.User && OS.User.pushSubscription && typeof OS.User.pushSubscription.addEventListener === 'function') {
          OS.User.pushSubscription.addEventListener('change', function(state) {
            try {
              var prev = state && state.previous;
              var curr = state && state.current;
              console.log('[OSSubscription] change event:'
                + ' prev.id=' + (prev && prev.id)
                + ' prev.optedIn=' + (prev && prev.optedIn)
                + ' prev.token=' + (prev && prev.token ? prev.token.slice(0,8) + '…' : 'none')
                + ' curr.id=' + (curr && curr.id)
                + ' curr.optedIn=' + (curr && curr.optedIn)
                + ' curr.token=' + (curr && curr.token ? curr.token.slice(0,8) + '…' : 'none'));
            } catch (_se) {
              console.warn('[OSSubscription] observer error:', _se);
            }
          });
          console.log('[OSSubscription] change observer registered');
        }
      } catch (_soe) {
        console.warn('[OSSubscription] failed to register change observer:', _soe);
      }

      // ── DIAGNOSTIC: Permission change observer ────────────────────────
      // Fires whenever the OS-level notification permission changes.
      try {
        if (OS.Notifications && typeof OS.Notifications.addEventListener === 'function') {
          OS.Notifications.addEventListener('permissionChange', function(granted) {
            console.log('[OSSubscription] permissionChange: granted=' + granted);
          });
          console.log('[OSSubscription] permissionChange observer registered');
        }
      } catch (_pco) {
        console.warn('[OSSubscription] failed to register permissionChange observer:', _pco);
      }

      // ── Foreground notification display ───────────────────────────────
      // Fires when a push arrives while the app is in the foreground.
      // For friend.request.created: show the in-app toast banner.
      // For all other events: let OneSignal display the system banner (no preventDefault).
      // API: OS.Notifications.addEventListener('foregroundWillDisplay', fn)
      try {
        if (OS.Notifications && typeof OS.Notifications.addEventListener === 'function') {
          OS.Notifications.addEventListener('foregroundWillDisplay', function(event) {
            try {
              var n = event && event.notification;
              var _evt   = (n && n.additionalData && n.additionalData.event) || '';
              var _title = (n && n.title)  || '';
              var _body  = (n && n.body)   || '';
              var _url   = (n && n.additionalData && n.additionalData.url) || '';

              console.log('[OneSignal] foregroundWillDisplay event=' + _evt
                + ' title=' + _title.slice(0, 40));

              if (_evt === 'friend.request.created') {
                _showFgBanner(
                  _title || 'New friend request',
                  _body  || 'Someone wants to connect.',
                  _url   || '/friends?requests=1'
                );
              }
              // All other events: OneSignal shows system banner (no action needed here)
            } catch (_fwe) {
              console.warn('[OneSignal] foregroundWillDisplay handler error:', _fwe);
            }
          });
          console.log('[OneSignal] foregroundWillDisplay listener registered');
        } else {
          console.warn('[OneSignal] OS.Notifications.addEventListener not available — foreground display unregistered');
        }
      } catch (_fwde) {
        console.warn('[OneSignal] foregroundWillDisplay registration error:', _fwde);
      }

      // ── Notification tap / click routing ─────────────────────────────
      // Fires when the user taps a notification (warm-start, background, OR
      // cold-launch — the SDK replays stored clicks on listener registration).
      // Extracts data.url from notification.additionalData.url and navigates.
      // _pushNavDone prevents double-navigation if cold-launch replay and
      // live listener both fire for the same tap.
      // API: OS.Notifications.addEventListener('click', fn)
      var _pushNavDone = false;

      function _doNavFromPush(payload, source) {
        if (_pushNavDone) {
          console.log('[PushRoute] duplicate nav suppressed from ' + source);
          return;
        }
        var url = _extractPushUrl(payload);
        if (url) {
          _pushNavDone = true;
          console.log('[PushRoute] navigating to ' + url + ' (source=' + source + ')');
          window.location.href = url;
        }
      }

      try {
        if (OS.Notifications && typeof OS.Notifications.addEventListener === 'function') {
          OS.Notifications.addEventListener('click', function(event) {
            console.log('[PushRoute] click event received (source=OS.Notifications.click)');
            _doNavFromPush(event, 'OS.Notifications.click');
          });
          console.log('[OneSignal] click listener registered (covers warm + cold launch)');
        } else {
          console.warn('[OneSignal] OS.Notifications.addEventListener not available — click listener not registered');
        }
      } catch (_cle) {
        console.warn('[OneSignal] click listener registration error:', _cle);
      }

      // ── Cold-launch belt-and-suspenders ──────────────────────────────
      // OS.Notifications click listener replays stored taps on registration,
      // so cold-launch is covered above. getLaunchNotification() is an
      // additional safety net for edge cases where the replay does not fire.
      // Only runs if not already handled by the click listener above.
      try {
        var _launchNotif = null;
        if (typeof OS.getLaunchNotification === 'function') {
          _launchNotif = await OS.getLaunchNotification();
          console.log('[PushRoute] getLaunchNotification:', _launchNotif ? 'found' : 'null');
        } else if (typeof OS.getInitialNotification === 'function') {
          _launchNotif = await OS.getInitialNotification();
          console.log('[PushRoute] getInitialNotification:', _launchNotif ? 'found' : 'null');
        }
        if (_launchNotif) {
          _doNavFromPush(_launchNotif, 'getLaunchNotification');
        }
      } catch (_cl) {
        console.warn('[PushRoute] cold-launch check error:', _cl);
      }

      // ── Initialize ────────────────────────────────────────────────────
      // Cordova bridge: initialize(appId: string)
      // Capacitor native: initialize({ appId: string })
      // Must run AFTER listener registration so foreground and click events
      // registered above are not missed during the init async handshake.
      // NOTE: listeners are registered before init intentionally — SDK
      // queues events until JS listeners are attached.
      try {
        if (typeof OS.initialize === 'function') {
          if (_isCordovaBridge) {
            console.log('[OneSignal] calling initialize(appId) — Cordova string, appId=' + _osAppId);
            await OS.initialize(_osAppId);
          } else {
            console.log('[OneSignal] calling initialize({ appId }) — Capacitor object');
            await OS.initialize({ appId: _osAppId });
          }
          console.log('[OneSignal] initialize() complete');
        } else if (typeof OS.setAppId === 'function') {
          // SDK 4.x fallback
          if (_isCordovaBridge) {
            await OS.setAppId(_osAppId);
          } else {
            await OS.setAppId({ appId: _osAppId });
          }
          console.log('[OneSignal] setAppId() complete (SDK 4.x fallback)');
        } else {
          console.warn('[OneSignal] no initialize / setAppId method — unknown SDK version, aborting');
          return;
        }
      } catch (_initErr) {
        console.warn('[OneSignal] initialization error:', _initErr);
        return;
      }

      // ── DIAGNOSTIC: Log subscription state after initialize ───────────
      try {
        if (OS.User && OS.User.pushSubscription) {
          var _subAfterInit = OS.User.pushSubscription;
          console.log('[OSSubscription] after initialize:'
            + ' id=' + (_subAfterInit.id || 'none')
            + ' token=' + (_subAfterInit.token ? _subAfterInit.token.slice(0,8) + '…' : 'none')
            + ' optedIn=' + _subAfterInit.optedIn);
        }
      } catch (_di) {}

      // ── Associate logged-in user via stable external ID ───────────────
      // Uses BaseLodge integer user ID as string — matches send_onesignal_push targeting.
      // Cordova: login(externalId: string)
      // Capacitor native: login({ externalId: string })
      if (userId) {
        try {
          if (typeof OS.login === 'function') {
            if (_isCordovaBridge) {
              console.log('[OneSignal] calling login(externalId) — Cordova string, id=' + userId);
              await OS.login(String(userId));
            } else {
              console.log('[OneSignal] calling login({ externalId }) — Capacitor object, id=' + userId);
              await OS.login({ externalId: String(userId) });
            }
            console.log('[OneSignal] login() complete');
          } else if (typeof OS.setExternalUserId === 'function') {
            // SDK 4.x fallback
            if (_isCordovaBridge) {
              await OS.setExternalUserId(String(userId));
            } else {
              await OS.setExternalUserId({ externalUserId: String(userId) });
            }
            console.log('[OneSignal] setExternalUserId() complete (SDK 4.x fallback)');
          } else {
            console.log('[OneSignal] no login / setExternalUserId method — user association skipped');
          }
        } catch (_loginErr) {
          console.warn('[OneSignal] user association error:', _loginErr);
        }
      } else {
        console.log('[OneSignal] no authenticated user — login() skipped');
      }

      // ── DIAGNOSTIC: Log subscription state after login ────────────────
      try {
        if (OS.User && OS.User.pushSubscription) {
          var _subAfterLogin = OS.User.pushSubscription;
          console.log('[OSSubscription] after login:'
            + ' id=' + (_subAfterLogin.id || 'none')
            + ' token=' + (_subAfterLogin.token ? _subAfterLogin.token.slice(0,8) + '…' : 'none')
            + ' optedIn=' + _subAfterLogin.optedIn);
        }
      } catch (_dl) {}

      // ── Request push permission ───────────────────────────────────────
      // API: OS.Notifications.requestPermission(fallbackToSettings?: boolean): Promise<boolean>
      // Only prompts if not already determined; OS returns immediately if already granted.
      // Fallback chain covers SDK version differences.
      try {
        var _permResult;
        if (OS.Notifications && typeof OS.Notifications.requestPermission === 'function') {
          console.log('[OneSignal] calling OS.Notifications.requestPermission()');
          _permResult = await OS.Notifications.requestPermission(true);
        } else if (typeof OS.requestPermission === 'function') {
          // Cordova plugin may also expose at root level
          console.log('[OneSignal] calling OS.requestPermission() (root-level)');
          _permResult = await OS.requestPermission(true);
        } else if (typeof OS.requestPermissionAsync === 'function') {
          console.log('[OneSignal] calling OS.requestPermissionAsync()');
          _permResult = await OS.requestPermissionAsync(true);
        } else if (typeof OS.promptForPushNotificationsWithUserResponse === 'function') {
          console.log('[OneSignal] calling promptForPushNotificationsWithUserResponse() (SDK 4.x)');
          _permResult = await OS.promptForPushNotificationsWithUserResponse(true);
        } else {
          console.log('[OneSignal] no permission-request method found — skipping');
        }
        if (_permResult !== undefined) {
          console.log('[OneSignal] requestPermission result:', JSON.stringify(_permResult));
        }
      } catch (_permErr) {
        console.warn('[OneSignal] permission request error:', _permErr);
      }

      // ── DIAGNOSTIC: Log subscription state after permission request ────
      try {
        if (OS.User && OS.User.pushSubscription) {
          var _subAfterPerm = OS.User.pushSubscription;
          console.log('[OSSubscription] after requestPermission:'
            + ' id=' + (_subAfterPerm.id || 'none')
            + ' token=' + (_subAfterPerm.token ? _subAfterPerm.token.slice(0,8) + '…' : 'none')
            + ' optedIn=' + _subAfterPerm.optedIn);
        }
      } catch (_dp) {}

      console.log('[OneSignal] init sequence complete');

      // ── OS permission state — check once after init ───────────────────
      // Resolves to boolean or null. Stored in closure; blOnOSPermReady / blGetOSPermStatus exposed.
      var _blOSPerm  = null;   // { granted: bool | null }
      var _blPermCbs = [];

      window.blOnOSPermReady = function(cb) {
        if (_blOSPerm !== null) { try { cb(_blOSPerm); } catch(_) {} return; }
        _blPermCbs.push(cb);
      };
      window.blGetOSPermStatus = function() {
        return _blOSPerm ? (_blOSPerm.granted ? 'granted' : 'denied') : null;
      };

      async function _blCheckOSPerm() {
        try {
          if (OS.Notifications && typeof OS.Notifications.getPermissionAsync === 'function') {
            var _p = await OS.Notifications.getPermissionAsync();
            // getPermissionAsync returns boolean in SDK 5.x; some bridge versions wrap it
            if (_p === true)  return true;
            if (_p === false) return false;
            if (_p && (_p.value === true  || _p.permission === true))  return true;
            if (_p && (_p.value === false || _p.permission === false)) return false;
            return null;
          }
          if (typeof OS.getDeviceState === 'function') {
            var _s = await OS.getDeviceState();
            return (_s && _s.hasNotificationPermission) ? true : false;
          }
        } catch (_ce) {
          console.warn('[OneSignal] OS perm check error:', _ce);
        }
        return null;
      }

      _blCheckOSPerm().then(function(granted) {
        _blOSPerm = { granted: granted };
        console.log('[OneSignal] OS permission granted=' + granted);
        _blPermCbs.forEach(function(cb) { try { cb(_blOSPerm); } catch(_) {} });
        _blPermCbs = [];
      });

      // ── Re-prompt OS permission (only called when user explicitly enables) ─
      async function _blRequestPermIfNeeded() {
        if (_blOSPerm === null) {
          await new Promise(function(r) { _blPermCbs.push(function() { r(); }); });
        }
        if (_blOSPerm && _blOSPerm.granted === true) {
          console.log('[OneSignal] OS permission already granted — no re-prompt');
          return;
        }
        console.log('[OneSignal] OS permission not granted — requesting');
        try {
          var _rr;
          if (OS.Notifications && typeof OS.Notifications.requestPermission === 'function') {
            _rr = await OS.Notifications.requestPermission(true);
          } else if (typeof OS.requestPermission === 'function') {
            _rr = await OS.requestPermission(true);
          } else if (typeof OS.promptForPushNotificationsWithUserResponse === 'function') {
            _rr = await OS.promptForPushNotificationsWithUserResponse(true);
          } else {
            console.warn('[OneSignal] no permission-request method for re-prompt');
            return;
          }
          if (_rr !== undefined) console.log('[OneSignal] re-prompt result:', JSON.stringify(_rr));
          var newGrant = await _blCheckOSPerm();
          _blOSPerm = { granted: newGrant };
          console.log('[OneSignal] post-prompt granted=' + newGrant);
        } catch (_rpe) {
          console.warn('[OneSignal] _blRequestPermIfNeeded error:', _rpe);
        }
      }

      // ── DIAGNOSTIC: App foreground — log subscription state ───────────
      // Fires whenever the app comes to the foreground. Purely observational.
      // Provides a time-stamped subscription snapshot for diagnosing
      // enabled→disabled transitions between launch and foreground.
      try {
        var AppPlugin4sub = Cap.Plugins && Cap.Plugins.App;
        if (!AppPlugin4sub && typeof Cap.registerPlugin === 'function') {
          AppPlugin4sub = Cap.registerPlugin('App');
        }
        if (AppPlugin4sub && typeof AppPlugin4sub.addListener === 'function') {
          await AppPlugin4sub.addListener('appStateChange', function(state) {
            if (!(state && state.isActive)) return;
            try {
              if (OS.User && OS.User.pushSubscription) {
                var _subFg = OS.User.pushSubscription;
                console.log('[OSSubscription] foreground:'
                  + ' id=' + (_subFg.id || 'none')
                  + ' token=' + (_subFg.token ? _subFg.token.slice(0,8) + '…' : 'none')
                  + ' optedIn=' + _subFg.optedIn);
              }
            } catch (_fge) {}
          });
          console.log('[OSSubscription] foreground state observer registered');
        }
      } catch (_fso) {
        console.warn('[OSSubscription] foreground observer registration error:', _fso);
      }

      // ── Expose opt-in/out helper for the push preference toggle ──────────
      // Called by blTogglePushPref() in push_settings.html after the server
      // preference is saved. No-op in browser. When enabling, re-prompts if needed.
      // Verified APIs: OS.User.pushSubscription.optIn() / optOut() → void
      window.blSetPushEnabled = function(enabled) {
        try {
          var _pushSub = (OS.User && (OS.User.pushSubscription || OS.User.PushSubscription)) || null;
          if (_pushSub && typeof _pushSub.optIn === 'function') {
            var _subResult;
            if (enabled) {
              console.log('[OneSignal] blSetPushEnabled: calling optIn() — bridge=' + _osVia);
              _subResult = _pushSub.optIn();
              // optIn() returns void on Cordova; Promise.resolve handles both.
              Promise.resolve(_subResult).then(function() {
                console.log('[OneSignal] blSetPushEnabled: optIn() complete');
                _blRequestPermIfNeeded();
              }).catch(function(e) {
                console.warn('[OneSignal] blSetPushEnabled: optIn() error:', e);
              });
            } else {
              console.log('[OneSignal] blSetPushEnabled: calling optOut() — bridge=' + _osVia);
              _subResult = _pushSub.optOut();
              Promise.resolve(_subResult).then(function() {
                console.log('[OneSignal] blSetPushEnabled: optOut() complete');
              }).catch(function(e) {
                console.warn('[OneSignal] blSetPushEnabled: optOut() error:', e);
              });
            }
          } else if (typeof OS.disablePush === 'function') {
            // SDK 4.x fallback
            var _dpArg   = _isCordovaBridge ? !enabled : { disabled: !enabled };
            var _dpLabel = _isCordovaBridge ? 'Cordova bool' : 'Capacitor object';
            console.log('[OneSignal] blSetPushEnabled: disablePush(' + !enabled + ') SDK 4.x ' + _dpLabel);
            var _dpResult = OS.disablePush(_dpArg);
            Promise.resolve(_dpResult).then(function() {
              console.log('[OneSignal] blSetPushEnabled: disablePush complete');
              if (enabled) _blRequestPermIfNeeded();
            }).catch(function(e) {
              console.warn('[OneSignal] blSetPushEnabled: disablePush error:', e);
            });
          } else {
            console.warn('[OneSignal] blSetPushEnabled: no opt-in/out method found on bridge=' + _osVia);
          }
        } catch (_opte) {
          console.warn('[OneSignal] blSetPushEnabled error:', _opte);
        }
      };
      console.log('[OneSignal] blSetPushEnabled helper registered (bridge=' + _osVia + ')');

      // ── Expose identity-logout helper for the sign-out flow ──────────
      // Called by the logout link handler in profile.html before navigating away.
      // Clears OneSignal external_id — device subscription is no longer tied to this user.
      // API: OS.logout(): void | Promise
      window.blOSLogout = function() {
        return new Promise(function(resolve) {
          try {
            if (typeof OS.logout === 'function') {
              console.log('[OneSignal] blOSLogout: calling logout()');
              Promise.resolve(OS.logout()).then(function() {
                console.log('[OneSignal] blOSLogout: logout() complete');
                resolve();
              }).catch(function(_le) {
                console.warn('[OneSignal] blOSLogout: logout() error:', _le);
                resolve();
              });
            } else {
              console.log('[OneSignal] blOSLogout: no logout() method — skip');
              resolve();
            }
          } catch (_le2) {
            console.warn('[OneSignal] blOSLogout error:', _le2);
            resolve();
          }
        });
      };
      console.log('[OneSignal] blOSLogout helper registered');

    })();
  });
})();

/* ── Badge clear + delivered-notification sweep ── native shell only ─────
   Clears the iOS app badge count and removes delivered notifications from
   the system tray whenever the app launches, resumes from foreground, or
   when the user taps a notification to open it.

   Uses OneSignal (OS.Notifications.clearAll) as the primary clear mechanism.
   @capacitor/push-notifications is NOT used here — it has been removed.

   Plugins used:
     - Capacitor App plugin  (appStateChange event for foreground)
     - OneSignal plugin (OS.Notifications.clearAll — SDK 5.x)

   Push tap routing is handled in the OneSignal block above (click listener).
   This block handles only badge/notification-center clearing and back button. */
(function() {
  'use strict';

  var _cap0b = window.Capacitor;
  var _wk0b  = window.webkit;
  var _isNativeB = !!(_cap0b && typeof _cap0b.isNativePlatform === 'function' && _cap0b.isNativePlatform());
  var _hasWkB    = !!(_wk0b && _wk0b.messageHandlers && _wk0b.messageHandlers.capacitor);

  if (!_isNativeB && !_hasWkB) {
    return;
  }

  async function _waitCapB(maxMs) {
    var deadline = Date.now() + maxMs;
    while (Date.now() < deadline) {
      if (window.Capacitor && typeof window.Capacitor.isNativePlatform === 'function') {
        return window.Capacitor;
      }
      await new Promise(function(r) { setTimeout(r, 100); });
    }
    return null;
  }

  document.addEventListener('DOMContentLoaded', function() {
    (async function() {

      var Cap = await _waitCapB(3000);
      if (!Cap) {
        console.warn('[BadgeClear] Capacitor bridge not ready after 3 s — badge clear skipped');
        return;
      }
      console.log('[BadgeClear] bridge ready');

      // ── Locate Capacitor plugins ──────────────────────────────────────
      var AppPlugin  = null;
      var OSPlugin   = null;

      try {
        if (Cap.Plugins) {
          AppPlugin  = Cap.Plugins.App  || null;
          OSPlugin   = Cap.Plugins.OneSignal || null;
        }
        if (!AppPlugin  && typeof Cap.registerPlugin === 'function') AppPlugin  = Cap.registerPlugin('App');
        if (!OSPlugin   && typeof Cap.registerPlugin === 'function') OSPlugin   = Cap.registerPlugin('OneSignal');
        // Cordova bridge exposes OneSignal under window.plugins
        if (!OSPlugin && window.plugins && window.plugins.OneSignal) OSPlugin = window.plugins.OneSignal;
      } catch (_pe) {
        console.warn('[BadgeClear] plugin lookup error:', _pe);
      }

      // ── Core clear function ───────────────────────────────────────────
      async function _clearBadgeAndNotifs(reason) {
        console.log('[BadgeClear] clearing badge, reason=' + reason);
        // Primary: OneSignal SDK 5.x clearAll (clears badge + notification center)
        try {
          if (OSPlugin && OSPlugin.Notifications && typeof OSPlugin.Notifications.clearAll === 'function') {
            await OSPlugin.Notifications.clearAll();
            console.log('[BadgeClear] OS.Notifications.clearAll() done');
          } else if (OSPlugin && typeof OSPlugin.clearOneSignalNotifications === 'function') {
            await OSPlugin.clearOneSignalNotifications();
            console.log('[BadgeClear] clearOneSignalNotifications() done (SDK 4.x)');
          }
        } catch (_e2) {
          console.warn('[BadgeClear] OneSignal clear error:', _e2);
        }
      }

      // ── Run once on load (covers cold launch) ─────────────────────────
      await _clearBadgeAndNotifs('launch');

      // ── Listen for app foregrounding ──────────────────────────────────
      if (AppPlugin && typeof AppPlugin.addListener === 'function') {
        try {
          await AppPlugin.addListener('appStateChange', async function(state) {
            if (state && state.isActive) {
              await _clearBadgeAndNotifs('foreground');
            }
          });
          console.log('[BadgeClear] appStateChange listener registered');
        } catch (_ae) {
          console.warn('[BadgeClear] appStateChange listener error:', _ae);
        }
      }

      // ── Android back button handler ───────────────────────────────────
      // Priority 1: close any open modal/overlay.
      // Priority 2: go back in browser history if available.
      // Priority 3: already at root — the Capacitor App plugin default
      //             exits the app, which is the correct behaviour.
      if (AppPlugin && typeof AppPlugin.addListener === 'function') {
        try {
          await AppPlugin.addListener('backButton', function(info) {
            var modal = document.querySelector(
              '.modal-overlay[style*="flex"], .modal-overlay[style*="block"], ' +
              '[id$="-modal"][style*="flex"], [id$="-modal"][style*="block"]'
            );
            if (modal) { modal.style.display = 'none'; return; }
            if (info && info.canGoBack) { window.history.back(); return; }
          });
          console.log('[BackButton] handler registered');
        } catch (_be) {
          console.warn('[BackButton] handler error:', _be);
        }
      }

      console.log('[BadgeClear] init complete');

    })();
  });
})();

/* ── Capacitor deep-link handler (appUrlOpen) ───────────────────────────────
   Handles Universal Links (iOS) and App Links (Android) for /invite/* and
   /trip-invite/* paths.

   appUrlOpen is fired by the Capacitor App plugin for warm starts, background
   resumes, and cold starts.  Capacitor explicitly queues cold-start events and
   delivers them after the bridge is ready, so this single listener covers all
   start types reliably.  No getLaunchUrl() supplement is needed: both APIs
   surface the same URL and getLaunchUrl() adds no reliability benefit when the
   app uses a remote server.url (the bridge cannot miss an event that is queued
   for it before the WKWebView/WebView finishes loading).

   _lastHandledDeepLinkUrl + _handleDeepLinkUrl provide a shared entry point
   so future callers (e.g. a second listener) cannot navigate to the same path
   twice without any architectural change.

   NATIVE PROJECT REQUIREMENTS (outside this repo):
   ─────────────────────────────────────────────────
   iOS (Xcode):
     1. Target → Signing & Capabilities → + Associated Domains
        Add:  applinks:app.baselodgeapp.com
     2. AppDelegate.swift — implement:
          func application(_ application: UIApplication,
                           continue userActivity: NSUserActivity,
                           restorationHandler: ...) -> Bool
        Forward the userActivity.webpageURL to Capacitor:
          ApplicationDelegateProxy.shared.application(application,
            continue: userActivity, restorationHandler: restorationHandler)

   Android (Android Studio):
     1. android/app/src/main/AndroidManifest.xml — inside <activity>:
          <intent-filter android:autoVerify="true">
            <action android:name="android.intent.action.VIEW" />
            <category android:name="android.intent.category.DEFAULT" />
            <category android:name="android.intent.category.BROWSABLE" />
            <data android:scheme="https"
                  android:host="app.baselodgeapp.com"
                  android:pathPrefix="/invite/" />
          </intent-filter>
          <!-- repeat for /trip-invite/ -->

   Without these native changes, this JS listener is unreachable
   even though it is registered — the OS never fires the event.
   ─────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  /* Only run inside a Capacitor WKWebView/WebView — no-op in Safari/browser. */
  var _cap = window.Capacitor;
  if (!_cap || typeof _cap.isNativePlatform !== 'function' || !_cap.isNativePlatform()) {
    return;
  }

  var _plugins = (_cap.Plugins || {});
  var _App = _plugins.App;
  if (!_App || typeof _App.addListener !== 'function') {
    console.warn('[DeepLink] @capacitor/app App plugin unavailable — deep link handlers not registered');
    return;
  }

  /* Last URL handled — prevents any future duplicate navigation attempts. */
  var _lastHandledDeepLinkUrl = null;

  /* Shared handler: parse the URL and navigate if it is an invite path. */
  function _handleDeepLinkUrl(url) {
    if (!url) return;
    if (_lastHandledDeepLinkUrl === url) return; /* duplicate — already handled */
    try {
      var parsed = new URL(url);
      var path = parsed.pathname + parsed.search + parsed.hash;
      var ALLOWED_PREFIXES = ['/invite/', '/trip-invite/', '/friends'];
      var isAllowed = ALLOWED_PREFIXES.some(function(prefix) {
        return path.indexOf(prefix) === 0;
      });
      if (isAllowed) {
        _lastHandledDeepLinkUrl = url;
        console.log('[DeepLink] navigating to', path);
        window.location.href = path;
      }
    } catch (e) {
      console.warn('[DeepLink] URL handling error:', e);
    }
  }

  /* Covers warm-start, background-resume, and cold-start.  Capacitor queues
     this event until the bridge is ready, so it never fires before JS is live. */
  _App.addListener('appUrlOpen', function (event) {
    var url = event && (event.url || event.URL || '');
    _handleDeepLinkUrl(url);
  });

  console.log('[DeepLink] appUrlOpen handler registered');
})();
