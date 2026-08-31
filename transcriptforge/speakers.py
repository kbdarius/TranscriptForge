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
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .audio import rms_dbfs

PROFILE_MATCH_THRESHOLD = 0.78
PROFILE_DUPLICATE_THRESHOLD = 0.995
PROFILE_MATCH_MARGIN = 0.04
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
    sample_embeddings: list[list[float]] = field(default_factory=list)
    training_embeddings: list[list[float]] = field(default_factory=list)
    training_qualities: list[float] = field(default_factory=list)


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
        self.embedding_metadata: dict[str, list[dict]] = {}
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
            metadata = payload.get("embedding_metadata", {})
            self.embedding_metadata = {
                str(name): [item for item in values if isinstance(item, dict)]
                for name, values in metadata.items()
                if isinstance(values, list)
            } if isinstance(metadata, dict) else {}
            for name in self.profiles:
                self.embedding_metadata.setdefault(name, [])
        except (OSError, ValueError, TypeError) as exc:
            # A bad profile file must not prevent transcription. Keep it in place
            # for manual recovery and start with an empty, safe profile set.
            self.profiles = {}
            self.embedding_metadata = {}

    def save(self) -> None:
        payload = {"version": 2, "updated": datetime.now(timezone.utc).isoformat(), "profiles": self.profiles, "embedding_metadata": self.embedding_metadata}
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
        candidates = self.match_candidates(embedding)
        best_name, best_score = candidates[0] if candidates else (None, None)
        if best_score is None or best_score < threshold:
            return None, best_score
        return best_name, best_score

    def match_candidates(self, embedding: list[float]) -> list[tuple[str, float]]:
        candidates = []
        for name, vectors in self.profiles.items():
            if not vectors:
                continue
            prototype_score = max(cosine_similarity(embedding, vector) for vector in vectors)
            centroid = np.mean(np.asarray(vectors, dtype=np.float32), axis=0)
            centroid_score = cosine_similarity(embedding, centroid)
            candidates.append((name, max(prototype_score, centroid_score)))
        return sorted(candidates, key=lambda item: item[1], reverse=True)

    def best_match_with_margin(self, embedding: list[float], threshold: float = PROFILE_MATCH_THRESHOLD) -> tuple[str | None, float | None, float | None]:
        candidates = self.match_candidates(embedding)
        if not candidates:
            return None, None, None
        name, score = candidates[0]
        margin = score - candidates[1][1] if len(candidates) > 1 else 1.0
        return (name, score, margin) if score >= threshold else (None, score, margin)

    def add_confirmed_embedding(self, name: str, embedding: list[float], max_samples: int | None = None, metadata: dict | None = None) -> bool:
        clean_name = " ".join(name.strip().split())
        if not clean_name or clean_name.lower() in {"unknown", "speaker", "none"}:
            return False
        vector = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            return False
        normalized = (vector / norm).astype(float).tolist()
        samples = self.profiles.setdefault(clean_name, [])
        if any(cosine_similarity(normalized, existing) >= PROFILE_DUPLICATE_THRESHOLD for existing in samples):
            return False
        samples.append(normalized)
        self.profiles[clean_name] = samples if max_samples is None else samples[-max_samples:]
        details = dict(metadata or {})
        details.setdefault("quality", 1.0)
        details.setdefault("added", datetime.now(timezone.utc).isoformat())
        self.embedding_metadata.setdefault(clean_name, []).append(details)
        if max_samples is not None:
            self.embedding_metadata[clean_name] = self.embedding_metadata[clean_name][-max_samples:]
        return True


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


def write_review_samples(wav_path: Path, clusters: list[SpeakerCluster], directory: Path) -> dict[str, list[str]]:
    """Persist short review clips for a pending CLI handoff."""
    directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, list[str]] = {}
    with wave.open(str(wav_path), "rb") as reader:
        rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
        for cluster in clusters:
            files = []
            for index, (start, end) in enumerate(cluster.samples, start=1):
                target = directory / f"{cluster.identifier}-{index}.wav"
                reader.setpos(max(0, int(start * rate)))
                frames = reader.readframes(max(1, int((end - start) * rate)))
                with wave.open(str(target), "wb") as writer:
                    writer.setnchannels(channels); writer.setsampwidth(width); writer.setframerate(rate); writer.writeframes(frames)
                files.append(str(target))
            result[cluster.identifier] = files
    return result


