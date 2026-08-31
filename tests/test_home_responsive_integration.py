"""BL-196 Home integration and responsive presentation regressions."""

from pathlib import Path


HOME_TEMPLATE = Path("templates/home.html").read_text()
HEADER_TEMPLATE = Path("templates/partials/home/_header.html").read_text()
NEXT_TRIP_TEMPLATE = Path("templates/partials/home/_next_trip.html").read_text()


def _home_css():
    start = HOME_TEMPLATE.index("<style>")
    end = HOME_TEMPLATE.index("</style>", start)
    return HOME_TEMPLATE[start:end]


def test_home_module_order_remains_the_approved_vertical_flow():
    assert HOME_TEMPLATE.index("partials/home/_header.html") < HOME_TEMPLATE.index(
        "partials/home/_next_trip.html"
    )
    assert HOME_TEMPLATE.index("partials/home/_next_trip.html") < HOME_TEMPLATE.index(
        "partials/home/_section_happening.html"
    )
    assert HOME_TEMPLATE.index(
        "partials/home/_section_happening.html"
    ) < HOME_TEMPLATE.index("partials/home/_section_opportunities.html")
    assert HOME_TEMPLATE.index(
        "partials/home/_section_opportunities.html"
    ) < HOME_TEMPLATE.index("partials/home/_section_pills.html")

    assert "partials/home/_about_you_gear.html" in HEADER_TEMPLATE
    assert "partials/home/_activity.html" in HEADER_TEMPLATE
    assert "partials/home/_section_friend_passes.html" in HEADER_TEMPLATE


def test_home_long_trip_and_idea_copy_wrap_instead_of_being_truncated():
    css = _home_css()

    mountain_start = css.index(".home-next-trip__mountain")
    mountain_end = css.index("}", mountain_start)
    mountain_css = css[mountain_start:mountain_end]
    assert "white-space: normal;" in mountain_css
    assert "overflow-wrap: anywhere;" in mountain_css
    assert "text-overflow: ellipsis;" not in mountain_css

    meta_start = css.index(".home-next-trip__meta")
    meta_end = css.index("}", meta_start)
    meta_css = css[meta_start:meta_end]
    assert "white-space: normal;" in meta_css
    assert "overflow-wrap: anywhere;" in meta_css

    for selector in (".bl-opp-primary", ".bl-opp-secondary"):
        start = css.index(selector)
        end = css.index("}", start)
        rule = css[start:end]
        assert "white-space: normal;" in rule
        assert "overflow-wrap: anywhere;" in rule
        assert "text-overflow: ellipsis;" not in rule


def test_home_controls_keep_mobile_tap_targets_and_wide_carousel_density():
    css = _home_css()

    pill_start = css.index(".bl-pill {")
    pill_end = css.index("}", pill_start)
    assert "min-height: 44px;" in css[pill_start:pill_end]

    close_start = css.index(".avail-sheet-close")
    close_end = css.index("}", close_start)
    close_css = css[close_start:close_end]
    assert "min-width: 44px;" in close_css
    assert "min-height: 44px;" in close_css

    cta_start = css.index(".bl-opp-empty-cta")
    cta_end = css.index("}", cta_start)
    assert "min-height: 44px;" in css[cta_start:cta_end]

    assert "@media (min-width: 700px)" in css
    wide_start = css.index("@media (min-width: 700px)")
    assert "flex-basis: 520px;" in css[wide_start:]


def test_next_trip_keeps_view_trip_separate_from_optional_actions():
    assert "View trip" in NEXT_TRIP_TEMPLATE
    assert "Actions to take" in NEXT_TRIP_TEMPLATE
    assert "Add pass" not in NEXT_TRIP_TEMPLATE