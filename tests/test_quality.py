import unittest
import numpy as np
from transcriptforge.models import Segment
from transcriptforge.quality import find_suspect_ranges, normalize_text

class QualityTests(unittest.TestCase):
    def test_normalization(self): self.assertEqual(normalize_text("  Okay!  "), "okay")
    def test_repeated_short_token_is_suspect(self):
        segs = [Segment(i, i + 1, "R0.", avg_logprob=-1.5) for i in range(4)]
        ranges = find_suspect_ranges(segs, np.zeros(16000 * 5, dtype=np.float32), 16000)
        self.assertEqual(len(ranges), 1)
    def test_nonconsecutive_repetition_is_not_suspect(self):
        segs = [Segment(0, 1, "Okay"), Segment(2, 3, "Next"), Segment(35, 36, "Okay")]
        self.assertEqual(find_suspect_ranges(segs, np.zeros(16000 * 40, dtype=np.float32), 16000), [])

