import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from transcriptforge.cli import _emit, _review_names, build_parser
from transcriptforge.settings import FilenameTemplateSettings, RecordingFolderSettings, RecordingHistory, SampleRejectionStore


class CliTests(unittest.TestCase):
    def test_parser_supports_machine_readable_transcription(self):
        args = build_parser().parse_args(["--json-events", "transcribe", "meeting.mp4", "--speakers"])
        self.assertTrue(args.json_events)
        self.assertTrue(args.speakers)
        self.assertEqual(args.model, "small.en")

    def test_parser_supports_expected_speakers_and_diagnostics(self):
        args = build_parser().parse_args(["transcribe", "meeting.mp4", "--speakers", "--expected-speaker", "Alex", "--expected-speaker", "Blair"])
        self.assertEqual(args.expected_speakers, ["Alex", "Blair"])
        diagnostic = build_parser().parse_args(["diagnose", "meeting.mp4", "--expected-speaker", "Alex"])
        self.assertEqual(diagnostic.command, "diagnose")

    def test_parser_supports_source_quarantine_for_selected_profiles(self):
        args = build_parser().parse_args(["profiles", "quarantine-source", "meeting.mp4", "--name", "Alex", "--name", "Blair"])
        self.assertEqual(args.source, "meeting.mp4")
        self.assertEqual(args.names, ["Alex", "Blair"])

    def test_profile_event_has_a_visible_name(self):
        output = io.StringIO()
        with redirect_stdout(output):
            _emit(False, "profile", name="Alex", archive=2, active=2)
        self.assertIn("[profile] Alex", output.getvalue())

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

    def test_ignored_recording_can_be_requeued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "meeting.wav"; source.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json"); history.update(source, "ignored")
            self.assertTrue(history.has_completed(source))
            history.update(source, "retry")
            self.assertFalse(history.has_completed(source))
            self.assertTrue(history.is_retry(source))

    def test_history_keeps_multiple_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.wav"; second = root / "second.wav"
            first.write_bytes(b"one"); second.write_bytes(b"two")
            history = RecordingHistory(root / "recording-history.json")
            history.update(first, "completed", root / "first.md")
            history.update(second, "failed")
            self.assertEqual(len(RecordingHistory(root / "recording-history.json").records), 2)

    def test_history_update_after_rename_keeps_original_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); original = root / "recording.mp4"; original.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json"); history.update(original, "pending")
            original.unlink(); renamed = root / "final.mp4"; renamed.write_bytes(b"audio")
            history.update(original, "completed", root / "final.md", renamed)
            records = RecordingHistory(root / "recording-history.json").records
            self.assertEqual(len(records), 1); self.assertEqual(records[0]["status"], "completed"); self.assertEqual(records[0]["final_path"], str(renamed.resolve()))

    def test_latest_completed_recording_is_scan_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / "meeting.wav"; source.write_bytes(b"audio")
            history = RecordingHistory(root / "recording-history.json"); history.update(source, "completed")
            self.assertEqual(history.latest_completed_source_mtime(), source.stat().st_mtime)

    def test_filename_templates_remember_newest_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filename-templates.json"
            settings = FilenameTemplateSettings(path)
            settings.remember("SW Daily Standup"); settings.remember("Project Review"); settings.remember("sw daily standup")
            loaded = FilenameTemplateSettings(path)
            self.assertEqual(loaded.names, ["sw daily standup", "Project Review"])

    def test_sample_rejection_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rejections.json"; store = SampleRejectionStore(path); store.add([1.0, 0.0], "Too noisy or unclear", "Hard to hear", "meeting.wav")
            loaded = SampleRejectionStore(path)
            self.assertEqual(loaded.records[0]["reason"], "Too noisy or unclear")
