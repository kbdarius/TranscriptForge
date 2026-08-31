import tempfile
import unittest
from pathlib import Path
from transcriptforge.models import Segment, ProcessingStats
from transcriptforge.output import append_markdown_content, render_markdown, atomic_write, rename_media_to_match_output

class OutputTests(unittest.TestCase):
    def test_render_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "meeting.md"; content = render_markdown(Path("meeting.mp4"), "small.en", "en", 9.64, [Segment(0, 2.5, "Hello")], ProcessingStats(), Path(d) / "models"); atomic_write(path, content)
            rendered = path.read_text(encoding="utf-8"); self.assertIn("# Transcript: meeting.mp4", rendered); self.assertIn("[00:00:00.00 - 00:00:02.50] Hello", rendered); self.assertNotIn("## Processing Notes", rendered); self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_media_is_moved_to_match_transcript_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "original.mp4"; output = root / "Meeting Notes.md"; source.write_bytes(b"media")
            renamed = rename_media_to_match_output(source, output)
            self.assertEqual(renamed, root / "Meeting Notes.mp4"); self.assertTrue(renamed.is_file()); self.assertFalse(source.exists())

    def test_media_is_renamed_in_original_folder_when_output_is_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source_dir = root / "recordings"; output_dir = root / "transcripts"; source_dir.mkdir(); output_dir.mkdir()
            source = source_dir / "original.mp4"; source.write_bytes(b"media")
            renamed = rename_media_to_match_output(source, output_dir / "Meeting Notes.md")
            self.assertEqual(renamed, source_dir / "Meeting Notes.mp4"); self.assertTrue(renamed.is_file()); self.assertFalse((output_dir / "Meeting Notes.mp4").exists())

    def test_append_markdown_content_attributes_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meeting.md"; atomic_write(path, "# Transcript\n")
            append_markdown_content(path, "Alex", "Follow-up message")
            text = path.read_text(encoding="utf-8")
            self.assertIn("## Additional content", text); self.assertIn("**Provided by:** Alex", text); self.assertIn("Follow-up message", text)
