"""Task 545 Home Ideas J presentation regressions."""

from types import SimpleNamespace

from app import app


def _row(
    *,
    idea_type,
    name,
    state="UT",
    date_range=None,
    line2="Supporting context",
    going_count=0,
    considering_count=0,
    key=None,
):
    return {
        "idea_type": idea_type,
        "resort": SimpleNamespace(
            id=1,
            name=name,
            slug=name.lower().replace(" ", "-"),
            state_code=state,
        ),
        "line2": line2,
        "date_range": date_range,
        "friend_count": going_count + considering_count,
        "going_count": going_count,
        "considering_count": considering_count,
        "signal_type": 1,
        "_card_key": key or f"{idea_type}:1",
        "_url": "/mountains/example",
    }


def _render(rows, *, has_availability=True):
    with app.test_request_context():
        return app.jinja_env.get_template(
            "partials/home/_section_opportunities.html"
        ).render(
            dest_feed=rows,
            ideas_count=len(rows),
            show_add_dates=not has_availability,
            has_availability=has_availability,
            user_avail_ranges=[{"display": "Feb 1–3"}, {"display": "Mar 4–6"}]
            if has_availability else [],
            user_avail_overflow=1 if has_availability else 0,
            home_activity_empty=False,
        )


def test_j_treatment_maps_every_supported_reason_without_inventing_types():
    html = _render([
        _row(
            idea_type="friend_trip",
            name="Sun Valley",
            going_count=3,
            line2="Win, Maeve + 1 other",
        ),
        _row(
            idea_type="friend_trip",
            name="St. Moritz",
            considering_count=1,
        ),
        _row(
            idea_type="availability_overlap",
            name="Courchevel",
        ),
        _row(
            idea_type="wishlist_overlap",
            name="Whistler Blackcomb",
        ),
        _row(
            idea_type="unsupported",
            name="Unsupported Mountain",
        ),
    ])

    assert "3 FRIENDS GOING" in html
    assert "FRIEND CONSIDERING" in html
    assert "DATES ALIGN" in html
    assert "WISHLIST OVERLAP" in html
    assert "Unsupported Mountain" not in html


def test_j_treatment_separates_destination_dates_support_and_dismissal():
    html = _render([
        _row(
            idea_type="friend_trip",
            name="Whistler Blackcomb",
            state="BC",
            date_range="Feb 20–27",
            line2="Anneliese and Konstantina are going",
            going_count=2,
        ),
    ])

    assert "Where you could go next" in html
    assert "Whistler Blackcomb, BC" in html
    assert 'class="bl-opp-date">Feb 20–27</span>' in html
    assert "Anneliese and Konstantina are going" in html
    assert 'aria-label="Dismiss"' in html
    assert "dismissIdeaCard(" in html


def test_ideas_footer_uses_only_viewer_window_count_and_canonical_editor():
    available_html = _render([
        _row(
            idea_type="wishlist_overlap",
            name="Alta",
            considering_count=2,
        ),
    ])
    unavailable_html = _render([
        _row(
            idea_type="wishlist_overlap",
            name="Alta",
            considering_count=2,
        ),
    ], has_availability=False)

    assert "Matched to your <strong>3</strong> free windows" in available_html
    assert "Edit availability" in available_html
    assert "Add free dates to make Ideas more relevant" in unavailable_html
    assert "Add availability" in unavailable_html
    assert 'href="/add-open-dates"' in available_html


def test_ideas_partial_contains_no_query_or_recommendation_logic():
    source = app.jinja_loader.get_source(
        app.jinja_env,
        "partials/home/_section_opportunities.html",
    )[0]
    assert "query(" not in source
    assert "get_home_ideas" not in source
    assert "build_destination_feed" not in source