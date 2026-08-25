import tempfile
import unittest
from pathlib import Path
from transcriptforge.models import Segment, ProcessingStats
from transcriptforge.output import render_markdown, atomic_write

class OutputTests(unittest.TestCase):
    def test_render_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "meeting.md"; content = render_markdown(Path("meeting.mp4"), "small.en", "en", 9.64, [Segment(0, 2.5, "Hello")], ProcessingStats(), Path(d) / "models"); atomic_write(path, content)
            self.assertIn("[00:00:00.00 - 00:00:02.50] Hello", path.read_text(encoding="utf-8")); self.assertFalse(list(Path(d).glob("*.tmp")))

