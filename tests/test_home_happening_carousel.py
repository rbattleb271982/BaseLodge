"""Home Happening M digest presentation regressions."""

from pathlib import Path

from app import app


HAPPENING_TEMPLATE = Path(
    "templates/partials/home/_section_happening.html"
).read_text()
HOME_TEMPLATE = Path("templates/home.html").read_text()


def _item(index, *, trip=True):
    return {
        "headline": f"Friend {index} joined",
        "detail": f"{index} going · {index} of {index + 1} answered",
        "resort_name": f"Peak {index}" if trip else None,
        "date_range": "Feb 10–12" if trip else None,
        "trip_id": index if trip else None,
        "card_keys": [f"happening:rsvp:{index}"],
    }


def _render(categories):
    with app.test_request_context():
        return app.jinja_env.get_template(
            "partials/home/_section_happening.html"
        ).render(happening_digest=categories)


def test_happening_uses_fixed_m_digest_hierarchy():
    html = _render([
        {"key": "on_your_trips", "label": "ON YOUR TRIPS", "items": [_item(1)], "overflow": 0},
        {"key": "trips_forming", "label": "TRIPS FORMING", "items": [_item(2)], "overflow": 0},
        {"key": "your_people", "label": "YOUR PEOPLE", "items": [_item(3, trip=False)], "overflow": 0},
    ])
    assert html.index("ON YOUR TRIPS") < html.index("TRIPS FORMING") < html.index("YOUR PEOPLE")
    assert "Last 7 days" in html
    assert 'aria-label="Happening activity digest"' in html
    assert "bl-happening-rows" not in html


def test_happening_renders_bounded_rows_overflow_and_dismissal_keys():
    html = _render([
        {
            "key": "trips_forming",
            "label": "TRIPS FORMING",
            "items": [_item(1), _item(2), _item(3)],
            "overflow": 4,
        },
    ])
    assert html.count('class="bl-digest-item"') == 3
    assert "4 more" in html
    assert "Peak 1" in html
    assert "Feb 10–12" in html
    assert "dismissHappeningDigest" in html
    assert "happening:rsvp:1" in html


def test_happening_meaningful_copy_wraps_without_query_or_inline_script():
    assert "overflow-wrap: anywhere;" in HOME_TEMPLATE
    assert "white-space: normal;" in HOME_TEMPLATE
    assert "query(" not in HAPPENING_TEMPLATE
    assert "fetch(" not in HAPPENING_TEMPLATE
    assert "<script" not in HAPPENING_TEMPLATE