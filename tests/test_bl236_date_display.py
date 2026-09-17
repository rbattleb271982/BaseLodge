from datetime import date

from services.date_display import format_date_range


def test_compact_date_range_convention():
    assert format_date_range(date(2027, 1, 4)) == "Jan 4"
    assert format_date_range(date(2027, 1, 4), date(2027, 1, 8)) == "Jan 4–8"
    assert (
        format_date_range(date(2027, 1, 31), date(2027, 2, 2))
        == "Jan 31–Feb 2"
    )


def test_prompt_date_range_convention_includes_unambiguous_year():
    assert (
        format_date_range(
            date(2027, 12, 31), date(2028, 1, 2), include_year=True
        )
        == "Dec 31, 2027–Jan 2, 2028"
    )