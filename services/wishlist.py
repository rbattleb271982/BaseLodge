"""Canonical wishlist normalization and validation."""

from dataclasses import dataclass

from models import Resort


WISHLIST_LIMIT = 15


@dataclass
class WishlistValidationError(ValueError):
    message: str
    code: str = "invalid_wishlist"

    def __str__(self):
        return self.message


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


def _eligible_resorts_by_id(resort_ids):
    if not resort_ids:
        return {}
    resorts = Resort.query.filter(
        Resort.id.in_(resort_ids),
        Resort.is_active.is_(True),
        Resort.is_region.is_(False),
    ).all()
    return {resort.id: resort for resort in resorts}


def eligible_wishlist_resort_ids(resort_ids):
    """Return eligible IDs from one bulk Resort query."""
    return set(_eligible_resorts_by_id(resort_ids))


def validate_wishlist_resort_ids(raw_ids, *, maximum=WISHLIST_LIMIT):
    """Strictly validate a submitted wishlist with one bounded Resort query."""
    normalized = normalize_wishlist_resort_ids(raw_ids)
    eligible_by_id = _eligible_resorts_by_id(normalized)
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


def canonical_wishlist_resorts(raw_ids, *, maximum=WISHLIST_LIMIT):
    """Tolerantly resolve legacy JSON to eligible resorts in stored order."""
    normalized = normalize_wishlist_resort_ids(raw_ids, strict=False)
    eligible_by_id = _eligible_resorts_by_id(normalized)
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