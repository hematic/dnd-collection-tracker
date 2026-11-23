import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from app import db, pdf_indexer, settings


class ForcedReindexTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, value in (
            ("DATA_DIR", root),
            ("DB_PATH", root / "tracker.db"),
            ("COVERS_DIR", root / "covers"),
        ):
            self.enterContext(patch.object(db, name, value))
        self.enterContext(patch.object(settings, "PDF_MAP", []))
        self.pdf_path = root / "book.pdf"
        self.page_texts = [
            "This is the original searchable text on the first PDF page.",
            "This is the original searchable text on the second PDF page.",
        ]
        with pymupdf.open() as document:
            for text in self.page_texts:
                document.new_page().insert_text((72, 72), text)
            document.save(self.pdf_path)
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO work (id, title, edition, book_type) "
                "VALUES ('book', 'Test book', 'AD&D 1e', 'Core Rulebook')"
            )
            conn.execute(
                "INSERT INTO release (id, work_id, pdf_path) VALUES ('book--orig', 'book', ?)",
                (str(self.pdf_path),),
            )
        self.worker_id = "test-worker"
        pdf_indexer._acquire_worker(self.worker_id)
        pdf_indexer.resume_worker()

    def index_job(self, job):
        self.assertIsNotNone(job)
        release_id, force = job
        pdf_indexer._index_release(
            release_id, force=force, stop_event=threading.Event()
        )

    def indexed_texts(self):
        with db.connect() as conn:
            return [
                row["text"] for row in conn.execute(
                    "SELECT text FROM pdf_text_page WHERE release_id = 'book--orig' "
                    "ORDER BY page_number"
                )
            ]

    def test_force_requested_during_processing_reindexes_every_page_once(self):
        pdf_indexer.enqueue("book--orig")
        current_job = pdf_indexer._claim_next_job(self.worker_id)
        pdf_indexer.enqueue("book--orig", force=True)
        self.index_job(current_job)
        with db.connect() as conn:
            conn.execute(
                "UPDATE pdf_text_page SET text = 'Stale indexed text' "
                "WHERE release_id = 'book--orig'"
            )

        pdf_indexer._queue_forced_followup("book--orig")
        followup = pdf_indexer._claim_next_job(self.worker_id)
        self.index_job(followup)
        self.assertEqual(self.indexed_texts(), self.page_texts)
        self.assertEqual(followup, ("book--orig", True))

        pdf_indexer._queue_forced_followup("book--orig")
        self.assertIsNone(pdf_indexer._claim_next_job(self.worker_id))

    def test_nonforced_job_resumes_without_reindexing_completed_pages(self):
        pdf_indexer.enqueue("book--orig")
        file_stat = self.pdf_path.stat()
        with db.connect() as conn:
            conn.execute(
                "UPDATE pdf_index SET file_size = ?, file_mtime_ns = ?, page_count = 2, "
                "indexed_pages = 1, ocr_pages = 0 WHERE release_id = 'book--orig'",
                (file_stat.st_size, file_stat.st_mtime_ns),
            )
            conn.execute(
                "INSERT INTO pdf_text_page (release_id, page_number, text) "
                "VALUES ('book--orig', 1, 'Previously indexed first page')"
            )

        job = pdf_indexer._claim_next_job(self.worker_id)
        self.index_job(job)
        self.assertEqual(
            self.indexed_texts(),
            ["Previously indexed first page", self.page_texts[1]],
        )
        pdf_indexer._queue_forced_followup("book--orig")
        self.assertIsNone(pdf_indexer._claim_next_job(self.worker_id))

    def test_ocr_retries_an_oversized_render_at_lower_resolution(self):
        error = pymupdf.mupdf.FzErrorLimit("Overly large image")
        pdf_indexer.enqueue("book--orig")
        with patch.object(pymupdf.Page, "get_images", return_value=[object()]), \
                patch.object(pymupdf.Page, "get_text", side_effect=["", "Recovered scan text", self.page_texts[1]]), \
                patch.object(pymupdf.Page, "get_textpage_ocr", side_effect=[error, object()]) as ocr:
            self.index_job(pdf_indexer._claim_next_job(self.worker_id))
        resolutions = [call.kwargs["dpi"] for call in ocr.call_args_list]
        self.assertEqual(len(resolutions), 2)
        self.assertLess(resolutions[1], resolutions[0])
        self.assertEqual(self.indexed_texts(), ["Recovered scan text", self.page_texts[1]])
        self.assertEqual(pdf_indexer.status()["ocr_pages"], 1)
        self.assertEqual(pdf_indexer.status()["done"], 1)

    def test_persistent_image_limit_reports_the_failed_page(self):
        error = pymupdf.mupdf.FzErrorLimit("Overly large image")
        pdf_indexer.enqueue("book--orig")
        with patch.object(pymupdf.Page, "get_images", return_value=[object()]), \
                patch.object(pymupdf.Page, "get_text", side_effect=[self.page_texts[0], ""]), \
                patch.object(pymupdf.Page, "get_textpage_ocr", side_effect=error):
            with self.assertRaisesRegex(ValueError, "Page 2 of 2.*image"):
                self.index_job(pdf_indexer._claim_next_job(self.worker_id))
        status = pdf_indexer.status()
        self.assertEqual(status["error"], 1)
        self.assertIn("Page 2 of 2", status["failures"][0]["error"])
        self.assertEqual(self.indexed_texts(), [self.page_texts[0]])

    def test_enqueue_all_batches_writes_and_preserves_job_state(self):
        file_stat = self.pdf_path.stat()
        with db.connect() as conn:
            for suffix in ("unchanged", "backfill", "missing"):
                conn.execute(
                    "INSERT INTO release (id, work_id, pdf_path) VALUES (?, 'book', ?)",
                    (suffix, str(self.pdf_path) if suffix != "missing" else str(self.pdf_path) + ".missing"),
                )
            for release_id, status, ocr_pages, force in (
                ("book--orig", "processing", 0, 1),
                ("unchanged", "done", 0, 0),
                ("backfill", "done", None, 0),
                ("missing", "done", 0, 0),
            ):
                conn.execute(
                    "INSERT INTO pdf_index (release_id, status, ocr_pages, force_reindex, "
                    "file_size, file_mtime_ns) VALUES (?, ?, ?, ?, ?, ?)",
                    (release_id, status, ocr_pages, force, file_stat.st_size, file_stat.st_mtime_ns),
                )
        with patch.object(db, "connect", wraps=db.connect) as connect:
            self.assertEqual(pdf_indexer.enqueue_all(), 3)
        self.assertEqual(connect.call_count, 2)
        with db.connect() as conn:
            states = {
                row["release_id"]: (row["status"], row["force_reindex"])
                for row in conn.execute("SELECT * FROM pdf_index")
            }
        self.assertEqual(states, {
            "book--orig": ("processing", 1),
            "unchanged": ("done", 0),
            "backfill": ("queued", 1),
            "missing": ("queued", 0),
        })

    def test_retry_failed_batches_forced_jobs(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO release (id, work_id, pdf_path) VALUES ('other', 'book', ?)",
                (str(self.pdf_path),),
            )
            conn.executemany(
                "INSERT INTO pdf_index (release_id, status) VALUES (?, 'error')",
                [("book--orig",), ("other",)],
            )
        with patch.object(db, "connect", wraps=db.connect) as connect:
            self.assertEqual(pdf_indexer.retry_failed(), 2)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(pdf_indexer._claim_next_job(self.worker_id), ("book--orig", True))
        self.assertEqual(pdf_indexer._claim_next_job(self.worker_id), ("other", True))


if __name__ == "__main__":
    unittest.main()
