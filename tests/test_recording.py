import threading
import unittest
import wave
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from transcriptforge.recording import PlaybackAudioRecorder, _new_recording_path


class _FakeCapture:
    def __init__(self):
        self.read_started = threading.Event()
        self.release_read = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def record(self, numframes):
        self.read_started.set()
        self.release_read.wait(timeout=2)
        return np.full((numframes, 2), 0.25, dtype=np.float32)


class PlaybackAudioRecorderTests(unittest.TestCase):
    def test_recording_path_is_safe_and_unique(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            timestamp = datetime(2026, 9, 30, 12, 34, 56)
            first = _new_recording_path(folder, timestamp)
            first.touch()

            second = _new_recording_path(folder, timestamp)

            self.assertEqual(first.name, "system-recording-20260930-123456.wav")
            self.assertEqual(second.name, "system-recording-20260930-123456-1.wav")
            self.assertNotIn("/", second.name)

    def test_fake_loopback_capture_writes_a_finalized_pcm_wav(self):
        with TemporaryDirectory() as directory:
            capture = _FakeCapture()
            started = threading.Event()
            finished = threading.Event()
            events = []

            def callback(kind, value):
                events.append((kind, value))
                if kind == "started":
                    started.set()
                if kind in {"completed", "error"}:
                    finished.set()

            recorder = PlaybackAudioRecorder(
                Path(directory),
                callback,
                recorder_factory=lambda _rate, _blocksize: (capture, 2),
            )
            output_path = recorder.start()
            try:
                self.assertTrue(started.wait(timeout=2))
                self.assertTrue(capture.read_started.wait(timeout=2))
                recorder.stop()
                capture.release_read.set()
                self.assertTrue(finished.wait(timeout=2))
            finally:
                recorder.stop()
                capture.release_read.set()
                recorder.join(timeout=2)

            self.assertEqual([kind for kind, _value in events], ["started", "completed"])
            with wave.open(str(output_path), "rb") as recording:
                self.assertEqual(recording.getnchannels(), 2)
                self.assertEqual(recording.getsampwidth(), 2)
                self.assertEqual(recording.getframerate(), 48_000)
                self.assertGreater(recording.getnframes(), 0)


if __name__ == "__main__":
    unittest.main()
