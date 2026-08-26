import tempfile
import unittest
from pathlib import Path
from transcriptforge.models import Segment, ProcessingStats
from transcriptforge.output import render_markdown, atomic_write, rename_media_to_match_output

class OutputTests(unittest.TestCase):
    def test_render_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "meeting.md"; content = render_markdown(Path("meeting.mp4"), "small.en", "en", 9.64, [Segment(0, 2.5, "Hello")], ProcessingStats(), Path(d) / "models"); atomic_write(path, content)
            rendered = path.read_text(encoding="utf-8"); self.assertIn("# Transcript: meeting.mp4", rendered); self.assertIn("[00:00:00.00 - 00:00:02.50] Hello", rendered); self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_media_is_moved_to_match_transcript_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "original.mp4"; output = root / "Meeting Notes.md"; source.write_bytes(b"media")
            renamed = rename_media_to_match_output(source, output)
            self.assertEqual(renamed, root / "Meeting Notes.mp4"); self.assertTrue(renamed.is_file()); self.assertFalse(source.exists())
