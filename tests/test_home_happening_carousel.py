"""BL-195 Home Happening carousel presentation regressions."""

from pathlib import Path

from app import app


HAPPENING_TEMPLATE_PATH = Path(
    "templates/partials/home/_section_happening.html"
)
HAPPENING_TEMPLATE = HAPPENING_TEMPLATE_PATH.read_text()


def _signal(index):
    return {
        "person": f"Friend {index}",
        "action_verb": "Planning",
        "mountain": f"Peak {index}",
        "recency_label": "Added today",
        "friend_id": index,
        "_card_key": f"happening:{index}",
    }


def _render(signals):
    with app.test_request_context():
        return app.jinja_env.get_template(
            "partials/home/_section_happening.html"
        ).render(happening_signals=signals)


def test_happening_section_uses_native_horizontal_carousel_structure():
    assert 'class="bl-happening-rows"' in HAPPENING_TEMPLATE
    assert 'role="region"' in HAPPENING_TEMPLATE
    assert 'aria-label="Happening updates"' in HAPPENING_TEMPLATE
    assert "overflow-x: auto" in Path("templates/home.html").read_text()
    assert "scroll-snap-type: x proximity" in Path("templates/home.html").read_text()
    assert "-webkit-overflow-scrolling: touch" in Path(
        "templates/home.html"
    ).read_text()


def test_happening_cards_are_compact_width_with_a_visible_next_card_peek():
    home_template = Path("templates/home.html").read_text()

    assert "flex: 0 0 78%" in home_template
    assert "gap: 12px" in home_template
    assert "scroll-snap-align: start" in home_template
    assert "width: 100%" in home_template
    assert "max-width: 100%" in home_template


def test_happening_renders_five_server_ordered_cards_and_dismiss_controls():
    html = _render([_signal(index) for index in range(1, 6)])

    assert html.count('class="bl-happening-card"') == 5
    assert html.count('class="bl-happening-dismiss"') == 5
    assert html.count("dismissInsightCard('happening'") == 5
    assert [
        html.index(f"Friend {index}") for index in range(1, 6)
    ] == sorted(html.index(f"Friend {index}") for index in range(1, 6))
    assert "Peak 1" in html
    assert "Added today" in html


def test_happening_presentation_does_not_add_queries_or_carousel_javascript():
    assert "query(" not in HAPPENING_TEMPLATE
    assert "fetch(" not in HAPPENING_TEMPLATE
    assert "<script" not in HAPPENING_TEMPLATE
    assert "dismissInsightCard(" in HAPPENING_TEMPLATE