"""Task 539 keeps response actions out of the Round 11 G top treatment."""

from pathlib import Path


NEXT_TRIP_TEMPLATE = Path("templates/partials/home/_next_trip.html").read_text()


def test_round_11_g_defers_actions_to_the_following_home_batch():
    assert "Actions to take" not in NEXT_TRIP_TEMPLATE
    assert "home-next-trip__actions" not in NEXT_TRIP_TEMPLATE
    assert "action.destination" not in NEXT_TRIP_TEMPLATE
    assert "action.label" not in NEXT_TRIP_TEMPLATE


def test_round_11_g_next_trip_is_one_trip_detail_link():
    assert "url_for('trip_detail', trip_id=_trip.id)" in NEXT_TRIP_TEMPLATE
    assert 'class="home-next-trip__body"' in NEXT_TRIP_TEMPLATE
    assert "home-next-trip__countdown" in NEXT_TRIP_TEMPLATE


def test_round_11_g_template_contains_no_query_or_write_logic():
    assert "query(" not in NEXT_TRIP_TEMPLATE
    assert "fetch(" not in NEXT_TRIP_TEMPLATE
    assert "<script" not in NEXT_TRIP_TEMPLATE
    assert "INTERESTED" not in NEXT_TRIP_TEMPLATE
    assert "pending" not in NEXT_TRIP_TEMPLATE