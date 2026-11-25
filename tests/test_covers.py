import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import covers, db, main


class CoverFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.covers = self.root / "covers"
        self.covers.mkdir()
        self.enterContext(patch.object(db, "COVERS_DIR", self.covers))
        (self.covers / "2e-phb--orig.webp").write_bytes(b"cover")
        (self.covers / ".2e-phb--orig.preview.jpg.tmp").write_bytes(b"partial")
        (self.root / "tracker.db").write_bytes(b"database")

    def test_serves_a_stored_cover(self):
        self.assertEqual(
            covers.cover_file("2e-phb--orig.webp"),
            Path(self.covers, "2e-phb--orig.webp").resolve(),
        )
        response = main.serve_cover("2e-phb--orig.webp")
        self.assertEqual(Path(response.path).name, "2e-phb--orig.webp")

    def test_rejects_names_outside_the_covers_folder(self):
        for name in (
            "../tracker.db",
            "..",
            ".",
            "",
            str(self.root / "tracker.db"),
            "..\\tracker.db",
            "covers/../../tracker.db",
            ".2e-phb--orig.preview.jpg.tmp",
            "missing.jpg",
        ):
            with self.subTest(name=name):
                self.assertIsNone(covers.cover_file(name))
                with self.assertRaises(HTTPException) as raised:
                    main.serve_cover(name)
                self.assertEqual(raised.exception.status_code, 404)

    def test_saved_covers_stay_in_the_covers_folder(self):
        self.assertEqual(covers.save_upload("2e/phb", "image/png", b"png"), "2e_phb.png")
        self.assertEqual((self.covers / "2e_phb.png").read_bytes(), b"png")
        self.assertEqual(covers.save_pdf_cover("a\\b", b"jpg"), "a_b.jpg")
        for release_id in ("../../escape", "..", ".hidden"):
            with self.subTest(release_id=release_id):
                with self.assertRaises(ValueError):
                    covers.save_upload(release_id, "image/png", b"png")
        self.assertFalse((self.root / "escape.png").exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["covers", "tracker.db"])

    def test_clearing_a_cover_keeps_other_releases_covers(self):
        for name in ("2e-phb--orig.preview.jpg", "2e-phb--orig-2.jpg"):
            (self.covers / name).write_bytes(b"x")
        covers.remove("2e-phb--orig")
        self.assertEqual(
            sorted(p.name for p in self.covers.iterdir()),
            [".2e-phb--orig.preview.jpg.tmp", "2e-phb--orig-2.jpg"],
        )

    def test_rejects_a_symlink_that_leaves_the_covers_folder(self):
        link = self.covers / "escape.jpg"
        try:
            link.symlink_to(self.root / "tracker.db")
        except OSError:
            self.skipTest("Creating symlinks is not permitted here")
        self.assertIsNone(covers.cover_file("escape.jpg"))


if __name__ == "__main__":
    unittest.main()
