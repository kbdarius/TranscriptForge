import tempfile
import unittest
from pathlib import Path

from transcriptforge.settings import OutputLocationHistory


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

