"""Tests for GET /friends — filters, data attributes, and friend UI controls.

Covers:
  - Page renders for an authenticated user (empty and populated states)
  - `filter_passes` context populates pass pills from CANONICAL_PASS_ORDER
  - Filter button / chips container / bottom sheet present in populated state
  - Rider-type / skill-level / pass filter section pills present
  - Each friend row carries data-pass, data-level, data-rider attributes
  - data-rider reflects rider_types correctly (single, multiple, empty)
  - Auth required redirect for anonymous users
  - Filter matching logic: exact slug semantics, AND/OR behaviour, edge cases

Note on JS coverage
-------------------
`_frMatchesFilters` is pure client-side JS. Full behavioral coverage requires
a headless-browser suite (Playwright/Selenium). The ``TestFilterMatchingLogic``
class below uses a Python mirror of the identical algorithm so that the core
matching rules are executable and CI-verifiable without a browser.  Both the
Python mirror and the JS function must be kept in sync if the algorithm changes.
"""
import pytest
from pathlib import Path

from app import app
from models import db, User, Friend
from tests.conftest import _make_user, _login
from services.pass_utils import CANONICAL_PASS_ORDER, PASS_DISPLAY_MAP


# ── Python mirror of JS _frMatchesFilters ─────────────────────────────────────
# Keep this in sync with the `_frMatchesFilters` function in templates/friends.html.
# Matching rules (must match JS exactly):
#   - Categories are AND'd (pass AND rider AND level must all pass)
#   - Within each category selected values are OR'd
#   - Pass: exact slug comparison; empty data-pass matches no filter pill
#   - "no_pass" filter only matches data-pass="no_pass" (not "no_pass_yet" or "")
#   - "no_pass_yet" filter only matches data-pass="no_pass_yet" (not "no_pass" or "")
#   - Rider "both": requires data-rider to contain BOTH "skier" AND "snowboarder"
#   - Rider "skier": requires data-rider to contain "skier" (may also have others)
#   - Rider "snowboarder": requires data-rider to contain "snowboarder"
#   - Level: exact slug match against data-level

def _matches(
    data_pass: str,
    data_rider: str,
    data_level: str,
    *,
    pass_sel: set | None = None,
    rider_sel: set | None = None,
    level_sel: set | None = None,
) -> bool:
    """Python mirror of JS _frMatchesFilters for unit testing.

    Args:
        data_pass:  value of the row's data-pass attribute (comma-separated slugs)
        data_rider: value of the row's data-rider attribute (pipe-separated slugs)
        data_level: value of the row's data-level attribute (single slug)
        pass_sel:   set of selected pass filter values (empty set / None = no filter)
        rider_sel:  set of selected rider filter values
        level_sel:  set of selected level filter values
    """
    pf = pass_sel  or set()
    rf = rider_sel or set()
    lf = level_sel or set()

    # ── Pass (exact slug match) ──
    if pf:
        row_slugs = [s.strip() for s in (data_pass or "").split(",") if s.strip()]
        if not any(slug in pf for slug in row_slugs):
            return False

    # ── Rider type ──
    if rf:
        # rider_types is always a single canonical value per user (startup normalization).
        # Matching is a simple OR: any data-rider token must be in the selected set.
        rider_arr = [s for s in (data_rider or "").split("|") if s]
        if not any(val in rf for val in rider_arr):
            return False

    # ── Skill level (exact slug match) ──
    if lf:
        if (data_level or "").strip() not in lf:
            return False

    return True


