import tempfile
import unittest
from pathlib import Path

from transcriptforge.settings import LiveRecordingFolderSettings, OutputLocationHistory


class SettingsTests(unittest.TestCase):
    def test_remembers_newest_five_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locations.json"
            history = OutputLocationHistory(path)
            for index in range(7):
                history.remember(Path(directory) / f"output-{index}")
            self.assertEqual(len(history.locations), 5)
            self.assertTrue(history.locations[0].endswith("output-6"))
            loaded = OutputLocationHistory(path)
            self.assertEqual(loaded.locations, history.locations)

    def test_reusing_location_promotes_it_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locations.json"
            history = OutputLocationHistory(path)
            history.remember(Path(directory) / "one")
            history.remember(Path(directory) / "two")
            history.remember(Path(directory) / "one")
            self.assertEqual(history.locations[0].endswith("one"), True)
            self.assertEqual(len(history.locations), 2)

    def test_live_recording_folder_round_trips_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "live-recording-folder.json"
            settings = LiveRecordingFolderSettings(path)
            settings.set(root / "capture")

            loaded = LiveRecordingFolderSettings(path)

            self.assertEqual(loaded.folder, str((root / "capture").resolve()))
