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

    def test_rejects_a_symlink_that_leaves_the_covers_folder(self):
        link = self.covers / "escape.jpg"
        try:
            link.symlink_to(self.root / "tracker.db")
        except OSError:
            self.skipTest("Creating symlinks is not permitted here")
        self.assertIsNone(covers.cover_file("escape.jpg"))


if __name__ == "__main__":
    unittest.main()
