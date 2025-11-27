import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.rsync_parser import RsyncOutputParser


class TestRsyncOutputParser(unittest.TestCase):
    def test_parses_progress_and_summary(self) -> None:
        parser = RsyncOutputParser()
        sample_path = Path(__file__).resolve().parent.parent / "misc" / "rsync-stdout-sample.txt"
        sample_output = sample_path.read_text()

        progress_events = []
        for line in sample_output.replace("\r", "\n").splitlines():
            progress, _ = parser.parse_line(line.strip())
            if progress:
                progress_events.append(progress)

        self.assertGreater(len(progress_events), 0)
        self.assertEqual(parser.total_bytes, 112_267_108)
        self.assertEqual(parser.transferred_total, 112_267_108)

        last_progress = progress_events[-1]
        self.assertEqual(last_progress.transferred_bytes, 112_267_108)
        self.assertEqual(last_progress.total_bytes, 112_267_108)


if __name__ == "__main__":
    unittest.main()
