"""Playwright runner for a manifest row (capture execution is opt-in)."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import MANIFEST, validate_manifest


def _render_system_500_html() -> str:
    """Resolve the existing product 500 template for browser interception."""
    template = (
        Path(__file__).resolve().parents[1] / "templates" / "500.html"
    ).read_text()
    template = template.replace(
        "{% include 'components/analytics_head.html' %}", ""
    )
    template = template.replace(
        "{{ url_for('static', filename='styles.css') }}",
        "/static/styles.css",
    )
    template = template.replace("{{ url_for('home') }}", "/home")
    template = template.replace("{{ ICONS_VERSION }}", "capture")
    if "{{" in template or "{%" in template:
        raise RuntimeError("unresolved Jinja in intercepted 500 template")
    return template


class CaptureRunner:
    def __init__(self, base_url: str, output_dir: str | os.PathLike[str] = "capture-output",
                 executable: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.executable = executable or self.find_chromium()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "manifest.json").write_text(json.dumps(MANIFEST, indent=2, sort_keys=True))
        self._metadata: list[dict[str, Any]] = []

    @staticmethod
    def find_chromium() -> str:
        candidates = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        for path in ("/usr/bin/chromium", "/usr/bin/google-chrome"):
            if Path(path).exists():
                return path
        raise RuntimeError("System Chromium executable not found")

    def capture(self, row: dict[str, Any], bootstrap_endpoint: str = "/api/capture/auth") -> dict[str, Any]:
        """Capture one row using real routes; callers choose rows explicitly."""
        validate_manifest([row] + [r for r in MANIFEST if r is not row])
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is required to run captures") from exc
        errors: list[str] = []
        failed_requests: list[str] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        screenshot = self.output_dir / row["output_path"].split("/", 1)[1]
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=self.executable)
            context = browser.new_context(viewport=row["viewport"], is_mobile=True)
            context.add_init_script("""(() => {
              const Frozen = 1799949600000;
              const NativeDate = Date;
              class CaptureDate extends NativeDate {
                constructor(...args) { super(...(args.length ? args : [Frozen])); }
                static now() { return Frozen; }
              }
              window.Date = CaptureDate;
            })();""")
            if row["state"] in {
                "suggestions-loading", "suggestions-error",
                "progressive-loading", "error-retry", "retry",
                "no-filter-results",
            }:
                target = (
                    "/api/friends/suggestions/page"
                    if row["state"].startswith("suggestions-") or row["state"] == "retry"
                    else "/api/my-trips/friends/page"
                )
                mode = (
                    "loading" if row["state"].endswith("loading")
                    else "empty" if row["state"] == "no-filter-results"
                    else "error"
                )
                context.add_init_script(
                    f"""(() => {{
                      const target = {json.dumps(target)};
                      const mode = {json.dumps(mode)};
                      const nativeFetch = window.fetch.bind(window);
                      window.fetch = (input, init) => {{
                        const url = String(input && input.url ? input.url : input);
                        if (url.includes(target)) {{
                          if (mode === 'loading') return new Promise(() => {{}});
                          if (mode === 'empty') return Promise.resolve(new Response(
                            JSON.stringify({{
                              html: '', destinations: [], has_friends: true,
                              has_more: false, next_cursor: null
                            }}),
                            {{status: 200, headers: {{'Content-Type': 'application/json'}}}}
                          ));
                          return Promise.reject(new Error('deterministic capture failure'));
                        }}
                        return nativeFetch(input, init);
                      }};
                    }})();"""
                )
            if row["state"] == "social-loading":
                context.add_init_script(
                    "window.__BASELODGE_CAPTURE_MOUNTAIN_SOCIAL__ = 'loading';"
                )
            elif row["state"] == "social-error":
                context.add_init_script(
                    "window.__BASELODGE_CAPTURE_MOUNTAIN_SOCIAL__ = 'error';"
                )
            elif row["state"] == "export-error":
                context.add_init_script(
                    """Object.defineProperty(window, 'html2canvas', {
                      configurable: true, get: () => undefined, set: () => {}
                    });"""
                )
            page = context.new_page()
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda req: failed_requests.append(req.url))
            page.route("https://**", lambda route: route.abort())
            if row["screen"] == "system" and row["state"] == "500":
                page.route(
                    "**/capture-intentional-500",
                    lambda route: route.fulfill(
                        status=500,
                        content_type="text/html",
                        body=_render_system_500_html(),
                    ),
                )
            page.goto(self.base_url + "/home", wait_until="domcontentloaded")
            bootstrap = page.evaluate(
                """async args => {
                  const response = await fetch(args.endpoint, {method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body:JSON.stringify({persona:args.persona})});
                  if (!response.ok) throw new Error(`capture bootstrap failed: ${response.status}`);
                  return await response.json();
                }""",
                {"endpoint": bootstrap_endpoint, "persona": row["persona"]},
            )
            if bootstrap.get("ok") is False:
                raise RuntimeError("capture bootstrap rejected persona")
            page.evaluate(
                """async captureId => {
                  const response = await fetch('/api/capture/prepare', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({capture_id: captureId})
                  });
                  if (!response.ok) throw new Error(`capture prepare failed: ${response.status}`);
                }""",
                row["capture_id"],
            )
            logical_bindings = bootstrap.get("bindings", {})
            bindings = {
                key: logical_bindings.get(value, value)
                for key, value in row["logical_route_bindings"].items()
            }
            route = row["route_template"].format(**bindings)
            if row["screen"] == "auth":
                context.clear_cookies()
            page.goto(self.base_url + route, wait_until="domcontentloaded")
            page.wait_for_function("document.readyState === 'complete'")
            page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
            page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}")
            marker = {
                "home": "[data-fr-region], .home-page-container", "friends": ".tab-bar",
                "trips": ".view-tabs, .ss-card", "mountain-detail": "#md-social-region",
                "profile": ".profile-card", "system": "body",
            }.get(row["screen"], "main, .page-container, body")
            if row["state"] == "season-snapshot":
                marker = ".ss-card"
            page.wait_for_selector(marker, state="attached")
            if row["state"] == "social-loading":
                page.wait_for_selector(".md-social-loading", state="visible")
            elif row["state"] == "social-error":
                page.wait_for_selector(".md-social-load-failure", state="visible")
            elif row["screen"] == "mountain-detail":
                page.wait_for_function(
                    "() => !document.querySelector('.md-social-loading')"
                )
            if row["screen"] == "auth":
                if row["state"] == "validation-error":
                    page.locator("#form-login input[name='email']").fill(
                        "nobody@fixture.invalid"
                    )
                    page.locator("#login-password").fill("WrongPassword1")
                    page.locator("#login-btn").click()
                    page.wait_for_selector("#login-error", state="visible")
                elif row["state"] == "forgot-password":
                    page.locator("#forgot-wrap a").click()
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_selector("form", state="visible")
            elif row["screen"] == "onboarding":
                if row["state"] in {"pass", "validation"}:
                    page.locator(".ob-pill[data-grp='rider'][data-val='Skier']").click()
                    if row["state"] == "pass":
                        page.locator(
                            ".ob-pill[data-grp='skill'][data-val='Intermediate']"
                        ).click()
                        page.locator("#cta-1").click()
                        page.wait_for_selector("#ob-step-2", state="visible")
                elif row["state"] == "rider-type":
                    page.locator(
                        ".ob-pill[data-grp='rider'][data-val='Snowboarder']"
                    ).click()
            elif row["screen"] == "create-trip":
                if row["state"] == "resort-results":
                    page.locator("#mountain-search").fill("Aspen")
                    page.wait_for_selector(".at-result-item[data-id]", state="visible")
                elif row["state"] == "dates-selected":
                    days = page.locator(
                        "#cal-grid .at-day[data-date]:not(.past):not(.disabled)"
                    )
                    days.nth(2).click()
                    days.nth(4).click()
                    page.wait_for_selector("#staged-list .at-staged-item", state="visible")
                elif row["state"] == "validation-error":
                    days = page.locator(
                        "#cal-grid .at-day[data-date]:not(.past):not(.disabled)"
                    )
                    days.nth(2).click()
                    days.nth(4).click()
                    days.nth(2).click()
                    days.nth(4).click()
                    page.wait_for_selector("#range-error", state="visible")
            elif row["screen"] == "mountains":
                if row["state"] == "search":
                    page.locator("#md-search").fill("Aspen")
                    page.wait_for_function(
                        "() => document.querySelectorAll('#md-results .md-row').length === 1"
                    )
                elif row["state"] == "no-results":
                    page.locator("#md-search").fill("zzzzzzzz")
                    page.wait_for_selector("#md-empty", state="visible")
            elif row["screen"] == "availability" and row["state"] == "validation":
                page.locator(
                    "#calGrid .cal-day[data-date]:not(.cal-past):not(.cal-disabled)"
                ).nth(1).click()
                page.wait_for_function(
                    "() => document.querySelector('#summaryText')?.textContent.includes('pick end date')"
                )
            elif row["screen"] == "open-ski" and row["state"] == "export-error":
                page.locator(".ots-review .ots-submit").click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_selector(".ots-card", state="visible")
                page.locator("#ots-share-image").click()
                page.wait_for_function(
                    "() => document.querySelector('#ots-export-status')?.textContent.includes('could not prepare')"
                )
            elif row["screen"] == "profile" and row["state"] in {
                "wishlist-overlay", "settings",
            }:
                link = (
                    page.locator("a[href*='wish-list']").first
                    if row["state"] == "wishlist-overlay"
                    else page.get_by_text("Profile details", exact=True)
                )
                link.click()
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_selector("main, .page-container", state="visible")
            elif row["screen"] == "home":
                if row["state"] in {"ideas", "ideas-happening"}:
                    page.locator("#section-opportunities").scroll_into_view_if_needed()
                elif row["state"] == "happening":
                    page.locator("#section-happening").scroll_into_view_if_needed()
                elif row["state"] == "availability":
                    page.locator("#availability-sheet-trigger").click()
                    page.wait_for_selector("#availSheet.open", state="visible")
                elif row["state"] == "profile-intelligence":
                    page.evaluate("window.scrollTo(0, 0)")
                elif row["state"] == "pending-invite":
                    page.locator("#section-requests").scroll_into_view_if_needed()
                elif row["state"] == "next-trip-participant":
                    page.locator(".home-next-trip, .bl-next-trip").first.scroll_into_view_if_needed()
            elif row["screen"] == "trips":
                if row["state"] in {
                    "filter-sheet", "no-filter-results",
                    "progressive-loading", "error-retry",
                }:
                    page.locator(".tab-btn[data-tab='friends']").click()
                    page.wait_for_selector("#segment-friends.active", state="visible")
                if row["state"] == "filter-sheet":
                    page.evaluate("window.ftOpenMtnFilter()")
                    page.wait_for_selector("#ft-mtn-overlay.open", state="visible")
                elif row["state"] == "no-filter-results":
                    page.evaluate(
                        """() => {
                          window._ftActiveMtn = 'no-match';
                          document.getElementById('ft-mtn-filter-label').textContent =
                            'No matching mountain';
                          window._ftFetchPage(true);
                        }"""
                    )
                    page.wait_for_selector("#ft-empty-trips", state="visible")
                elif row["state"] == "progressive-loading":
                    page.wait_for_selector("#ft-loading", state="visible")
                elif row["state"] == "error-retry":
                    page.wait_for_function(
                        "() => document.querySelector('#ft-load-more')?.textContent.includes('Try again')"
                    )
                elif row["state"] == "continuation":
                    button = page.locator(
                        ".my-trips-load-more[data-section='upcoming']"
                    )
                    if button.count() and button.is_visible():
                        button.click()
                        page.wait_for_timeout(100)
                    page.locator("#mine-upcoming-ledger .trip-row").last.scroll_into_view_if_needed()
                elif row["state"] == "history":
                    toggle = page.locator(".earlier-toggle")
                    if toggle.get_attribute("aria-expanded") != "true":
                        toggle.click()
                    page.wait_for_selector("#earlier-rows", state="visible")
                    toggle.evaluate(
                        "(el) => el.scrollIntoView({block: 'start', behavior: 'instant'})"
                    )
                elif row["state"] == "friends-trips":
                    page.locator(".tab-btn[data-tab='friends']").click()
                    page.wait_for_selector("#segment-friends.active", state="visible")
                elif row["state"] == "pending-invites":
                    page.locator(".ledger-invite").first.scroll_into_view_if_needed()
                elif row["state"] == "three-invitations":
                    page.set_viewport_size({"width": 390, "height": 1300})
                    page.wait_for_function(
                        "() => document.querySelectorAll('.ledger-invite').length === 3"
                    )
                    page.locator(".ledger-invite").first.scroll_into_view_if_needed()
                elif row["state"] == "accept-choice":
                    page.locator(".invite-accept").first.click()
                    page.wait_for_selector("#invite-choice", state="visible")
            elif row["screen"] == "trip-detail":
                target_tab = {
                    "people": "#td-tab-people",
                    "you": "#td-tab-you",
                    "hero": "#td-tab-trip",
                    "planning": "#td-tab-trip",
                }.get(row["segment"])
                if target_tab:
                    page.locator(target_tab).click()
                    page.wait_for_selector(
                        target_tab + "[aria-selected='true']", state="visible"
                    )
            elif row["screen"] == "friends" and row["state"] in {
                "suggestions-loading", "suggestions-error",
            }:
                page.locator(".tab-btn[data-tab='suggested']").click()
                page.wait_for_selector("#segment-suggested.active", state="visible")
                page.wait_for_selector(
                    "#fr-sugg-loading" if row["state"].endswith("loading") else "#fr-sugg-load-more",
                    state="visible",
                )
            elif row["screen"] == "friends" and row["state"] == "pagination":
                button = page.locator("#fr-load-more")
                if button.count() and button.is_visible():
                    button.click()
                    page.wait_for_timeout(100)
                page.locator("#fr-directory-sentinel").scroll_into_view_if_needed()
            elif row["screen"] == "friends" and row["state"] == "filters-search":
                page.locator("#fr-search").fill("Friend0")
                page.evaluate("window.frOpenFilter()")
                page.locator(
                    "#fr-flt-pass-opts .fr-flt-pill[data-value='epic']"
                ).click()
                page.wait_for_selector("#fr-flt-overlay.open", state="visible")
            elif row["screen"] == "friends" and row["state"] == "pending-requests":
                page.locator("[data-fr-region='requests']").scroll_into_view_if_needed()
                action = page.locator(".fr-request-row button").first
                if action.count():
                    action.focus()
            elif row["screen"] == "system" and row["state"] == "retry":
                page.locator(".tab-btn[data-tab='suggested']").click()
                page.wait_for_selector("#fr-sugg-load-more", state="visible")
            if row.get("interaction") and row["interaction"] != "none":
                if row["interaction"] == "open delete-account modal":
                    page.locator(
                        "[onclick*='delete-account-modal']"
                    ).first.click(timeout=3000)
                    page.wait_for_selector(
                        "#delete-account-modal", state="visible"
                    )
                elif row["interaction"] == "open invitation sheet":
                    page.evaluate("window.openInviteModal()")
                    page.wait_for_selector("#inviteModal.active", state="visible")
                elif row["interaction"] == "open Suggested tab":
                    page.locator(".tab-btn[data-tab='suggested']").click(timeout=3000)
                    page.wait_for_selector("#segment-suggested.active", state="visible")
            # Prefer semantic anchors exposed by the real templates; otherwise
            # leave the page at its natural top position.
            explicit_states = {
                "availability", "continuation", "filters-search", "friends-trips",
                "happening", "ideas", "ideas-happening", "next-trip-participant",
                "pagination", "pending-invite", "pending-invites",
                "three-invitations", "accept-choice",
                "pending-requests", "profile-intelligence",
            }
            if row["state"] not in explicit_states:
                page.evaluate(
                """segment => {
                    const key = segment.toLowerCase().replaceAll('-', '');
                    const el = [...document.querySelectorAll(
                      '[id],[data-segment],[data-fr-region],[data-td-region]'
                    )].find(n => (
                      (n.id || '') +
                      (n.dataset.segment || '') +
                      (n.dataset.frRegion || '') +
                      (n.dataset.tdRegion || '')
                    ).toLowerCase().replaceAll('-', '').includes(key));
                    if (el) el.scrollIntoView({block: 'start', behavior: 'instant'});
                }""",
                    row["segment"],
                )
            page.screenshot(path=str(screenshot))
            dimensions = page.evaluate("""() => ({
              scroll_width: document.documentElement.scrollWidth,
              viewport_width: window.innerWidth
            })""")
            metadata = {"capture_id": row["capture_id"], "url": page.url, "console_errors": errors,
                        "failed_requests": failed_requests, "screenshot": str(screenshot),
                        "scroll_width": dimensions["scroll_width"],
                        "viewport_width": dimensions["viewport_width"],
                        "horizontal_overflow": dimensions["scroll_width"] > dimensions["viewport_width"],
                        "captured_at": datetime.now(timezone.utc).isoformat()}
            self._metadata.append(metadata)
            (self.output_dir / "run-metadata.json").write_text(json.dumps({"captures": self._metadata}, indent=2))
            browser.close()
        return metadata

    def capture_sample(self, ids: list[str]) -> list[dict[str, Any]]:
        selected = [r for r in MANIFEST if r["capture_id"] in ids]
        if len(selected) != len(ids):
            raise ValueError("unknown capture ID in sample")
        metadata = [self.capture(row) for row in selected]
        if len(ids) == len(MANIFEST):
            groups: dict[str, list[str]] = {}
            for item in metadata:
                digest = hashlib.sha256(Path(item["screenshot"]).read_bytes()).hexdigest()
                groups.setdefault(digest, []).append(item["capture_id"])
            allowed = {
                frozenset({
                    "friend-profile__heavy__complete__mobile__top",
                    "friend-profile__heavy__shared-context__mobile__top",
                    "friend-profile__heavy__high-overlap__mobile__top",
                }),
                frozenset({
                    "mountain-detail__heavy__on-pass__mobile__hero",
                    "mountain-detail__heavy__visited-wishlisted__mobile__hero",
                    "mountain-detail__heavy__social-success__mobile__community",
                }),
                frozenset({
                    "friends__edge__suggestions-error__mobile__suggestions",
                    "system__edge__retry__mobile__top",
                }),
                frozenset({
                    "home__heavy__ideas__mobile__ideas-happening",
                    "home__heavy__ideas-happening__mobile__ideas-happening",
                }),
                frozenset({
                    "home__heavy__happening__mobile__ideas-happening",
                    "home__heavy__profile-intelligence__mobile__lower-intelligence",
                }),
                frozenset({
                    "trips__typical__typical__mobile__top-upcoming",
                    "trips__typical__pending-invites__mobile__top-upcoming",
                }),
            }
            unexpected = [
                group for group in groups.values()
                if len(group) > 1 and frozenset(group) not in allowed
            ]
            if unexpected:
                raise RuntimeError(
                    f"unreviewed exact-duplicate capture states: {unexpected}"
                )
        return metadata