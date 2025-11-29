import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from frontend.path_hints import derive_hint_context


class TestPathHintContext(unittest.TestCase):
    def test_empty_value_defaults_to_home(self) -> None:
        ctx = derive_hint_context("")
        self.assertIsNotNone(ctx)
        assert ctx is not None  # for type checkers
        self.assertEqual(ctx.display_base, "~/")
        self.assertEqual(ctx.partial, "")
        self.assertEqual(ctx.query_path, str(Path.home()))

    def test_home_relative_path(self) -> None:
        ctx = derive_hint_context("~/Backups/2024")
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.display_base, "~/Backups/")
        self.assertEqual(ctx.partial, "2024")
        self.assertTrue(ctx.query_path.endswith("Backups"))

    def test_absolute_path(self) -> None:
        ctx = derive_hint_context("/var/log/sys")
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertEqual(ctx.display_base, "/var/log/")
        self.assertEqual(ctx.partial, "sys")
        self.assertEqual(ctx.query_path, "/var/log")

    def test_relative_paths_not_supported(self) -> None:
        ctx = derive_hint_context("relative/path")
        self.assertIsNone(ctx)


if __name__ == "__main__":
    unittest.main()

