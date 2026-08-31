"""Canonical BaseLodge ski-season boundaries and labels."""

from datetime import date


def get_ski_season_year(value):
    """Return ``(start_year, end_year)`` for the season containing ``value``.

    BaseLodge seasons run inclusively from June 1 through May 31.
    """
    if value.month < 6:
        return value.year - 1, value.year
    return value.year, value.year + 1


def get_ski_season_start_year(value=None):
    """Return the integer storage key for the season containing ``value``."""
    value = value or date.today()
    return get_ski_season_year(value)[0]


def get_ski_season_label(value):
    """Return a display label such as ``2026/27``."""
    start_year, end_year = get_ski_season_year(value)
    return f"{start_year}/{str(end_year)[2:]}"


def get_ski_season_window(value):
    """Return the inclusive ``(June 1, May 31)`` window for ``value``."""
    start_year, end_year = get_ski_season_year(value)
    return date(start_year, 6, 1), date(end_year, 5, 31)