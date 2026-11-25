import unittest
from unittest.mock import patch

from app import db, main, settings


class StartupCheckTests(unittest.TestCase):
    def test_required_proxy_must_be_set(self):
        with patch.object(settings, "REQUIRE_TRUSTED_PROXIES", True), \
                patch.object(settings, "TRUSTED_PROXIES", set()), \
                patch.object(db, "init_db", side_effect=AssertionError("started anyway")):
            with self.assertRaisesRegex(RuntimeError, "DND_TRACKER_TRUSTED_PROXIES"):
                main._startup()

    def test_starts_with_a_required_proxy_set(self):
        with patch.object(settings, "REQUIRE_TRUSTED_PROXIES", True), \
                patch.object(settings, "TRUSTED_PROXIES", {"192.0.2.10"}):
            settings.check_startup()

    def test_local_installs_need_no_proxy(self):
        with patch.object(settings, "REQUIRE_TRUSTED_PROXIES", False), \
                patch.object(settings, "TRUSTED_PROXIES", set()):
            settings.check_startup()


if __name__ == "__main__":
    unittest.main()
