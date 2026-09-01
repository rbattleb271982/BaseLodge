"""Focused source contracts for BL-173 Stage 1 targeted refreshes."""

from pathlib import Path
import re


BASE = Path("templates/base_app.html").read_text()
FRIENDS = Path("templates/friends.html").read_text()
PLANNING = Path("templates/trip_planning.html").read_text()
TRIP = Path("templates/trip_detail.html").read_text()
UTILITY = Path("static/js/bl-targeted-refresh.js").read_text()


def _region_count(source, prefix, name):
    pattern = re.compile(
        rf'<(?:div|section)[^>]*data-{prefix}-region="{re.escape(name)}"'
    )
    return len(pattern.findall(source))


def test_shared_utility_is_loaded_once_for_app_pages():
    assert BASE.count("js/bl-targeted-refresh.js") == 1
    assert "window.BLTargetedRefresh = { create: create };" in UTILITY
    assert "TARGETED_REFRESH_VERSION" in BASE


def test_shared_utility_keeps_refresh_safety_contracts():
    assert "regionVersions[region] = (regionVersions[region] || 0) + 1" in UTILITY
    assert "if (ticket[region] !== regionVersions[region]) return;" in UTILITY
    assert UTILITY.index("if (!response.ok)") < UTILITY.index(
        "if (!isCurrentPage(response.url))"
    )
    assert "cache: 'no-store'" in UTILITY
    assert "credentials: 'same-origin'" in UTILITY
    assert "window.scrollTo(scrollX, scrollY)" in UTILITY
    assert "setTimeout" not in UTILITY
    assert "retry" not in UTILITY.lower()


def test_duplicate_submit_is_prevented_before_pending_return():
    listener = UTILITY[
        UTILITY.index("document.addEventListener('submit'"):
        UTILITY.index("return {", UTILITY.index("document.addEventListener('submit'"))
    ]
    assert listener.index("event.preventDefault()") < listener.index(
        "pendingAttribute) === 'true'"
    )
    assert "submitter && submitter.isConnected" in listener


def test_trip_detail_uses_shared_engine_with_local_hooks():
    helper = TRIP[
        TRIP.index("// ── Canonical targeted region refresh"):
        TRIP.index("function dismissSuccess")
    ]
    assert "window.BLTargetedRefresh.create" in helper
    assert "window.tdRefreshRegions = controller.refresh;" in helper
    assert "td-edit-mode" in helper
    assert "invite-controls" in helper
    assert "regionVersions" not in helper


def test_friends_regions_and_only_approved_reload_paths_are_converted():
    for region in ("requests", "tabs", "directory", "suggestions"):
        assert _region_count(FRIENDS, "fr", region) == 1
    assert "window.frRefreshRegions = _frRefreshController.refresh;" in FRIENDS
    assert "await window.frRefreshRegions([" in FRIENDS
    assert "window.frRefreshRegions([" in FRIENDS
    assert "location.reload" not in FRIENDS
    assert "window.location.href = '/login'" in FRIENDS


def test_friends_refresh_preserves_bounded_state_without_full_dataset_fetch():
    hook = FRIENDS[
        FRIENDS.index("var _frRefreshController"):
        FRIENDS.index("window.frRefreshRegions")
    ]
    for state in (
        "_frCurrentTab",
        "_frSearchQuery",
        "searchValue",
        "focusId",
        "visibleFriendCount",
        "_frUpdateChips",
        "_frUpdateFilterBtn",
    ):
        assert state in hook
    assert "_frFetchDirectory" in FRIENDS
    assert "/api/friends/page?" in FRIENDS
    assert "event.target.closest('#fr-load-more')" in FRIENDS
    assert "while (currentCount < targetCount" in FRIENDS


def test_planning_regions_cover_create_edit_delete_and_empty_state():
    assert _region_count(TRIP, "td", "planning") == 1
    assert _region_count(PLANNING, "tp", "posts") == 1
    assert "await window.tdRefreshRegions(['planning'])" in TRIP
    assert PLANNING.count("await window.tpRefreshRegions(['posts'])") == 2
    assert "location.reload" not in PLANNING
    assert 'class="tp-empty"' in PLANNING


def test_planning_draft_is_cleared_only_after_refresh_success():
    success = PLANNING[
        PLANNING.index("if (resp.ok)"):
        PLANNING.index("} else {", PLANNING.index("if (resp.ok)"))
    ]
    assert success.index("await window.tpRefreshRegions") < success.index(
        "closeSheet()"
    )
    assert success.index("await window.tpRefreshRegions") < success.index(
        "clearSheet()"
    )
    assert "'X-CSRF-Token': TP_CSRF_TOKEN" in PLANNING
    assert "} finally {" in PLANNING
    assert "btn.disabled = false;" in PLANNING


def test_shared_path_has_no_native_specific_branch():
    assert "Capacitor" not in UTILITY
    assert "webkit" not in UTILITY.lower()