import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import db


class ConnectionTests(unittest.TestCase):
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
        with closing(sqlite3.connect(db.DB_PATH)) as conn:
            conn.executescript(
                "CREATE TABLE entry (value TEXT);"
                "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) "
                "DEFERRABLE INITIALLY DEFERRED);"
            )

    def assert_closed(self, conn):
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.cursor()

    def test_success_commits_and_closes(self):
        with db.connect() as conn:
            self.addCleanup(conn.close)
            conn.execute("INSERT INTO entry (value) VALUES ('saved')")
        with closing(sqlite3.connect(db.DB_PATH)) as check:
            self.assertEqual(check.execute("SELECT value FROM entry").fetchall(), [("saved",)])
        self.assert_closed(conn)

    def test_body_failure_rolls_back_closes_and_preserves_exception(self):
        failure = RuntimeError("transaction failed")
        with self.assertRaises(RuntimeError) as raised:
            with db.connect() as conn:
                self.addCleanup(conn.close)
                conn.execute("INSERT INTO entry (value) VALUES ('not saved')")
                raise failure
        self.assertIs(raised.exception, failure)
        with closing(sqlite3.connect(db.DB_PATH)) as check:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM entry").fetchone()[0], 0)
        self.assert_closed(conn)

    def test_commit_failure_rolls_back_and_closes(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connect() as conn:
                self.addCleanup(conn.close)
                conn.execute("INSERT INTO child (parent_id) VALUES (123)")
        with closing(sqlite3.connect(db.DB_PATH)) as check:
            self.assertEqual(check.execute("SELECT COUNT(*) FROM child").fetchone()[0], 0)
        self.assert_closed(conn)

    def test_configuration_failure_closes_and_propagates(self):
        class FailingConnection(sqlite3.Connection):
            def execute(self, *args, **kwargs):
                raise sqlite3.OperationalError("connection configuration failed")

        conn = sqlite3.connect(db.DB_PATH, factory=FailingConnection)
        self.addCleanup(conn.close)
        with patch.object(db.sqlite3, "connect", return_value=conn):
            with self.assertRaisesRegex(sqlite3.OperationalError, "configuration failed"):
                with db.connect():
                    self.fail("A connection with failed configuration must not be used")
        self.assert_closed(conn)


class PublisherTests(unittest.TestCase):
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
        db.init_db()
        with db.connect() as conn:
            for work_id, title, publisher in (
                ("shared", "The Shared Book", "TSR"),
                ("other", "Another Book", " TSR "),
                ("missing", "Missing Publisher", None),
                ("empty", "Empty Publisher", ""),
                ("spaces", "Space-only Publisher", "   "),
                ("literal", "Literal Publisher Name", "No publisher set"),
                ("special", "Special Publisher Name", 'A&B | "Press"'),
            ):
                conn.execute(
                    "INSERT INTO work (id, title, edition, book_type) "
                    "VALUES (?, ?, 'AD&D 1e', 'Sourcebook')", (work_id, title),
                )
                conn.execute(
                    "INSERT INTO release (id, work_id, publisher, is_primary) VALUES (?, ?, ?, 1)",
                    (work_id, work_id, publisher),
                )
            conn.execute(
                "INSERT INTO release (id, work_id, publisher, release_kind) "
                "VALUES ('reprint', 'shared', 'Wizards of the Coast', 'Reprint')"
            )
            conn.execute("UPDATE release SET owned_physical = 1 WHERE id = 'other'")

    def test_publisher_choices_are_distinct_trimmed_and_exclude_blanks(self):
        self.assertEqual(db.publisher_names(),
                         ['A&B | "Press"', "No publisher set", "TSR", "Wizards of the Coast"])

    def test_blank_and_named_publisher_filters_can_be_combined(self):
        blank_ids = {"missing", "empty", "spaces"}
        self.assertEqual({row["id"] for row in db.list_books(publishers=[""])}, blank_ids)
        self.assertEqual(
            {row["id"] for row in db.list_books(publishers=["", "TSR"])},
            blank_ids | {"shared", "other"},
        )
        self.assertEqual(
            [row["id"] for row in db.list_books(publishers=["No publisher set"])], ["literal"],
        )
        self.assertEqual(
            [row["id"] for row in db.list_books(publishers=['A&B | "Press"'])], ["special"],
        )

    def test_publisher_filters_match_releases_before_picking_a_shelf_face(self):
        self.assertEqual(
            [row["id"] for row in db.list_books(publishers=["Wizards of the Coast"])], ["reprint"],
        )
        self.assertEqual(
            {row["id"] for row in db.list_books(
                publishers=["TSR", "Wizards of the Coast"], all_releases=True,
            )}, {"shared", "other", "reprint"},
        )
        self.assertEqual(db.list_books(
            publishers=["Wizards of the Coast"], hide_kinds=["Reprint"],
        ), [])
        self.assertEqual(
            [row["id"] for row in db.list_books(publishers=["TSR"], owned=True)], ["other"],
        )
        self.assertEqual(db.list_books(publishers=["TS"]), [])

    def test_publisher_sort_supports_both_directions_and_title_ties(self):
        for desc in (False, True):
            with self.subTest(desc=desc):
                rows = db.list_books(sort="publisher", desc=desc, all_releases=True)
                keys = [(row["publisher"] or "").strip().lower() or "~" for row in rows]
                self.assertEqual(keys, sorted(keys, reverse=desc))
                self.assertEqual(
                    [row["id"] for row in rows if (row["publisher"] or "").strip() == "TSR"],
                    ["other", "shared"],
                )


if __name__ == "__main__":
    unittest.main()
