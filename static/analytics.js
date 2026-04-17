/* analytics.js — PostHog Phase 1
 * Initializes PostHog, wires identity, fires app_loaded.
 * Keys and user context are injected by analytics_head.html.
 */
(function () {
  'use strict';

  var key = window.__POSTHOG_KEY__;
  var host = window.__POSTHOG_HOST__ || 'https://us.i.posthog.com';

  if (!key) { return; }

  /* PostHog JS CDN snippet — do not modify */
  /* eslint-disable */
  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]);t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+" (stub)"},o="init capture alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys getNextSurveyStep onSessionId setPersonPropertiesForFlags".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a]),e.__SV=1})}(document,window.posthog||[]);
  /* eslint-enable */

  posthog.init(key, {
    api_host: host,
    autocapture: false,
    capture_pageview: false,
    loaded: function (ph) {
      /* 1. Reset session if flagged (user just logged out) */
      if (window.__POSTHOG_RESET__) {
        ph.reset();
      }

      /* 2. Identify logged-in users.
       *    Internal users are NOT excluded — they are tagged via is_internal
       *    person property and filtered in PostHog dashboards. */
      var user = window.__USER__ || {};
      if (user.id) {
        ph.identify(String(user.id));
      }

      /* 3. Test event — fires for all users (anonymous, internal, external) */
      ph.capture('app_loaded');
    }
  });
}());
