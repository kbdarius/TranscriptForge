import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from transcriptforge import scheduler


class ScheduledScanTests(unittest.TestCase):
    def test_saved_recording_folder_overrides_stale_task_argument(self):
        saved_folder = Path("D:/OneDrive/Recordings")
        stale_folder = Path("C:/Users/old/Recordings")
        with patch.object(
            scheduler,
            "RecordingFolderSettings",
            return_value=SimpleNamespace(folder=str(saved_folder)),
        ):
            self.assertEqual(scheduler.resolve_recording_folder(stale_folder), saved_folder)

    def test_legacy_folder_argument_is_used_when_no_saved_setting_exists(self):
        legacy_folder = Path("D:/Recordings")
        with patch.object(
            scheduler,
            "RecordingFolderSettings",
            return_value=SimpleNamespace(folder=None),
        ):
            self.assertEqual(scheduler.resolve_recording_folder(legacy_folder), legacy_folder)

    def test_missing_saved_folder_does_not_fall_back_to_stale_task_argument(self):
        stale_folder = Path("C:/Users/old/Recordings")
        with tempfile.TemporaryDirectory() as directory:
            saved_folder = Path(directory) / "missing"
            with (
                patch.object(
                    scheduler,
                    "RecordingFolderSettings",
                    return_value=SimpleNamespace(folder=str(saved_folder)),
                ),
                patch.object(scheduler, "RecordingHistory"),
                patch.object(scheduler, "find_new_recording") as find_new_recording,
                patch.object(scheduler, "_launch_gui") as launch_gui,
            ):
                self.assertEqual(scheduler.scan_and_launch(stale_folder), 0)
            find_new_recording.assert_not_called()
            launch_gui.assert_called_once_with(["--prompt-recording-folder"], None)

    def test_scan_uses_saved_folder_when_legacy_task_argument_is_present(self):
        with tempfile.TemporaryDirectory() as directory:
            saved_folder = Path(directory)
            stale_folder = Path("C:/Users/old/Recordings")
            history = object()
            with (
                patch.object(
                    scheduler,
                    "RecordingFolderSettings",
                    return_value=SimpleNamespace(folder=str(saved_folder)),
                ),
                patch.object(scheduler, "RecordingHistory", return_value=history),
                patch.object(scheduler, "find_new_recording", return_value=None) as find_new_recording,
                patch.object(scheduler, "_launch_gui") as launch_gui,
            ):
                self.assertEqual(scheduler.scan_and_launch(stale_folder), 0)
            find_new_recording.assert_called_once_with(saved_folder, history)
            launch_gui.assert_not_called()

    def test_scan_without_any_folder_prompts_for_recording_folder(self):
        with (
            patch.object(
                scheduler,
                "RecordingFolderSettings",
                return_value=SimpleNamespace(folder=None),
            ),
            patch.object(scheduler, "RecordingHistory"),
            patch.object(scheduler, "_launch_gui") as launch_gui,
        ):
            self.assertEqual(scheduler.scan_and_launch(), 0)
        launch_gui.assert_called_once_with(["--prompt-recording-folder"], None)


if __name__ == "__main__":
    unittest.main()
