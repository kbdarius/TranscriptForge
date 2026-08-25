import threading
from pathlib import Path

import numpy as np

from .audio import slice_audio, interval_rms_dbfs
from .models import Segment, ProcessingStats, TranscriptionResult, SuspectRange
from .quality import find_suspect_ranges, in_range, scoped_duplicate_cleanup

WINDOW = 300.0; OVERLAP = 2.0

def _segments(raw: dict, offset: float) -> list[Segment]:
    return [Segment(float(x.get("start", 0)) + offset, float(x.get("end", 0)) + offset, x.get("text", ""), x.get("avg_logprob"), x.get("no_speech_prob"), x.get("compression_ratio"), x.get("temperature"), offset) for x in raw.get("segments", [])]

def transcribe_samples(samples: np.ndarray, rate: int, model, language: str, cancel: threading.Event | None = None, log=None, progress=None) -> tuple[list[Segment], ProcessingStats]:
    cancel = cancel or threading.Event(); log = log or (lambda _: None); progress = progress or (lambda _: None)
    duration = len(samples) / rate; all_segments = []; stats = ProcessingStats()
    starts = list(np.arange(0, max(duration, 0.01), WINDOW - OVERLAP))
    for index, start in enumerate(starts):
        if cancel.is_set(): raise InterruptedError("Transcription cancelled")
        end = min(duration, start + WINDOW)
        raw = model.transcribe(slice_audio(samples, rate, start, end), language=language, fp16=False, verbose=False, condition_on_previous_text=False, temperature=0, no_speech_threshold=.6, logprob_threshold=-1.0, compression_ratio_threshold=2.4)
        all_segments.extend(_segments(raw, start)); progress((index + 1) / max(1, len(starts))); log(f"Transcribed window {index + 1}/{len(starts)}")
    # Remove duplicate overlap boundaries only when timestamps overlap and text matches.
    deduped = []
    for s in sorted(all_segments, key=lambda x: (x.start, x.end)):
        if deduped and s.start < deduped[-1].end and s.text.strip().lower() == deduped[-1].text.strip().lower(): continue
        deduped.append(s)
    suspects = find_suspect_ranges(deduped, samples, rate)
    for suspect in suspects:
        if cancel.is_set(): raise InterruptedError("Transcription cancelled")
        stats.retries += 1; retry_start = max(0, suspect.start - 5); retry_end = min(duration, suspect.end + 5)
        log(f"Retrying suspect range {retry_start:.2f}s-{retry_end:.2f}s: {suspect.reason}")
        raw = model.transcribe(slice_audio(samples, rate, retry_start, retry_end), language=language, fp16=False, verbose=False, condition_on_previous_text=False, temperature=0, no_speech_threshold=.6, logprob_threshold=-1.0, compression_ratio_threshold=2.4)
        replacement = []
        for item in _segments(raw, retry_start):
            if item.end > suspect.start and item.start < suspect.end:
                item.start = max(item.start, suspect.start); item.end = min(item.end, suspect.end); replacement.append(item)
        if replacement and not find_suspect_ranges(replacement, samples, rate):
            deduped = [s for s in deduped if not in_range(s, suspect)] + replacement
        else:
            stats.omitted += 1; deduped = [s for s in deduped if not in_range(s, suspect)]
            quiet = interval_rms_dbfs(samples, rate, suspect.start, suspect.end) <= -45.0
            deduped.append(Segment(suspect.start, suspect.end, "[Unclear or silent audio omitted after retry]" if quiet else "[Unclear speech]"))
    return scoped_duplicate_cleanup(sorted(deduped, key=lambda x: x.start), suspects), stats
