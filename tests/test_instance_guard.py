import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from transcriptforge import app, instance_guard


class AppInstanceGuardTests(unittest.TestCase):
    def test_acquires_and_closes_the_named_event(self):
        kernel32 = Mock()
        kernel32.CreateEventW.return_value = 123
        kernel32.CloseHandle.return_value = 1
        with (
            patch.object(instance_guard.os, "name", "nt"),
            patch.object(instance_guard, "_kernel32", return_value=kernel32),
            patch.object(instance_guard.ctypes, "get_last_error", return_value=0),
        ):
            guard = instance_guard.AppInstanceGuard.try_acquire()
            self.assertIsNotNone(guard)
            guard.close()

        kernel32.CreateEventW.assert_called_once_with(
            None,
            True,
            True,
            r"Local\TranscriptForge.AppRunning",
        )
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_existing_named_event_prevents_another_instance(self):
        kernel32 = Mock()
        kernel32.CreateEventW.return_value = 123
        kernel32.CloseHandle.return_value = 1
        with (
            patch.object(instance_guard.os, "name", "nt"),
            patch.object(instance_guard, "_kernel32", return_value=kernel32),
            patch.object(
                instance_guard.ctypes,
                "get_last_error",
                return_value=instance_guard._ERROR_ALREADY_EXISTS,
            ),
        ):
            self.assertIsNone(instance_guard.AppInstanceGuard.try_acquire())

        kernel32.CloseHandle.assert_called_once_with(123)

    def test_running_app_is_detected_by_opening_its_named_event(self):
        kernel32 = Mock()
        kernel32.OpenEventW.return_value = 456
        kernel32.CloseHandle.return_value = 1
        with (
            patch.object(instance_guard.os, "name", "nt"),
            patch.object(instance_guard, "_kernel32", return_value=kernel32),
        ):
            self.assertTrue(instance_guard.is_desktop_app_running())

        kernel32.OpenEventW.assert_called_once_with(
            instance_guard._SYNCHRONIZE,
            False,
            r"Local\TranscriptForge.AppRunning",
        )
        kernel32.CloseHandle.assert_called_once_with(456)

    def test_missing_named_event_means_app_is_not_running(self):
        kernel32 = Mock()
        kernel32.OpenEventW.return_value = None
        with (
            patch.object(instance_guard.os, "name", "nt"),
            patch.object(instance_guard, "_kernel32", return_value=kernel32),
            patch.object(
                instance_guard.ctypes,
                "get_last_error",
                return_value=instance_guard._ERROR_FILE_NOT_FOUND,
            ),
        ):
            self.assertFalse(instance_guard.is_desktop_app_running())

    def test_duplicate_scheduled_gui_requeues_recording_instead_of_opening(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "meeting.mp4"
            source.touch()
            history = Mock()
            history.records = [{
                "original_path": str(source.resolve()),
                "status": "pending",
            }]
            with (
                patch.object(app.AppInstanceGuard, "try_acquire", return_value=None),
                patch.object(app, "App") as gui,
                patch.object(app, "RecordingHistory", return_value=history),
                patch.object(
                    app.sys,
                    "argv",
                    ["transcriptforge", "--input", str(source), "--auto-start"],
                ),
            ):
                app.main()

        gui.assert_not_called()
        history.update.assert_called_once_with(source, "retry")

    def test_duplicate_scheduled_gui_does_not_requeue_completed_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "meeting.mp4"
            source.touch()
            history = Mock()
            history.records = [{
                "original_path": str(source.resolve()),
                "status": "completed",
            }]
            with (
                patch.object(app.AppInstanceGuard, "try_acquire", return_value=None),
                patch.object(app, "App") as gui,
                patch.object(app, "RecordingHistory", return_value=history),
                patch.object(
                    app.sys,
                    "argv",
                    ["transcriptforge", "--input", str(source), "--auto-start"],
                ),
            ):
                app.main()

        gui.assert_not_called()
        history.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
