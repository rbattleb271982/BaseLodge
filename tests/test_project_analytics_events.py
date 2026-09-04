from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_project_analytics_wrapper_is_safe_when_tracker_is_unavailable():
    source = _source("static/analytics.js")

    assert "window.blTrackProjectEvent" in source
    assert "window.umami.track(name, data || {})" in source
    assert "try {" in source
    assert "catch (error)" in source


def test_posthog_wrapper_swallows_synchronous_capture_errors():
    script = f"""
const vm = require('vm');
const source = {str((ROOT / "static/analytics.js").read_text(encoding="utf-8"))!r};
const context = {{
  window: {{
    __POSTHOG_KEY__: '',
    posthog: {{
      capture: function () {{ throw new Error('synchronous capture failure'); }}
    }}
  }}
}};
vm.runInNewContext(source, context);
context.window.blTrackPostHogEvent('signup_started');
context.window.blTrackPostHogEvent('onboarding_step_completed', {{
  step_index: 1,
  step_name: 'rider_and_skill'
}});
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_signup_and_onboarding_use_only_the_safe_posthog_wrapper():
    auth_source = _source("templates/auth.html")
    onboarding_source = _source("templates/identity_setup.html")

    assert "window.blTrackPostHogEvent('signup_started')" in auth_source
    assert "posthog.capture('signup_started')" not in auth_source
    assert (
        "window.blTrackPostHogEvent('onboarding_step_completed', eventData)"
        in onboarding_source
    )
    assert "posthog.capture('onboarding_step_completed'" not in onboarding_source
    assert "slideTo(from + 1);" in onboarding_source


def test_meaningful_project_events_are_instrumented():
    sources = {
        "signup_started": _source("templates/auth.html"),
        "onboarding_step_completed": _source("templates/identity_setup.html"),
        "push_preference_updated": _source("templates/push_settings.html"),
        "mountain_wishlist_toggled": _source("templates/mountain_detail.html"),
        "trip_planning_post_created": _source("templates/trip_detail.html"),
        "trip_invite_shared": _source("templates/trip_detail.html"),
    }

    for event_name, source in sources.items():
        assert f"window.blTrackProjectEvent('{event_name}'" in source


def test_project_events_do_not_send_user_content_or_invite_tokens():
    planning_source = _source("templates/trip_detail.html")
    planning_call = planning_source.split(
        "window.blTrackProjectEvent('trip_planning_post_created'", 1
    )[1].split(");", 1)[0]
    share_call = planning_source.split(
        "window.blTrackProjectEvent('trip_invite_shared'", 1
    )[1].split(");", 1)[0]

    assert "body" not in planning_call
    assert "link_url" not in planning_call
    assert "has_link: Boolean(linkUrl)" in planning_call
    assert "url" not in share_call
    assert "token" not in share_call