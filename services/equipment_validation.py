"""Validation helpers for optional numeric equipment measurements."""

import re


_INTEGER_TEXT = re.compile(r"^[0-9]+$")


def parse_nullable_measurement(
    value,
    *,
    field_label,
    minimum,
    maximum,
):
    """Return a bounded integer or None for an optional measurement.

    Empty values preserve the existing nullable-column behavior. Nonempty
    values must be integer text (or an actual integer from the JSON endpoint)
    and must fit the field's broad product sanity bounds.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(
            f"{field_label} must be an integer between {minimum} and {maximum}."
        )

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if not _INTEGER_TEXT.fullmatch(stripped):
            raise ValueError(
                f"{field_label} must be an integer between {minimum} and {maximum}."
            )
        parsed = int(stripped)
    else:
        raise ValueError(
            f"{field_label} must be an integer between {minimum} and {maximum}."
        )

    if not minimum <= parsed <= maximum:
        raise ValueError(
            f"{field_label} must be an integer between {minimum} and {maximum}."
        )
    return parsed