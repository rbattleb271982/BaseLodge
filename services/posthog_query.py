"""
PostHog Query Service — fetches HogQL event stats for the Admin Funnels page.

Requires POSTHOG_PERSONAL_API_KEY env var (a Personal API Key from PostHog Settings
→ Personal API Keys).  The project-level POSTHOG_KEY is write-only and cannot query
event data.

All functions return None / empty structures on failure and never raise.
"""
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

POSTHOG_HOST  = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
PERSONAL_KEY  = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")
QUERY_TIMEOUT = 12  # seconds per request

# Confidence thresholds (distinct users for any activation step)
_GROWING_THRESHOLD = 50
_HIGH_THRESHOLD    = 200

ACTIVATION_EVENTS = [
    "signup_started",
    "signup_completed",
    "onboarding_completed",
    "pass_added",
    "availability_added",
    "wishlist_added",
    "trip_created",
    "friend_connected",
    "invite_generated",
]

_LABEL_MAP = {
    "signup_started":       "Signup Started",
    "signup_completed":     "Signup Completed",
    "onboarding_completed": "Onboarding Completed",
    "pass_added":           "Pass Added",
    "availability_added":   "Availability Added",
    "wishlist_added":       "Wishlist Added",
    "trip_created":         "Trip Created",
    "friend_connected":     "Friend Connected",
    "invite_generated":     "Invite Generated",
}

_cache: dict = {}
_CACHE_TTL = 1800  # 30 minutes


def _cached(key, fetch_fn):
    now = time.time()
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < _CACHE_TTL:
            return val
    val = fetch_fn()
    _cache[key] = (now, val)
    return val


def _headers():
    return {
        "Authorization": f"Bearer {PERSONAL_KEY}",
        "Content-Type": "application/json",
    }


def _run_hogql(query_str):
    """Execute a HogQL query. Returns list of result rows or raises."""
    url = f"{POSTHOG_HOST}/api/projects/@current/query/"
    body = {"query": {"kind": "HogQLQuery", "query": query_str}}
    resp = requests.post(url, json=body, headers=_headers(), timeout=QUERY_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _format_ts(val):
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)[:16]


def fetch_event_audit():
    """
    Returns:
      has_credentials  bool   — POSTHOG_PERSONAL_API_KEY is set
      events           list   — per-event audit rows
      confidence       str    — 'low' | 'growing' | 'high'
      error            str|None
      min_user_count   int
      sufficient_data  bool
    """
    def _fetch():
        if not PERSONAL_KEY:
            return {
                "has_credentials": False,
                "events": [],
                "confidence": "low",
                "error": "POSTHOG_PERSONAL_API_KEY not configured",
                "min_user_count": 0,
                "sufficient_data": False,
            }

        events_csv = ", ".join(f"'{e}'" for e in ACTIVATION_EVENTS)
        hogql = f"""
            SELECT
                event,
                count()                    AS event_count,
                count(DISTINCT distinct_id) AS user_count,
                min(timestamp)             AS earliest,
                max(timestamp)             AS latest
            FROM events
            WHERE event IN ({events_csv})
            GROUP BY event
            ORDER BY event_count DESC
        """
        try:
            rows = _run_hogql(hogql)
        except Exception as exc:
            logger.warning("PostHog audit query failed: %s", exc)
            return {
                "has_credentials": True,
                "events": [],
                "confidence": "low",
                "error": str(exc)[:200],
                "min_user_count": 0,
                "sufficient_data": False,
            }

        row_map = {r[0]: r for r in rows}
        events = []
        for ev in ACTIVATION_EVENTS:
            r = row_map.get(ev)
            events.append({
                "name":        ev,
                "label":       _LABEL_MAP.get(ev, ev),
                "event_count": r[1] if r else 0,
                "user_count":  r[2] if r else 0,
                "earliest":    _format_ts(r[3]) if r else "—",
                "latest":      _format_ts(r[4]) if r else "—",
                "found":       bool(r),
            })

        activation_subset = [
            e for e in events
            if e["name"] in {
                "signup_started", "signup_completed", "onboarding_completed",
                "pass_added", "availability_added", "wishlist_added", "trip_created",
            }
        ]
        found = [e["user_count"] for e in activation_subset if e.get("found")]
        min_uc = min(found) if found else 0

        confidence = "high" if min_uc >= _HIGH_THRESHOLD else (
            "growing" if min_uc >= _GROWING_THRESHOLD else "low"
        )

        return {
            "has_credentials": True,
            "events": events,
            "confidence": confidence,
            "error": None,
            "min_user_count": min_uc,
            "sufficient_data": min_uc >= _GROWING_THRESHOLD,
        }

    return _cached("audit", _fetch)


