import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

import pymupdf

from app import covers, db, main, pdf_import, settings


class PdfImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.library = self.root / "library"
        self.library.mkdir()
        for attr, path in (("DATA_DIR", self.root), ("DB_PATH", self.root / "test.db"),
                           ("COVERS_DIR", self.root / "covers")):
            self.enterContext(patch.object(db, attr, path))
        self.enterContext(patch.object(settings, "PDF_ROOT", str(self.library)))
        self.enterContext(patch.object(settings, "PDF_MAP", [("//nas/Books", str(self.library))]))
        self.enterContext(patch.object(settings, "ADMINS", {"editor"}))
        self.enterContext(patch.object(settings, "TRUSTED_PROXIES", set()))
        db.init_db()
        with db.connect() as conn:
            for release, title in (("atlas", "Example Atlas"), ("tales", "Example Tales"),
                                   ("mapped", "Example Almanac"), ("third", "Example Handbook")):
                conn.execute("INSERT INTO work(id, title, edition, book_type) VALUES (?, ?, 'Basic', 'Other')",
                             (release, title))
                conn.execute("INSERT INTO release(id, work_id, is_primary) VALUES (?, ?, 1)", (release, release))

    def pdf(self, path, title=None):
        target = self.library / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((60, 50), "Sample cover")
            if title:
                document.set_metadata({"title": title})
            document.save(target)
        return target

    def request(self, method, url, body=None, *, editor=True):
        path, _, query = url.partition("?")
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": query.encode(), "root_path": "", "client": ("127.0.0.1", 1),
            "server": ("test", 80), "headers": [(b"content-type", b"application/json")],
        }
        if editor:
            scope["headers"].append((b"remote-user", b"editor"))
        messages = []
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"",
                        "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        asyncio.run(main.app(scope, receive, send))
        status = messages[0]["status"]
        payload = b"".join(m.get("body", b"") for m in messages[1:])
        headers = dict(messages[0]["headers"])
        return status, json.loads(payload) if headers.get(b"content-type") == b"application/json" else payload

    def scan(self):
        status, response = self.request("POST", "/api/pdf-import/scan")
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = pdf_import.status()
            if state["status"] != "scanning":
                self.assertEqual(state["status"], "done", state)
                return response["generation"]
            time.sleep(.01)
        self.fail("Background scan timed out")

    def decision(self, generation, path, action, release=None):
        return self.request("PATCH", "/api/pdf-import/files", {
            "generation": generation, "paths": [path], "action": action, "release_id": release,
        })

    def link(self, generation, *entries):
        status, data = self.request("POST", "/api/pdf-import/link", {
            "generation": generation, "items": [{"path": p, "release_id": r} for p, r in entries],
        })
        self.assertEqual(status, 200)
        return data["results"]

    def test_saved_review_and_in_place_link(self):
        atlas = self.pdf("Basic/Example Atlas.PDF")
        original_bytes = atlas.read_bytes()
        self.pdf("download.pdf", "Example Tales")
        self.pdf("ignore me.pdf")
        generation = self.scan()
        ready = self.request("GET", "/api/pdf-import/files?tier=ready&q=basic")[1]
        self.assertEqual(ready["total"], 1)
        self.assertEqual(ready["items"][0]["selected"]["id"], "atlas")
        self.assertEqual(pdf_import.status()["counts"], {"ready": 1, "review": 1, "none": 1, "ignored": 0})
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM release WHERE pdf_path IS NOT NULL").fetchone()[0], 0)
        query = urlencode({"path": "Basic/Example Atlas.PDF"})
        self.assertEqual(self.request("GET", f"/api/pdf-import/preview?{query}")[1][:2], b"\xff\xd8")
        self.assertEqual(self.request("GET", f"/api/pdf-import/file?{query}")[1], original_bytes)
        self.assertIn("error", self.link(generation, ("download.pdf", "tales"))[0])
        self.assertEqual(self.decision(generation, "download.pdf", "choose", "tales")[0], 204)
        self.assertEqual(self.decision(generation, "ignore me.pdf", "ignore")[0], 204)
        with patch.object(covers, "pdf_title", wraps=covers.pdf_title) as read_title:
            latest = self.scan()
            read_title.assert_not_called()
        self.assertEqual(pdf_import.status()["counts"], {"ready": 2, "review": 0, "none": 0, "ignored": 1})
        self.assertIn("error", self.link(generation, ("download.pdf", "tales"))[0])
        by_path = [("Basic/Example Atlas.PDF", "atlas"), ("download.pdf", "tales")]
        self.assertTrue(all(result.get("linked") for result in self.link(latest, *by_path)))
        self.assertEqual(atlas.read_bytes(), original_bytes)
        with db.connect() as conn:
            row = conn.execute("SELECT pdf_path, cover_source, owned_pdf, owned_physical FROM release WHERE id = 'atlas'").fetchone()
            self.assertEqual(tuple(row), ("library:Basic/Example Atlas.PDF", "pdf", 1, 0))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pdf_index").fetchone()[0], 0)
        self.assertEqual(self.decision(latest, "ignore me.pdf", "restore")[0], 204)
        self.assertEqual(pdf_import.status()["counts"]["none"], 1)

    def test_aliases_conflicts_and_changes_do_not_overwrite_links(self):
        original = self.pdf("Example Atlas.pdf")
        alias = self.library / "alternate.pdf"
        alias.hardlink_to(original)
        self.pdf("folder/Example Atlas.pdf")
        self.pdf("Example Tales.pdf")
        self.pdf("Example Handbook.pdf")
        self.pdf("mounted.pdf")
        outside = self.pdf("../outside.pdf")
        try:
            (self.library / "elsewhere.pdf").symlink_to(outside)
        except OSError:
            pass
        with db.connect() as conn:
            conn.execute("UPDATE release SET pdf_path = ? WHERE id = 'mapped'", (r"\\nas\Books\mounted.pdf",))
        generation = self.scan()
        self.assertEqual(pdf_import.status()["already_linked"], 1)
        review = self.request("GET", "/api/pdf-import/files?tier=review")[1]["items"]
        self.assertEqual({row["path"] for row in review}, {"Example Atlas.pdf", "folder/Example Atlas.pdf"})
        self.assertTrue(all("same printing" in row["note"] for row in review))
        self.assertEqual(self.decision(generation, "Example Atlas.pdf", "choose", "atlas")[0], 204)
        self.assertEqual(self.decision(generation, "folder/Example Atlas.pdf", "choose", "atlas")[0], 409)
        with db.connect() as conn:
            conn.execute("UPDATE release SET pdf_path = 'library:alternate.pdf' WHERE id = 'third'")
        original_tales = self.library / "Example Tales.pdf"
        original_tales.unlink()
        self.pdf("Example Tales.pdf", "New contents")
        results = self.link(generation, ("Example Atlas.pdf", "atlas"), ("Example Tales.pdf", "tales"),
                            ("Example Handbook.pdf", "third"))
        for result, text in zip(results, ("already linked", "changed since", "already")):
            self.assertIn(text, result["error"])
        self.assertEqual(self.request("GET", "/api/pdf-import/file?path=elsewhere.pdf")[0], 404)

    def test_editor_guard_and_interrupted_scan(self):
        for method, route in (("POST", "/scan"), ("GET", ""), ("GET", "/files"), ("PATCH", "/files"),
                              ("POST", "/link"), ("GET", "/preview?path=a.pdf"), ("GET", "/file?path=a.pdf")):
            with self.subTest(method=method, route=route):
                self.assertEqual(self.request(method, "/api/pdf-import" + route, editor=False)[0], 403)
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def wait_to_scan(*args):
            started.set()
            release.wait(5)
            finished.set()

        with patch.object(pdf_import, "_run_scan", wait_to_scan):
            self.assertEqual(self.request("POST", "/api/pdf-import/scan")[0], 202)
            try:
                self.assertTrue(started.wait(2))
                self.assertEqual(self.request("POST", "/api/pdf-import/scan")[0], 409)
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
        pdf_import.recover_scan()
        self.assertEqual(pdf_import.status()["status"], "error")
        self.scan()

    def test_batch_rechecks_target_after_cover_render_and_continues(self):
        self.pdf("Example Atlas.pdf")
        self.pdf("Example Tales.pdf")
        generation = self.scan()
        render = covers.render_pdf_cover

        def link_while_rendering(path):
            if Path(path).stem == "Example Atlas":
                with db.connect() as conn:
                    conn.execute("UPDATE release SET pdf_path = 'library:other.pdf' WHERE id = 'atlas'")
            return render(path)

        with patch.object(covers, "render_pdf_cover", side_effect=link_while_rendering):
            first, second = self.link(generation, ("Example Atlas.pdf", "atlas"), ("Example Tales.pdf", "tales"))
        self.assertIn("already has a PDF", first["error"])
        self.assertTrue(second["linked"])
        with db.connect(read_only=True) as conn:
            stored = conn.execute("SELECT pdf_path FROM release WHERE id = 'atlas'").fetchone()[0]
        self.assertEqual(stored, "library:other.pdf")
