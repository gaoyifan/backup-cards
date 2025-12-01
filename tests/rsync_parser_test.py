"""Tests for rsync output parser."""

from pathlib import Path

from backend.rsync_parser import RsyncOutputParser


def test_parses_progress_and_summary():
    """Test that parser correctly parses rsync progress and summary."""
    parser = RsyncOutputParser()
    sample_path = Path(__file__).resolve().parent.parent / "misc" / "rsync-stdout-sample.txt"
    sample_output = sample_path.read_text()

    progress_events = []
    for line in sample_output.replace("\r", "\n").splitlines():
        progress, _ = parser.parse_line(line.strip())
        if progress:
            progress_events.append(progress)

    assert len(progress_events) > 0
    assert parser.total_bytes == 112_267_108
    assert parser.transferred_total == 112_267_108

    last_progress = progress_events[-1]
    assert last_progress.transferred_bytes == 112_267_108
    assert last_progress.total_bytes == 112_267_108
