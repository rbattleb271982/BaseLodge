"""Run the isolated Phase 3 validation sample or a selected manifest subset."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from capture_harness.browser import CaptureRunner
from capture_harness.config import DisposableDatabase, disposable_database_path
from capture_harness.manifest import MANIFEST, validate_manifest


VALIDATION_SAMPLE_IDS = (
    "home__empty__empty__mobile__empty",
    "home__heavy__dense__mobile__top",
    "friends__heavy__heavy-25-friends__mobile__top",
    "trip-detail__heavy__dense-roster__narrow__people",
    "mountain-detail__heavy__social-success__mobile__community",
    "mountain-detail__edge__social-loading__mobile__community",
    "mountain-detail__edge__social-error__mobile__community",
    "profile__heavy__delete-account-modal__mobile__overlays-settings",
    "system__edge__404__mobile__top",
)


def _capture_environment(database_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key in (
        "BASELODGE_DEVELOPMENT_DATABASE_URL",
        "BASELODGE_PRODUCTION_DATABASE_URL",
        "SUPABASE_DATABASE_URL",
        "DATABASE_URL",
    ):
        environment.pop(key, None)
    url = f"sqlite:///{database_path}"
    environment.update(
        BASELODGE_RUNTIME_ENV="test",
        BASELODGE_CAPTURE_MODE="1",
        BASELODGE_CAPTURE_DATABASE_URL=url,
        BASELODGE_TEST_DATABASE_URL=url,
        RATELIMIT_STORAGE_URI="memory://",
        SESSION_SECRET="capture-only-not-a-production-secret",
    )
    return environment


def _wait_for_server(url: str, process: subprocess.Popen, timeout: float = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"capture server exited with {process.returncode}")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("capture server did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="capture-output")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Capture the full manifest (reserved for Phase 4).",
    )
    args = parser.parse_args()
    validate_manifest()
    if args.full and args.ids:
        parser.error("--full and --ids cannot be combined")
    ids = [row["capture_id"] for row in MANIFEST] if args.full else (
        args.ids or list(VALIDATION_SAMPLE_IDS)
    )

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "entries": MANIFEST}, indent=2) + "\n"
    )
    database_path = disposable_database_path()
    environment = _capture_environment(database_path)
    command = [
        sys.executable,
        "-m",
        "capture_harness.server",
        "--port",
        str(args.port),
    ]
    log_path = output / "server.log"
    with DisposableDatabase(database_path), log_path.open("w") as log_file:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{args.port}"
            _wait_for_server(f"{base_url}/api/capture/health", process)
            runner = CaptureRunner(base_url, output)
            metadata = runner.capture_sample(ids)
            (output / "run-metadata.json").write_text(
                json.dumps({"captures": metadata}, indent=2) + "\n"
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())