import re
from collections import defaultdict

from .audio import interval_rms_dbfs
from .models import Segment, SuspectRange

def normalize_text(text: str) -> str:
    return re.sub(r"[^\w\s]", "", " ".join(text.strip().lower().split()))

def _weak(segment: Segment, quiet: bool, threshold: float) -> bool:
    return quiet or (segment.no_speech_prob is not None and segment.no_speech_prob >= threshold) or (segment.avg_logprob is not None and segment.avg_logprob < -1.0)

def find_suspect_ranges(segments: list[Segment], samples, rate: int, no_speech_threshold: float = .6, quiet_dbfs: float = -45.0) -> list[SuspectRange]:
    suspects = []
    i = 0
    while i < len(segments):
        key = normalize_text(segments[i].text)
        if not key:
            i += 1; continue
        j = i + 1
        while j < len(segments) and normalize_text(segments[j].text) == key and segments[j].start - segments[j-1].end <= 1.0:
            j += 1
        run = segments[i:j]
        span = run[-1].end - run[0].start
        token_like = len(key.split()) <= 3
        quiet = any(interval_rms_dbfs(samples, rate, s.start, s.end) <= quiet_dbfs for s in run)
        weak = any(_weak(s, quiet, no_speech_threshold) for s in run)
        if len(run) >= 3 and span >= 3.0 and (token_like or any((s.compression_ratio or 0) >= 2.4 for s in run)) and weak:
            suspects.append(SuspectRange(run[0].start, run[-1].end, f"contiguous repeated output: {run[0].text.strip()!r}"))
        elif len(run) >= 4 and token_like and (run[-1].end - run[0].start) >= 3.0:
            suspects.append(SuspectRange(run[0].start, run[-1].end, f"repeated short token: {run[0].text.strip()!r}"))
        i = max(i + 1, j)
    return suspects

def in_range(segment: Segment, suspect: SuspectRange) -> bool:
    return segment.start < suspect.end and segment.end > suspect.start

def scoped_duplicate_cleanup(segments: list[Segment], suspects: list[SuspectRange]) -> list[Segment]:
    result = []
    for segment in segments:
        if any(in_range(segment, r) for r in suspects) and result and normalize_text(result[-1].text) == normalize_text(segment.text):
            continue
        result.append(segment)
    return result

