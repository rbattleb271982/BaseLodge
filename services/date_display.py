"""Shared compact calendar-date presentation conventions."""


def format_date_range(start, end=None, *, include_year=False):
    """Format an inclusive range with abbreviated months and an en dash."""
    if not start:
        return ""
    end = end or start
    if start == end:
        return start.strftime("%b %-d, %Y" if include_year else "%b %-d")
    if start.year == end.year and start.month == end.month:
        suffix = end.strftime("%-d, %Y" if include_year else "%-d")
        return f"{start.strftime('%b %-d')}–{suffix}"
    if start.year == end.year:
        suffix = end.strftime("%b %-d, %Y" if include_year else "%b %-d")
        return f"{start.strftime('%b %-d')}–{suffix}"
    return (
        f"{start.strftime('%b %-d, %Y')}–"
        f"{end.strftime('%b %-d, %Y')}"
    )