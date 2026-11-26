import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, main, seed


class ReseedingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.covers = root / "covers"
        self.catalog_path = root / "catalog.json"
        self.catalog = {
            "works": [
                {
                    "id": "book",
                    "title": "Catalog book",
                    "edition": "AD&D 1e",
                    "type": "Core Rulebook",
                    "year": 1978,
                    "releases": [
                        {"key": "orig", "primary": True},
                        {"key": "reprint", "kind": "Reprint", "year": 2012},
                    ],
                },
                {
                    "id": "box",
                    "title": "Catalog box",
                    "edition": "AD&D 2e",
                    "type": "Boxed Set",
                    "year": 1994,
                    "contents": [{"key": "child", "title": "Inside the box"}],
                },
            ]
        }
        for name, value in (
            ("DATA_DIR", root),
            ("DB_PATH", root / "tracker.db"),
            ("COVERS_DIR", self.covers),
        ):
            self.enterContext(patch.object(db, name, value))
        db.init_db()
        self.reseed()

    def reseed(self):
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
        return seed.seed(self.catalog_path)

    def rows(self, sql, params=()):
        with db.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def assert_primary(self, release_id):
        rows = self.rows("SELECT id FROM release WHERE work_id = 'book' AND is_primary = 1")
        self.assertEqual(rows, [{"id": release_id}])

    def assert_primary_survives(self, release_id):
        self.catalog["works"][0]["releases"].append(
            {"key": "new", "kind": "Special Edition", "primary": True}
        )
        self.catalog["works"][0]["releases"][0]["primary"] = False
        self.reseed()
        self.reseed()
        self.assert_primary(release_id)
        self.assertTrue(self.rows("SELECT id FROM release WHERE id = 'book--new'"))

    def test_deleted_edited_catalog_book_stays_deleted(self):
        main.update_work("book", main.WorkUpdate(title="My title"))
        main.delete_work("book")
        self.reseed()
        self.reseed()
        self.assertFalse(self.rows("SELECT id FROM work WHERE id = 'book'"))
        self.assertFalse(self.rows("SELECT id FROM release WHERE work_id = 'book'"))

    def test_deleted_release_stays_deleted(self):
        main.update_release("book--reprint", main.ReleaseIn(label="My printing"))
        main.delete_release("book--reprint")
        self.reseed()
        self.assertFalse(self.rows("SELECT id FROM release WHERE id = 'book--reprint'"))
        self.assert_primary("book--orig")

    def test_deleted_primary_release_keeps_its_replacement(self):
        main.delete_release("book--orig")
        self.reseed()
        self.assertFalse(self.rows("SELECT id FROM release WHERE id = 'book--orig'"))
        self.assert_primary_survives("book--reprint")

    def test_deleted_box_keeps_its_contents_detached(self):
        main.delete_work("box")
        self.reseed()
        self.reseed()
        self.assertFalse(self.rows("SELECT id FROM work WHERE id = 'box'"))
        self.assertEqual(
            self.rows("SELECT parent_id FROM work WHERE id = 'box--child'"),
            [{"parent_id": None}],
        )

    def test_deleted_box_content_stays_deleted(self):
        main.delete_work("box--child")
        self.reseed()
        self.assertTrue(self.rows("SELECT id FROM work WHERE id = 'box'"))
        self.assertFalse(self.rows("SELECT id FROM work WHERE id = 'box--child'"))

    def test_release_editor_primary_choice_survives(self):
        main.update_release("book--reprint", main.ReleaseIn(is_primary=True))
        self.assert_primary_survives("book--reprint")

    def test_work_editor_primary_choice_survives(self):
        main.update_work(
            "book",
            main.WorkUpdate(
                release_id="book--reprint", release=main.ReleaseIn(is_primary=True)
            ),
        )
        self.assert_primary_survives("book--reprint")

    def test_new_primary_release_survives(self):
        work = main.create_release("book", main.ReleaseIn(is_primary=True))
        chosen = next(r["id"] for r in work["releases"] if r["is_primary"])
        self.assert_primary_survives(chosen)

    def test_explicitly_cleared_primary_stays_cleared(self):
        main.update_release("book--orig", main.ReleaseIn(is_primary=False))
        self.reseed()
        self.assertFalse(
            self.rows("SELECT id FROM release WHERE work_id = 'book' AND is_primary = 1")
        )

    def test_primary_choice_does_not_block_catalog_or_overwrite_user_data(self):
        main.update_release(
            "book--reprint",
            main.ReleaseIn(is_primary=True, owned_physical=True, notes="Keep my notes"),
        )
        with db.connect() as conn:
            conn.execute(
                "UPDATE release SET pdf_path = ?, cover_path = ?, cover_source = 'upload' "
                "WHERE id = 'book--reprint'",
                ("/library/book.pdf", "custom.jpg"),
            )
        self.catalog["works"][0]["title"] = "Updated catalog title"
        self.catalog["works"][0]["releases"][1]["publisher"] = "Updated publisher"
        self.reseed()
        self.assert_primary("book--reprint")
        self.assertEqual(
            self.rows("SELECT title FROM work WHERE id = 'book'"),
            [{"title": "Updated catalog title"}],
        )
        release = self.rows("SELECT * FROM release WHERE id = 'book--reprint'")[0]
        self.assertEqual(release["publisher"], "Updated publisher")
        self.assertEqual(release["owned_physical"], 1)
        self.assertEqual(release["notes"], "Keep my notes")
        self.assertEqual(release["pdf_path"], "/library/book.pdf")
        self.assertEqual(release["cover_path"], "custom.jpg")
        self.assertEqual(release["cover_source"], "upload")

    def test_upgrade_preserves_an_existing_user_primary_choice(self):
        with db.connect() as conn:
            conn.execute("UPDATE release SET is_primary = 0 WHERE work_id = 'book'")
            conn.execute(
                "UPDATE release SET is_primary = 1, source = 'user' WHERE id = 'book--reprint'"
            )
            # Reproduce the duplicate primary left by the old seed behavior.
            conn.execute("UPDATE release SET is_primary = 1 WHERE id = 'book--orig'")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(work)")}
            if "primary_release_override" in columns:
                conn.execute("ALTER TABLE work DROP COLUMN primary_release_override")
        db.init_db()
        self.reseed()
        self.assert_primary("book--reprint")

    def test_catalog_defaults_can_still_change_without_a_user_choice(self):
        self.catalog["works"][0]["releases"][0]["primary"] = False
        self.catalog["works"][0]["releases"][1]["primary"] = True
        self.reseed()
        self.assert_primary("book--reprint")

    def add_mapped_box(self):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO work(id,title,edition,book_type,source) "
                "VALUES ('local-box','My box title','AD&D 2e','Boxed Set','catalog')"
            )
            conn.execute(
                "INSERT INTO release(id,work_id,is_primary,notes) "
                "VALUES ('local-box-printing','local-box',1,'Keep this')"
            )
            conn.execute(
                "INSERT INTO catalog_work_mapping(catalog_id,local_id,backup_name) "
                "VALUES ('future-box','local-box','fixture.db')"
            )
            conn.execute(
                "INSERT INTO catalog_release_mapping(catalog_id,local_id,backup_name) "
                "VALUES ('future-box--orig','local-box-printing','fixture.db')"
            )
        self.catalog["works"].append({
            "id": "future-box", "title": "Shared catalog title", "edition": "AD&D 2e",
            "type": "Boxed Set", "year": 1994, "contents": [{"key": "leaf", "title": "New content"}],
        })

    def test_aliases_preserve_metadata_and_resolve_new_child_parent_ids(self):
        self.add_mapped_box()
        self.reseed()
        self.reseed()
        self.assertEqual(self.rows("SELECT title FROM work WHERE id='local-box'"), [{"title": "My box title"}])
        self.assertFalse(self.rows("SELECT id FROM work WHERE id='future-box'"))
        self.assertEqual(self.rows("SELECT parent_id FROM work WHERE id='future-box--leaf'"),
                         [{"parent_id": "local-box"}])
        self.assertEqual(self.rows("SELECT id,notes,is_primary FROM release WHERE work_id='local-box'"),
                         [{"id": "local-box-printing", "notes": "Keep this", "is_primary": 1}])

    def test_existing_canonical_and_mapped_records_cannot_be_silently_combined(self):
        self.add_mapped_box()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO work(id,title,edition,book_type) "
                "VALUES ('future-box','Other existing box','AD&D 2e','Boxed Set')"
            )
        with self.assertRaisesRegex(ValueError, "Both canonical and mapped local work exist"):
            self.reseed()
        self.assertEqual(self.rows("SELECT title FROM work WHERE id='future-box'"),
                         [{"title": "Other existing box"}])

    def test_fresh_startup_seeds_reviewed_catalog_but_later_additions_stay_gated(self):
        self.catalog["works"].append({
            "id": "reviewed", "title": "Reviewed book", "edition": "Basic",
            "type": "Sourcebook", "year": 1983, "requires_reconciliation": True,
            "releases": [{"key": "orig"}, {"key": "later", "kind": "Reprint", "year": 1984}],
        })
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
        fresh = db.DATA_DIR / "fresh"
        with patch.object(db, "DATA_DIR", fresh), patch.object(db, "DB_PATH", fresh / "tracker.db"), \
                patch.object(db, "COVERS_DIR", fresh / "covers"), patch.object(seed, "CATALOG", self.catalog_path):
            main._startup()
            self.assertEqual({row["id"] for row in self.rows("SELECT id FROM release WHERE work_id='reviewed'")},
                             {"reviewed--orig", "reviewed--later"})
            with db.connect() as conn:
                before = list(conn.iterdump())
            main._startup()
            with db.connect() as conn:
                self.assertEqual(list(conn.iterdump()), before)
            self.catalog["works"][-1]["releases"].append({"key": "new", "kind": "Reprint", "year": 1985})
            self.catalog["works"].append({
                "id": "future", "title": "Future book", "edition": "Basic",
                "type": "Sourcebook", "requires_reconciliation": True,
            })
            self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
            main._startup()
            self.assertFalse(self.rows("SELECT id FROM work WHERE id='future'"))
            self.assertFalse(self.rows("SELECT id FROM release WHERE id='reviewed--new'"))
            self.assertFalse(self.rows("SELECT * FROM catalog_work_mapping"))
            main.delete_work("reviewed")
            main._startup()
            self.assertFalse(self.rows("SELECT id FROM work WHERE id='reviewed'"))

    def test_empty_collection_with_deletion_history_is_not_a_fresh_installation(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM work")
            conn.execute("INSERT INTO catalog_deletion VALUES ('work','previously-deleted')")
        self.catalog["works"] = [{
            "id": "reviewed", "title": "Reviewed book", "edition": "Basic",
            "type": "Sourcebook", "requires_reconciliation": True,
        }]
        self.reseed()
        self.assertFalse(self.rows("SELECT id FROM work"))

    def test_retired_tool_history_redirects_and_assets_survive_startup(self):
        self.add_mapped_box()
        self.reseed()
        pdf = db.DATA_DIR / "private.pdf"
        pdf.write_bytes(b"PRIVATE-PDF")
        cover = db.COVERS_DIR / "private.jpg"
        cover.write_bytes(b"PRIVATE-COVER")
        backups = db.DATA_DIR / "backups"
        backups.mkdir()
        backup = backups / "fixture.db"
        backup.write_bytes(b"PRIVATE-EXISTING-BACKUP")
        with db.connect() as conn:
            conn.execute("UPDATE release SET pdf_path=?,cover_path='private.jpg',notes='PRIVATE-NOTES',owned_pdf=1 "
                         "WHERE id='book--orig'", (str(pdf),))
            conn.execute("INSERT INTO pdf_index(release_id,status,indexed_pages) VALUES ('book--orig','done',1)")
            conn.execute("INSERT INTO pdf_text_page(release_id,page_number,text) VALUES ('book--orig',1,'PRIVATE-TEXT')")
            conn.execute("INSERT INTO catalog_metadata_repair VALUES "
                         "('prior','prior','book','book--orig','fixture.db','[]','before')")
            conn.execute("INSERT INTO catalog_copy_repair VALUES ('copy','fixture.db','{\"retired_work\":{}}','before')")
            conn.execute("INSERT INTO catalog_work_redirect VALUES ('retired-book','book')")
            conn.execute("INSERT INTO catalog_deletion VALUES ('work','retired-book')")
        with db.connect(read_only=True) as conn:
            before = list(conn.iterdump())
        with patch.object(seed, "CATALOG", self.catalog_path):
            main._startup()
            main._startup()
        with db.connect(read_only=True) as conn:
            self.assertEqual(list(conn.iterdump()), before)
        self.assertEqual(main.work_detail("retired-book")["id"], "book")
        self.assertEqual((pdf.read_bytes(), cover.read_bytes(), backup.read_bytes()),
                         (b"PRIVATE-PDF", b"PRIVATE-COVER", b"PRIVATE-EXISTING-BACKUP"))

    def test_blank_settings_are_filled_on_edited_and_mapped_books_without_overwriting_choices(self):
        main.update_work("book", main.WorkUpdate(title="My title"))
        main.update_work("box", main.WorkUpdate(setting="My world"))
        self.add_mapped_box()
        self.catalog["works"][0]["setting"] = "Greyhawk"
        self.catalog["works"][1]["setting"] = "Mystara"
        self.catalog["works"][-1]["setting"] = "Planescape"
        self.reseed()
        self.reseed()
        self.assertEqual(
            self.rows("SELECT id, title, setting, source FROM work "
                      "WHERE id IN ('book','box','local-box') ORDER BY id"),
            [
                {"id": "book", "title": "My title", "setting": "Greyhawk", "source": "user"},
                {"id": "box", "title": "Catalog box", "setting": "My world", "source": "user"},
                {"id": "local-box", "title": "My box title", "setting": "Planescape", "source": "catalog"},
            ],
        )
        # Contents inherit the box's catalog setting even when the user changed the box.
        self.assertEqual(self.rows("SELECT setting FROM work WHERE id='box--child'"), [{"setting": "Mystara"}])

    def test_protected_existing_bibliography_and_new_release_gates_remain_effective(self):
        self.catalog["works"][0]["preserve_existing_bibliography"] = True
        self.catalog["works"][0]["releases"].append(
            {"key": "new", "kind": "Alternate Cover", "requires_reconciliation": True}
        )
        with db.connect() as conn:
            conn.execute("UPDATE work SET first_year=1977 WHERE id='book'")
            conn.execute("UPDATE release SET year=1977 WHERE id='book--orig'")
        self.reseed()
        self.reseed()
        self.assertEqual(self.rows("SELECT first_year FROM work WHERE id='book'"), [{"first_year": 1977}])
        self.assertEqual(self.rows("SELECT year FROM release WHERE id='book--orig'"), [{"year": 1977}])
        self.assertFalse(self.rows("SELECT id FROM release WHERE id='book--new'"))

    def test_full_public_catalog_seeds_once_without_review_manifests_or_approvals(self):
        fresh = db.DATA_DIR / "fresh"
        with patch.object(db, "DATA_DIR", fresh), patch.object(db, "DB_PATH", fresh / "tracker.db"), \
                patch.object(db, "COVERS_DIR", fresh / "covers"), patch.object(seed, "CATALOG", db.CATALOG_PATH):
            main._startup()
            self.assertEqual(len(db.list_books()), 1398)
            self.assertEqual(len(db.list_books(show_contents=True)), 1438)
            self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM release"), [{"n": 1571}])
            with db.connect(read_only=True) as conn:
                before = list(conn.iterdump())
                for table in ("catalog_work_mapping", "catalog_release_mapping", "catalog_metadata_repair",
                              "catalog_copy_repair", "catalog_work_redirect"):
                    self.assertIsNone(conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone())
            main._startup()
            with db.connect(read_only=True) as conn:
                self.assertEqual(list(conn.iterdump()), before)

    def test_failed_fresh_seed_rolls_back_completely_and_can_retry_the_full_catalog(self):
        reviewed = {"id": "reviewed", "title": "Reviewed", "edition": "Basic",
                    "type": "Sourcebook", "requires_reconciliation": True}
        broken = {"id": "broken", "title": "Broken relationship", "edition": "Basic",
                  "type": "Sourcebook", "parent_id": "missing"}
        self.catalog["works"].extend([reviewed, broken])
        self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
        fresh = db.DATA_DIR / "fresh"
        with patch.object(db, "DATA_DIR", fresh), patch.object(db, "DB_PATH", fresh / "tracker.db"), \
                patch.object(db, "COVERS_DIR", fresh / "covers"), patch.object(seed, "CATALOG", self.catalog_path):
            db.init_db()
            with self.assertRaises(sqlite3.IntegrityError):
                seed.seed()
            self.assertFalse(self.rows("SELECT id FROM work"))
            self.assertFalse(self.rows("SELECT id FROM release"))
            self.catalog["works"].remove(broken)
            self.catalog_path.write_text(json.dumps(self.catalog), encoding="utf-8")
            seed.seed()
            self.assertEqual(self.rows("SELECT id FROM release WHERE work_id='reviewed'"),
                             [{"id": "reviewed--orig"}])


if __name__ == "__main__":
    unittest.main()
