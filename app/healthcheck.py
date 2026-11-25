"""Container health check for both services: python -m app.healthcheck

The web app is healthy when GET /healthz answers. The OCR worker is healthy when it
has renewed its queue lease recently, which it records by touching a local file, so
neither check queries the database. The role comes from the container's command line,
so the Dockerfile's single HEALTHCHECK covers both services.

Kept free of heavy imports: it runs every interval in its own Python process.
"""
from __future__ import annotations

import sys
import tempfile
import time
import urllib.request
from pathlib import Path

WEB_URL = "http://127.0.0.1:8000/healthz"
WORKER_HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "dnd-tracker-worker.heartbeat"
# Matches the lease the UI uses to show the worker as online.
WORKER_MAX_AGE_SECONDS = 60
WORKER_MODULE = "app.pdf_worker"


def touch_worker_heartbeat() -> None:
    WORKER_HEARTBEAT_FILE.touch()


def clear_worker_heartbeat() -> None:
    WORKER_HEARTBEAT_FILE.unlink(missing_ok=True)


def is_worker_container(cmdline_path: Path = Path("/proc/1/cmdline")) -> bool:
    try:
        args = cmdline_path.read_bytes().split(b"\0")
    except OSError:
        return False
    return WORKER_MODULE.encode() in args


def check_worker() -> str | None:
    try:
        age = time.time() - WORKER_HEARTBEAT_FILE.stat().st_mtime
    except FileNotFoundError:
        return "OCR worker has not claimed the indexing queue"
    if age > WORKER_MAX_AGE_SECONDS:
        return f"OCR worker heartbeat is {age:.0f}s old"
    return None


def check_web() -> str | None:
    try:
        with urllib.request.urlopen(WEB_URL, timeout=4) as response:
            response.read()
    except Exception as exc:
        return f"Web app did not answer {WEB_URL}: {exc}"
    return None


def main() -> int:
    problem = check_worker() if is_worker_container() else check_web()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
