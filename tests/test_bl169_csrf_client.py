from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _source(path):
    return (ROOT / path).read_text()


def test_auth_password_forms_render_hidden_csrf_tokens():
    auth = _source("templates/auth.html")
    forgot = _source("templates/forgot_password.html")
    reset = _source("templates/reset_password.html")

    assert auth.count(
        'type="hidden" name="csrf_token" value="{{ csrf_token() }}"'
    ) == 2
    assert 'type="hidden" name="csrf_token" value="{{ csrf_token() }}"' in forgot
    assert 'type="hidden" name="csrf_token" value="{{ csrf_token() }}"' in reset


def test_analytics_head_exposes_csrf_helper_and_keeps_fetch_compatibility():
    source = _source("templates/components/analytics_head.html")

    assert "window.blFetch = csrfFetch;" in source
    assert "window.fetch = csrfFetch;" in source
    assert "'X-CSRF-Token'" in source
    assert "meta[name=\"csrf-token\"]" in source


def test_profile_mutation_uses_meta_token_and_canonical_header():
    source = _source("templates/profile.html")
    function = source.split("function _profToggleDiscoverable(checked)", 1)[1]
    function = function.split("// ── OneSignal identity logout", 1)[0]

    assert "window.blFetch('/api/profile/update'" in function
    assert "meta[name=\"csrf-token\"]" in function
    assert "'X-CSRF-Token': csrf" in function
    assert "document.cookie" not in function
    assert "X-CSRFToken" not in function


def test_native_push_mutations_use_canonical_csrf_helper():
    source = _source("static/js/bl-native.js")

    assert "window.blFetch('/api/push/beacon'" in source
    assert "window.blFetch('/api/push/register-token'" in source
    assert "window.fetch('/api/push/beacon'" not in source
    assert "window.fetch('/api/push/register-token'" not in source


def test_every_explicit_post_form_renders_a_csrf_token():
    missing = []
    pattern = re.compile(
        r'<form\b[^>]*method\s*=\s*["\']POST["\'][^>]*>.*?</form\s*>',
        re.IGNORECASE | re.DOTALL,
    )
    for path in sorted((ROOT / "templates").rglob("*.html")):
        source = path.read_text()
        for form in pattern.finditer(source):
            if "csrf_token" not in form.group(0):
                line = source.count("\n", 0, form.start()) + 1
                missing.append(f"{path.relative_to(ROOT)}:{line}")

    assert missing == []