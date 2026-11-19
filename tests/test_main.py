import asyncio
import csv
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi import HTTPException, Request

from app import covers, db, main, pdf_indexer, settings


class DatabaseOptimizationTests(unittest.TestCase):
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
        db.init_db()
        self.pdf_path = root / "book.pdf"
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), "A cover for the test book.")
            document.save(self.pdf_path)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO work (id, title, edition, book_type) "
                "VALUES ('book', 'Test book', 'AD&D 1e', 'Boxed Set')"
            )
            conn.execute("INSERT INTO release (id, work_id) VALUES ('release', 'book')")

    def test_retired_catalog_apis_and_assets_are_unavailable_even_to_admins(self):
        async def request(path, method):
            messages = []
            scope = {
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1", "method": method, "scheme": "http",
                "path": path, "raw_path": path.encode(), "query_string": b"",
                "root_path": "", "client": ("127.0.0.1", 1234), "server": ("test", 80),
                "headers": [(b"remote-user", b"admin")],
            }
            requested = False

            async def receive():
                nonlocal requested
                if not requested:
                    requested = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Event().wait()

            async def send(message):
                messages.append(message)

            await asyncio.wait_for(main.app(scope, receive, send), timeout=5)
            return next(m["status"] for m in messages if m["type"] == "http.response.start")

        with db.connect(read_only=True) as conn:
            before = list(conn.iterdump())
        with patch.object(settings, "ADMINS", {"admin"}), patch.object(settings, "TRUSTED_PROXIES", set()):
            for path, methods in (
                ("/api/admin/reconciliation", ("GET",)),
                ("/api/admin/reconciliation/export.json", ("GET",)),
                ("/api/admin/reconciliation/pilot", ("GET", "POST")),
                ("/api/admin/reconciliation/metadata", ("GET", "POST")),
                ("/api/admin/reconciliation/copies", ("GET", "POST")),
                ("/reconciliation.js", ("GET",)),
                ("/catalog-pilot.js", ("GET",)),
                ("/catalog-metadata.js", ("GET",)),
            ):
                for method in methods:
                    with self.subTest(path=path, method=method):
                        self.assertEqual(asyncio.run(request(path, method)), 404 if method == "GET" else 405)
        self.assertFalse(any(path.startswith("/api/admin/reconciliation") for path in main.app.openapi()["paths"]))
        with db.connect(read_only=True) as conn:
            self.assertEqual(list(conn.iterdump()), before)

    def test_pdf_cover_rendering_does_not_hold_a_write_lock(self):
        original_render = pymupdf.Page.get_pixmap

        def render(page, *args, **kwargs):
            with closing(sqlite3.connect(db.DB_PATH, timeout=0)) as writer:
                writer.execute("UPDATE work SET notes = 'Another writer' WHERE id = 'book'")
                writer.commit()
            return original_render(page, *args, **kwargs)

        with patch.object(pymupdf.Page, "get_pixmap", render):
            result = main.link_pdf("release", main.PdfIn(path=str(self.pdf_path)))
        self.assertIsNone(result["warning"])
        self.assertEqual(result["notes"], "Another writer")
        release = result["releases"][0]
        self.assertEqual(release["pdf_path"], str(self.pdf_path))
        self.assertEqual(release["cover_source"], "pdf")
        self.assertTrue((db.COVERS_DIR / release["cover_path"]).is_file())

    def test_library_picker_lists_only_folders_and_pdfs_and_requires_editor(self):
        root = self.pdf_path.parent / "library"
        root.mkdir()
        (root / "2e").mkdir()
        (root / "sample.PDF").write_bytes(self.pdf_path.read_bytes())
        (root / "notes.txt").touch()
        outside_link = root / "elsewhere.pdf"
        try:
            outside_link.symlink_to(self.pdf_path)
        except OSError:
            if outside_link.exists():
                raise
        reader = Request({"type": "http", "headers": []})
        editor = Request({"type": "http", "headers": [(b"remote-user", b"editor")]})
        with patch.object(settings, "PDF_ROOT", str(root)), patch.object(settings, "ADMINS", {"editor"}):
            with self.assertRaises(HTTPException) as denied:
                main.browse_pdf_library(reader)
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual(main.browse_pdf_library(editor), {"entries": [
                {"name": "2e", "path": "2e", "directory": True},
                {"name": "sample.PDF", "path": "sample.PDF", "directory": False},
            ]})
            self.assertEqual(main.browse_pdf_library(editor, "2e"), {"entries": []})
            with self.assertRaises(HTTPException):
                main.link_pdf("release", main.PdfIn(library_path="elsewhere.pdf"))

    def test_library_link_survives_move_and_legacy_mapping_still_works(self):
        root = self.pdf_path.parent / "library"
        folder = root / "2e"
        folder.mkdir(parents=True)
        source = folder / "A Book & Map.pdf"
        source.write_bytes(self.pdf_path.read_bytes())
        attempted_legacy_path = r"\\nas\Books\2e\A Book & Map.pdf"
        with patch.object(settings, "PDF_ROOT", str(root)), \
                patch.object(settings, "PDF_MAP", [("//nas/Books", str(root))]):
            legacy = main.link_pdf("release", main.PdfIn(path=attempted_legacy_path))
            self.assertEqual(legacy["releases"][0]["pdf_path"], attempted_legacy_path)
            self.assertEqual(main.serve_pdf("release").path, source)
            work = main.link_pdf("release", main.PdfIn(library_path="2e/A Book & Map.pdf"))
            release = work["releases"][0]
            self.assertEqual(release["pdf_path"], "library:2e/A Book & Map.pdf")
            self.assertEqual(release["cover_source"], "pdf")
        moved = root.rename(root.with_name("moved-library"))
        with patch.object(settings, "PDF_ROOT", str(moved)):
            self.assertEqual(main.serve_pdf("release").path, (moved / "2e" / source.name).resolve())
            self.assertEqual(pdf_indexer.enqueue_all(), 1)

    def test_companion_shelf_supports_create_edit_and_filter_without_moving_other_books(self):
        companion = main.create_work(main.NewWork(
            title="Official companion", edition="D&D Companions", book_type="Other", first_year=1990,
            release=main.ReleaseIn(publisher="TSR", product_code="8442"),
        ))
        personal = main.create_work(main.NewWork(
            title="Personal third-party guide", edition="Other", book_type="Other",
            release=main.ReleaseIn(publisher="Independent Press", owned_pdf=True),
        ))
        self.assertEqual([row["work_id"] for row in db.list_books(editions=["D&D Companions"])], [companion["id"]])
        self.assertEqual([row["work_id"] for row in db.list_books(editions=["Other"])], [personal["id"]])
        main.update_work("book", main.WorkUpdate(edition="D&D Companions"))
        self.assertEqual({row["work_id"] for row in db.list_books(editions=["D&D Companions"])},
                         {companion["id"], "book"})
        self.assertEqual(main.work_detail(personal["id"]), personal)

    def test_upload_during_pdf_rendering_is_preserved(self):
        original_render = pymupdf.Page.get_pixmap
        uploaded = None

        def render(page, *args, **kwargs):
            nonlocal uploaded
            pixmap = original_render(page, *args, **kwargs)
            uploaded = pixmap.tobytes(output="png")
            with db.connect() as conn:
                name = covers.save_upload("release", "image/png", uploaded)
                conn.execute(
                    "UPDATE release SET cover_path = ?, cover_source = 'upload' WHERE id = 'release'",
                    (name,),
                )
            return pixmap

        with patch.object(pymupdf.Page, "get_pixmap", render):
            result = main.link_pdf("release", main.PdfIn(path=str(self.pdf_path)))
        self.assertIsNone(result["warning"])
        release = result["releases"][0]
        self.assertEqual(release["cover_source"], "upload")
        self.assertEqual((db.COVERS_DIR / release["cover_path"]).read_bytes(), uploaded)

    def test_render_failure_keeps_the_pdf_link_and_reports_a_warning(self):
        main.link_pdf("release", main.PdfIn(path=str(self.pdf_path)))
        with patch.object(pymupdf.Page, "get_pixmap", side_effect=ValueError("broken cover")):
            result = main.link_pdf("release", main.PdfIn(path=str(self.pdf_path)))
        self.assertIn("broken cover", result["warning"])
        release = result["releases"][0]
        self.assertEqual(release["pdf_path"], str(self.pdf_path))
        self.assertTrue((db.COVERS_DIR / release["cover_path"]).is_file())

    def test_reset_and_unlink_preserve_cover_and_index_cleanup(self):
        main.link_pdf("release", main.PdfIn(path=str(self.pdf_path)))
        reset = main.reset_cover("release")
        self.assertEqual(reset["releases"][0]["cover_source"], "pdf")
        pdf_indexer.enqueue("release")
        result = main.link_pdf("release", main.PdfIn(path=""))
        release = result["releases"][0]
        self.assertIsNone(release["pdf_path"])
        self.assertIsNone(release["cover_path"])
        self.assertEqual(release["owned_pdf"], 1)
        self.assertFalse(list(db.COVERS_DIR.glob("release.*")))
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pdf_index").fetchone()[0], 0)

    def test_box_contents_use_one_release_query_for_all_children(self):
        with db.connect() as conn:
            for index in range(4):
                conn.execute(
                    "INSERT INTO work (id, title, edition, book_type, parent_id) "
                    "VALUES (?, ?, 'AD&D 1e', 'Sourcebook', 'book')",
                    (f"child-{index}", f"Child {index}"),
                )
                if index < 3:
                    conn.execute(
                        "INSERT INTO release (id, work_id, is_primary) VALUES (?, ?, 1)",
                        (f"child-{index}-primary", f"child-{index}"),
                    )
                    conn.execute(
                        "INSERT INTO release (id, work_id, cover_path, pdf_path, owned_physical) "
                        "VALUES (?, ?, 'cover.jpg', '/library/book.pdf', 1)",
                        (f"child-{index}-pdf", f"child-{index}"),
                    )
        statements = []
        original_connect = db.connect

        @contextmanager
        def traced_connect():
            with original_connect() as conn:
                conn.set_trace_callback(statements.append)
                yield conn

        with patch.object(db, "connect", traced_connect):
            result = main.work_detail("book")
        selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(selects), 5)
        self.assertEqual([child["title"] for child in result["contents"]],
                         ["Child 0", "Child 1", "Child 2", "Child 3"])
        for index, child in enumerate(result["contents"][:3]):
            self.assertEqual(child["pdf_release_id"], f"child-{index}-pdf")
            self.assertTrue(child["cover_url"].startswith("/covers/cover.jpg?"))
            self.assertTrue(child["owned_physical"])
            self.assertTrue(child["owned_pdf"])
        self.assertIsNone(result["contents"][3]["cover_url"])
        self.assertIsNone(result["contents"][3]["pdf_release_id"])

    def test_books_api_passes_publisher_selections_to_release_filtering(self):
        with db.connect() as conn:
            conn.execute("UPDATE release SET publisher = 'TSR' WHERE id = 'release'")
            conn.execute(
                "INSERT INTO release (id, work_id) VALUES ('missing-publisher', 'book')"
            )
        self.assertEqual([row["id"] for row in main.books(publisher=["TSR"])], ["release"])
        self.assertEqual(
            [row["id"] for row in main.books(publisher=[""])], ["missing-publisher"],
        )
        self.assertEqual(
            {row["id"] for row in main.books(publisher=["", "TSR"], all_releases=True)},
            {"release", "missing-publisher"},
        )

    def test_missing_pdf_filter_checks_other_releases_in_book_view(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO release (id, work_id, pdf_path) "
                "VALUES ('linked', 'book', '/library/book.pdf')"
            )
            conn.execute(
                "INSERT INTO work (id, title, edition, book_type) "
                "VALUES ('unlinked', 'Unlinked book', 'AD&D 1e', 'Sourcebook')"
            )
            conn.execute(
                "INSERT INTO release (id, work_id, owned_pdf) VALUES ('unlinked', 'unlinked', 1)"
            )
        self.assertEqual(
            [row["id"] for row in main.books(publisher=None, no_pdf=True)], ["unlinked"],
        )
        self.assertEqual(
            {row["id"] for row in main.books(publisher=None, no_pdf=True, all_releases=True)},
            {"release", "unlinked"},
        )
        self.assertEqual(
            [row["id"] for row in main.books(publisher=None, has_pdf=True)], ["linked"],
        )
        for all_releases in (False, True):
            self.assertEqual(main.books(
                publisher=None, no_pdf=True, has_pdf=True, all_releases=all_releases,
            ), [])

    def test_filtered_csv_matches_collection_filters_order_and_release_options(self):
        title = '=Test, "box"'
        publisher = 'A&B | "Press"'
        with db.connect() as conn:
            conn.execute(
                "UPDATE work SET title = ?, first_year = 1990 WHERE id = 'book'", (title,),
            )
            conn.execute(
                "UPDATE release SET publisher = ?, year = 1996, is_primary = 1, "
                "owned_physical = 1, product_code = '=CODE', isbn = '001234' "
                "WHERE id = 'release'", (publisher,),
            )
            conn.execute(
                "INSERT INTO release (id, work_id, release_kind, year, owned_physical) "
                "VALUES ('reprint', 'book', 'Reprint', 1997, 1)"
            )
            conn.execute(
                "INSERT INTO work (id, title, edition, book_type, first_year, parent_id) "
                "VALUES ('child', 'Test child', 'AD&D 1e', 'Sourcebook', 1992, 'book')"
            )
            conn.execute(
                "INSERT INTO release (id, work_id, year) VALUES ('child', 'child', 1996)"
            )
            for work_id, name, pub, year, owned, pdf in (
                ("year", "Wrong year", publisher, 2005, 1, None),
                ("publisher", "Wrong publisher", "Other press", 1996, 1, None),
                ("linked", "Already linked", publisher, 1996, 1, "/library/book.pdf"),
                ("unowned", "Not physically owned", publisher, 1996, 0, None),
            ):
                conn.execute(
                    "INSERT INTO work (id, title, edition, book_type) "
                    "VALUES (?, ?, 'AD&D 1e', 'Sourcebook')", (work_id, name),
                )
                conn.execute(
                    "INSERT INTO release (id, work_id, publisher, year, owned_physical, pdf_path) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (work_id, work_id, pub, year, owned, pdf),
                )
        for all_releases, contents, count in (
            (False, False, 1), (False, True, 2), (True, False, 2), (True, True, 3),
        ):
            with self.subTest(all_releases=all_releases, contents=contents):
                books = main.books(
                    edition="AD&D 1e", type="Boxed Set|Sourcebook", publisher=[publisher, ""],
                    year_min=1995, year_max=1999, owned=True, no_pdf=True,
                    sort="title", desc=True, all_releases=all_releases, contents=contents,
                )
                response = main.export_view_csv(rows=books)
                rows = list(csv.DictReader(StringIO(bytes(response.body).decode("utf-8-sig"))))
                self.assertEqual(len(rows), count)
                self.assertEqual(
                    [row["Title"] for row in rows],
                    [("'" if row["title"].startswith("=") else "") + row["title"] for row in books],
                )
                self.assertTrue(all(row["Physical copy owned"] == "Yes" for row in rows))
                original = next(row for row in rows if row["Release kind"] == "Original"
                                and row["Title"] == "'" + title)
                self.assertEqual(original["Publisher"], publisher)
                self.assertEqual(original["First published"], "1990")
                self.assertEqual(original["Release year"], "1996")
                self.assertEqual(original["Product code"], "'=CODE")
                self.assertEqual(original["ISBN"], "001234")
                if contents:
                    child = next(row for row in rows if row["Title"] == "Test child")
                    self.assertEqual(child["Part of box set"], "'" + title)
                if all_releases:
                    self.assertTrue(any(row["Release kind"] == "Reprint" for row in rows))
                self.assertTrue(bytes(response.body).startswith(b"\xef\xbb\xbf"))
                self.assertIn("dnd-collection-filtered.csv", response.headers["content-disposition"])
        empty = main.export_view_csv(rows=[])
        self.assertEqual(
            list(csv.DictReader(StringIO(bytes(empty.body).decode("utf-8-sig")))), [],
        )

    def test_inventory_csv_keeps_existing_scopes_and_includes_box_contents(self):
        with db.connect() as conn:
            conn.execute("UPDATE release SET owned_physical = 1 WHERE id = 'release'")
            conn.execute(
                "INSERT INTO work (id, title, edition, book_type, parent_id) "
                "VALUES ('child', 'Test child', 'AD&D 1e', 'Sourcebook', 'book')"
            )
            conn.execute("INSERT INTO release (id, work_id) VALUES ('child', 'child')")
        for scope, edition, expected in (
            ("all", None, ["Test book", "Test child"]),
            ("owned", "AD&D 1e", ["Test book", "Test child"]),
            ("missing", None, []),
            ("all", "Other", []),
        ):
            with self.subTest(scope=scope, edition=edition):
                response = main.export_csv(scope=scope, edition=edition)
                rows = list(csv.DictReader(StringIO(bytes(response.body).decode("utf-8-sig"))))
                self.assertEqual([row["Title"] for row in rows], expected)
                if rows:
                    self.assertEqual(rows[1]["Part of box set"], "Test book")


if __name__ == "__main__":
    unittest.main()
