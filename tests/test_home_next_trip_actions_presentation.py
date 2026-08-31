"""BL-194 presentation tests for canonical Home Next Trip actions."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app import app


NEXT_TRIP_TEMPLATE_PATH = Path("templates/partials/home/_next_trip.html")
NEXT_TRIP_TEMPLATE = NEXT_TRIP_TEMPLATE_PATH.read_text()


def _render_next_trip(actions=None, action_count=None):
    trip = SimpleNamespace(
        id=41,
        user_id=7,
        mountain="Test Peak",
        resort=None,
        start_date=date(2027, 1, 10),
        end_date=date(2027, 1, 11),
        attendance_start_date=date(2027, 1, 10),
        attendance_end_date=date(2027, 1, 11),
    )
    resolved_actions = [] if actions is None else actions
    summary = {
        "next_trip": {
            "trip": trip,
            "is_owner": True,
            "friends_going_count": 0,
            "actions": resolved_actions,
            "action_count": (
                len(resolved_actions)
                if action_count is None
                else action_count
            ),
        }
    }
    with app.test_request_context():
        return app.jinja_env.get_template(
            "partials/home/_next_trip.html"
        ).render(
            home_summary=summary,
            home_today=date(2027, 1, 1),
        )


def test_actions_row_is_collapsed_and_renders_server_ordered_canonical_actions():
    actions = [
        {
            "key": "future-key-1",
            "type": "future_action_type",
            "label": "Review join requests",
            "destination": "/trips/41#td-join-requests",
            "priority": 20,
        },
        {
            "key": "future-key-2",
            "type": "another_future_action_type",
            "label": "Review RSVP",
            "destination": "/trips/41#td-self-rsvp",
            "priority": 10,
        },
    ]

    html = _render_next_trip(actions)

    assert '<details id="next-trip-actions" class="home-disclosure home-next-trip__actions">' in html
    assert "Actions to take · 2" in html
    assert "open" not in html.split("<details", 1)[1].split(">", 1)[0]
    assert '<summary class="home-disclosure__summary">' in html
    assert 'aria-hidden="true"' in html
    assert "home-disclosure__arrow" in html
    assert ">↓</span>" in html
    assert 'role="region"' in html
    assert 'aria-labelledby="next-trip-actions-title"' in html
    assert 'href="/trips/41#td-join-requests"' in html
    assert 'href="/trips/41#td-self-rsvp"' in html
    assert html.index("Review join requests") < html.index("Review RSVP")
    assert "future-key-1" not in html
    assert "future_action_type" not in html
    assert "another_future_action_type" not in html
    assert ">20<" not in html
    assert ">10<" not in html


def test_zero_actions_omit_disclosure_without_changing_view_trip_cta():
    html = _render_next_trip([], action_count=0)

    assert "Actions to take" not in html
    assert "home-next-trip__actions" not in html
    assert 'href="/trips/41"' in html
    assert "View trip" in html


def test_action_template_consumes_contract_without_eligibility_or_query_logic():
    assert "action.destination" in NEXT_TRIP_TEMPLATE
    assert "action.label" in NEXT_TRIP_TEMPLATE
    assert "action.key" not in NEXT_TRIP_TEMPLATE
    assert "action.type" not in NEXT_TRIP_TEMPLATE
    assert "action.priority" not in NEXT_TRIP_TEMPLATE
    assert "INTERESTED" not in NEXT_TRIP_TEMPLATE
    assert "GOING" not in NEXT_TRIP_TEMPLATE
    assert "pending" not in NEXT_TRIP_TEMPLATE
    assert "query(" not in NEXT_TRIP_TEMPLATE
    assert "fetch(" not in NEXT_TRIP_TEMPLATE
    assert "sort(" not in NEXT_TRIP_TEMPLATE
    assert "selectattr" not in NEXT_TRIP_TEMPLATE
    assert "<script" not in NEXT_TRIP_TEMPLATE


def test_actions_disclosure_uses_native_keyboard_accessible_primitive():
    html = _render_next_trip([{
        "key": "review-rsvp",
        "type": "review_rsvp",
        "label": "Review RSVP",
        "destination": "/trips/41#td-self-rsvp",
        "priority": 10,
    }])

    assert "<details" in html
    assert "<summary" in html
    assert "onclick" not in html
    assert "onkeydown" not in html
    assert "localStorage" not in html
    assert "sessionStorage" not in html
    assert "home-disclosure__chevron" not in html
    assert "home-disclosure__arrow" in html