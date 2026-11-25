"""Checks the Docker smoke test (.github/workflows/docker.yml) runs inside the image.

The image doesn't contain this file, so the workflow pipes it in:
    python - make-pdf DIR        write an image-only PDF that indexing has to OCR
    python - web EXPECTED_EDIT   check the web container, including every path that writes
    python - worker              check the OCR worker container

Not a unittest module: it needs a running stack.
"""
from __future__ import annotations

import errno
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PDF_NAME = "ocr-smoke.pdf"
OCR_WORD = "Beholder"
# Editor identity for the authenticated stack; ignored where everyone can edit.
EDITOR = {"Remote-User": "smoke"}
# Larger than Starlette's 1 MB in-memory limit, so the upload is buffered in /tmp.
UPLOAD_BYTES = 2 * 1024 * 1024


def make_pdf(directory: str) -> None:
    import pymupdf

    with pymupdf.open() as source:
        page = source.new_page()
        page.insert_text((72, 144), f"{OCR_WORD} lair tactics", fontsize=36)
        image = page.get_pixmap(dpi=200).tobytes("png")
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_image(page.rect, stream=image)
        assert not page.get_text().strip(), "the smoke PDF must have no embedded text"
        document.save(Path(directory) / PDF_NAME, garbage=3, deflate=True)


def check_hardening() -> None:
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        status[key] = value.strip()
    assert status["NoNewPrivs"] == "1", f"no-new-privileges is off: {status['NoNewPrivs']}"
    assert int(status["CapBnd"], 16) == 0, f"capabilities were not dropped: {status['CapBnd']}"
    try:
        Path("/app/.write-test").write_text("x")
    except OSError as exc:
        assert exc.errno == errno.EROFS, exc
    else:
        raise AssertionError("the root filesystem is writable")
    probe = Path(tempfile.gettempdir()) / f"write-test-{uuid.uuid4().hex}"
    probe.write_text("x")
    probe.unlink()


def call(method: str, endpoint: str, body: bytes | None = None, content_type: str | None = None,
         headers: dict[str, str] | None = None):
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{endpoint}", data=body, method=method, headers=dict(headers or {})
    )
    if content_type:
        request.add_header("Content-Type", content_type)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def wait_for(description: str, probe, timeout: float = 120):
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if result:
            return result
        if time.monotonic() > deadline:
            raise SystemExit(f"Timed out waiting for {description}")
        time.sleep(1)


def first_release_id() -> str:
    with sqlite3.connect("file:/data/tracker.db?mode=ro", uri=True) as conn:
        return conn.execute("SELECT id FROM release ORDER BY id LIMIT 1").fetchone()[0]


def upload_cover(path: str) -> None:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="cover.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + os.urandom(UPLOAD_BYTES) + f"\r\n--{boundary}--\r\n".encode()
    call("POST", path, body, f"multipart/form-data; boundary={boundary}", EDITOR)


def index_finished():
    status = call("GET", "/api/pdf-index")
    if status["error"]:
        raise SystemExit(f"PDF indexing failed: {status['failures']}")
    return status if status["done"] and not status["queued"] and not status["processing"] else None


def web(expected_edit: str) -> None:
    from app.version import APP_VERSION

    check_hardening()
    meta = call("GET", "/api/meta")
    assert meta["version"] == APP_VERSION
    assert meta["can_edit"] is (expected_edit == "true")
    wait_for("the OCR worker", lambda: call("GET", "/api/pdf-index")["worker_online"], timeout=30)

    release = urllib.parse.quote(first_release_id(), safe="")
    linked = call(
        "PATCH", f"/api/releases/{release}/pdf",
        json.dumps({"library_path": PDF_NAME}).encode(), "application/json", EDITOR,
    )
    assert linked.get("warning") is None, linked["warning"]
    upload_cover(f"/api/releases/{release}/cover")

    call("POST", "/api/pdf-index?mode=all", b"", None, EDITOR)
    status = wait_for("PDF indexing", index_finished)
    assert status["ocr_pages"] > 0, status
    found = call("GET", f"/api/search/pdf?q={OCR_WORD}")
    assert found["total"] > 0, f"OCR text for {OCR_WORD!r} is not searchable: {status}"


def worker() -> None:
    check_hardening()


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    {"make-pdf": make_pdf, "web": web, "worker": worker}[command](*args)
