"""Static contract coverage for BL-28's native startup checklist."""

from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
NATIVE_JS = (ROOT / "static/js/bl-native.js").read_text()
SPLASH_STORYBOARD = (ROOT / "ios/App/App/Base.lproj/LaunchScreen.storyboard").read_text()
CAPACITOR_CONFIG = (ROOT / "capacitor.config.json").read_text()


def _startup_block():
    start = NATIVE_JS.index("/* ── Native startup checklist")
    end = NATIVE_JS.index("/* ── Form submit loader")
    return NATIVE_JS[start:end]


def test_native_startup_checklist_is_native_only_and_one_shot():
    startup = _startup_block()

    assert "window.Capacitor" in startup
    assert "if (!_isNativeSp && !_hasWkSp) return;" in startup
    assert "bl_native_startup_handoff_seen" in startup
    assert "bl-native-startup" in startup
    assert "window.history" not in startup


def test_native_startup_copy_uses_only_approved_truthful_milestones():
    startup = _startup_block()

    for approved_copy in (
        "Hang tight while we",
        "Opening BaseLodge",
        "Restoring your session",
        "Preparing your screen",
        "Loading sign in",
        "Taking you to your invite",
        "Taking you to your trip invite",
        "Taking you to your link",
    ):
        assert approved_copy in startup

    lowered = startup.lower()
    for unsupported_claim in (
        "finding friends",
        "checking trips",
        "checking preferences",
        "matching availability",
        "loading passes",
        "syncing notifications",
    ):
        assert unsupported_claim not in lowered


def test_native_startup_has_bounded_fallback_and_no_push_gate():
    startup = _startup_block()

    assert "}, 7000);" in startup
    assert "Try again" in startup
    assert "Continue" in startup
    assert "bl-native-startup--stalled" in startup
    assert "OneSignal" not in startup
    assert "PushNotifications" not in startup
    assert '"launchAutoHide": true' in CAPACITOR_CONFIG
    assert '"launchShowDuration": 8000' in CAPACITOR_CONFIG


def test_native_startup_respects_reduced_motion_and_deep_link_navigation():
    startup = _startup_block()

    assert "prefers-reduced-motion:reduce" in startup
    assert "animation:none" in startup
    assert "wordmark.complete" in startup
    assert "_startupVisualReady" in startup
    assert "bl-native-startup__wordmark-fallback" in startup
    assert "wordmark.addEventListener('error', _showWordmarkFallback" in startup
    assert 'data-bl-startup-wordmark-fallback hidden' not in startup
    assert "_hideNativeSplash();\n      _maybeDismissStartupOverlay();" in startup
    assert "window.blNativeStartupSetDestination" in NATIVE_JS
    assert NATIVE_JS.index("window.blNativeStartupSetDestination(path)") < NATIVE_JS.index(
        "window.location.href = path;"
    )


def test_ios_static_launch_artwork_no_longer_contains_generic_loading_label():
    assert "Loading" not in SPLASH_STORYBOARD


