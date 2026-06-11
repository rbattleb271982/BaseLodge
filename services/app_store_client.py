"""
App Store Connect API client.

Required environment variables:
  ASC_KEY_P8      — raw contents of the .p8 private key (PEM text)
  ASC_KEY_ID      — 10-char Key ID from App Store Connect → Users and Access → Keys
  ASC_ISSUER_ID   — Issuer ID (UUID) from the same page
  ASC_VENDOR_NO   — Vendor/Provider number (shown in App Store Connect → Sales)
  ASC_APP_ID      — Numeric App ID from App Store Connect (optional, for ratings)

Note on page-views / conversion rate:
  Apple's public App Store Connect API does NOT expose app analytics (page views,
  conversion rates). Those metrics exist only in the ASC web UI. This client
  fetches what IS available via the API: downloads (Sales/Trends) and ratings.
"""

import os
import gzip
import io
import csv
import time
import logging
from datetime import date, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_ASC_BASE = "https://api.appstoreconnect.apple.com/v1"


def is_configured() -> bool:
    """Return True if the minimum required ASC env vars are all present."""
    return all(
        os.environ.get(k)
        for k in ("ASC_KEY_P8", "ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_VENDOR_NO")
    )


def _build_jwt() -> str:
    """Return a signed ES256 JWT valid for 20 minutes."""
    import jwt as _jwt
    key_p8    = os.environ.get("ASC_KEY_P8", "")
    key_id    = os.environ.get("ASC_KEY_ID", "")
    issuer_id = os.environ.get("ASC_ISSUER_ID", "")
    if not (key_p8 and key_id and issuer_id):
        raise RuntimeError("ASC_KEY_P8 / ASC_KEY_ID / ASC_ISSUER_ID not configured")
    now = int(time.time())
    return _jwt.encode(
        {"iss": issuer_id, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        key_p8,
        algorithm="ES256",
        headers={"kid": key_id},
    )


def _headers() -> dict:
    return {"Authorization": f"Bearer {_build_jwt()}"}


def fetch_daily_downloads(days_back: int = 30) -> list:
    """
    Pull daily download/install counts from Sales/Trends Reports.

    Returns a list of dicts: [{"report_date": date, "downloads": int}, ...]
    Skips dates where the report is not yet available (HTTP 404).
    """
    import requests

    vendor_no = os.environ.get("ASC_VENDOR_NO", "")
    if not vendor_no:
        raise RuntimeError("ASC_VENDOR_NO not configured")

    results = []
    today = date.today()
    # Yesterday is the most recent available daily report
    for delta in range(1, days_back + 1):
        report_date = today - timedelta(days=delta)
        params = {
            "filter[reportType]":    "SALES",
            "filter[reportSubType]": "SUMMARY",
            "filter[frequency]":     "DAILY",
            "filter[vendorNumber]":  vendor_no,
            "filter[reportDate]":    report_date.strftime("%Y-%m-%d"),
        }
        try:
            resp = requests.get(
                f"{_ASC_BASE}/salesReports",
                headers=_headers(),
                params=params,
                timeout=15,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                total = 0
                for row in reader:
                    try:
                        total += int(float(row.get("Units", 0)))
                    except (ValueError, TypeError):
                        pass
            results.append({"report_date": report_date, "downloads": total})
        except Exception as exc:
            log.warning("ASC sales report unavailable for %s: %s", report_date, exc)

    return results


def fetch_app_rating() -> Optional[dict]:
    """
    Fetch average rating and total review count via ASC Reviews API.

    Returns {"rating": float, "review_count": int} or None on failure.
    """
    import requests

    app_id = os.environ.get("ASC_APP_ID", "")
    if not app_id:
        return None

    try:
        resp = requests.get(
            f"{_ASC_BASE}/apps/{app_id}/customerReviews",
            headers=_headers(),
            params={"limit": 1, "sort": "-createdDate"},
            timeout=15,
        )
        resp.raise_for_status()
        meta  = resp.json().get("meta", {}).get("paging", {})
        total = meta.get("total", 0)

        # Fetch the app record for the ratings summary
        app_resp = requests.get(
            f"{_ASC_BASE}/apps/{app_id}",
            headers=_headers(),
            params={"fields[apps]": "reviewRatingsSummary"},
            timeout=15,
        )
        app_resp.raise_for_status()
        attrs   = app_resp.json().get("data", {}).get("attributes", {})
        summary = attrs.get("reviewRatingsSummary", {})
        avg     = summary.get("average")
        if avg is None:
            return None
        rating_counts = summary.get("ratingCount", {})
        count = (
            sum(rating_counts.values())
            if isinstance(rating_counts, dict)
            else int(total)
        )
        return {"rating": round(float(avg), 2), "review_count": int(count)}
    except Exception as exc:
        log.warning("ASC rating fetch failed: %s", exc)
        return None
