import threading
import unittest
import numpy as np
from transcriptforge.transcription import transcribe_samples

class FakeModel:
    def __init__(self): self.calls = []
    def transcribe(self, audio, **kwargs):
        self.calls.append((len(audio), kwargs)); return {"segments": [{"start": 0, "end": 1, "text": "Hello", "avg_logprob": -.2, "no_speech_prob": .01}]}

class TranscriptionTests(unittest.TestCase):
    def test_uses_sample_arrays_and_independent_windows(self):
        model = FakeModel(); segments, _ = transcribe_samples(np.zeros(16000 * 2, dtype=np.float32), 16000, model, "en", threading.Event())
        self.assertTrue(model.calls); self.assertIsInstance(model.calls[0][0], int); self.assertFalse(model.calls[0][1]["condition_on_previous_text"])

