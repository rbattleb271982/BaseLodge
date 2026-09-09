"""Pure presentation helpers for the owner-only Open to Ski share preview."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


MAX_SELECTED_DAYS = 31
MAX_DISPLAY_RANGES = 12
EXPORT_WIDTH = 1080
EXPORT_HEIGHT = 1350
ASPECT_RATIO = "4:5"


class OpenToSkiSelectionError(ValueError):
    """Raised when a reviewed Open to Ski selection cannot produce a preview."""


@dataclass(frozen=True)
class _DateRange:
    start: date
    end: date


def _parse_iso_dates(values):
    parsed = set()
    for value in values:
        if not isinstance(value, str):
            raise OpenToSkiSelectionError("Review your selected dates and try again.")
        try:
            parsed_value = date.fromisoformat(value)
        except ValueError as exc:
            raise OpenToSkiSelectionError(
                "Review your selected dates and try again."
            ) from exc
        if parsed_value.isoformat() != value:
            raise OpenToSkiSelectionError("Review your selected dates and try again.")
        parsed.add(parsed_value)
    return sorted(parsed)


def _contiguous_ranges(values):
    if not values:
        return []
    ranges = []
    start = previous = values[0]
    for current in values[1:]:
        if current == previous + timedelta(days=1):
            previous = current
            continue
        ranges.append(_DateRange(start=start, end=previous))
        start = previous = current
    ranges.append(_DateRange(start=start, end=previous))
    return ranges


def _split_range_by_month(value):
    segments = []
    current = value.start
    while current <= value.end:
        month_end = date(
            current.year,
            current.month,
            calendar.monthrange(current.year, current.month)[1],
        )
        segment_end = min(value.end, month_end)
        segments.append(_DateRange(start=current, end=segment_end))
        current = segment_end + timedelta(days=1)
    return segments


def _range_label(value):
    if value.start == value.end:
        return str(value.start.day)
    return f"{value.start.day}–{value.end.day}"


def _accessible_range_label(value):
    if value.start == value.end:
        return value.start.strftime("%B %-d, %Y")
    return (
        f"{value.start.strftime('%B %-d, %Y')} through "
        f"{value.end.strftime('%B %-d, %Y')}"
    )


def _density_for(month_count, range_count):
    if month_count <= 1 and range_count <= 2:
        return "sparse", 1
    if month_count <= 2 and range_count <= 5:
        return "normal", 1
    if month_count <= 4 and range_count <= 8:
        return "compact", 2
    return "dense", 2


def _distribute_months(month_groups, column_count):
    if column_count == 1:
        return [month_groups]
    columns = []
    remaining = list(month_groups)
    for column_index in range(column_count):
        columns_left = column_count - column_index
        if columns_left == 1:
            columns.append(remaining)
            break
        remaining_weight = sum(len(group["ranges"]) + 1 for group in remaining)
        target_weight = remaining_weight / columns_left
        column = []
        column_weight = 0
        while len(remaining) > columns_left - 1:
            group = remaining[0]
            group_weight = len(group["ranges"]) + 1
            if column and column_weight + group_weight > target_weight:
                break
            column.append(remaining.pop(0))
            column_weight += group_weight
        columns.append(column)
    return columns


def group_open_to_ski_dates(values):
    """Return deterministic month groups and layout metadata for selected dates."""
    parsed = _parse_iso_dates(values)
    if not parsed:
        raise OpenToSkiSelectionError(
            "Select at least one future date to create your preview."
        )
    if len(parsed) > MAX_SELECTED_DAYS:
        raise OpenToSkiSelectionError(
            f"Choose no more than {MAX_SELECTED_DAYS} calendar days."
        )

    segments = [
        segment
        for value in _contiguous_ranges(parsed)
        for segment in _split_range_by_month(value)
    ]
    if len(segments) > MAX_DISPLAY_RANGES:
        raise OpenToSkiSelectionError(
            f"Choose dates that create no more than {MAX_DISPLAY_RANGES} ranges."
        )

    month_groups = []
    current_key = None
    for segment in segments:
        key = (segment.start.year, segment.start.month)
        if key != current_key:
            month_groups.append({
                "key": f"{segment.start.year}-{segment.start.month:02d}",
                "label": segment.start.strftime("%b %Y").upper(),
                "ranges": [],
            })
            current_key = key
        month_groups[-1]["ranges"].append({
            "start": segment.start.isoformat(),
            "end": segment.end.isoformat(),
            "label": _range_label(segment),
            "accessible_label": _accessible_range_label(segment),
        })

    density, column_count = _density_for(len(month_groups), len(segments))
    first = parsed[0]
    last = parsed[-1]
    period_label = (
        first.strftime("%B %Y")
        if first.year == last.year and first.month == last.month
        else f"{first.strftime('%B %Y')} — {last.strftime('%B %Y')}"
    )
    accessible_summary = ", ".join(
        item["accessible_label"]
        for group in month_groups
        for item in group["ranges"]
    )
    return {
        "selected_dates": [value.isoformat() for value in parsed],
        "selected_count": len(parsed),
        "range_count": len(segments),
        "month_count": len(month_groups),
        "month_groups": month_groups,
        "columns": _distribute_months(month_groups, column_count),
        "density": density,
        "column_count": column_count,
        "period_label": period_label,
        "accessible_summary": accessible_summary,
    }


def build_open_to_ski_page_model(
    *,
    first_name,
    eligible_values,
    selected_values=None,
    ready=False,
    error=None,
    availability_changed=False,
):
    """Build the explicit allowlist passed to the Open to Ski template."""
    eligible_dates = _parse_iso_dates(eligible_values)
    selected_dates = _parse_iso_dates(
        eligible_values if selected_values is None else selected_values
    )
    selection_notice = None
    if selected_dates and len(selected_dates) <= MAX_SELECTED_DAYS:
        try:
            group_open_to_ski_dates(
                [value.isoformat() for value in selected_dates]
            )
        except OpenToSkiSelectionError as exc:
            selection_notice = str(exc)
    grouped = group_open_to_ski_dates(
        [value.isoformat() for value in selected_dates]
    ) if ready else None
    return {
        "brand": "BASELODGE",
        "first_name": first_name or "I’m",
        "eligible_dates": [
            {
                "value": value.isoformat(),
                "label": value.strftime("%A, %B %-d, %Y"),
                "month_label": value.strftime("%B %Y"),
            }
            for value in eligible_dates
        ],
        "selected_dates": {value.isoformat() for value in selected_dates},
        "eligible_count": len(eligible_dates),
        "ready": ready,
        "error": error,
        "availability_changed": availability_changed,
        "max_selected_days": MAX_SELECTED_DAYS,
        "max_display_ranges": MAX_DISPLAY_RANGES,
        "selection_notice": selection_notice,
        "card": None if grouped is None else {
            "brand": "BASELODGE",
            "first_name": first_name or "I’m",
            "headline": "OPEN TO SKI",
            "period_label": grouped["period_label"],
            "columns": grouped["columns"],
            "density": grouped["density"],
            "column_count": grouped["column_count"],
            "selected_count": grouped["selected_count"],
            "range_count": grouped["range_count"],
            "snapshot_label": "Availability snapshot",
            "footer": "Check with me before planning",
            "accessible_summary": grouped["accessible_summary"],
            "export_width": EXPORT_WIDTH,
            "export_height": EXPORT_HEIGHT,
            "aspect_ratio": ASPECT_RATIO,
        },
        "empty_message": (
            "Choose future dates you're open to ski. Then share them with friends."
        ),
    }