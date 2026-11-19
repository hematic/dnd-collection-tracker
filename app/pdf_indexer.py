"""Local, resumable indexing of linked PDF pages."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

import pymupdf

from . import db, settings

logger = logging.getLogger(__name__)
MIN_EMBEDDED_CHARS = 30
OCR_DPI = 200
WORKER_LEASE_SECONDS = 60
WORKER_HEARTBEAT_SECONDS = 10
WORKER_POLL_SECONDS = 1


def resume_worker() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE pdf_index_control SET paused = 0 WHERE id = 1")
    logger.info("PDF indexing resumed")


def pause_worker() -> None:
    with db.connect() as conn:
        conn.execute("UPDATE pdf_index_control SET paused = 1 WHERE id = 1")
    logger.info("PDF indexing paused; the current page will finish first")


def enqueue(release_id: str, *, force: bool = False) -> None:
    _enqueue_many([(release_id, force)])


def _enqueue_many(jobs: list[tuple[str, bool]]) -> int:
    if not jobs:
        return 0
    with db.connect() as conn:
        result = conn.executemany(
            "INSERT INTO pdf_index (release_id, status, force_reindex, error, updated_at) "
            "SELECT id, 'queued', ?, NULL, CURRENT_TIMESTAMP "
            "FROM release WHERE id = ? AND pdf_path IS NOT NULL "
            "ON CONFLICT(release_id) DO UPDATE SET "
            "status = CASE WHEN pdf_index.status = 'processing' THEN 'processing' ELSE 'queued' END, "
            "force_reindex = MAX(pdf_index.force_reindex, excluded.force_reindex), "
            "error = NULL, updated_at = CURRENT_TIMESTAMP",
            ((int(force), release_id) for release_id, force in jobs),
        )
        return result.rowcount


def enqueue_all(*, force: bool = False) -> int:
    with db.connect() as conn:
        releases = [
            dict(row) for row in conn.execute(
                "SELECT r.id, r.pdf_path, i.status, i.ocr_pages, i.file_size, i.file_mtime_ns "
                "FROM release r "
                "LEFT JOIN pdf_index i ON i.release_id = r.id "
                "WHERE r.pdf_path IS NOT NULL ORDER BY r.id"
            )
        ]
    jobs = []
    for release in releases:
        needs_tracking_backfill = release["status"] == "done" and release["ocr_pages"] is None
        needs_index = release["status"] != "done" or force or needs_tracking_backfill
        if not needs_index:
            path = settings.local_path(release["pdf_path"])
            try:
                file_stat = path.stat() if path is not None else None
            except OSError:
                needs_index = True
            else:
                needs_index = file_stat is None or (release["file_size"], release["file_mtime_ns"]) != (
                    file_stat.st_size,
                    file_stat.st_mtime_ns,
                )
        if needs_index:
            jobs.append((release["id"], force or needs_tracking_backfill))
    queued = _enqueue_many(jobs)
    logger.info(
        "%s PDF indexing for %d linked PDFs",
        "Starting forced re-index" if force else "Queued",
        queued,
    )
    return queued


def retry_failed() -> int:
    with db.connect() as conn:
        release_ids = [
            row["release_id"] for row in conn.execute(
                "SELECT i.release_id FROM pdf_index i JOIN release r ON r.id = i.release_id "
                "WHERE i.status = 'error' AND r.pdf_path IS NOT NULL ORDER BY r.id"
            )
        ]
    queued = _enqueue_many([(release_id, True) for release_id in release_ids])
    logger.info("Queued %d failed PDFs for retry", queued)
    return queued


def remove(release_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
        conn.execute("DELETE FROM pdf_index WHERE release_id = ?", (release_id,))
        # A currently active job will see the now-unlinked release before persisting
        # another page; queued jobs are harmless and exit without a linked path.


def status() -> dict:
    with db.connect() as conn:
        control = conn.execute(
            "SELECT paused, worker_id, worker_heartbeat FROM pdf_index_control WHERE id = 1"
        ).fetchone()
        counts = {
            row["status"]: row["count"]
            for row in conn.execute(
                "SELECT i.status, COUNT(*) AS count FROM pdf_index i "
                "JOIN release r ON r.id = i.release_id WHERE r.pdf_path IS NOT NULL "
                "GROUP BY i.status"
            )
        }
        linked = conn.execute("SELECT COUNT(*) FROM release WHERE pdf_path IS NOT NULL").fetchone()[0]
        ocr = conn.execute(
            "SELECT COUNT(*) AS books, COALESCE(SUM(i.ocr_pages), 0) AS pages "
            "FROM pdf_index i JOIN release r ON r.id = i.release_id "
            "WHERE r.pdf_path IS NOT NULL AND i.ocr_pages > 0"
        ).fetchone()
        ocr_unrecorded = conn.execute(
            "SELECT COUNT(*) FROM release r LEFT JOIN pdf_index i ON i.release_id = r.id "
            "WHERE r.pdf_path IS NOT NULL AND i.ocr_pages IS NULL"
        ).fetchone()[0]
        current = conn.execute(
            "SELECT w.title, r.id AS release_id, i.indexed_pages, i.page_count, i.ocr_pages "
            "FROM pdf_index i JOIN release r ON r.id = i.release_id "
            "JOIN work w ON w.id = r.work_id WHERE r.pdf_path IS NOT NULL AND i.status = 'processing' "
            "ORDER BY i.updated_at DESC LIMIT 1"
        ).fetchone()
        failures = [
            dict(row) for row in conn.execute(
                "SELECT w.title, r.id AS release_id, i.error FROM pdf_index i "
                "JOIN release r ON r.id = i.release_id JOIN work w ON w.id = r.work_id "
                "WHERE r.pdf_path IS NOT NULL AND i.status = 'error' ORDER BY w.title LIMIT 50"
            )
        ]
    return {
        "linked": linked,
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "done": counts.get("done", 0),
        "error": counts.get("error", 0),
        "not_indexed": max(0, linked - sum(counts.values())),
        "ocr_books": ocr["books"],
        "ocr_pages": ocr["pages"],
        "ocr_unrecorded": ocr_unrecorded,
        "paused": bool(control["paused"]),
        "worker_online": bool(
            control["worker_id"]
            and control["worker_heartbeat"]
            and control["worker_heartbeat"] > time.time() - WORKER_LEASE_SECONDS
        ),
        "current": dict(current) if current else None,
        "failures": failures,
    }


def _update_error(release_id: str, message: str, *, page_count: int = 0, indexed_pages: int = 0) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pdf_index (release_id, status, page_count, indexed_pages, error, updated_at) "
            "SELECT ?, 'error', ?, ?, ?, CURRENT_TIMESTAMP "
            "WHERE EXISTS (SELECT 1 FROM release WHERE id = ? AND pdf_path IS NOT NULL) "
            "ON CONFLICT(release_id) DO UPDATE SET "
            "status = 'error', error = excluded.error, updated_at = CURRENT_TIMESTAMP",
            (release_id, page_count, indexed_pages, message[:1000], release_id),
        )


def run_worker(stop_event: threading.Event) -> None:
    _lower_worker_priority()
    worker_id = uuid.uuid4().hex
    _acquire_worker(worker_id)
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_worker,
        args=(worker_id, heartbeat_stop, stop_event),
        name="pdf-indexer-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()
    logger.info("PDF indexing worker started")

    try:
        while not stop_event.is_set():
            job = _claim_next_job(worker_id)
            if job is None:
                stop_event.wait(WORKER_POLL_SECONDS)
                continue
            release_id, force = job
            try:
                _index_release(release_id, force=force, stop_event=stop_event)
            except Exception as exc:
                logger.exception("Could not index PDF release %s", release_id)
                try:
                    _update_error(release_id, f"{type(exc).__name__}: {exc}")
                except Exception:
                    logger.exception("Could not record PDF indexing failure for release %s", release_id)
            _queue_forced_followup(release_id)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=WORKER_HEARTBEAT_SECONDS + 1)
        _release_worker(worker_id)
        logger.info("PDF indexing worker stopped")


def _acquire_worker(worker_id: str) -> None:
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        control = conn.execute(
            "SELECT worker_id, worker_heartbeat FROM pdf_index_control WHERE id = 1"
        ).fetchone()
        if (
            control["worker_id"]
            and control["worker_heartbeat"]
            and control["worker_heartbeat"] > now - WORKER_LEASE_SECONDS
        ):
            raise RuntimeError("Another PDF indexing worker currently owns the queue")
        conn.execute(
            "UPDATE pdf_index_control SET worker_id = ?, worker_heartbeat = ? WHERE id = 1",
            (worker_id, now),
        )
        conn.execute(
            "UPDATE pdf_index SET status = 'queued', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'processing'"
        )
    logger.info("Claimed PDF indexing worker lease")


def _heartbeat_worker(
    worker_id: str,
    heartbeat_stop: threading.Event,
    stop_event: threading.Event,
) -> None:
    while not heartbeat_stop.wait(WORKER_HEARTBEAT_SECONDS):
        try:
            with db.connect() as conn:
                result = conn.execute(
                    "UPDATE pdf_index_control SET worker_heartbeat = ? "
                    "WHERE id = 1 AND worker_id = ?",
                    (time.time(), worker_id),
                )
        except Exception:
            logger.exception("Could not renew PDF indexing worker lease")
            stop_event.set()
            return
        if result.rowcount != 1:
            logger.error("PDF indexing worker lease was lost")
            stop_event.set()
            return


def _claim_next_job(worker_id: str) -> tuple[str, bool] | None:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        control = conn.execute(
            "SELECT paused, worker_id FROM pdf_index_control WHERE id = 1"
        ).fetchone()
        if control is None or control["worker_id"] != worker_id or control["paused"]:
            return None
        row = conn.execute(
            "SELECT release_id, force_reindex FROM pdf_index "
            "WHERE status = 'queued' ORDER BY updated_at, release_id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE pdf_index SET status = 'processing', force_reindex = 0, "
            "updated_at = CURRENT_TIMESTAMP WHERE release_id = ? AND status = 'queued'",
            (row["release_id"],),
        )
        return row["release_id"], bool(row["force_reindex"])


def _queue_forced_followup(release_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE pdf_index SET status = 'queued', error = NULL, "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE release_id = ? AND status = 'done' AND force_reindex = 1",
            (release_id,),
        )


def _release_worker(worker_id: str) -> None:
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE pdf_index SET status = 'queued', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'processing' AND EXISTS ("
            "SELECT 1 FROM pdf_index_control WHERE id = 1 AND worker_id = ?)",
            (worker_id,),
        )
        conn.execute(
            "UPDATE pdf_index_control SET worker_id = NULL, worker_heartbeat = NULL "
            "WHERE id = 1 AND worker_id = ?",
            (worker_id,),
        )


def _lower_worker_priority() -> None:
    if hasattr(os, "nice"):
        try:
            priority = os.nice(10)
        except OSError:
            logger.warning(
                "Could not lower PDF indexer CPU priority; OCR may compete with web requests",
                exc_info=True,
            )
        else:
            logger.info("PDF indexer running at reduced CPU priority (nice %d)", priority)
    else:
        logger.info("Reduced PDF indexer CPU priority is unavailable on this platform")


def _index_release(
    release_id: str,
    *,
    force: bool,
    stop_event: threading.Event,
) -> None:
    started_at = time.monotonic()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT r.pdf_path, w.title FROM release r JOIN work w ON w.id = r.work_id WHERE r.id = ?",
            (release_id,),
        ).fetchone()
        if row is None or not row["pdf_path"]:
            conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
            conn.execute("DELETE FROM pdf_index WHERE release_id = ?", (release_id,))
            return
        raw_path = row["pdf_path"]
        title = row["title"]

    path = settings.local_path(raw_path)
    if path is None or not path.is_file():
        message = "Linked PDF is missing or unreadable at its configured path"
        logger.warning("PDF indexing failed for %r (release %s): %s", title, release_id, message)
        _update_error(release_id, message)
        return
    file_stat = path.stat()

    with db.connect() as conn:
        previous = conn.execute("SELECT * FROM pdf_index WHERE release_id = ?", (release_id,)).fetchone()
        same_file = bool(
            previous
            and previous["file_size"] == file_stat.st_size
            and previous["file_mtime_ns"] == file_stat.st_mtime_ns
        )
        if force or not same_file:
            conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
            start_page = 0
            ocr_pages = 0
        elif previous["status"] == "done":
            return
        elif previous["ocr_pages"] is None:
            conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
            start_page = 0
            ocr_pages = 0
        else:
            start_page = previous["indexed_pages"]
            ocr_pages = previous["ocr_pages"]
        conn.execute(
            "INSERT INTO pdf_index (release_id, status, file_size, file_mtime_ns, page_count, indexed_pages, ocr_pages, error, updated_at) "
            "VALUES (?, 'processing', ?, ?, 0, ?, ?, NULL, CURRENT_TIMESTAMP) "
            "ON CONFLICT(release_id) DO UPDATE SET status = 'processing', file_size = excluded.file_size, "
            "file_mtime_ns = excluded.file_mtime_ns, page_count = 0, indexed_pages = excluded.indexed_pages, "
            "ocr_pages = excluded.ocr_pages, error = NULL, updated_at = CURRENT_TIMESTAMP",
            (release_id, file_stat.st_size, file_stat.st_mtime_ns, start_page, ocr_pages),
        )

    page_count = 0
    try:
        logger.info(
            "Opening PDF for indexing: %r (release %s)%s",
            title,
            release_id,
            " [forced re-index]" if force else "",
        )
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ValueError("PDF is password-protected")
            page_count = document.page_count
            start_page = min(start_page, page_count)
            logger.info(
                "Indexing PDF %r (release %s): %d pages, resuming at page %d",
                title,
                release_id,
                page_count,
                start_page + 1 if start_page < page_count else page_count,
            )
            with db.connect() as conn:
                conn.execute(
                    "UPDATE pdf_index SET page_count = ?, indexed_pages = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE release_id = ?",
                    (page_count, start_page, release_id),
                )
            for page_index in range(start_page, page_count):
                while not stop_event.is_set():
                    if not _is_paused():
                        break
                    stop_event.wait(0.5)
                if stop_event.is_set():
                    return
                with db.connect() as conn:
                    linked = conn.execute(
                        "SELECT pdf_path FROM release WHERE id = ?", (release_id,)
                    ).fetchone()
                if linked is None or not linked["pdf_path"]:
                    with db.connect() as conn:
                        conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
                        conn.execute("DELETE FROM pdf_index WHERE release_id = ?", (release_id,))
                    return
                if linked["pdf_path"] != raw_path:
                    return

                page = document.load_page(page_index)
                text = page.get_text("text", sort=True).strip()
                if len(re.sub(r"\s+", "", text)) < MIN_EMBEDDED_CHARS and page.get_images():
                    ocr_started_at = time.monotonic()
                    logger.info(
                        "OCR started: %r (release %s), page %d/%d",
                        title,
                        release_id,
                        page_index + 1,
                        page_count,
                    )
                    text_page = page.get_textpage_ocr(language="eng", dpi=OCR_DPI, full=True)
                    text = page.get_text("text", textpage=text_page, sort=True).strip()
                    ocr_pages += 1
                    logger.info(
                        "OCR finished: %r (release %s), page %d/%d in %.1fs (%d characters)",
                        title,
                        release_id,
                        page_index + 1,
                        page_count,
                        time.monotonic() - ocr_started_at,
                        len(text),
                    )

                with db.connect() as conn:
                    if text:
                        conn.execute(
                            "INSERT INTO pdf_text_page (release_id, page_number, text) VALUES (?, ?, ?) "
                            "ON CONFLICT(release_id, page_number) DO UPDATE SET text = excluded.text",
                            (release_id, page_index + 1, text),
                        )
                    conn.execute(
                        "UPDATE pdf_index SET indexed_pages = ?, ocr_pages = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE release_id = ?",
                        (page_index + 1, ocr_pages, release_id),
                    )
                if (page_index + 1) % 25 == 0:
                    logger.info(
                        "PDF indexing progress: %r (release %s), page %d/%d; %d pages OCRed",
                        title,
                        release_id,
                        page_index + 1,
                        page_count,
                        ocr_pages,
                    )

        with db.connect() as conn:
            linked = conn.execute(
                "SELECT pdf_path FROM release WHERE id = ?", (release_id,)
            ).fetchone()
            if linked is None or not linked["pdf_path"]:
                conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
                conn.execute("DELETE FROM pdf_index WHERE release_id = ?", (release_id,))
                return
            if linked["pdf_path"] != raw_path:
                return

        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (file_stat.st_size, file_stat.st_mtime_ns):
            with db.connect() as conn:
                conn.execute("DELETE FROM pdf_text_page WHERE release_id = ?", (release_id,))
                conn.execute(
                    "UPDATE pdf_index SET indexed_pages = 0, ocr_pages = 0 WHERE release_id = ?",
                    (release_id,),
                )
            _update_error(release_id, "PDF changed while it was being indexed; retry indexing this file")
            return
        with db.connect() as conn:
            conn.execute(
                "UPDATE pdf_index SET status = 'done', page_count = ?, indexed_pages = ?, error = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE release_id = ?",
                (page_count, page_count, release_id),
            )
        logger.info(
            "PDF indexing complete: %r (release %s), %d pages indexed, %d pages OCRed in %.1fs",
            title,
            release_id,
            page_count,
            ocr_pages,
            time.monotonic() - started_at,
        )
    except Exception as exc:
        with db.connect() as conn:
            conn.execute(
                "UPDATE pdf_index SET status = 'error', page_count = ?, error = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE release_id = ?",
                (page_count, f"{type(exc).__name__}: {exc}"[:1000], release_id),
            )
        raise


def _is_paused() -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT paused FROM pdf_index_control WHERE id = 1").fetchone()
    return row is None or bool(row["paused"])