def test_native_startup_waits_for_wordmark_and_continue_releases_stall():
    """Exercise the startup block's two critical handoff paths in a tiny DOM shim."""
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const source = fs.readFileSync({str(ROOT / "static/js/bl-native.js")!r}, 'utf8');
        const startup = source.slice(
          source.indexOf('/* ── Native startup checklist'),
          source.indexOf('/* ── Form submit loader')
        );

        let hideCalls = 0;
        let nextTimer = 1;
        const timers = [];
        const rafs = [];
        const docListeners = {{}};
        const windowListeners = {{}};
        const ids = {{}};
        const readinessEvent = process.argv[1];

        class Element {{
          constructor(tag) {{
            this.tagName = tag.toUpperCase();
            this.children = [];
            this.attributes = {{}};
            this.listeners = {{}};
            this.queries = {{}};
            this.classList = {{
              values: new Set(),
              add: (...names) => names.forEach((name) => this.classList.values.add(name))
            }};
            this.complete = false;
          }}
          appendChild(child) {{
            this.children.push(child);
            child.parentNode = this;
            if (child.id) ids[child.id] = child;
            return child;
          }}
          removeChild(child) {{
            this.children = this.children.filter((item) => item !== child);
            child.parentNode = null;
          }}
          addEventListener(name, callback) {{
            (this.listeners[name] ||= []).push(callback);
          }}
          dispatch(name) {{
            (this.listeners[name] || []).forEach((callback) => callback({{
              preventDefault() {{}}, key: name, shiftKey: false
            }}));
          }}
          setAttribute(name, value) {{ this.attributes[name] = String(value); }}
          removeAttribute(name) {{ delete this.attributes[name]; }}
          querySelector(selector) {{ return this.queries[selector] || null; }}
          querySelectorAll() {{
            return ['[data-bl-startup-retry]', '[data-bl-startup-continue]']
              .map((selector) => this.queries[selector]).filter(Boolean);
          }}
          focus() {{ document.activeElement = this; }}
          set innerHTML(value) {{
            if (!value.includes('bl-native-startup__content')) return;
            const wordmark = new Element('img');
            const heading = new Element('p');
            const steps = new Element('div');
            const message = new Element('p');
            const fallback = new Element('div');
            const retry = new Element('button');
            const continueButton = new Element('button');
            wordmark.complete = false;
            fallback.hidden = false;
            this.queries['.bl-native-startup__wordmark'] = wordmark;
            this.queries['[data-bl-startup-heading]'] = heading;
            this.queries['[data-bl-startup-steps]'] = steps;
            this.queries['[data-bl-startup-message]'] = message;
            this.queries['[data-bl-startup-wordmark-fallback]'] = fallback;
            this.queries['[data-bl-startup-retry]'] = retry;
            this.queries['[data-bl-startup-continue]'] = continueButton;
          }}
        }}

        const document = {{
          readyState: 'loading',
          head: new Element('head'),
          body: new Element('body'),
          activeElement: new Element('button'),
          createElement(tag) {{ return new Element(tag); }},
          getElementById(id) {{ return ids[id] || null; }},
          addEventListener(name, callback) {{ (docListeners[name] ||= []).push(callback); }},
          removeEventListener() {{}},
          contains() {{ return true; }}
        }};
        const window = {{
          Capacitor: {{
            isNativePlatform: () => true,
            Plugins: {{ SplashScreen: {{ hide: () => {{ hideCalls += 1; }} }} }}
          }},
          webkit: {{ messageHandlers: {{ capacitor: {{}} }} }},
          sessionStorage: {{ getItem: () => null, setItem: () => {{}} }},
          location: {{ pathname: '/home', reload: () => {{}} }},
          setTimeout(callback, ms) {{
            const timer = {{ id: nextTimer++, callback, ms }};
            timers.push(timer);
            return timer.id;
          }},
          clearTimeout(id) {{
            const index = timers.findIndex((timer) => timer.id === id);
            if (index >= 0) timers.splice(index, 1);
          }},
          addEventListener(name, callback) {{ (windowListeners[name] ||= []).push(callback); }}
        }};
        const context = {{
          window, document, console,
          Promise,
          setTimeout: window.setTimeout.bind(window),
          requestAnimationFrame: (callback) => rafs.push(callback)
        }};

        async function flushFrames(count) {{
          for (let index = 0; index < count; index += 1) {{
            await Promise.resolve();
            const batch = rafs.splice(0);
            batch.forEach((callback) => callback());
          }}
          await Promise.resolve();
        }}

        (async () => {{
          vm.runInNewContext(startup, context);
          docListeners.DOMContentLoaded.forEach((callback) => callback());
          if (hideCalls !== 0) throw new Error('native splash hid before wordmark readiness');

          const overlay = document.body.children.find((child) => child.id === 'bl-native-startup');
          if (overlay.querySelector('[data-bl-startup-wordmark-fallback]').hidden !== false) {{
            throw new Error('pending wordmark did not retain a visible fallback');
          }}
          overlay.querySelector('.bl-native-startup__wordmark').dispatch(readinessEvent);
          if (readinessEvent === 'error'
              && overlay.querySelector('[data-bl-startup-wordmark-fallback]').hidden !== false) {{
            throw new Error('wordmark failure did not install a visible fallback');
          }}
          await flushFrames(5);
          if (hideCalls !== 1) throw new Error('native splash did not hide after wordmark paint');

          const stall = timers.find((timer) => timer.ms === 7000);
          stall.callback();
          await flushFrames(1);
          if (overlay.attributes.role !== 'dialog') throw new Error('stalled state is not actionable');
          overlay.querySelector('[data-bl-startup-continue]').dispatch('click');
          const exit = timers.find((timer) => timer.ms === 190);
          exit.callback();
          if (document.body.children.includes(overlay)) throw new Error('Continue did not release overlay');
        }})().catch((error) => {{
          console.error(error);
          process.exit(1);
        }});
        """
    )
    for readiness_event in ("load", "error"):
        result = subprocess.run(
            ["node", "-e", script, readiness_event],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout