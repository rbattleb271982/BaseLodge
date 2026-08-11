"""
Shared test fixtures and helpers for the BaseLodge regression test suite.

Isolation strategy:
  Every test function receives a fresh SQLite in-memory database via the
  `client` fixture.  Flask-SQLAlchemy's engine is swapped for the duration
  of the fixture using the same _swap_engine trick as test_regression_guards.py.

CRITICAL: The `client` fixture does NOT keep an app_context active during tests.
  Each HTTP request via the test client creates its own app_context (and pops
  it on teardown), giving Flask-Login a fresh `current_user` per request and
  calling db.session.remove() after each request.

  Setup fixtures create data inside `with app.app_context():` blocks that
  CLOSE before the fixture yields, so the test body sees no active context.
  Assertions similarly use their own `with app.app_context():` blocks.

CSRF pattern:
  validate_csrf_request() checks session['_csrf_token'] against
  request.form['csrf_token'] OR request.headers['X-CSRF-Token'].
"""
import os
import secrets as _secrets
from datetime import datetime, timedelta, date

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app import app, limiter
from models import (
    db, User, SkiTrip, SkiTripParticipant, Resort,
    GuestStatus, ParticipantRole,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_TEST_CSRF = "test-csrf-fixed-value-baselodge-regression"

_FUTURE_START  = date.today() + timedelta(days=60)
_FUTURE_END    = date.today() + timedelta(days=65)
_FUTURE_START2 = date.today() + timedelta(days=80)
_FUTURE_END2   = date.today() + timedelta(days=85)


# ── Engine-swap helper ────────────────────────────────────────────────────────

def _swap_engine(new_engine):
    engines_map = db._app_engines.setdefault(app, {})
    old = engines_map.get(None)
    if old is not None:
        old.dispose()
    engines_map[None] = new_engine
    return old


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Fresh SQLite in-memory test client.

    IMPORTANT: the app_context is NOT kept open after setup.  Each HTTP
    request creates its own context (and tears it down), which means
    Flask-Login gets a fresh current_user per request and
    db.session.remove() is called after each request.
    """
    sqlite_engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    saved = _swap_engine(sqlite_engine)
    _orig_enabled = limiter.enabled
    limiter.enabled = False

    with app.app_context():
        db.create_all()

    yield app.test_client()

    with app.app_context():
        db.session.remove()
        db.drop_all()

    limiter.enabled = _orig_enabled
    if saved is not None:
        _swap_engine(saved)
    sqlite_engine.dispose()


@pytest.fixture
def rate_limit_client():
    """Like `client` but with the rate limiter ENABLED."""
    sqlite_engine = sa.create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    saved = _swap_engine(sqlite_engine)
    limiter.enabled = True
    try:
        limiter._limiter._storage.clear()
    except Exception:
        pass

    with app.app_context():
        db.create_all()

    yield app.test_client()

    with app.app_context():
        db.session.remove()
        db.drop_all()

    limiter.enabled = False
    if saved is not None:
        _swap_engine(saved)
    sqlite_engine.dispose()


# ── Model helpers (call inside with app.app_context():) ───────────────────────

def _make_user(label="", **extra):
    tag = f"{label}_{_secrets.token_hex(4)}"
    u = User(
        email=extra.pop("email", f"{tag}@test.bl"),
        first_name=f"U{label[:6] or 'ser'}",
        last_name="Test",
        rider_types=["Skier"],
        pass_type="epic",
        skill_level="Intermediate",
        lifecycle_stage="active",
        onboarding_completed_at=datetime.utcnow(),
        is_seeded=True,
        **extra,
    )
    u.set_password("TestPass1!")
    db.session.add(u)
    db.session.flush()
    return u


def _make_resort(name=None):
    tag = _secrets.token_hex(4)
    r = Resort(
        name=name or f"Resort_{tag}",
        slug=f"resort-{tag}",
        state="CO",
        state_code="CO",
        country_code="US",
        is_active=True,
        is_region=False,
    )
    db.session.add(r)
    db.session.flush()
    return r


def _make_trip(owner, resort=None, **kwargs):
    t = SkiTrip(
        user_id=owner.id,
        mountain=(resort.name if resort else kwargs.pop("mountain", "Test Peak")),
        resort_id=(resort.id if resort else None),
        start_date=kwargs.pop("start_date", _FUTURE_START),
        end_date=kwargs.pop("end_date", _FUTURE_END),
        is_public=kwargs.pop("is_public", True),
        trip_status=kwargs.pop("trip_status", "planning"),
        **kwargs,
    )
    db.session.add(t)
    db.session.flush()
    db.session.add(SkiTripParticipant(
        trip_id=t.id,
        user_id=owner.id,
        status=GuestStatus.ACCEPTED,
        role=ParticipantRole.OWNER,
    ))
    db.session.flush()
    return t


def _add_participant(trip, user, status=GuestStatus.ACCEPTED):
    p = SkiTripParticipant(
        trip_id=trip.id,
        user_id=user.id,
        status=status,
        role=ParticipantRole.GUEST,
    )
    db.session.add(p)
    db.session.flush()
    return p


# ── Session / auth helpers ────────────────────────────────────────────────────

def _login(client, user_id, csrf=_TEST_CSRF):
    """Inject Flask-Login session + CSRF token without going through /auth."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
        sess["_csrf_token"] = csrf


# ── Request helpers ───────────────────────────────────────────────────────────

def json_post(client, url, data=None, csrf=_TEST_CSRF):
    return client.post(url, json=data or {}, headers={"X-CSRF-Token": csrf})


def json_patch(client, url, data=None, csrf=_TEST_CSRF):
    return client.patch(url, json=data or {}, headers={"X-CSRF-Token": csrf})


def json_delete(client, url, csrf=_TEST_CSRF):
    return client.delete(url, headers={"X-CSRF-Token": csrf})


def form_post(client, url, data=None, csrf=_TEST_CSRF):
    payload = dict(data or {})
    payload["csrf_token"] = csrf
    return client.post(url, data=payload, follow_redirects=False)
