import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from transcriptforge.app import App, NO_MEETING_SELECTION
from transcriptforge.controller import _review_speaker_names
from transcriptforge.speakers import SpeakerProfileStore


class ScheduledMeetingDialogTests(unittest.TestCase):
    def test_no_meeting_option_keeps_current_workflow_available(self):
        self.assertIn("No meeting selected", NO_MEETING_SELECTION)

    def test_speaker_limit_accepts_empty_and_positive_whole_numbers(self):
        self.assertIsNone(App._parse_speaker_limit(""))
        self.assertIsNone(App._parse_speaker_limit("  "))
        self.assertEqual(App._parse_speaker_limit("4"), 4)

    def test_speaker_limit_rejects_invalid_values(self):
        for value in ("0", "-1", "2.5", "many"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    App._parse_speaker_limit(value)

    def test_recording_timestamp_is_preferred_over_file_modified_time(self):
        source = Path("Standup-20260925_084638-Meeting Recording.mp4")
        self.assertEqual(
            App._recording_datetime(source),
            datetime(2026, 9, 25, 8, 46, 38),
        )

    def test_modified_time_is_fallback_when_filename_has_no_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recording.mp4"
            source.write_bytes(b"audio")
            expected = datetime(2024, 1, 2, 3, 4, 5)
            timestamp = expected.timestamp()
            os.utime(source, (timestamp, timestamp))
            self.assertEqual(App._recording_datetime(source), expected)

    def test_meeting_review_suggestions_are_limited_but_empty_meeting_keeps_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex Yu", [1.0, 0.0])
            store.add_confirmed_embedding("Blair Moore", [0.0, 1.0])
            self.assertEqual(_review_speaker_names(store, None), ["Alex Yu", "Blair Moore"])
            self.assertEqual(_review_speaker_names(store, ["Alex Yu"]), ["Alex Yu"])


if __name__ == "__main__":
    unittest.main()
