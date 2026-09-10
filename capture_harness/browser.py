"""Playwright runner for a manifest row (capture execution is opt-in)."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import MANIFEST, validate_manifest


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
            if row["state"] == "social-loading":
                context.add_init_script(
                    "window.__BASELODGE_CAPTURE_MOUNTAIN_SOCIAL__ = 'loading';"
                )
            elif row["state"] == "social-error":
                context.add_init_script(
                    "window.__BASELODGE_CAPTURE_MOUNTAIN_SOCIAL__ = 'error';"
                )
            page = context.new_page()
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("requestfailed", lambda req: failed_requests.append(req.url))
            page.route("https://**", lambda route: route.abort())
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
            logical_bindings = bootstrap.get("bindings", {})
            bindings = {
                key: logical_bindings.get(value, value)
                for key, value in row["logical_route_bindings"].items()
            }
            route = row["route_template"].format(**bindings)
            page.goto(self.base_url + route, wait_until="domcontentloaded")
            page.wait_for_function("document.readyState === 'complete'")
            page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
            page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}")
            marker = {
                "home": "[data-fr-region], .home-page-container", "friends": ".tab-bar",
                "trips": ".tab-bar", "mountain-detail": "#md-social-region",
                "profile": ".profile-card", "system": "body",
            }.get(row["screen"], "main, .page-container, body")
            page.wait_for_selector(marker, state="attached")
            if row["state"] == "social-loading":
                page.wait_for_selector(".md-social-loading", state="visible")
            elif row["state"] == "social-error":
                page.wait_for_selector(".md-social-load-failure", state="visible")
            if row.get("interaction") and row["interaction"] != "none":
                if "modal" in row["interaction"] or "sheet" in row["interaction"]:
                    page.locator(
                        "[onclick*='delete-account-modal']"
                    ).first.click(timeout=3000)
                    page.wait_for_selector(
                        "#delete-account-modal", state="visible"
                    )
            # Prefer semantic anchors exposed by the real templates; otherwise
            # leave the page at its natural top position.
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
            metadata = {"capture_id": row["capture_id"], "url": page.url, "console_errors": errors,
                        "failed_requests": failed_requests, "screenshot": str(screenshot),
                        "captured_at": datetime.now(timezone.utc).isoformat()}
            self._metadata.append(metadata)
            (self.output_dir / "run-metadata.json").write_text(json.dumps({"captures": self._metadata}, indent=2))
            browser.close()
        return metadata

    def capture_sample(self, ids: list[str]) -> list[dict[str, Any]]:
        selected = [r for r in MANIFEST if r["capture_id"] in ids]
        if len(selected) != len(ids):
            raise ValueError("unknown capture ID in sample")
        return [self.capture(row) for row in selected]