def fetch_activation_funnel():
    """Funnel 1 — signup → trip. Returns list of step dicts or None on failure."""
    steps = [
        ("signup_started",       "Signup Started"),
        ("signup_completed",     "Signup Completed"),
        ("onboarding_completed", "Onboarding Completed"),
        ("pass_added",           "Pass Added"),
        ("availability_added",   "Availability Added"),
        ("wishlist_added",       "Wishlist Added"),
        ("trip_created",         "Trip Created"),
    ]

    def _fetch():
        events_csv = ", ".join(f"'{s[0]}'" for s in steps)
        hogql = f"""
            SELECT event, count(DISTINCT distinct_id) AS user_count
            FROM events
            WHERE event IN ({events_csv})
            GROUP BY event
        """
        try:
            rows = _run_hogql(hogql)
        except Exception as exc:
            logger.warning("PostHog activation funnel query failed: %s", exc)
            return None

        count_map = {r[0]: r[1] for r in rows}
        top = count_map.get("signup_started", 1) or 1
        result = []
        prev_uc = None
        for ev, label in steps:
            uc = count_map.get(ev, 0)
            vs_prev = round(uc / prev_uc * 100) if prev_uc else None
            result.append({
                "event":      ev,
                "label":      label,
                "user_count": uc,
                "pct_of_top": round(uc / top * 100) if top else 0,
                "vs_prev":    vs_prev,
            })
            prev_uc = uc or 1
        return result

    return _cached("funnel1", _fetch)


def fetch_social_funnel():
    """Funnel 2 — signup → friend → invite. Returns list or None."""
    steps = [
        ("signup_completed",  "Signup Completed"),
        ("friend_connected",  "Friend Connected"),
        ("invite_generated",  "Invite Generated"),
    ]

    def _fetch():
        events_csv = ", ".join(f"'{s[0]}'" for s in steps)
        hogql = f"""
            SELECT event, count(DISTINCT distinct_id) AS user_count
            FROM events WHERE event IN ({events_csv}) GROUP BY event
        """
        try:
            rows = _run_hogql(hogql)
        except Exception as exc:
            logger.warning("PostHog social funnel query failed: %s", exc)
            return None

        count_map = {r[0]: r[1] for r in rows}
        top = count_map.get("signup_completed", 1) or 1
        result = []
        prev_uc = None
        for ev, label in steps:
            uc = count_map.get(ev, 0)
            vs_prev = round(uc / prev_uc * 100) if prev_uc else None
            result.append({
                "event":      ev,
                "label":      label,
                "user_count": uc,
                "pct_of_top": round(uc / top * 100) if top else 0,
                "vs_prev":    vs_prev,
            })
            prev_uc = uc or 1
        return result

    return _cached("funnel2", _fetch)


def fetch_time_to_value():
    """Median minutes between key event pairs. Returns list or None."""
    pairs = [
        ("signup_completed",     "onboarding_completed", "Signup → Onboarding"),
        ("onboarding_completed", "pass_added",            "Onboarding → Pass Added"),
        ("pass_added",           "availability_added",    "Pass Added → Availability"),
        ("availability_added",   "trip_created",          "Availability → Trip Created"),
    ]

    def _fetch():
        results = []
        for from_ev, to_ev, label in pairs:
            hogql = f"""
                WITH
                  e1 AS (
                    SELECT distinct_id, min(timestamp) AS ts
                    FROM events WHERE event = '{from_ev}'
                    GROUP BY distinct_id
                  ),
                  e2 AS (
                    SELECT distinct_id, min(timestamp) AS ts
                    FROM events WHERE event = '{to_ev}'
                    GROUP BY distinct_id
                  )
                SELECT median(dateDiff('minute', e1.ts, e2.ts))
                FROM e1
                INNER JOIN e2 ON e1.distinct_id = e2.distinct_id
                WHERE e2.ts > e1.ts
            """
            try:
                rows = _run_hogql(hogql)
                med = rows[0][0] if rows and rows[0][0] is not None else None
            except Exception:
                med = None

            results.append({
                "from_event": from_ev,
                "to_event":   to_ev,
                "label":      label,
                "median_min": med,
            })
        return results

    return _cached("ttv", _fetch)


def clear_cache():
    """Force-clear the query cache (useful after event flood or testing)."""
    _cache.clear()
