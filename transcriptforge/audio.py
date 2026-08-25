import math
import wave
from pathlib import Path

import numpy as np

def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
        if width != 2:
            raise ValueError("Decoded audio must be signed 16-bit PCM")
        raw = wav.readframes(frames)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate

def slice_audio(samples: np.ndarray, rate: int, start: float, end: float) -> np.ndarray:
    left = max(0, int(start * rate)); right = min(len(samples), int(end * rate))
    return samples[left:right]

def rms_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return -120.0 if rms <= 1e-9 else 20.0 * math.log10(min(1.0, rms))

def interval_rms_dbfs(samples: np.ndarray, rate: int, start: float, end: float) -> float:
    return rms_dbfs(slice_audio(samples, rate, start, end))

