import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, healthcheck, main, pdf_indexer, settings


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.heartbeat = self.root / "worker.heartbeat"
        self.enterContext(patch.object(healthcheck, "WORKER_HEARTBEAT_FILE", self.heartbeat))

    def write_cmdline(self, *args):
        path = self.root / "cmdline"
        path.write_bytes(b"\0".join(arg.encode() for arg in args) + b"\0")
        return path

    def test_healthz_answers_without_the_database(self):
        with patch.object(db, "connect", side_effect=AssertionError("healthz used the database")):
            self.assertEqual(main.healthz(), {"status": "ok"})

    def test_role_comes_from_the_container_command(self):
        worker = self.write_cmdline("python", "-m", "app.pdf_worker")
        self.assertTrue(healthcheck.is_worker_container(worker))
        with_init = self.write_cmdline("/sbin/docker-init", "--", "python", "-m", "app.pdf_worker")
        self.assertTrue(healthcheck.is_worker_container(with_init))
        web = self.write_cmdline("uvicorn", "app.main:app", "--host", "0.0.0.0")
        self.assertFalse(healthcheck.is_worker_container(web))
        self.assertFalse(healthcheck.is_worker_container(self.root / "missing"))

    def test_worker_check_requires_a_fresh_heartbeat(self):
        self.assertIn("has not claimed", healthcheck.check_worker())
        healthcheck.touch_worker_heartbeat()
        self.assertIsNone(healthcheck.check_worker())
        stale = time.time() - healthcheck.WORKER_MAX_AGE_SECONDS - 5
        os.utime(self.heartbeat, (stale, stale))
        self.assertIn("old", healthcheck.check_worker())

    def test_worker_max_age_matches_the_ui_lease(self):
        self.assertEqual(healthcheck.WORKER_MAX_AGE_SECONDS, pdf_indexer.WORKER_LEASE_SECONDS)


class WorkerHeartbeatFileTests(unittest.TestCase):
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
        self.heartbeat = root / "worker.heartbeat"
        self.enterContext(patch.object(healthcheck, "WORKER_HEARTBEAT_FILE", self.heartbeat))
        self.enterContext(patch.object(pdf_indexer, "_lower_worker_priority"))
        db.init_db()

    def test_worker_records_heartbeat_while_running_and_clears_it_on_stop(self):
        stop_event = threading.Event()
        seen = []

        def claim_once(worker_id):
            seen.append(healthcheck.check_worker())
            stop_event.set()
            return None

        with patch.object(pdf_indexer, "_claim_next_job", side_effect=claim_once):
            pdf_indexer.run_worker(stop_event)

        self.assertEqual(seen, [None])
        self.assertFalse(self.heartbeat.exists())

    def test_lease_renewal_refreshes_the_heartbeat(self):
        worker_id = "test-worker"
        pdf_indexer._acquire_worker(worker_id)
        heartbeat_stop = threading.Event()
        stop_event = threading.Event()
        waits = iter([False, True])
        with patch.object(heartbeat_stop, "wait", side_effect=lambda _: next(waits)):
            pdf_indexer._heartbeat_worker(worker_id, heartbeat_stop, stop_event)
        self.assertTrue(self.heartbeat.exists())
        self.assertFalse(stop_event.is_set())

    def test_lost_lease_does_not_refresh_the_heartbeat(self):
        pdf_indexer._acquire_worker("other-worker")
        heartbeat_stop = threading.Event()
        stop_event = threading.Event()
        with patch.object(heartbeat_stop, "wait", return_value=False):
            pdf_indexer._heartbeat_worker("test-worker", heartbeat_stop, stop_event)
        self.assertFalse(self.heartbeat.exists())
        self.assertTrue(stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
