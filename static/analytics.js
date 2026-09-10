/* analytics.js — PostHog Phase 1
 * Initializes PostHog, wires identity, fires app_loaded.
 * Keys and user context are injected by analytics_head.html.
 */
(function () {
  'use strict';

  window.blTrackProjectEvent = function (name, data) {
    try {
      if (window.umami && typeof window.umami.track === 'function') {
        window.umami.track(name, data || {});
      }
    } catch (error) {
      /* Analytics must never interrupt the user flow. */
    }
  };

  window.blTrackPostHogEvent = function (name, data) {
    try {
      if (window.posthog && typeof window.posthog.capture === 'function') {
        if (arguments.length > 1) {
          window.posthog.capture(name, data);
        } else {
          window.posthog.capture(name);
        }
      }
    } catch (error) {
      /* Analytics must never interrupt the user flow. */
    }
  };

  var key = window.__POSTHOG_KEY__;
  var host = window.__POSTHOG_HOST__ || 'https://us.i.posthog.com';
  var authenticatedUserMarker = 'baselodge_posthog_authenticated_user_id';

  if (!key) { return; }

  /* PostHog JS CDN snippet — do not modify */
  /* eslint-disable */
  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]);t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+" (stub)"},o="init capture alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys getNextSurveyStep onSessionId setPersonPropertiesForFlags".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a]),e.__SV=1})}(document,window.posthog||[]);
  /* eslint-enable */

  posthog.init(key, {
    api_host: host,
    autocapture: false,
    capture_pageview: false,
    disable_session_recording: true,
    loaded: function (ph) {
      var user = window.__USER__ || {};
      var currentUserId = (
        typeof user.id === 'number' && Number.isInteger(user.id) && user.id > 0
      ) ? String(user.id) : null;
      var storedUserId = null;
      var shouldReset = Boolean(window.__POSTHOG_RESET__);

      try {
        storedUserId = window.localStorage.getItem(authenticatedUserMarker);
        if (storedUserId && !/^[1-9][0-9]*$/.test(storedUserId)) {
          window.localStorage.removeItem(authenticatedUserMarker);
          storedUserId = null;
        }
        if (!currentUserId && storedUserId) {
          shouldReset = true;
        } else if (
          currentUserId && storedUserId && currentUserId !== storedUserId
        ) {
          shouldReset = true;
        }
      } catch (error) {
        storedUserId = null;
      }

      if (shouldReset) {
        ph.reset();
        try {
          window.localStorage.removeItem(authenticatedUserMarker);
        } catch (error) {
          /* Storage denial must not interrupt analytics initialization. */
        }
      }

      /* Identify logged-in users.
       *    Internal users are NOT excluded — they are tagged via is_internal
       *    person property and filtered in PostHog dashboards. */
      if (currentUserId) {
        ph.identify(currentUserId, {
          is_internal: Boolean(user.is_internal)
        });
        try {
          window.localStorage.setItem(
            authenticatedUserMarker,
            currentUserId
          );
        } catch (error) {
          /* Storage denial must not interrupt analytics initialization. */
        }
      }

      /* Core activation event — fires for all users. */
      ph.capture('app_loaded');
    }
  });
}());
