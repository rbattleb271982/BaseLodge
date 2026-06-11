"""
Google Play Developer Reporting API client.

Required environment variables:
  GOOGLE_PLAY_SERVICE_ACCOUNT_JSON — full service account JSON as a string
  GOOGLE_PLAY_PACKAGE_NAME         — e.g. 'com.baselodge.app'

Uses google-auth + requests directly (no google-api-python-client required).
Scopes: playdeveloperreporting (installs/crashes) + androidpublisher (reviews).

Crash data is returned as a raw crash-rate percentage from the
crashRateMetricSet endpoint; store it in the `crashes` column as a float.
"""

import os
import json
import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_REPORTING_BASE = "https://playdeveloperreporting.googleapis.com/v1beta1"
_PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

_SCOPES = [
    "https://www.googleapis.com/auth/playdeveloperreporting",
    "https://www.googleapis.com/auth/androidpublisher",
]


def is_configured() -> bool:
    """Return True if both required Play env vars are present."""
    return all(
        os.environ.get(k)
        for k in ("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "GOOGLE_PLAY_PACKAGE_NAME")
    )


def _get_credentials():
    from google.oauth2 import service_account
    raw = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON not configured")
    return service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=_SCOPES
    )


def _auth_header(credentials) -> dict:
    import google.auth.transport.requests as _ga_req
    credentials.refresh(_ga_req.Request())
    return {"Authorization": f"Bearer {credentials.token}"}


def _timeline_spec(days_back: int) -> dict:
    today = date.today()
    end   = today - timedelta(days=1)
    start = today - timedelta(days=days_back)
    return {
        "aggregationPeriod": "DAILY",
        "startTime": {"year": start.year, "month": start.month, "day": start.day},
        "endTime":   {"year": end.year,   "month": end.month,   "day": end.day},
    }


def fetch_daily_installs(days_back: int = 30) -> list:
    """
    Fetch daily new-device activations via Play Developer Reporting API.
    Returns [{"report_date": date, "downloads": int}, ...].
    """
    import requests as rq

    pkg = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "")
    if not pkg:
        raise RuntimeError("GOOGLE_PLAY_PACKAGE_NAME not configured")

    creds   = _get_credentials()
    headers = {**_auth_header(creds), "Content-Type": "application/json"}
    body = {
        "metrics":      ["newDeviceActivations"],
        "timelineSpec": _timeline_spec(days_back),
        "dimensions":   [],
    }
    try:
        resp = rq.post(
            f"{_REPORTING_BASE}/apps/{pkg}/storePerformanceClusterMetrics:query",
            headers=headers,
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        results = []
        for row in resp.json().get("rows", []):
            ts  = row.get("startTime", {})
            val = row.get("metrics", {}).get("newDeviceActivations", {}).get("doubleValue", 0)
            d   = date(int(ts["year"]), int(ts["month"]), int(ts["day"]))
            results.append({"report_date": d, "downloads": int(float(val))})
        return results
    except Exception as exc:
        log.warning("Play installs fetch failed: %s", exc)
        return []


def fetch_daily_crashes(days_back: int = 30) -> list:
    """
    Fetch daily crash rate (as a percentage float) via Play Developer Reporting API.
    Returns [{"report_date": date, "crashes": float}, ...].
    The value is a crash-rate percentage (e.g. 0.42 = 0.42% of sessions crashed).
    """
    import requests as rq

    pkg = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME", "")
    if not pkg:
        raise RuntimeError("GOOGLE_PLAY_PACKAGE_NAME not configured")

    creds   = _get_credentials()
    headers = {**_auth_header(creds), "Content-Type": "application/json"}
    body = {
        "metrics":      ["crashRate"],
        "timelineSpec": _timeline_spec(days_back),
        "dimensions":   [],
    }
    try:
        resp = rq.post(
            f"{_REPORTING_BASE}/apps/{pkg}/crashRateMetricSet:query",
            headers=headers,
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        results = []
        for row in resp.json().get("rows", []):
            ts  = row.get("startTime", {})
            val = row.get("metrics", {}).get("crashRate", {}).get("doubleValue", 0.0)
            d   = date(int(ts["year"]), int(ts["month"]), int(ts["day"]))
            results.append({"report_date": d, "crashes": round(float(val) * 100, 4)})
        return results
    except Exception as exc:
        log.warning("Play crash rate fetch failed: %s", exc)
        return []


def fetch_app_rating() -> Optional[dict]:
    """
    Play Store does not expose an aggregated average rating via the public API.
    The androidpublisher reviews endpoint returns individual review text + stars,
    not a pre-computed average. Returns None; ratings must be entered manually
    or scraped from a third-party source.
    """
    return None
