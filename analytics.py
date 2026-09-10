"""
PostHog analytics module — PostHog Python v7 compatible.
Server-side client: track, identify (set/set_once), alias.
All functions are silent no-ops when POSTHOG_KEY is not set.

PostHog v7 API notes:
  capture(event, *, distinct_id, properties, ...)  — event is positional, rest are kwargs
  set(*, distinct_id, properties, ...)             — replaces identify() for person props
  set_once(*, distinct_id, properties, ...)        — replaces identify() for set-once props
  alias(previous_id, distinct_id)                  — unchanged from v2
  flush()                                           — unchanged
"""
import atexit
import json
import logging
import os
import re
import uuid
from urllib.parse import unquote

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

POSTHOG_KEY = os.environ.get("POSTHOG_KEY", "")
POSTHOG_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")

_client = None
_init_logged = False
_ANON_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")

# Analytics payloads must not contain email addresses, full names, passwords,
# auth/reset/session tokens, invite tokens, planning free text, or exact
# residential addresses. Keep intentionally bounded travel/social metadata only.


def _get_client():
    global _client, _init_logged
    if not POSTHOG_KEY:
        logger.warning("PostHog track skipped: POSTHOG_KEY is not set")
        return None
    if _client is None:
        try:
            from posthog import Posthog
            _client = Posthog(project_api_key=POSTHOG_KEY, host=POSTHOG_HOST)
            if not _init_logged:
                logger.info(
                    "PostHog server client initialized (v7) host=%s key_prefix=%s",
                    POSTHOG_HOST, POSTHOG_KEY[:8] + "…",
                )
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


def _valid_anon_id(value):
    """Return a safe browser-generated anonymous ID, or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or value == "anonymous"
        or value.startswith("anonymous_event:")
        or value.isdigit()
        or not _ANON_ID_PATTERN.fullmatch(value)
    ):
        return None
    return value


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
            data = json.loads(unquote(cookie_val))
            if not isinstance(data, dict):
                return None
            return _valid_anon_id(data.get("distinct_id"))
        except Exception:
            pass
    return None


def track(
    user_id,
    event,
    properties=None,
    set_props=None,
    set_once_props=None,
    *,
    anonymous_id=None,
):
    """
    Track a server-side event. PostHog v7 compatible.
    Always call AFTER db.session.commit() — never before a successful DB write.

    PostHog v7: capture(event, *, distinct_id, properties)
    """
    client = _get_client()
    if not client:
        return
    distinct_id = (
        str(user_id)
        if user_id is not None
        else (_valid_anon_id(anonymous_id) or f"anonymous_event:{uuid.uuid4()}")
    )
    props = dict(properties or {})
    if set_props:
        props["$set"] = set_props
    if set_once_props:
        props["$set_once"] = set_once_props

    try:
        client.capture(event, distinct_id=distinct_id, properties=props)
        logger.info("PostHog capture OK: event=%s distinct_id=%s", event, distinct_id)
    except Exception as exc:
        logger.warning("PostHog capture FAILED: event=%s distinct_id=%s error=%s", event, distinct_id, exc)


def identify(user_id, properties=None, set_once_props=None):
    """
    Associate a user ID with person properties. PostHog v7 compatible.

    PostHog v7 removed identify(). Use set() for mutable person props
    and set_once() for immutable/first-seen props.
    """
    client = _get_client()
    if not client:
        return
    uid = str(user_id)
    try:
        if properties:
            client.set(distinct_id=uid, properties=dict(properties))
        if set_once_props:
            client.set_once(distinct_id=uid, properties=dict(set_once_props))
        if properties or set_once_props:
            logger.info("PostHog identify OK: distinct_id=%s", uid)
    except Exception as exc:
        logger.warning("PostHog identify FAILED: distinct_id=%s error=%s", uid, exc)


def alias(anon_id, user_id):
    """
    Alias an anonymous browser ID to a real user ID.
    ONLY call this on signup, never on login.
    Silently skips if anon_id is None.

    PostHog v7: alias(previous_id, distinct_id) — unchanged from v2.
    """
    client = _get_client()
    if not client or not anon_id:
        return
    try:
        client.alias(anon_id, str(user_id))
    except Exception as exc:
        logger.warning("PostHog alias FAILED: anon_id=%s user_id=%s error=%s", anon_id, user_id, exc)


def _shutdown_client():
    """Best-effort delivery at clean process shutdown, never request time."""
    client = _client
    if client is None:
        return
    try:
        shutdown = getattr(client, "shutdown", None)
        if callable(shutdown):
            shutdown()
            return
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
    except Exception as exc:
        logger.warning("PostHog shutdown delivery failed: %s", exc)


atexit.register(_shutdown_client)
