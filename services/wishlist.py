"""Canonical wishlist normalization, validation, and transitions."""

from dataclasses import dataclass

import sqlalchemy as sa

from models import Resort, User, WishlistResortEvent


WISHLIST_LIMIT = 15


@dataclass
class WishlistValidationError(ValueError):
    message: str
    code: str = "invalid_wishlist"

    def __str__(self):
        return self.message


@dataclass
class WishlistChange:
    user: User
    old_ids: list[int]
    new_ids: list[int]
    added_ids: list[int]
    removed_ids: list[int]
    current_state_changed: bool
    limit_reached: bool = False

    @property
    def membership_changed(self):
        return bool(self.added_ids or self.removed_ids)

    @property
    def count(self):
        return len(self.new_ids)

    @property
    def at_limit(self):
        return self.count >= WISHLIST_LIMIT


def coerce_wishlist_resort_id(value):
    """Return one canonical integer resort ID or raise for malformed input."""
    if isinstance(value, bool) or value is None:
        raise WishlistValidationError("Wishlist resort IDs must be integers.")
    if isinstance(value, int):
        resort_id = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or not stripped.isascii() or not stripped.isdecimal():
            raise WishlistValidationError("Wishlist resort IDs must be integers.")
        resort_id = int(stripped)
    else:
        raise WishlistValidationError("Wishlist resort IDs must be integers.")
    if resort_id <= 0:
        raise WishlistValidationError("Wishlist resort IDs must be positive integers.")
    return resort_id


def normalize_wishlist_resort_ids(raw_ids, *, strict=True):
    """Coerce and stably deduplicate IDs without querying the database."""
    if not isinstance(raw_ids, (list, tuple)):
        if strict:
            raise WishlistValidationError("resort_ids must be a list.")
        return []

    normalized = []
    seen = set()
    for raw_id in raw_ids:
        try:
            resort_id = coerce_wishlist_resort_id(raw_id)
        except WishlistValidationError:
            if strict:
                raise
            continue
        if resort_id not in seen:
            seen.add(resort_id)
            normalized.append(resort_id)
    return normalized


def _eligible_resorts_by_id(resort_ids, *, session=None):
    if not resort_ids:
        return {}
    filters = (
        Resort.id.in_(resort_ids),
        Resort.is_active.is_(True),
        Resort.is_region.is_(False),
    )
    if session is None:
        resorts = Resort.query.filter(*filters).all()
    else:
        resorts = session.execute(
            sa.select(Resort).where(*filters)
        ).scalars().all()
    return {resort.id: resort for resort in resorts}


def eligible_wishlist_resort_ids(resort_ids, *, session=None):
    """Return eligible IDs from one bulk Resort query."""
    return set(_eligible_resorts_by_id(resort_ids, session=session))


def validate_wishlist_resort_ids(
    raw_ids,
    *,
    maximum=WISHLIST_LIMIT,
    session=None,
):
    """Strictly validate a submitted wishlist with one bounded Resort query."""
    normalized = normalize_wishlist_resort_ids(raw_ids)
    eligible_by_id = _eligible_resorts_by_id(normalized, session=session)
    if len(eligible_by_id) != len(normalized):
        raise WishlistValidationError(
            "Wishlist destinations must be active resorts.",
            code="invalid_destination",
        )
    if maximum is not None and len(normalized) > maximum:
        raise WishlistValidationError(
            f"Maximum {maximum} resorts allowed.",
            code="wishlist_limit",
        )
    return normalized


def canonical_wishlist_resorts(
    raw_ids,
    *,
    maximum=WISHLIST_LIMIT,
    session=None,
):
    """Tolerantly resolve legacy JSON to eligible resorts in stored order."""
    normalized = normalize_wishlist_resort_ids(raw_ids, strict=False)
    eligible_by_id = _eligible_resorts_by_id(normalized, session=session)
    canonical_ids = [
        resort_id for resort_id in normalized if resort_id in eligible_by_id
    ]
    if maximum is not None:
        canonical_ids = canonical_ids[:maximum]
    return canonical_ids, [eligible_by_id[resort_id] for resort_id in canonical_ids]


def remove_wishlist_resort_id(raw_ids, resort_id):
    """Remove every normalized occurrence while retaining unrelated legacy values."""
    remaining = []
    if not isinstance(raw_ids, list):
        return remaining
    for raw_id in raw_ids:
        try:
            if coerce_wishlist_resort_id(raw_id) == resort_id:
                continue
        except WishlistValidationError:
            pass
        remaining.append(raw_id)
    return remaining


def wishlist_contains_resort_id(raw_ids, resort_id):
    """Return whether tolerant canonical storage references one resort."""
    return resort_id in normalize_wishlist_resort_ids(raw_ids, strict=False)


