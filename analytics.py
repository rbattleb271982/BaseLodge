"""
PostHog analytics module — Phase 1.
Server-side Python client: track, identify, alias.
All functions are silent no-ops when POSTHOG_KEY is not set.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

POSTHOG_KEY = os.environ.get("POSTHOG_KEY", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")

_client = None
_init_logged = False


def _get_client():
    global _client, _init_logged
    if not POSTHOG_KEY:
        return None
    if _client is None:
        try:
            from posthog import Posthog
            _client = Posthog(project_api_key=POSTHOG_KEY, host=POSTHOG_HOST)
            if not _init_logged:
                logger.info("PostHog server client initialized")
                _init_logged = True
        except Exception as exc:
            logger.warning("PostHog init failed: %s", exc)
    return _client


def is_internal(email):
    """Return True if the email belongs to an internal/team user."""
    if not email:
        return False
    email = email.lower().strip()
    domain = email.split("@")[-1] if "@" in email else ""

    raw_domains = os.environ.get("INTERNAL_EMAIL_DOMAINS", "")
    raw_emails = os.environ.get("INTERNAL_USER_EMAILS", "")

    domains = [d.strip().lower() for d in raw_domains.split(",") if d.strip()]
    emails = [e.strip().lower() for e in raw_emails.split(",") if e.strip()]

    return domain in domains or email in emails


def get_anon_id(cookies):
    """
    Extract PostHog anonymous distinct_id from the browser cookie.
    PostHog sets a cookie named ph_{POSTHOG_KEY}_posthog containing JSON.
    """
    if not POSTHOG_KEY:
        return None
    cookie_name = "ph_{}_posthog".format(POSTHOG_KEY)
    cookie_val = cookies.get(cookie_name, "")
    if cookie_val:
        try:
            data = json.loads(cookie_val)
            return data.get("distinct_id")
        except Exception:
            pass
    return None


def track(user_id, event, properties=None, set_props=None, set_once_props=None):
    """
    Track a server-side event.
    Always call AFTER db.session.commit() — never before a successful DB write.
    """
    client = _get_client()
    if not client:
        logger.info("PostHog track skipped: client unavailable")
        return
    distinct_id = str(user_id) if user_id is not None else "anonymous"
    props = dict(properties or {})
    if set_props:
        props["$set"] = set_props
    if set_once_props:
        props["$set_once"] = set_once_props
    try:
        client.capture(distinct_id, event, props)
    except Exception as exc:
        logger.warning("PostHog track failed: %s", exc)


def identify(user_id, properties=None, set_once_props=None):
    """Associate a user ID with person properties."""
    client = _get_client()
    if not client:
        return
    try:
        props = dict(properties or {})
        if set_once_props:
            props["$set_once"] = set_once_props
        client.identify(str(user_id), props)
    except Exception as exc:
        logger.warning("PostHog identify failed: %s", exc)


def alias(anon_id, user_id):
    """
    Alias an anonymous browser ID to a real user ID.
    ONLY call this on signup, never on login.
    Silently skips if anon_id is None.
    """
    client = _get_client()
    if not client or not anon_id:
        return
    try:
        client.alias(anon_id, str(user_id))
    except Exception as exc:
        logger.warning("PostHog alias failed: %s", exc)