def remove_review_sample(analysis: SpeakerAnalysis, cluster: SpeakerCluster, index: int) -> tuple[float, float]:
    """Remove one review clip from profile training and current labeling."""
    if index < 0 or index >= len(cluster.samples):
        raise IndexError("Speaker sample index is out of range")
    removed = cluster.samples.pop(index)
    removed_embedding = cluster.sample_embeddings.pop(index) if index < len(cluster.sample_embeddings) else None
    if removed_embedding is not None and cluster.training_embeddings:
        nearest = max(range(len(cluster.training_embeddings)), key=lambda item: cosine_similarity(removed_embedding, cluster.training_embeddings[item]))
        cluster.training_embeddings.pop(nearest)
        if nearest < len(cluster.training_qualities):
            cluster.training_qualities.pop(nearest)
    cluster.intervals = [interval for interval in cluster.intervals if interval != removed]
    analysis.interval_labels = [item for item in analysis.interval_labels if item[:2] != removed]
    centroid_embeddings = cluster.training_embeddings or cluster.sample_embeddings
    if centroid_embeddings:
        average = np.mean(np.asarray(centroid_embeddings, dtype=float), axis=0)
        cluster.embedding = (average / max(float(np.linalg.norm(average)), 1e-8)).tolist()
    else:
        cluster.embedding = []
    return removed


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
        quality_values = []
        for (start, end), embedding in zip(intervals, cluster["embeddings"]):
            duration_score = min(1.0, (end - start) / 3.0)
            segment = samples[int(start * rate):int(end * rate)]
            level_score = min(1.0, max(0.0, (rms_dbfs(segment) + 45.0) / 35.0))
            quality_values.append(duration_score * level_score)
        ranked = sorted(zip(intervals, cluster["embeddings"], quality_values), key=lambda item: item[2], reverse=True)[:3]
        samples_for_review = [item[0] for item in ranked]
        sample_embeddings = [item[1].astype(float).tolist() for item in ranked]
        vector = cluster["centroid"].astype(float).tolist()
        suggested, score = store.best_match(vector)
        training = [item.astype(float).tolist() for item in cluster["embeddings"]]
        training_qualities = quality_values
        output.append(SpeakerCluster(identifier, vector, intervals, samples_for_review, suggested, score, sample_embeddings, training, training_qualities))
        interval_labels.extend((start, end, identifier) for start, end in intervals)
        log(f"Detected {identifier} with {len(intervals)} voice samples")
    return SpeakerAnalysis(output, sorted(interval_labels))


def save_confirmed_profiles(analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None, metadata: dict | None = None) -> SpeakerProfileStore:
    store = store or SpeakerProfileStore()
    for cluster in analysis.clusters:
        name = " ".join(names.get(cluster.identifier, "").strip().split())
        if name:
            # Learn only from samples the user kept. The centroid fallback
            # preserves compatibility with programmatically-created clusters.
            embeddings = cluster.training_embeddings or cluster.sample_embeddings or ([cluster.embedding] if cluster.samples else [])
            qualities = cluster.training_qualities if cluster.training_embeddings else []
            for index, embedding in enumerate(embeddings):
                details = dict(metadata or {})
                if index < len(qualities):
                    details["quality"] = qualities[index]
                store.add_confirmed_embedding(name, embedding, metadata=details)
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
        # A user may remove every review sample from a cluster. There is then
        # nothing left to identify, so do not ask for a second decision.
        if not cluster.samples or not cluster.embedding:
            continue
        suggested, score, margin = store.best_match_with_margin(cluster.embedding, threshold=0.0)
        cluster.suggestion_score = score
        if suggested and score is not None and score >= PROFILE_MATCH_THRESHOLD and (margin is None or margin >= PROFILE_MATCH_MARGIN):
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


def fill_unknown_speakers_from_neighbors(segments, max_gap_segments: int = 1, max_segment_seconds: float = 3.0) -> int:
    """Fill only short Unknown runs bracketed by the same confirmed speaker."""
    filled = 0
    for index, segment in enumerate(segments):
        if segment.speaker not in (None, "", "Unknown") or segment.duration > max_segment_seconds or index == 0 or index >= len(segments) - 1:
            continue
        previous = next((segments[position] for position in range(index - 1, max(-1, index - max_gap_segments - 1), -1) if segments[position].speaker not in (None, "", "Unknown")), None)
        following = next((segments[position] for position in range(index + 1, min(len(segments), index + max_gap_segments + 2)) if segments[position].speaker not in (None, "", "Unknown")), None)
        if previous and following and previous.speaker == following.speaker:
            segment.speaker = previous.speaker
            segment.diagnostics["speaker_inferred"] = "matching neighboring speakers"
            filled += 1
    return filled


class _NeverCancel:
    def is_set(self):
        return False
