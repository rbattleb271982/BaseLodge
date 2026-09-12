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

    assert "home-foundation-card" in HEADER_TEMPLATE
    assert "home-pass-row" in HEADER_TEMPLATE
    assert "home-stat-band" in HEADER_TEMPLATE
    assert "home-friends-row" in HEADER_TEMPLATE


def test_home_long_trip_and_idea_copy_wrap_instead_of_being_truncated():
    css = _home_css()

    mountain_start = css.rindex(".home-page-container .home-next-trip__mountain")
    mountain_end = css.index("}", mountain_start)
    mountain_css = css[mountain_start:mountain_end]
    assert "white-space: normal;" in mountain_css
    assert "white-space: normal;" in mountain_css
    assert "text-overflow: ellipsis;" not in mountain_css

    meta_start = css.rindex(".home-page-container .home-next-trip__meta {")
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


def test_home_controls_keep_mobile_tap_targets_and_digest_density():
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

    assert ".bl-happening-digest {" in css
    assert "overflow: hidden;" in css
    assert ".bl-digest-item-copy { min-width: 0; }" in css


def test_next_trip_matches_round_11_g_and_defers_actions():
    assert "Next Trip" in NEXT_TRIP_TEMPLATE
    assert "ORGANIZING" in NEXT_TRIP_TEMPLATE
    assert "GOING" in NEXT_TRIP_TEMPLATE
    assert "Starts today" in NEXT_TRIP_TEMPLATE
    assert "Actions to take" not in NEXT_TRIP_TEMPLATE
    assert "home-next-trip__body" in NEXT_TRIP_TEMPLATE