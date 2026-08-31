"""Focused contract tests for the reusable Home disclosure foundation."""

import json
from pathlib import Path
import re

from app import app


MACRO_TEMPLATE = Path("templates/macros/home_disclosure.html").read_text()
HOME_TEMPLATE = Path("templates/home.html").read_text()


def _render_disclosures(*disclosures):
    calls = "\n".join(
        f"""
        {{% call home_disclosure(
            {json.dumps(disclosure_id)},
            {json.dumps(title, ensure_ascii=False)},
            {json.dumps(summary, ensure_ascii=False)}
        ) %}}
            <p>{content}</p>
        {{% endcall %}}
        """
        for disclosure_id, title, summary, content in disclosures
    )
    source = f"""
    {{% from 'macros/home_disclosure.html' import home_disclosure %}}
    {calls}
    """
    with app.app_context():
        return app.jinja_env.from_string(source).render()


def _disclosure_css():
    start = HOME_TEMPLATE.index("/* ── BL-188 collapsed disclosure foundation ── */")
    end = HOME_TEMPLATE.index("/* ── Section label ── */", start)
    return HOME_TEMPLATE[start:end]


def test_home_disclosure_uses_native_closed_details_and_caller_content():
    html = _render_disclosures(
        ("about-you", "About You", "Skier · Intermediate", "Gear details")
    )

    assert '<details id="about-you" class="home-disclosure">' in html
    assert "<summary" in html
    assert "About You" in html
    assert "Skier · Intermediate" in html
    assert "Gear details" in html
    assert 'id="about-you-title"' in html
    assert 'id="about-you-panel"' in html
    assert 'role="region"' in html
    assert 'aria-labelledby="about-you-title"' in html
    assert " open" not in html
    assert html.count("home-disclosure__chevron") == 1
    assert 'aria-hidden="true"' in html
    assert 'focusable="false"' in html


def test_home_disclosure_has_no_custom_control_or_persistence_hooks():
    assert 'role="button"' not in MACRO_TEMPLATE
    assert "tabindex" not in MACRO_TEMPLATE
    assert "aria-expanded" not in MACRO_TEMPLATE
    assert "aria-controls" not in MACRO_TEMPLATE
    assert "onclick" not in MACRO_TEMPLATE
    assert "onkeydown" not in MACRO_TEMPLATE
    assert "localStorage" not in MACRO_TEMPLATE
    assert "sessionStorage" not in MACRO_TEMPLATE
    assert "function" not in MACRO_TEMPLATE


def test_multiple_home_disclosures_have_independent_unique_ids():
    html = _render_disclosures(
        ("activity", "Your Activity", "2 upcoming trips", "Activity content"),
        ("passes", "Friends' Passes", "3 friends", "Pass content"),
    )

    assert html.count("<details") == 2
    assert html.count("<summary") == 2
    assert html.count('id="activity"') == 1
    assert html.count('id="activity-title"') == 1
    assert html.count('id="activity-panel"') == 1
    assert html.count('id="passes"') == 1
    assert html.count('id="passes-title"') == 1
    assert html.count('id="passes-panel"') == 1
    assert html.count("home-disclosure__chevron") == 2


def test_home_disclosure_escapes_long_title_and_summary_without_clipping():
    title = "A very long module title " * 8 + "<unsafe>"
    summary = "A very long summary with a pass name " * 8 + "<unsafe>"
    html = _render_disclosures(("long-copy", title, summary, "Expanded content"))

    assert title.replace("<", "&lt;").replace(">", "&gt;") in html
    assert summary.replace("<", "&lt;").replace(">", "&gt;") in html
    assert "<unsafe>" not in html


def test_home_disclosure_css_preserves_mobile_accessibility_contract():
    css = _disclosure_css()

    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert "min-height: 44px;" in css
    assert "width: 100%;" in css
    assert "overflow-wrap: anywhere;" in css
    assert "white-space: normal;" in css
    assert ":focus-visible" in css
    assert ".home-disclosure[open] .home-disclosure__collapsed" in css
    assert ".home-disclosure[open] > .home-disclosure__summary .home-disclosure__chevron" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "transition: none;" in css
    assert "max-height" not in css
    assert re.search(r"(?<![-\w])height\s*:", css) is None


def test_home_disclosure_does_not_change_existing_home_composition():
    assert "partials/home/_header.html" in HOME_TEMPLATE
    assert "partials/home/_header_empty.html" in HOME_TEMPLATE
    assert "partials/home/_section_happening.html" in HOME_TEMPLATE
    assert "partials/home/_section_opportunities.html" in HOME_TEMPLATE
    assert "partials/home/_section_friend_passes.html" not in HOME_TEMPLATE
    assert "home_summary" not in HOME_TEMPLATE