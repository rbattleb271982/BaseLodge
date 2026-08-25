"""Focused BL-60 coverage for Mountains defaults and education persistence."""
from app import app
from models import db, User
from tests.conftest import _make_user, _login, json_post


def _mountains_users(client):
    with app.app_context():
        owner = _make_user("mountains-owner", home_state="CO")
        other = _make_user("mountains-other", home_state="UT")
        db.session.commit()
        return {"owner_id": owner.id, "other_id": other.id}


def test_mountains_requires_authentication(client):
    response = client.get("/mountains")
    assert response.status_code == 302


def test_mountains_starts_unfiltered_and_shows_first_visit_education(client):
    users = _mountains_users(client)
    _login(client, users["owner_id"])

    response = client.get("/mountains")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "var DEFAULT_COUNTRY" not in html
    assert "var DEFAULT_STATE" not in html
    assert "var SHOW_FILTER_EDUCATION = true;" in html
    assert "Filter mountains by state and pass." in html
    assert 'onclick="mdClearFilters()" style="display:none;">Clear</button>' in html


def test_mountains_hides_education_after_account_has_seen_it(client):
    users = _mountains_users(client)
    _login(client, users["owner_id"])

    response = json_post(client, "/api/mountains/filter-education-seen")
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "seen": True}

    response = client.get("/mountains")
    html = response.get_data(as_text=True)
    assert "var SHOW_FILTER_EDUCATION = false;" in html
    assert "Filter mountains by state and pass." not in html


def test_filter_education_endpoint_requires_authentication(client):
    response = client.post("/api/mountains/filter-education-seen")
    assert response.status_code == 302


def test_filter_education_endpoint_requires_valid_csrf(client):
    users = _mountains_users(client)
    _login(client, users["owner_id"])

    response = client.post("/api/mountains/filter-education-seen")
    assert response.status_code == 403

    response = client.post(
        "/api/mountains/filter-education-seen",
        headers={"X-CSRF-Token": "not-the-session-token"},
    )
    assert response.status_code == 403


def test_filter_education_endpoint_only_updates_current_user_and_is_idempotent(client):
    users = _mountains_users(client)
    _login(client, users["owner_id"])

    first = json_post(client, "/api/mountains/filter-education-seen")
    assert first.status_code == 200

    with app.app_context():
        owner_seen_at = User.query.get(users["owner_id"]).mountains_filter_education_seen_at
        other_seen_at = User.query.get(users["other_id"]).mountains_filter_education_seen_at
        assert owner_seen_at is not None
        assert other_seen_at is None

    second = json_post(client, "/api/mountains/filter-education-seen")
    assert second.status_code == 200

    with app.app_context():
        assert User.query.get(users["owner_id"]).mountains_filter_education_seen_at == owner_seen_at
        assert User.query.get(users["other_id"]).mountains_filter_education_seen_at is None


def test_mountains_template_resets_all_inputs_and_reuses_bfcache_data():
    with open("templates/mountains_tab.html", encoding="utf-8") as template:
        source = template.read()

    assert "elCountry.value = '';" in source
    assert "renderStateOptions('', '');" in source
    assert "function resetFilters()" in source
    assert "if (e.persisted && _mdLoaded) {\n            resetFilters();" in source
    assert "Filter mountains by state and pass." in source
    assert "md-filter-area--education" in source


def test_mountains_template_keeps_explicit_filters_and_no_results_behavior():
    with open("templates/mountains_tab.html", encoding="utf-8") as template:
        source = template.read()

    assert 'id="md-search"' in source
    assert 'id="md-country"' in source
    assert 'id="md-state"' in source
    assert 'id="md-pass"' in source
    assert "if (country && r.country_code !== country) return false;" in source
    assert "if (state   && r.state_code   !== state)   return false;" in source
    assert "if (pass    && r.pass_keys.indexOf(pass) === -1) return false;" in source
    assert "No mountains found." in source
    assert 'href="/mountain/' in source


def test_filter_education_is_dismissed_only_by_the_close_button():
    with open("templates/mountains_tab.html", encoding="utf-8") as template:
        source = template.read()

    education = source.split("/* ── First-visit education ─────────────────────────────────── */", 1)[1]
    event_listeners = source.split("/* ── Event listeners ───────────────────────────────────────── */", 1)[1]

    assert "elEducationClose.addEventListener('click', dismissFilterEducation);" in education
    assert "onEducationPointerDown" not in education
    assert "pointerdown" not in education
    assert "setTimeout" not in education
    assert "_educationTimer" not in source
    assert "dismissFilterEducation();" not in event_listeners


def test_mountains_filter_controls_have_accessible_touch_targets():
    with open("templates/mountains_tab.html", encoding="utf-8") as template:
        source = template.read()

    close_css = source.split(".md-filter-education-close {", 1)[1].split("}", 1)[0]
    clear_css = source.split(".md-clear-btn {", 1)[1].split("}", 1)[0]

    assert "width: 44px;" in close_css
    assert "height: 44px;" in close_css
    assert "min-width: 44px;" in clear_css
    assert "min-height: 44px;" in clear_css