def _lock_user(session, user_id):
    statement = (
        sa.select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = session.execute(statement).scalar_one_or_none()
    if user is None:
        raise WishlistValidationError("User not found.", code="user_not_found")
    return user


def _append_events(
    session,
    *,
    user_id,
    actor_user_id,
    source,
    removed_ids,
    added_ids,
):
    if source not in {"settings", "mountain_detail"}:
        raise WishlistValidationError(
            "Invalid wishlist event source.", code="invalid_source"
        )
    session.add_all([
        WishlistResortEvent(
            user_id=user_id,
            resort_id=resort_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            source=source,
        )
        for event_type, resort_ids in (
            ("removed", removed_ids),
            ("added", added_ids),
        )
        for resort_id in resort_ids
    ])


def replace_wishlist(
    session,
    *,
    user_id,
    requested_ids,
    actor_user_id,
    source="settings",
):
    """Replace ordered current state and append exact membership differences."""
    user = _lock_user(session, user_id)
    old_ids, _ = canonical_wishlist_resorts(
        user.wish_list_resorts, session=session
    )
    new_ids = validate_wishlist_resort_ids(
        requested_ids, session=session
    )
    old_set = set(old_ids)
    new_set = set(new_ids)
    removed_ids = [resort_id for resort_id in old_ids if resort_id not in new_set]
    added_ids = [resort_id for resort_id in new_ids if resort_id not in old_set]
    current_state_changed = user.wish_list_resorts != new_ids
    if current_state_changed:
        user.wish_list_resorts = new_ids
    _append_events(
        session,
        user_id=user.id,
        actor_user_id=actor_user_id,
        source=source,
        removed_ids=removed_ids,
        added_ids=added_ids,
    )
    session.flush()
    return WishlistChange(
        user=user,
        old_ids=old_ids,
        new_ids=new_ids,
        added_ids=added_ids,
        removed_ids=removed_ids,
        current_state_changed=current_state_changed,
    )


def add_wishlist_resort(
    session,
    *,
    user_id,
    resort_id,
    actor_user_id,
    source="mountain_detail",
):
    """Add one eligible resort, preserving duplicate and at-limit semantics."""
    resort_id = coerce_wishlist_resort_id(resort_id)
    user = _lock_user(session, user_id)
    old_ids, _ = canonical_wishlist_resorts(
        user.wish_list_resorts, session=session
    )
    if resort_id in old_ids:
        current_state_changed = user.wish_list_resorts != old_ids
        if current_state_changed:
            user.wish_list_resorts = old_ids
        session.flush()
        return WishlistChange(
            user=user,
            old_ids=old_ids,
            new_ids=old_ids,
            added_ids=[],
            removed_ids=[],
            current_state_changed=current_state_changed,
        )

    validate_wishlist_resort_ids(
        [resort_id], maximum=None, session=session
    )
    if len(old_ids) >= WISHLIST_LIMIT:
        session.flush()
        return WishlistChange(
            user=user,
            old_ids=old_ids,
            new_ids=old_ids,
            added_ids=[],
            removed_ids=[],
            current_state_changed=False,
            limit_reached=True,
        )

    new_ids = [*old_ids, resort_id]
    user.wish_list_resorts = new_ids
    _append_events(
        session,
        user_id=user.id,
        actor_user_id=actor_user_id,
        source=source,
        removed_ids=[],
        added_ids=[resort_id],
    )
    session.flush()
    return WishlistChange(
        user=user,
        old_ids=old_ids,
        new_ids=new_ids,
        added_ids=[resort_id],
        removed_ids=[],
        current_state_changed=True,
    )


def remove_wishlist_resort(
    session,
    *,
    user_id,
    resort_id,
    actor_user_id,
    source="mountain_detail",
):
    """Remove one canonical membership and clean legacy storage without history."""
    resort_id = coerce_wishlist_resort_id(resort_id)
    user = _lock_user(session, user_id)
    old_ids, _ = canonical_wishlist_resorts(
        user.wish_list_resorts, session=session
    )
    removed_ids = [resort_id] if resort_id in old_ids else []
    new_ids = [item for item in old_ids if item != resort_id]
    current_state_changed = user.wish_list_resorts != new_ids
    if current_state_changed:
        user.wish_list_resorts = new_ids
    _append_events(
        session,
        user_id=user.id,
        actor_user_id=actor_user_id,
        source=source,
        removed_ids=removed_ids,
        added_ids=[],
    )
    session.flush()
    return WishlistChange(
        user=user,
        old_ids=old_ids,
        new_ids=new_ids,
        added_ids=[],
        removed_ids=removed_ids,
        current_state_changed=current_state_changed,
    )


def rewrite_wishlists_for_resort_merge(
    session,
    *,
    duplicate_ids,
    canonical_id,
):
    """Normalize resort-merge maintenance under ordered locks without events."""
    duplicate_ids = {
        coerce_wishlist_resort_id(resort_id) for resort_id in duplicate_ids
    }
    canonical_id = coerce_wishlist_resort_id(canonical_id)
    users = session.execute(
        sa.select(User)
        .where(User.wish_list_resorts.is_not(None))
        .order_by(User.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars().all()

    rewritten = []
    candidate_ids = set()
    for user in users:
        normalized = normalize_wishlist_resort_ids(
            user.wish_list_resorts, strict=False
        )
        if duplicate_ids.isdisjoint(normalized):
            continue
        replaced = [
            canonical_id if resort_id in duplicate_ids else resort_id
            for resort_id in normalized
        ]
        new_ids = normalize_wishlist_resort_ids(replaced)
        rewritten.append((user, new_ids))
        candidate_ids.update(new_ids)

    eligible_ids = eligible_wishlist_resort_ids(
        candidate_ids, session=session
    )
    changed_count = 0
    for user, candidate in rewritten:
        new_ids = [
            resort_id for resort_id in candidate if resort_id in eligible_ids
        ][:WISHLIST_LIMIT]
        if user.wish_list_resorts != new_ids:
            user.wish_list_resorts = new_ids
            changed_count += 1
    session.flush()
    return changed_count
