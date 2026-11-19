import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

from app import version


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.baseline = "# Changelog\n\nRelease history.\n\n## [0.2.9] - 2026-11-16\n\n- Earlier changes.\n"
        self.reset_release()

    def reset_release(self):
        (self.root / "VERSION").write_text("0.2.9\n", encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text(self.baseline, encoding="utf-8")

    def snapshot(self):
        return {
            name: (self.root / name).read_bytes()
            for name in ("VERSION", "CHANGELOG.md")
        }

    def test_bumps_update_version_and_prepend_dated_notes(self):
        for part, expected in (("patch", "0.2.10"), ("minor", "0.3.0"), ("major", "1.0.0")):
            with self.subTest(part=part):
                self.reset_release()
                result = version.bump_release(part, [" Fix one ", "Improve two"], self.root)
                self.assertEqual(result, expected)
                self.assertEqual(version.check_release(self.root), expected)
                changelog = (self.root / "CHANGELOG.md").read_text(encoding="utf-8")
                self.assertIn(f"## [{expected}] - {date.today().isoformat()}", changelog)
                self.assertIn("- Fix one\n- Improve two\n", changelog)
                self.assertTrue(changelog.endswith(self.baseline[self.baseline.index("## "):]))
                self.assertEqual(list(self.root.glob(".release-*")), [])

    def test_invalid_versions_are_rejected_without_writing(self):
        for invalid in ("v1.2.3", "01.2.3", "1.2", "1.2.3.4", "-1.0.0", "1.\u0662.3"):
            with self.subTest(version=invalid):
                self.reset_release()
                (self.root / "VERSION").write_text(invalid, encoding="utf-8")
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "Invalid version"):
                    version.bump_release("patch", ["A change"], self.root)
                self.assertEqual(self.snapshot(), before)

    def test_mismatched_metadata_is_rejected_without_writing(self):
        (self.root / "VERSION").write_text("0.2.8\n", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "latest dated release"):
            version.bump_release("patch", ["A change"], self.root)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_release_requests_are_rejected_without_writing(self):
        for part, notes in (
            ("patch", []),
            ("patch", [" "]),
            ("patch", ["Line one\nLine two"]),
            ("unknown", ["A change"]),
        ):
            with self.subTest(part=part, notes=notes):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    version.bump_release(part, notes, self.root)
                self.assertEqual(self.snapshot(), before)

    def test_cli_prepares_and_checks_a_release(self):
        output = io.StringIO()
        with redirect_stdout(output):
            version.main(["patch", "--note", "Fix a bug"], root=self.root)
            version.main(["--check"], root=self.root)
            version.main([], root=self.root)
        self.assertIn("Prepared version 0.2.10", output.getvalue())
        self.assertIn('git tag -a v0.2.10 -m "Release 0.2.10"', output.getvalue())
        self.assertIn("Release metadata OK: 0.2.10", output.getvalue())
        self.assertTrue(output.getvalue().endswith("0.2.10\n"))

    def test_cli_errors_do_not_modify_the_release(self):
        for args in (["patch"], ["--check", "patch"], ["--note", "No bump"]):
            with self.subTest(args=args):
                before = self.snapshot()
                errors = io.StringIO()
                with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    version.main(args, root=self.root)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("error:", errors.getvalue())
                self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
