import json
import tempfile
import unittest
from pathlib import Path

from transcriptforge.cli import _review_names, build_parser
from transcriptforge.settings import RecordingFolderSettings, RecordingHistory


class CliTests(unittest.TestCase):
    def test_parser_supports_machine_readable_transcription(self):
        args = build_parser().parse_args(["--json-events", "transcribe", "meeting.mp4", "--speakers"])
        self.assertTrue(args.json_events)
        self.assertTrue(args.speakers)
        self.assertEqual(args.model, "small.en")

    def test_review_names_reads_edited_cluster_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            path.write_text(json.dumps({"names": {}, "clusters": [{"id": "SPEAKER_01", "name": "Alex"}]}), encoding="utf-8")
            self.assertEqual(_review_names(path), {"SPEAKER_01": "Alex"})

    def test_recording_folder_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recording-folder.json"
            settings = RecordingFolderSettings(path)
            settings.set(Path(directory))
            loaded = RecordingFolderSettings(path)
            self.assertEqual(loaded.folder, str(Path(directory).resolve()))

    def test_recording_history_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "meeting.wav"; source.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json")
            history.update(source, "completed", root / "meeting.md", root / "meeting.wav")
            self.assertTrue(RecordingHistory(root / "recording-history.json").has_completed(source))

    def test_pending_recording_is_not_selected_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "meeting.wav"; source.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json"); history.update(source, "pending")
            self.assertTrue(history.has_completed(source))

    def test_history_keeps_multiple_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.wav"; second = root / "second.wav"
            first.write_bytes(b"one"); second.write_bytes(b"two")
            history = RecordingHistory(root / "recording-history.json")
            history.update(first, "completed", root / "first.md")
            history.update(second, "failed")
            self.assertEqual(len(RecordingHistory(root / "recording-history.json").records), 2)

    def test_latest_completed_recording_is_scan_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "meeting.wav"; source.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json"); history.update(source, "completed")
            self.assertEqual(history.latest_completed_source_mtime(), source.stat().st_mtime)
