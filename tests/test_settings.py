import tempfile
import unittest
from pathlib import Path

from transcriptforge.settings import ContentProviderHistory, LiveRecordingFolderSettings, OutputLocationHistory


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

    def test_content_provider_history_persists_and_prioritizes_recent_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "content-provider-history.json"
            history = ContentProviderHistory(path)
            history.remember("Alex Yu")
            history.remember("Blair Moore")
            history.remember(" alex   yu ")

            loaded = ContentProviderHistory(path)

            self.assertEqual(loaded.last_selected, "alex yu")
            self.assertEqual(loaded.recent_providers, ["alex yu", "Blair Moore"])
            self.assertEqual(
                loaded.choices(["Zoe Taylor", "Alex Yu", "Unknown", "Casey Reed"]),
                ["Alex Yu", "Blair Moore", "Unknown", "Casey Reed", "Zoe Taylor"],
            )

    def test_unknown_can_be_remembered_without_removing_recent_people(self):
        with tempfile.TemporaryDirectory() as directory:
            history = ContentProviderHistory(Path(directory) / "providers.json")
            history.remember("Alex Yu")
            history.remember("Unknown")

            self.assertEqual(history.last_selected, "Unknown")
            self.assertEqual(history.recent_providers, ["Alex Yu"])
            self.assertEqual(
                history.choices(["Blair Moore", "Alex Yu"]),
                ["Alex Yu", "Unknown", "Blair Moore"],
            )

    def test_content_provider_history_is_bounded_to_the_most_recent_names(self):
        with tempfile.TemporaryDirectory() as directory:
            history = ContentProviderHistory(Path(directory) / "providers.json")
            for index in range(15):
                history.remember(f"Provider {index}")

            self.assertEqual(len(history.recent_providers), 10)
            self.assertEqual(history.recent_providers[0], "Provider 14")
            self.assertEqual(history.recent_providers[-1], "Provider 5")
