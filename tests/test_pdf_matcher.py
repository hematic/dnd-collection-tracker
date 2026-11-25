import json
import unittest

from app import db, seed
from app.pdf_matcher import Matcher, Release


class PdfMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        works = seed._flatten(json.loads(db.CATALOG_PATH.read_text(encoding="utf-8"))["works"])
        cls.matcher = Matcher([
            Release(r["id"], work["id"], work["title"], work["edition"], r["year"], r["label"],
                    r["release_kind"], bool(r["is_primary"]), False, r["product_code"], r["isbn"],
                    tuple(filter(None, (work.get("module"), *work.get("module_aliases", [])))))
            for work in works for r in seed._expand(work)
        ])

    def test_confident_matches_across_filename_styles(self):
        for path, work_id in (
            ("Basic/TSR_9034_B2_The_Keep_on_the_Borderlands.pdf", "basic-b2-the-keep-on-the-borderlands"),
            ("Rules_Cyclopedia.pdf", "basic-dungeons-dragons-rules-cyclopedia"),
            ("CM1 TestOfTheWarlords [OCR].pdf", "basic-cm1-test-of-the-warlords"),
        ):
            with self.subTest(path=path):
                result = self.matcher.match(path)
                self.assertEqual(result.tier, "ready")
                self.assertEqual(result.candidates[0].release.work_id, work_id)

    def test_uncertain_or_unrelated_names_do_not_get_preselected(self):
        for path, title, tier in (
            ("Monster Manual.pdf", None, "review"),
            ("5e/Player_s_Handbook.pdf", None, "review"),
            ("5e (2024)/Monster Manual.pdf", None, "review"),
            ("A map of the Keep on the Borderlands.pdf", None, "review"),
            ("CM1 Test of the Warlords.pdf", "Ghost of Lion Castle", "review"),
            ("download_58429017.pdf", "Ghost of Lion Castle", "review"),
            ("Ghost of Lion Caslte.pdf", None, "review"),
            ("invoice_2023.pdf", None, "none"),
            ("Character Sheet.pdf", "Microsoft Word - scan", "none"),
            ("map.pdf", "Untitled", "none"),
        ):
            with self.subTest(path=path, title=title):
                self.assertEqual(self.matcher.match(path, title).tier, tier)

    def test_printing_and_edition_clues_disambiguate_only_when_supported(self):
        original = Release("1", "w", "Example Atlas", "AD&D 1e", 1981, None, "Original", True, False,
                           "2010", "978-0-306-40615-7")
        reprint = Release("2", "w", "Example Atlas", "AD&D 1e", 1999, None, "Reprint", False, False)
        other = Release("3", "x", "Example Atlas", "AD&D 2e", 1993, None, "Original", True, False)
        matcher = Matcher([original, reprint, other])
        for path, release in (
            ("1e/Example Atlas 1999.pdf", "2"),
            ("ISBN 978-0-306-40615-7.pdf", "1"),
            ("2e/Example Atlas.pdf", "3"),
        ):
            with self.subTest(path=path):
                result = matcher.match(path)
                self.assertEqual((result.tier, result.candidates[0].release.id), ("ready", release))
        self.assertEqual(matcher.match("invoice 2010.pdf").tier, "none")
        self.assertEqual(matcher.match("ISBN 978-0-306-40615-8.pdf").tier, "none")
