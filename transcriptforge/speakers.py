"""Local speaker clustering and confirmed voice-profile matching.

The module stores speaker embeddings, not recordings.  The optional
Resemblyzer dependency supplies the local voice encoder; the rest of the
workflow is dependency-light so it remains testable without that model.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .audio import rms_dbfs

PROFILE_MATCH_THRESHOLD = 0.78
MIN_VOICE_SECONDS = 1.5
MAX_SAMPLE_SECONDS = 6.0
FRAME_SECONDS = 0.25


@dataclass
class SpeakerCluster:
    identifier: str
    embedding: list[float]
    intervals: list[tuple[float, float]] = field(default_factory=list)
    samples: list[tuple[float, float]] = field(default_factory=list)
    suggested_name: str | None = None
    suggestion_score: float | None = None


@dataclass
class SpeakerAnalysis:
    clusters: list[SpeakerCluster]
    interval_labels: list[tuple[float, float, str]]


def profiles_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / "LocalAudioTranscriber" / "speaker-profiles.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def cosine_similarity(left: list[float] | np.ndarray, right: list[float] | np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denominator <= 1e-8 else float(np.dot(a, b) / denominator)


class SpeakerProfileStore:
    """A small JSON store of user-confirmed speaker embeddings."""

    def __init__(self, path: Path | None = None):
        self.path = path or profiles_path()
        self.profiles: dict[str, list[list[float]]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.profiles = {
                str(name): [list(map(float, vector)) for vector in vectors]
                for name, vectors in payload.get("profiles", {}).items()
                if isinstance(vectors, list)
            }
        except (OSError, ValueError, TypeError) as exc:
            # A bad profile file must not prevent transcription. Keep it in place
            # for manual recovery and start with an empty, safe profile set.
            self.profiles = {}

    def save(self) -> None:
        payload = {"version": 1, "updated": datetime.now(timezone.utc).isoformat(), "profiles": self.profiles}
        fd, temporary = tempfile.mkstemp(prefix="speaker-profiles-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def best_match(self, embedding: list[float], threshold: float = PROFILE_MATCH_THRESHOLD) -> tuple[str | None, float | None]:
        best_name, best_score = None, None
        for name, vectors in self.profiles.items():
            for vector in vectors:
                score = cosine_similarity(embedding, vector)
                if best_score is None or score > best_score:
                    best_name, best_score = name, score
        if best_score is None or best_score < threshold:
            return None, best_score
        return best_name, best_score

    def add_confirmed_embedding(self, name: str, embedding: list[float], max_samples: int = 20) -> None:
        clean_name = " ".join(name.strip().split())
        if not clean_name or clean_name.lower() in {"unknown", "speaker", "none"}:
            return
        samples = self.profiles.setdefault(clean_name, [])
        samples.append([float(value) for value in embedding])
        self.profiles[clean_name] = samples[-max_samples:]


def _voice_intervals(samples: np.ndarray, rate: int, threshold_dbfs: float = -45.0) -> list[tuple[float, float]]:
    frame_size = max(1, int(rate * FRAME_SECONDS))
    active: list[tuple[float, float]] = []
    start: float | None = None
    quiet_frames = 0
    for offset in range(0, len(samples), frame_size):
        end = min(len(samples), offset + frame_size)
        is_voice = rms_dbfs(samples[offset:end]) > threshold_dbfs
        if is_voice and start is None:
            start = offset / rate
            quiet_frames = 0
        elif is_voice:
            quiet_frames = 0
        elif start is not None:
            quiet_frames += 1
            if quiet_frames >= int(0.5 / FRAME_SECONDS):
                finish = max(start, (offset - (quiet_frames - 1) * frame_size) / rate)
                if finish - start >= MIN_VOICE_SECONDS:
                    active.append((start, finish))
                start = None
                quiet_frames = 0
    if start is not None:
        finish = len(samples) / rate
        if finish - start >= MIN_VOICE_SECONDS:
            active.append((start, finish))
    return active


def _sample_ranges(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    samples = []
    for start, end in intervals:
        cursor = start
        while cursor < end:
            finish = min(end, cursor + MAX_SAMPLE_SECONDS)
            if finish - cursor >= MIN_VOICE_SECONDS:
                samples.append((cursor, finish))
            cursor = finish
    return samples


def _load_encoder():
    try:
        from resemblyzer import VoiceEncoder
    except ImportError as exc:
        raise RuntimeError("Speaker identification requires the resemblyzer package. Install requirements.txt first.") from exc
    try:
        return VoiceEncoder(device="cpu")
    except Exception as exc:
        raise RuntimeError(f"Could not load the local speaker encoder: {exc}") from exc


def analyze_speakers(samples: np.ndarray, rate: int, cancel=None, log=None, progress=None) -> SpeakerAnalysis:
    cancel = cancel or _NeverCancel()
    log = log or (lambda _: None)
    progress = progress or (lambda _: None)
    if rate != 16000:
        raise ValueError("Speaker analysis expects decoded 16 kHz audio")
    ranges = _sample_ranges(_voice_intervals(samples, rate))
    if not ranges:
        return SpeakerAnalysis([], [])
    encoder = _load_encoder()
    clusters: list[dict] = []
    for index, (start, end) in enumerate(ranges):
        if cancel.is_set():
            raise InterruptedError("Speaker analysis cancelled")
        waveform = samples[int(start * rate):int(end * rate)]
        embedding = np.asarray(encoder.embed_utterance(waveform), dtype=np.float32)
        if embedding.size == 0:
            continue
        best_index, best_score = None, -1.0
        for cluster_index, cluster in enumerate(clusters):
            score = cosine_similarity(embedding, cluster["centroid"])
            if score > best_score:
                best_index, best_score = cluster_index, score
        if best_index is None or best_score < PROFILE_MATCH_THRESHOLD:
            clusters.append({"centroid": embedding, "embeddings": [embedding], "intervals": [(start, end)]})
        else:
            cluster = clusters[best_index]
            cluster["embeddings"].append(embedding)
            cluster["intervals"].append((start, end))
            average = np.mean(np.stack(cluster["embeddings"]), axis=0)
            cluster["centroid"] = average / max(float(np.linalg.norm(average)), 1e-8)
        progress((index + 1) / len(ranges))
    output: list[SpeakerCluster] = []
    interval_labels: list[tuple[float, float, str]] = []
    store = SpeakerProfileStore()
    for number, cluster in enumerate(clusters, start=1):
        identifier = f"SPEAKER_{number:02d}"
        intervals = sorted(cluster["intervals"])
        samples_for_review = sorted(intervals, key=lambda item: item[1] - item[0], reverse=True)[:3]
        vector = cluster["centroid"].astype(float).tolist()
        suggested, score = store.best_match(vector)
        output.append(SpeakerCluster(identifier, vector, intervals, samples_for_review, suggested, score))
        interval_labels.extend((start, end, identifier) for start, end in intervals)
        log(f"Detected {identifier} with {len(intervals)} voice samples")
    return SpeakerAnalysis(output, sorted(interval_labels))


def save_confirmed_profiles(analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None) -> SpeakerProfileStore:
    store = store or SpeakerProfileStore()
    for cluster in analysis.clusters:
        name = " ".join(names.get(cluster.identifier, "").strip().split())
        if name:
            store.add_confirmed_embedding(name, cluster.embedding)
    if names:
        store.save()
    return store


def refine_unresolved_clusters(analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None) -> tuple[dict[str, str], list[SpeakerCluster], SpeakerProfileStore]:
    """Use confirmed profiles to resolve obvious blanks and return only uncertain clusters."""
    store = store or SpeakerProfileStore()
    final_names = dict(names)
    unresolved = []
    for cluster in analysis.clusters:
        if final_names.get(cluster.identifier, "").strip() != "":
            continue
        suggested, score = store.best_match(cluster.embedding, threshold=0.0)
        cluster.suggestion_score = score
        if suggested and score is not None and score >= PROFILE_MATCH_THRESHOLD:
            final_names[cluster.identifier] = suggested
        else:
            cluster.suggested_name = None
            unresolved.append(cluster)
    return final_names, unresolved, store


def apply_speaker_names(segments, analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None, save_profiles: bool = True):
    if save_profiles:
        save_confirmed_profiles(analysis, names, store)
    for segment in segments:
        overlaps: dict[str, float] = {}
        for start, end, identifier in analysis.interval_labels:
            overlap = max(0.0, min(segment.end, end) - max(segment.start, start))
            if overlap:
                overlaps[identifier] = overlaps.get(identifier, 0.0) + overlap
        if overlaps:
            identifier = max(overlaps, key=overlaps.get)
            segment.speaker = names.get(identifier, "").strip() or "Unknown"
        else:
            segment.speaker = "Unknown"
    return segments


class _NeverCancel:
    def is_set(self):
        return False
