"""
Capture admin console screenshots at iPhone 15 Pro viewport (393x852).
Authenticates via Flask session injection, then uses Playwright to
scroll and screenshot each admin page top/mid/bottom.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "screenshots", "admin-mobile-review")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "http://localhost:5000"

# ── Step 1: generate a valid session cookie via Flask test client ──────────
os.environ.setdefault("FLASK_ENV", "development")
from app import app, db, User

app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

with app.app_context():
    admin = User.query.filter_by(email="richardbattlebaxter@gmail.com").first()
    assert admin, "Admin user not found"
    admin_id = admin.id
    print(f"Admin user: id={admin_id} email={admin.email}")

session_cookie_value = None
with app.test_client() as client:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True
    # Force cookie generation
    resp = client.get("/home")
    assert resp.status_code in (200, 302), f"Unexpected status: {resp.status_code}"
    # Pull the Set-Cookie header
    for raw in resp.headers.getlist("Set-Cookie"):
        if raw.startswith("session="):
            session_cookie_value = raw.split("=", 1)[1].split(";")[0]
            break
    # Fallback: read from cookie jar
    if not session_cookie_value:
        for c in client.cookie_jar:
            if c.name == "session":
                session_cookie_value = c.value
                break

assert session_cookie_value, "Could not extract session cookie"
print(f"Session cookie obtained (length={len(session_cookie_value)})")

# ── Step 2: Define pages ───────────────────────────────────────────────────
PAGES = [
    ("01", "02", "03", "/admin/dashboard",    "Admin Dashboard"),
    ("04", "05", "06", "/admin/growth",        "Admin Growth"),
    ("07", "08", "09", "/admin/messaging",     "Admin Messaging"),
    ("10", "11", "12", "/admin/trips",         "Admin Trips"),
    ("13", "14", "15", "/admin/user-insights", "Admin User Insights"),
    ("16", "17", "18", "/admin/resorts",       "Admin Resorts"),
]
EXTRA_PAGES = [
    ("19", "20", "/admin/message-events", "Admin Message Events"),
]

results = []  # list of dicts for README

# ── Step 3: Run Playwright ─────────────────────────────────────────────────
from playwright.sync_api import sync_playwright

def take_page_shots(page, num_top, num_mid, num_bot, path, label):
    url = BASE_URL + path
    print(f"\n→ {label}  {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=20000)
    except Exception as e:
        print(f"  WARN goto timeout/error: {e} — continuing")

    # Confirm not redirected to login
    current = page.url
    if "/auth" in current:
        print(f"  ERROR: redirected to login for {path}")
        results.append({"label": label, "url": url, "status": "ERROR — redirected to login", "files": []})
        return

    total_height = page.evaluate("document.body.scrollHeight")
    vp_height    = 852
    mid_y        = max(0, (total_height - vp_height) // 2)
    bot_y        = max(0, total_height - vp_height)

    files = []
    for (scroll_y, suffix, num) in [
        (0,      "top",    num_top),
        (mid_y,  "mid",    num_mid),
        (bot_y,  "bottom", num_bot),
    ]:
        page.evaluate(f"window.scrollTo(0, {scroll_y})")
        time.sleep(0.3)
        slug = label.lower().replace(" ", "_")
        fname = f"{num}_{slug}_{suffix}_iphone15pro.png"
        fpath = os.path.join(OUTPUT_DIR, fname)
        page.screenshot(path=fpath, type="png")
        print(f"  ✓ {fname}  (scrollY={scroll_y}, pageH={total_height})")
        files.append(fname)

    results.append({
        "label":  label,
        "url":    url,
        "status": "OK",
        "files":  files,
    })

def take_extra_shots(page, num_top, num_bot, path, label):
    url = BASE_URL + path
    print(f"\n→ {label}  {url}")
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=10000)
    except Exception as e:
        print(f"  WARN: {e}")
        results.append({"label": label, "url": url, "status": "NOT ACCESSIBLE (timeout/error)", "files": []})
        return

    current = page.url
    if "/auth" in current or (resp and resp.status in (404, 302)):
        status = f"NOT ACCESSIBLE (status={resp.status if resp else '?'}, redirected={'/auth' in current})"
        print(f"  SKIP: {status}")
        results.append({"label": label, "url": url, "status": status, "files": []})
        return

    total_height = page.evaluate("document.body.scrollHeight")
    vp_height    = 852
    bot_y        = max(0, total_height - vp_height)

    files = []
    for (scroll_y, suffix, num) in [(0, "top", num_top), (bot_y, "bottom", num_bot)]:
        page.evaluate(f"window.scrollTo(0, {scroll_y})")
        time.sleep(0.3)
        slug = label.lower().replace(" ", "_")
        fname = f"{num}_{slug}_{suffix}_iphone15pro.png"
        fpath = os.path.join(OUTPUT_DIR, fname)
        page.screenshot(path=fpath, type="png")
        print(f"  ✓ {fname}  (scrollY={scroll_y})")
        files.append(fname)

    results.append({"label": label, "url": url, "status": "OK", "files": files})

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 393, "height": 852},
        device_scale_factor=3,      # Retina-level for iPhone 15 Pro
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        is_mobile=True,
        has_touch=True,
    )

    # Inject session cookie
    context.add_cookies([{
        "name":     "session",
        "value":    session_cookie_value,
        "domain":   "localhost",
        "path":     "/",
        "httpOnly": True,
        "secure":   False,
        "sameSite": "Lax",
    }])

    page = context.new_page()

    # Verify auth works before looping
    page.goto(BASE_URL + "/home", wait_until="networkidle", timeout=15000)
    if "/auth" in page.url:
        print("SESSION COOKIE NOT WORKING — trying login form...")
        # Fallback: this won't work without the real password, but let's note it
        print("FATAL: Could not authenticate. Aborting.")
        sys.exit(1)
    else:
        print(f"Auth OK — current URL: {page.url}")

    # Capture all main pages
    for (n1, n2, n3, path, label) in PAGES:
        take_page_shots(page, n1, n2, n3, path, label)

    # Capture extra pages
    for (n1, n2, path, label) in EXTRA_PAGES:
        take_extra_shots(page, n1, n2, path, label)

    browser.close()

# ── Step 4: Write README ───────────────────────────────────────────────────
readme_path = os.path.join(OUTPUT_DIR, "README.md")
lines = [
    "# Admin Console — Mobile Screenshot Review",
    "",
    "**Captured:** 2026-05-27  |  **Viewport:** 393×852 (iPhone 15 Pro logical pixels, 3× device scale)  |  **Tool:** Playwright/Chromium headless",
    "",
    "---",
    "",
    "## Screenshot Index",
    "",
    "| File | Page | URL | Status | Notes |",
    "|------|------|-----|--------|-------|",
]
for r in results:
    for fname in r["files"]:
        row = f"| `{fname}` | {r['label']} | `{r['url']}` | {r['status']} | |"
        lines.append(row)
    if not r["files"]:
        row = f"| — | {r['label']} | `{r['url']}` | {r['status']} | No screenshots captured |"
        lines.append(row)

lines += [
    "",
    "---",
    "",
    "## Pages Summary",
    "",
]
for r in results:
    icon = "✅" if r["status"] == "OK" else "❌"
    lines.append(f"- {icon} **{r['label']}** (`{r['url']}`) — {r['status']}")
    for f in r["files"]:
        lines.append(f"  - `{f}`")

with open(readme_path, "w") as fh:
    fh.write("\n".join(lines) + "\n")

print(f"\n✅ README written to {readme_path}")
print(f"\n{'='*60}")
print("DONE")
total_shots = sum(len(r["files"]) for r in results)
print(f"Total screenshots captured: {total_shots}")
for r in results:
    status_icon = "✅" if r["status"] == "OK" else "❌"
    print(f"  {status_icon} {r['label']}: {len(r['files'])} shots")
