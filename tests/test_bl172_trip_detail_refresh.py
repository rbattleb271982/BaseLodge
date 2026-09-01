"""Focused contracts for BL-172 canonical Trip Detail region refreshes."""

from pathlib import Path
import re


TEMPLATE = Path("templates/trip_detail.html").read_text()
UTILITY = Path("static/js/bl-targeted-refresh.js").read_text()


def test_canonical_trip_detail_regions_are_stable_and_unique():
    expected = {
        "summary",
        "stay",
        "setup",
        "people",
        "actions",
        "lifecycle",
        "invite-controls",
        "stay-editor",
        "participant-editor",
        "participant-tools",
        "planning",
    }
    for region in expected:
        marker = re.compile(
            rf'<(?:div|section)[^>]*data-td-region="{re.escape(region)}"'
        )
        assert len(marker.findall(TEMPLATE)) == 1


def test_safe_mutations_use_targeted_refresh_mappings():
    assert (
        "await window.tdRefreshRegions(['stay', 'stay-editor'])" in TEMPLATE
    )
    assert (
        "await window.tdRefreshRegions(['summary', 'people', 'invite-controls'])"
        in TEMPLATE
    )
    assert (
        "window.tdRefreshRegions(['setup', 'people', 'actions', 'invite-controls'])"
        in TEMPLATE
    )
    assert (
        'data-td-targeted-form="setup,participant-editor,people,actions,lifecycle"'
        in TEMPLATE
    )
    assert 'data-td-targeted-form="people,actions,invite-controls"' in TEMPLATE


def test_lifecycle_and_access_ending_forms_keep_normal_navigation():
    complete = 'action="{{ url_for(\'complete_trip_form\', trip_id=trip.id) }}"'
    delete = 'action="{{ url_for(\'delete_trip_form\', trip_id=trip.id) }}"'
    leave = 'action="{{ url_for(\'leave_trip\', trip_id=trip.id) }}"'
    decline = (
        '<input type="hidden" name="response" value="decline">\n'
        '                    <button type="submit"'
    )
    for action in (complete, delete, leave):
        start = TEMPLATE.index(action)
        form_end = TEMPLATE.index("</form>", start)
        assert "data-td-targeted-form" not in TEMPLATE[start:form_end]
    assert decline in TEMPLATE
    decline_start = TEMPLATE.rindex(
        '<form method="POST" action="{{ url_for(\'respond_to_trip_invite\'',
        0,
        TEMPLATE.index(decline),
    )
    assert "data-td-targeted-form" not in TEMPLATE[
        decline_start:TEMPLATE.index("</form>", decline_start)
    ]


def test_refresh_helper_is_latest_response_only_and_never_retries():
    assert "regionVersions[region] = (regionVersions[region] || 0) + 1" in UTILITY
    assert "if (ticket[region] !== regionVersions[region]) return;" in UTILITY
    assert "refreshHeaderName: 'X-Trip-Detail-Refresh'" in TEMPLATE
    assert "setTimeout" not in UTILITY
    assert "retry" not in UTILITY.lower()


def test_non_success_is_rejected_before_redirect_or_dom_replacement():
    helper = UTILITY[
        UTILITY.index("async function applyResponse"):
        UTILITY.index("async function refresh")
    ]
    assert helper.index("if (!response.ok)") < helper.index(
        "if (!isCurrentPage(response.url))"
    )
    assert helper.index("if (!response.ok)") < helper.index("replaceWith")


def test_targeted_forms_keep_existing_csrf_fields():
    for marker in (
        'data-td-targeted-form="setup,participant-editor,people,actions,lifecycle"',
        'data-td-targeted-form="people,actions,invite-controls"',
        'data-td-targeted-form="setup,participant-tools,people,actions,lifecycle,invite-controls"',
    ):
        cursor = 0
        while True:
            start = TEMPLATE.find("<form", cursor)
            if start == -1:
                break
            end = TEMPLATE.index("</form>", start)
            form = TEMPLATE[start:end]
            if marker in form:
                assert 'name="csrf_token"' in form
            cursor = end + len("</form>")


def test_converted_json_mutations_send_explicit_csrf_header():
    resort = TEMPLATE[
        TEMPLATE.index("window.selectResort"):
        TEMPLATE.index("// Keyboard-aware height for iOS")
    ]
    join_request = TEMPLATE[
        TEMPLATE.index("async function respondToJoinRequest"):
        TEMPLATE.index("function updateSelectionState")
    ]
    for mutation in (resort, join_request):
        assert "'X-CSRF-Token': _tdCanonicalCsrfToken" in mutation


def test_capacitor_and_browser_share_the_same_fetch_path():
    assert "Capacitor" not in UTILITY
    assert "fetch(" in UTILITY
    assert "window.location.assign" in UTILITY
    assert "window.tdRefreshRegions = controller.refresh;" in TEMPLATE


def test_pending_invitee_initializers_tolerate_tools_before_regions_exist():
    assert "{% if is_member or is_invited %}" in TEMPLATE
    assert "if (capHint) capHint.style.display" in TEMPLATE
    assert (
        "{% if not is_owner and (is_member or is_invited) %}" in TEMPLATE
    )


def test_replaced_invite_modal_keeps_delegated_backdrop_dismissal():
    assert "document.addEventListener('click', function(e)" in TEMPLATE
    assert "if (e.target.matches('#confirmInviteModal')) hideConfirmModal();" in TEMPLATE