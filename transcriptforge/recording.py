"""Live recording of Windows playback audio through WASAPI loopback."""

from __future__ import annotations

import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np


RecorderFactory = Callable[[int, int], tuple[object, int]]


def _default_loopback_recorder(sample_rate: int, blocksize: int) -> tuple[object, int]:
    try:
        import soundcard
    except ImportError as exc:
        raise RuntimeError(
            "Live system-audio recording requires the SoundCard package. "
            "Install the application dependencies and try again."
        ) from exc

    speaker = soundcard.default_speaker()
    loopback = soundcard.get_microphone(speaker.name, include_loopback=True)
    channels = int(loopback.channels)
    if channels < 1:
        raise RuntimeError("The default Windows playback device has no recordable channels.")
    return (
        loopback.recorder(samplerate=sample_rate, blocksize=blocksize),
        channels,
    )


def _pcm16le(frames: np.ndarray) -> bytes:
    samples = np.asarray(frames, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    if samples.ndim != 2:
        raise ValueError("Playback capture returned audio in an unsupported shape.")
    samples = np.nan_to_num(samples, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
    return np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _new_recording_path(folder: Path, now: datetime | None = None) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    candidate = folder / f"system-recording-{timestamp}.wav"
    suffix = 1
    while candidate.exists():
        candidate = folder / f"system-recording-{timestamp}-{suffix}.wav"
        suffix += 1
    return candidate


class PlaybackAudioRecorder:
    """Capture the default playback device and emit lifecycle events on a worker thread."""

    def __init__(
        self,
        folder: Path,
        callback: Callable[[str, object], None],
        *,
        recorder_factory: RecorderFactory | None = None,
        sample_rate: int = 48_000,
        blocksize: int = 4_096,
    ):
        self.folder = Path(folder)
        self.callback = callback
        self.recorder_factory = recorder_factory or _default_loopback_recorder
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self.output_path: Path | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> Path:
        if self._thread is not None:
            raise RuntimeError("This recorder has already been started.")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.output_path = _new_recording_path(self.folder)
        self._thread = threading.Thread(target=self._capture, daemon=True)
        self._thread.start()
        return self.output_path

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _capture(self) -> None:
        path = self.output_path
        frames_written = 0
        try:
            if path is None:
                raise RuntimeError("The recording output path was not initialized.")
            recorder, channels = self.recorder_factory(self.sample_rate, self.blocksize)
            if channels < 1:
                raise RuntimeError("The playback device has no recordable channels.")
            with recorder as capture, wave.open(str(path), "wb") as output:
                output.setnchannels(channels)
                output.setsampwidth(2)
                output.setframerate(self.sample_rate)
                self.callback("started", path)
                while not self._stop_event.is_set():
                    data = np.asarray(capture.record(numframes=self.blocksize // 2))
                    if data.size == 0:
                        continue
                    if data.ndim == 1:
                        data = data.reshape(-1, 1)
                    if data.ndim != 2 or data.shape[1] != channels:
                        raise ValueError(
                            "Playback capture returned an unexpected number of audio channels."
                        )
                    output.writeframesraw(_pcm16le(data))
                    frames_written += data.shape[0]
            if frames_written == 0:
                raise RuntimeError(
                    "No playback audio was captured. Check that audio was playing and try again."
                )
            self.callback("completed", path)
        except Exception as exc:
            if path is not None and frames_written == 0 and path.is_file():
                try:
                    path.unlink()
                except OSError as cleanup_error:
                    exc = RuntimeError(
                        f"{exc} The empty recording file could not be removed: {cleanup_error}"
                    )
            self.callback("error", (path, str(exc), frames_written > 0))
