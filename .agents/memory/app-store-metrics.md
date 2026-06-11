---
name: App Store metrics architecture
description: How AppStoreMetric model, services, and admin routes are wired together; key API limitations.
---

# App Store Metrics Architecture

## Rule
The admin dashboard and /admin/app-store page NEVER call Apple or Google APIs at render time. All metrics are read from the `app_store_metric` DB table. External API calls happen only via POST /admin/app-store/refresh (admin-triggered).

**Why:** Live API calls at page-render time would make the already query-heavy dashboard fragile (timeouts, credential failures). The store APIs have rate limits and require secrets that may not always be set.

**How to apply:** Any new store metric should be added to AppStoreMetric model + fetched in the refresh route + displayed from DB in the GET route. Never add store API calls to admin_dashboard() or any GET handler.

## Credential pattern
Six new secrets needed (not yet set in Replit):
- iOS: `ASC_KEY_P8`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_VENDOR_NO`, `ASC_APP_ID` (optional, for ratings)
- Android: `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`, `GOOGLE_PLAY_PACKAGE_NAME`

Both clients check `is_configured()` before attempting network calls. Missing credentials produce a flash notice, not a 500.

## iOS API limitations (important)
Apple's public App Store Connect API does NOT expose:
- App page views
- Conversion rate (page view → install)

These exist only in the ASC web UI under Analytics. The `page_views` and `conversion_pct` columns in `AppStoreMetric` are intentionally nullable and left blank for iOS. Do not try to populate them from the API — they are not available.

What IS available via ASC API:
- Daily downloads: `/v1/salesReports` (gzipped TSV, requires VENDOR_NO)
- Ratings/reviews: `/v1/apps/{id}/customerReviews` + `/v1/apps/{id}` (requires ASC_APP_ID)

## Android API
Uses Google Play Developer Reporting API v1beta1 (`playdeveloperreporting.googleapis.com`).
- Installs: `storePerformanceClusterMetrics:query` with `newDeviceActivations` metric
- Crashes: `crashRateMetricSet:query` with `crashRate` metric (returns a rate, not a count — multiply by 100 for percentage, stored as float in `crashes` column)
- Ratings: NOT available via public API — `play_store_client.fetch_app_rating()` always returns None

## Sparkline pattern
The `admin_app_store.html` template defines its own `sparkline` macro (copy of the dashboard macro). The sparkline series is a 30-element Python list built in the route (`_sparkline_series()`) — oldest to newest, with zeros for missing days.

## Table startup migration
Created by `_run_app_store_metric_migration()` in app.py, called unconditionally at startup. Uses `CREATE TABLE IF NOT EXISTS` so it's safe to re-run. The UNIQUE constraint `uq_app_store_metric_platform_date` on (platform, report_date) enables clean upserts in the refresh route.