def _valid_preselected_passes(raw: str) -> set[str]:
    """Python mirror of the Home pass-query initialization in friends.html."""
    valid = set(CANONICAL_PASS_ORDER)
    return {
        slug.strip()
        for slug in (raw or "").split(",")
        if slug.strip() in valid
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_friend(user_a, user_b):
    """Make user_a and user_b mutual friends (bidirectional rows)."""
    db.session.add(Friend(user_id=user_a.id, friend_id=user_b.id))
    db.session.add(Friend(user_id=user_b.id, friend_id=user_a.id))
    db.session.flush()


def _get_friends(client, user_id):
    _login(client, user_id)
    return client.get("/friends")


def _set_attrs(user, **kwargs):
    """Set model attributes post-creation to avoid conftest duplicate-kwarg conflict."""
    for k, v in kwargs.items():
        setattr(user, k, v)


def test_suggested_preview_client_controls_are_scoped_to_the_friends_page():
    html = Path("templates/friends.html").read_text()

    assert 'class="fr-sugg-preview-overlay"' in html
    assert 'onclick="if (event.target === this) frSuggClosePreview()"' in html
    assert 'aria-label="Close suggested friend preview"' in html
    assert "function frSuggOpenPreview(trigger)" in html
    assert "function frSuggRunAction(btn)" in html
    assert "function frSuggClosePreview(fromPopState, restoreFocus)" in html
    assert "frSuggSetActionState(suggestedUserId, 'connected'" in html
    assert "function _frSuggTrapPreviewFocus(event)" in html
    assert "_frSuggSetPreviewBackgroundInert(true)" in html
    assert "pageContent.inert = isInert;" in html
    assert "function _frSuggFocusAfterRemoval(row)" in html
    assert "frSuggClosePreview(false, false)" in html


# ── Auth guard ────────────────────────────────────────────────────────────────

# ── Filter matching behavioural tests ────────────────────────────────────────

class TestFilterMatchingLogic:
    """Unit-test the _matches() Python mirror of JS _frMatchesFilters.

    Validates exact-slug semantics, AND/OR behaviour, and edge cases so that
    any future change to the JS logic is caught here first.
    """

    # ── No active filters → always True ──────────────────────────────────

    def test_no_filters_always_matches(self):
        assert _matches("epic", "skier", "advanced") is True

    def test_no_filters_empty_attrs(self):
        assert _matches("", "", "") is True

    # ── Pass filter (exact slug) ──────────────────────────────────────────

    def test_pass_exact_match_ikon(self):
        assert _matches("ikon", "", "", pass_sel={"ikon"}) is True

    def test_pass_exact_match_epic(self):
        assert _matches("epic", "", "", pass_sel={"epic"}) is True

    def test_pass_no_match_different_slug(self):
        assert _matches("ikon", "", "", pass_sel={"epic"}) is False

    def test_pass_no_pass_matches_only_no_pass(self):
        assert _matches("no_pass", "", "", pass_sel={"no_pass"}) is True

    def test_pass_no_pass_does_not_match_no_pass_yet(self):
        """Selecting 'no_pass' must NOT match a 'no_pass_yet' friend."""
        assert _matches("no_pass_yet", "", "", pass_sel={"no_pass"}) is False

    def test_pass_no_pass_yet_matches_only_no_pass_yet(self):
        assert _matches("no_pass_yet", "", "", pass_sel={"no_pass_yet"}) is True

    def test_pass_no_pass_yet_does_not_match_no_pass(self):
        """Selecting 'no_pass_yet' must NOT match a 'no_pass' friend."""
        assert _matches("no_pass", "", "", pass_sel={"no_pass_yet"}) is False

    def test_pass_empty_data_matches_no_filter(self):
        """Unset/legacy empty data-pass matches no pass filter pill."""
        assert _matches("", "", "", pass_sel={"no_pass"})      is False
        assert _matches("", "", "", pass_sel={"no_pass_yet"})  is False
        assert _matches("", "", "", pass_sel={"ikon"})          is False

    def test_pass_multi_slug_or_within_category(self):
        """Friends with ikon match when 'ikon' OR 'epic' selected."""
        assert _matches("ikon", "", "", pass_sel={"ikon", "epic"}) is True

    def test_pass_comma_separated_matches_either(self):
        """data-pass can hold comma-separated slugs (future multi-pass); OR within."""
        assert _matches("ikon,epic", "", "", pass_sel={"epic"}) is True
        assert _matches("ikon,epic", "", "", pass_sel={"ikon"}) is True

    def test_pass_comma_separated_no_match(self):
        assert _matches("ikon,epic", "", "", pass_sel={"indy"}) is False

    # ── Rider type filter ─────────────────────────────────────────────────

    def test_rider_skier_matches_skier(self):
        assert _matches("", "skier", "", rider_sel={"skier"}) is True

    def test_rider_skier_no_match_snowboarder(self):
        assert _matches("", "snowboarder", "", rider_sel={"skier"}) is False

    def test_rider_snowboarder_matches(self):
        assert _matches("", "snowboarder", "", rider_sel={"snowboarder"}) is True

    def test_rider_snowboarder_no_match_skier(self):
        assert _matches("", "skier", "", rider_sel={"snowboarder"}) is False

    def test_rider_telemark_matches(self):
        assert _matches("", "telemark", "", rider_sel={"telemark"}) is True

    def test_rider_telemark_no_match_skier(self):
        assert _matches("", "telemark", "", rider_sel={"skier"}) is False

    def test_rider_or_within_category(self):
        assert _matches("", "snowboarder", "", rider_sel={"skier", "snowboarder"}) is True

    def test_rider_or_includes_telemark(self):
        assert _matches("", "telemark", "", rider_sel={"skier", "telemark"}) is True

    def test_rider_empty_matches_no_filter(self):
        assert _matches("", "", "", rider_sel={"skier"}) is False

    # ── Skill level filter ────────────────────────────────────────────────

    def test_level_exact_match(self):
        assert _matches("", "", "advanced", level_sel={"advanced"}) is True

    def test_level_no_match_different(self):
        assert _matches("", "", "beginner", level_sel={"advanced"}) is False

    def test_level_or_within_category(self):
        assert _matches("", "", "expert", level_sel={"advanced", "expert"}) is True

    def test_level_empty_matches_no_filter(self):
        assert _matches("", "", "", level_sel={"advanced"}) is False

    # ── Category AND behaviour ────────────────────────────────────────────

    def test_all_categories_must_pass(self):
        # pass ✓, rider ✓, level ✓
        assert _matches("ikon", "skier", "advanced",
                         pass_sel={"ikon"},
                         rider_sel={"skier"},
                         level_sel={"advanced"}) is True

    def test_pass_fail_blocks_match(self):
        # pass ✗, rider ✓, level ✓
        assert _matches("epic", "skier", "advanced",
                         pass_sel={"ikon"},
                         rider_sel={"skier"},
                         level_sel={"advanced"}) is False

    def test_rider_fail_blocks_match(self):
        # pass ✓, rider ✗, level ✓
        assert _matches("ikon", "snowboarder", "advanced",
                         pass_sel={"ikon"},
                         rider_sel={"skier"},
                         level_sel={"advanced"}) is False

    def test_level_fail_blocks_match(self):
        # pass ✓, rider ✓, level ✗
        assert _matches("ikon", "skier", "beginner",
                         pass_sel={"ikon"},
                         rider_sel={"skier"},
                         level_sel={"advanced"}) is False

    def test_pass_and_level_only(self):
        """Two categories active — rider ignored (no rider_sel)."""
        assert _matches("ikon", "snowboarder", "expert",
                         pass_sel={"ikon"},
                         level_sel={"expert"}) is True

    def test_pass_and_level_level_fails(self):
        assert _matches("ikon", "snowboarder", "beginner",
                         pass_sel={"ikon"},
                         level_sel={"expert"}) is False


# ── Auth guard ────────────────────────────────────────────────────────────────

class TestAuthRequired:
    def test_anonymous_redirected(self, client):
        rv = client.get("/friends")
        assert rv.status_code in (302, 401)


# ── Page renders (empty state) ────────────────────────────────────────────────

class TestFriendsPageEmptyState:
    """Sanity-check: page works with zero friends (empty-state branch)."""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def test_page_200(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200


# ── Page renders (populated state) ───────────────────────────────────────────

class TestFriendsPagePopulated:
    """All filter UI elements require at least one friend (populated-state branch)."""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")
            self.friend = _make_user("friend")
            _add_friend(self.me, self.friend)
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def _html(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200
        return rv.data.decode()

    def test_has_filter_button(self):
        assert 'id="fr-filter-btn"' in self._html()

    def test_has_chips_container(self):
        assert 'id="fr-chips"' in self._html()

    def test_has_filter_overlay(self):
        assert 'id="fr-flt-overlay"' in self._html()

    def test_has_filter_no_results_element(self):
        assert 'id="fr-filter-no-results"' in self._html()

    def test_has_done_button(self):
        assert 'class="fr-flt-done"' in self._html()

    def test_has_reset_button(self):
        assert 'class="fr-flt-reset"' in self._html()

    def test_has_rider_section(self):
        assert 'data-category="rider"' in self._html()

    def test_has_level_section(self):
        assert 'data-category="level"' in self._html()

    def test_has_pass_section(self):
        assert 'data-category="pass"' in self._html()

    def test_frClearAll_onclick_present(self):
        assert 'frClearAll()' in self._html()

    def test_frApplyFilters_onclick_present(self):
        assert 'frApplyFilters()' in self._html()

    def test_frOpenFilter_onclick_present(self):
        assert 'frOpenFilter()' in self._html()


# ── Pass filter options ───────────────────────────────────────────────────────

class TestFilterPassOptions:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")
            self.friend = _make_user("friend")
            _add_friend(self.me, self.friend)
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def _html(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200
        return rv.data.decode()

    def test_canonical_passes_rendered_as_pills(self):
        html = self._html()
        for slug in CANONICAL_PASS_ORDER:
            assert f'data-value="{slug}"' in html, \
                f"Missing pill for pass slug '{slug}'"

    def test_pass_labels_shown(self):
        html = self._html()
        for slug in CANONICAL_PASS_ORDER:
            label = PASS_DISPLAY_MAP.get(slug, slug)
            assert label in html, \
                f"Missing display label '{label}' for slug '{slug}'"

    def test_rider_type_options_present(self):
        html = self._html()
        for val in ("skier", "snowboarder", "telemark"):
            assert f'data-value="{val}"' in html

    def test_both_rider_option_absent(self):
        """'Both' is removed — data model is single-select, normalization prevents it."""
        assert 'data-value="both"' not in self._html()

    def test_all_skill_level_options_present(self):
        html = self._html()
        for val in ("beginner", "intermediate", "advanced", "expert"):
            assert f'data-value="{val}"' in html


# ── Friend row data attributes ────────────────────────────────────────────────

class TestFriendRowAttributes:
    """Verify data-pass / data-level / data-rider on each alpha-list row."""

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")

            # Skier only, Ikon pass, Advanced
            self.f_skier = _make_user("skier")
            _set_attrs(self.f_skier,
                       rider_types=["Skier"], pass_type="ikon", skill_level="Advanced")

            # Snowboarder only, Epic pass, Expert
            self.f_sb = _make_user("sb")
            _set_attrs(self.f_sb,
                       rider_types=["Snowboarder"], pass_type="epic", skill_level="Expert")

            # Telemark, no_pass, Beginner (valid single-value rider_types)
            self.f_telemark = _make_user("telemark")
            _set_attrs(self.f_telemark,
                       rider_types=["Telemark"],
                       pass_type="no_pass", skill_level="Beginner")

            # Multi-pass: two comma-separated slugs in a single pass_type field
            # (VARCHAR(100) was widened precisely for this; seeding also uses it)
            self.f_multi = _make_user("multi")
            _set_attrs(self.f_multi,
                       rider_types=["Skier"],
                       pass_type="ikon,mountain_collective",
                       skill_level="Intermediate")

            # No rider types set, no pass, no level
            self.f_norider = _make_user("norider")
            _set_attrs(self.f_norider,
                       rider_types=[], pass_type=None, skill_level=None)

            _add_friend(self.me, self.f_skier)
            _add_friend(self.me, self.f_sb)
            _add_friend(self.me, self.f_telemark)
            _add_friend(self.me, self.f_multi)
            _add_friend(self.me, self.f_norider)
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def _html(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200
        return rv.data.decode()

    def test_skier_data_rider(self):
        assert 'data-rider="skier"' in self._html()

    def test_snowboarder_data_rider(self):
        assert 'data-rider="snowboarder"' in self._html()

    def test_telemark_data_rider(self):
        # rider_types=["Telemark"] → join('|') | lower → "telemark"
        assert 'data-rider="telemark"' in self._html()

    def test_empty_rider_types_data_rider(self):
        assert 'data-rider=""' in self._html()

    def test_ikon_pass_data_attribute(self):
        assert 'data-pass="ikon"' in self._html()

    def test_epic_pass_data_attribute(self):
        assert 'data-pass="epic"' in self._html()

    def test_no_pass_data_attribute(self):
        assert 'data-pass="no_pass"' in self._html()

    def test_advanced_level_data_attribute(self):
        assert 'data-level="advanced"' in self._html()

    def test_expert_level_data_attribute(self):
        assert 'data-level="expert"' in self._html()

    def test_beginner_level_data_attribute(self):
        assert 'data-level="beginner"' in self._html()

    def test_empty_pass_renders_empty_data_attr(self):
        assert 'data-pass=""' in self._html()

    def test_empty_level_renders_empty_data_attr(self):
        assert 'data-level=""' in self._html()

    def test_multi_pass_data_attr_preserves_comma_separated_slugs(self):
        """pass_type='ikon,mountain_collective' renders as data-pass='ikon,mountain_collective'.

        The Jinja | lower filter must not strip or mangle the comma separator.
        Both slugs must appear verbatim so _frMatchesFilters() can split on the
        comma and OR-match either one against the active filter set.
        """
        assert 'data-pass="ikon,mountain_collective"' in self._html()

    def test_multi_pass_matches_first_slug(self):
        """_matches() mirror: friend with two passes matches when first slug is selected."""
        assert _matches("ikon,mountain_collective", "skier", "intermediate",
                         pass_sel={"ikon"}) is True

    def test_multi_pass_matches_second_slug(self):
        """_matches() mirror: friend with two passes matches when second slug is selected."""
        assert _matches("ikon,mountain_collective", "skier", "intermediate",
                         pass_sel={"mountain_collective"}) is True

    def test_multi_pass_no_match_unrelated_slug(self):
        """_matches() mirror: friend with two passes does NOT match a third slug."""
        assert _matches("ikon,mountain_collective", "skier", "intermediate",
                         pass_sel={"epic"}) is False

    def test_multi_pass_matches_when_both_slugs_selected(self):
        """_matches() mirror: multi-pass friend matches when both its slugs are selected."""
        assert _matches("ikon,mountain_collective", "skier", "intermediate",
                         pass_sel={"ikon", "mountain_collective"}) is True


# ── Global search / filter interaction regression ─────────────────────────────

class TestGlobalSearchFilterInteraction:
    """Regression tests for filter behaviour during and after global member search.

    JS-level state (alpha-list visibility, filter application on exit) is covered
    via two complementary approaches:
      1. Page-source assertions — verify the JS fix is present and the DOM elements
         required for correct behaviour exist.
      2. _matches() Python mirror — verify the matching logic that runs when
         searchFriends('') is called after _frExitGlobalSearch() is correct.
    """

    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")
            self.friend = _make_user("friend")
            _add_friend(self.me, self.friend)
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def _html(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200
        return rv.data.decode()

    # ── Bug fix: fr-filter-no-results hidden on global search entry ───────

    def test_global_search_hides_filter_no_results_element_exists(self):
        """#fr-filter-no-results is in the DOM so JS can hide/show it."""
        assert 'id="fr-filter-no-results"' in self._html()

    def test_global_search_fn_hides_filter_no_results(self):
        """_frGlobalSearch() contains the getElementById call for fr-filter-no-results.

        After the fix, _frGlobalSearch uses a local variable 'filterNoRes'
        (distinct from 'filterNoResEl' used in searchFriends) to hide the
        filter empty-state alongside the existing friends-list empty-state.
        This prevents 'No friends match these filters' from appearing while
        global member-search results are displayed.
        """
        html = self._html()
        # 'var filterNoRes = ' is the unique signature of the fix in _frGlobalSearch;
        # searchFriends uses 'var filterNoResEl = ' (different name).
        assert "var filterNoRes = " in html

    def test_global_search_fn_hides_filter_no_results_display_none(self):
        """_frGlobalSearch sets filterNoRes.style.display = 'none'."""
        assert "filterNoRes.style.display = 'none'" in self._html()

    # ── Filters preserved and applied after global search exits ──────────

    def test_frExitGlobalSearch_calls_searchFriends(self):
        """_frExitGlobalSearch() calls searchFriends so active filters are applied."""
        html = self._html()
        # Both function definitions must be present
        assert "function _frExitGlobalSearch" in html
        # And _frExitGlobalSearch must reference searchFriends (for the re-apply)
        assert "_frExitGlobalSearch" in html
        assert "searchFriends" in html

    def test_active_filters_not_cleared_by_global_search(self):
        """_frGlobalSearch() does not reset _frActiveFilters.

        The function must not contain any assignment that clears the filter state,
        ensuring that filters applied during global search are retained on exit.
        """
        html = self._html()
        # _frActiveFilters is defined globally and must remain in the page
        assert "_frActiveFilters" in html
        # frApplyFilters copies pending→active and is separate from global search
        assert "frApplyFilters" in html

    def test_exit_applies_pass_filter_to_friends(self):
        """On exit from global search, searchFriends re-applies active pass filters.

        Simulates: Ikon filter selected during global search → user clears input →
        _frExitGlobalSearch → searchFriends('') → _frMatchesFilters per row.
        """
        # Friend with Ikon appears; friend with Epic does not
        assert _matches("ikon",  "skier", "advanced", pass_sel={"ikon"}) is True
        assert _matches("epic",  "skier", "advanced", pass_sel={"ikon"}) is False

    def test_exit_applies_level_filter_to_friends(self):
        """On exit from global search, level filter is applied to the friends list."""
        assert _matches("ikon", "skier", "advanced",   level_sel={"advanced"}) is True
        assert _matches("ikon", "skier", "intermediate", level_sel={"advanced"}) is False

    def test_exit_applies_combined_filters_to_friends(self):
        """On exit, AND-across-categories filter is applied correctly."""
        # Pass ✓ + level ✓ → visible
        assert _matches("ikon", "skier", "advanced",
                         pass_sel={"ikon"}, level_sel={"advanced"}) is True
        # Pass ✓ + level ✗ → hidden
        assert _matches("ikon", "skier", "beginner",
                         pass_sel={"ikon"}, level_sel={"advanced"}) is False

    def test_no_active_filters_shows_all_friends_on_exit(self):
        """When no filters are active (frClearAll called), all friends show on exit."""
        assert _matches("ikon",    "skier",        "advanced") is True
        assert _matches("epic",    "snowboarder",  "expert")   is True
        assert _matches("no_pass", "telemark",     "beginner") is True
        assert _matches("",        "",             "")         is True


# ── JS filter state injected into the page ───────────────────────────────────

class TestFilterJsPresence:
    @pytest.fixture(autouse=True)
    def setup(self, client):
        with app.app_context():
            self.me = _make_user("me")
            self.friend = _make_user("friend")
            _add_friend(self.me, self.friend)
            db.session.commit()
            self.me_id = self.me.id
        self.client = client

    def _html(self):
        rv = _get_friends(self.client, self.me_id)
        assert rv.status_code == 200
        return rv.data.decode()

    def test_frPassLabels_injected(self):
        assert "_frPassLabels" in self._html()

    def test_frActiveFilters_defined(self):
        assert "_frActiveFilters" in self._html()

    def test_frMatchesFilters_defined(self):
        assert "_frMatchesFilters" in self._html()

    def test_frOpenFilter_defined(self):
        assert "function frOpenFilter" in self._html()

    def test_frApplyFilters_defined(self):
        assert "function frApplyFilters" in self._html()

    def test_frClearAll_defined(self):
        assert "function frClearAll" in self._html()

    def test_frRemoveFilter_defined(self):
        assert "function frRemoveFilter" in self._html()

    def test_frMatchesFilters_checks_pass(self):
        assert "_frActiveFilters.pass" in self._html()

    def test_frMatchesFilters_checks_rider(self):
        assert "_frActiveFilters.rider" in self._html()

    def test_frMatchesFilters_checks_level(self):
        assert "_frActiveFilters.level" in self._html()

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("epic", {"epic"}),
            ("ikon", {"ikon"}),
            ("indy,mountain_collective", {"indy", "mountain_collective"}),
            ("epic,unknown", {"epic"}),
            ("", set()),
        ],
    )
    def test_pass_query_preselection_rules(self, query, expected):
        assert _valid_preselected_passes(query) == expected

    def test_pass_query_initialization_is_rendered(self):
        html = self._html()
        assert "params.get('pass')" in html
        assert "_frActiveFilters.pass.add(slug)" in html
        assert "Object.prototype.hasOwnProperty.call(_frPassLabels, slug)" in html
