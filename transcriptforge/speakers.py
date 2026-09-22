"""Local speaker clustering and confirmed voice-profile matching.

The module stores speaker embeddings, not recordings.  The optional
Resemblyzer dependency supplies the local voice encoder; the rest of the
workflow is dependency-light so it remains testable without that model.
"""

from __future__ import annotations

import json
import math
import os
import shutil
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
PROFILE_SCHEMA_VERSION = 3
ACTIVE_PROFILE_LIMIT = 60
ACTIVE_PROFILE_SOURCE_LIMIT = 12
ACTIVE_PROFILE_RECENT_QUOTA = 12
ACTIVE_PROFILE_RECENT_SOURCE_LIMIT = 6
ACTIVE_PROFILE_MIN_QUALITY = 0.35
ACTIVE_PROFILE_DIVERSITY_THRESHOLD = 0.96
PROFILE_GUIDED_ASSIGN_THRESHOLD = 0.72
PROFILE_GUIDED_MIN_CORE_SAMPLES = 2
CLUSTER_MATCH_THRESHOLD = 0.82
CLUSTER_MERGE_THRESHOLD = 0.86
MIN_VOICE_SECONDS = 1.5
MAX_SAMPLE_SECONDS = 6.0
MIN_REVIEW_QUALITY = 0.35
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


def _source_key(source: str | Path | None) -> str:
    if not source:
        return ""
    return os.path.normcase(os.path.normpath(str(source)))


class SpeakerProfileStore:
    """A small JSON store of user-confirmed speaker embeddings."""

    def __init__(self, path: Path | None = None):
        self.path = path or profiles_path()
        self.profiles: dict[str, list[list[float]]] = {}
        self.embedding_metadata: dict[str, list[dict]] = {}
        self.active_indices: dict[str, list[int]] = {}
        self.schema_version = PROFILE_SCHEMA_VERSION
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.schema_version = int(payload.get("version", 1)) if isinstance(payload, dict) else 1
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
            for name, vectors in self.profiles.items():
                values = self.embedding_metadata.setdefault(name, [])
                # Version 2 files may have metadata only for newer vectors.
                # Padding at the front preserves the historical vector order.
                if len(values) < len(vectors):
                    self.embedding_metadata[name] = ([{}] * (len(vectors) - len(values))) + values
                elif len(values) > len(vectors):
                    self.embedding_metadata[name] = values[-len(vectors):]
            raw_active = payload.get("active_indices", {}) if isinstance(payload, dict) else {}
            self.active_indices = {
                str(name): [int(index) for index in indexes if isinstance(index, int) and index >= 0]
                for name, indexes in raw_active.items()
                if isinstance(indexes, list)
            } if isinstance(raw_active, dict) else {}
            self.rebuild_active_indices()
        except (OSError, ValueError, TypeError) as exc:
            # A bad profile file must not prevent transcription. Keep it in place
            # for manual recovery and start with an empty, safe profile set.
            self.profiles = {}
            self.embedding_metadata = {}
            self.active_indices = {}

    def save(self) -> None:
        if self.schema_version < PROFILE_SCHEMA_VERSION and self.path.is_file():
            backup = self.path.with_name(self.path.name + ".v2.bak")
            if not backup.exists():
                shutil.copy2(self.path, backup)
        self.schema_version = PROFILE_SCHEMA_VERSION
        self.rebuild_active_indices()
        payload = {"version": PROFILE_SCHEMA_VERSION, "updated": datetime.now(timezone.utc).isoformat(), "profiles": self.profiles, "embedding_metadata": self.embedding_metadata, "active_indices": self.active_indices}
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

    def _select_active_indices(self, name: str, excluded_sources: set[str] | None = None) -> list[int]:
        vectors = self.profiles.get(name, [])
        metadata = self.embedding_metadata.get(name, [])
        excluded_sources = excluded_sources or set()
        candidates = []
        for index, _vector in enumerate(vectors):
            details = metadata[index] if index < len(metadata) else {}
            if _source_key(details.get("source")) in excluded_sources or details.get("active_excluded"):
                continue
            try:
                quality = float(details.get("quality", 0.65))
            except (TypeError, ValueError):
                quality = 0.65
            if quality >= ACTIVE_PROFILE_MIN_QUALITY:
                candidates.append((index, quality, str(details.get("source") or "legacy")))
        if not candidates:
            candidates = [
                (index, 0.1, "legacy")
                for index in range(len(vectors))
                if index >= len(metadata)
                or (
                    _source_key(metadata[index].get("source")) not in excluded_sources
                    and not metadata[index].get("active_excluded")
                )
            ]
        candidates.sort(key=lambda item: (item[1], -item[0]), reverse=True)
        selected: list[int] = []
        source_counts: dict[str, int] = {}

        # Keep recent, user-confirmed samples visible to the recognizer. The
        # previous quality-only ordering could fill all 60 slots with older
        # samples, leaving correctly labeled newer meetings archived but
        # unused. Recent samples are still capped per source and the normal
        # diversity pass fills the remainder.
        recent_by_source: dict[str, list[tuple[int, float, str]]] = {}
        source_latest: dict[str, str] = {}
        for index, quality, source in candidates:
            details = metadata[index] if index < len(metadata) else {}
            if not details.get("reviewed") or source == "legacy":
                continue
            recent_by_source.setdefault(source, []).append((index, quality, source))
            added = str(details.get("added", ""))
            if added > source_latest.get(source, ""):
                source_latest[source] = added
        recent_sources = sorted(recent_by_source, key=lambda source: source_latest.get(source, ""), reverse=True)
        for source in recent_sources:
            if len(selected) >= ACTIVE_PROFILE_RECENT_QUOTA:
                break
            for candidate in recent_by_source[source][:ACTIVE_PROFILE_RECENT_SOURCE_LIMIT]:
                if len(selected) >= ACTIVE_PROFILE_RECENT_QUOTA:
                    break
                index = candidate[0]
                if index not in selected:
                    selected.append(index)
                    source_counts[source] = source_counts.get(source, 0) + 1

        for index, _quality, source in candidates:
            if len(selected) >= ACTIVE_PROFILE_LIMIT or source_counts.get(source, 0) >= ACTIVE_PROFILE_SOURCE_LIMIT:
                continue
            if index in selected:
                continue
            if selected and max(cosine_similarity(vectors[index], vectors[item]) for item in selected) >= ACTIVE_PROFILE_DIVERSITY_THRESHOLD:
                continue
            selected.append(index)
            source_counts[source] = source_counts.get(source, 0) + 1
        if len(selected) < min(ACTIVE_PROFILE_LIMIT, len(candidates)):
            for index, _quality, source in candidates:
                if len(selected) >= ACTIVE_PROFILE_LIMIT or index in selected:
                    continue
                if source_counts.get(source, 0) >= ACTIVE_PROFILE_SOURCE_LIMIT:
                    continue
                selected.append(index)
                source_counts[source] = source_counts.get(source, 0) + 1
        return selected

    def active_profile_indices(self, name: str, excluded_sources: list[str | Path] | None = None) -> list[int]:
        excluded = {_source_key(source) for source in excluded_sources or [] if source}
        if excluded:
            return self._select_active_indices(name, excluded)
        vectors = self.profiles.get(name, [])
        valid = [index for index in self.active_indices.get(name, []) if index < len(vectors)]
        return valid if valid or not vectors else self._select_active_indices(name)

    def active_vectors(self, name: str, excluded_sources: list[str | Path] | None = None) -> list[list[float]]:
        vectors = self.profiles.get(name, [])
        return [vectors[index] for index in self.active_profile_indices(name, excluded_sources)]

    def active_profile_counts(self) -> dict[str, int]:
        return {name: len(self.active_profile_indices(name)) for name in self.profiles}

    def rebuild_active_indices(self) -> None:
        self.active_indices = {name: self._select_active_indices(name) for name in self.profiles}

    def best_match(self, embedding: list[float], threshold: float = PROFILE_MATCH_THRESHOLD, allowed_names: list[str] | None = None, excluded_sources: list[str | Path] | None = None) -> tuple[str | None, float | None]:
        candidates = self.match_candidates(embedding, allowed_names, excluded_sources)
        best_name, best_score = candidates[0] if candidates else (None, None)
        if best_score is None or best_score < threshold:
            return None, best_score
        return best_name, best_score

    def _profile_signatures(self, allowed_names: list[str] | None = None, excluded_sources: list[str | Path] | None = None) -> list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]:
        allowed = {" ".join(name.strip().split()).casefold() for name in allowed_names or [] if name.strip()}
        signatures = []
        for name in self.profiles:
            if allowed and name.casefold() not in allowed:
                continue
            vectors = self.active_vectors(name, excluded_sources)
            if not vectors:
                continue
            matrix = np.asarray(vectors, dtype=np.float32)
            matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
            center = np.mean(matrix, axis=0)
            centroid = center / max(float(np.linalg.norm(center)), 1e-8)
            similarities = matrix @ matrix.T
            medoid = matrix[int(np.argmax(np.sum(similarities, axis=1)))]
            signatures.append((name, matrix, centroid, medoid))
        return signatures

    @staticmethod
    def _match_signatures(embedding: list[float] | np.ndarray, signatures: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]) -> list[tuple[str, float]]:
        vector = np.asarray(embedding, dtype=np.float32)
        vector /= max(float(np.linalg.norm(vector)), 1e-8)
        candidates = []
        for name, matrix, centroid, medoid in signatures:
            similarities = np.sort(matrix @ vector)[::-1]
            top_mean = float(np.mean(similarities[:min(5, len(similarities))]))
            centroid_score = float(centroid @ vector)
            medoid_score = float(medoid @ vector)
            candidates.append((name, 0.5 * centroid_score + 0.3 * medoid_score + 0.2 * top_mean))
        return sorted(candidates, key=lambda item: item[1], reverse=True)

    def match_candidates(self, embedding: list[float], allowed_names: list[str] | None = None, excluded_sources: list[str | Path] | None = None) -> list[tuple[str, float]]:
        return self._match_signatures(embedding, self._profile_signatures(allowed_names, excluded_sources))

    def best_match_with_margin(self, embedding: list[float], threshold: float = PROFILE_MATCH_THRESHOLD, allowed_names: list[str] | None = None, minimum_margin: float | None = None, excluded_sources: list[str | Path] | None = None) -> tuple[str | None, float | None, float | None]:
        candidates = self.match_candidates(embedding, allowed_names, excluded_sources)
        if not candidates:
            return None, None, None
        name, score = candidates[0]
        margin = score - candidates[1][1] if len(candidates) > 1 else 1.0
        accepted = score >= threshold and (minimum_margin is None or margin >= minimum_margin)
        return (name, score, margin) if accepted else (None, score, margin)

    def quarantine_source(self, source: str | Path, names: list[str] | None = None, reason: str = "source quarantined") -> int:
        """Keep source embeddings in the archive but exclude them from matching."""
        target = _source_key(source)
        allowed = {name.casefold() for name in names or []}
        changed = 0
        for name, rows in self.embedding_metadata.items():
            if allowed and name.casefold() not in allowed:
                continue
            for details in rows:
                if _source_key(details.get("source")) != target or details.get("active_excluded"):
                    continue
                details["active_excluded"] = True
                details["exclusion_reason"] = reason
                details["excluded_at"] = datetime.now(timezone.utc).isoformat()
                changed += 1
        if changed:
            self.save()
        return changed

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
        self.active_indices = {}
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


def _interval_quality(samples: np.ndarray, rate: int, start: float, end: float) -> float:
    duration_score = min(1.0, (end - start) / 3.0)
    segment = samples[int(start * rate):int(end * rate)]
    level_score = min(1.0, max(0.0, (rms_dbfs(segment) + 45.0) / 35.0))
    return duration_score * level_score


def _acoustic_clusters(observations: list[tuple[float, float, np.ndarray, float]]) -> list[dict]:
    """Conservatively cluster voices when no reliable known-speaker seed exists."""
    clusters: list[dict] = []
    ordered = sorted(observations, key=lambda item: (item[3], item[1] - item[0]), reverse=True)
    for start, end, embedding, quality in ordered:
        best_index, best_score = None, -1.0
        for cluster_index, cluster in enumerate(clusters):
            score = cosine_similarity(embedding, cluster["centroid"])
            if score > best_score:
                best_index, best_score = cluster_index, score
        if best_index is None or best_score < CLUSTER_MATCH_THRESHOLD:
            clusters.append({"centroid": embedding, "embeddings": [embedding], "intervals": [(start, end)], "qualities": [quality], "review_scores": [quality]})
            continue
        cluster = clusters[best_index]
        cluster["embeddings"].append(embedding); cluster["intervals"].append((start, end)); cluster["qualities"].append(quality); cluster["review_scores"].append(quality)
        average = np.mean(np.stack(cluster["embeddings"]), axis=0)
        cluster["centroid"] = average / max(float(np.linalg.norm(average)), 1e-8)

    # A second pass joins small fragments that are close to a stable cluster.
    # It avoids turning every short interruption into a new apparent person.
    changed = True
    while changed:
        changed = False
        best_pair = None
        best_score = CLUSTER_MERGE_THRESHOLD
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                score = cosine_similarity(clusters[left]["centroid"], clusters[right]["centroid"])
                smaller = min(len(clusters[left]["intervals"]), len(clusters[right]["intervals"]))
                if score >= best_score and (smaller <= 3 or score >= CLUSTER_MERGE_THRESHOLD + 0.04):
                    best_pair, best_score = (left, right), score
        if best_pair is not None:
            left, right = best_pair
            destination, source = clusters[left], clusters[right]
            destination["embeddings"].extend(source["embeddings"]); destination["intervals"].extend(source["intervals"]); destination["qualities"].extend(source["qualities"]); destination["review_scores"].extend(source["review_scores"])
            average = np.mean(np.stack(destination["embeddings"]), axis=0)
            destination["centroid"] = average / max(float(np.linalg.norm(average)), 1e-8)
            clusters.pop(right); changed = True
    return clusters


def _profile_guided_clusters(observations: list[tuple[float, float, np.ndarray, float]], store: SpeakerProfileStore, expected_speakers: list[str] | None = None, excluded_sources: list[str | Path] | None = None) -> list[dict] | None:
    """Seed recurring speakers from confident individual windows before clustering.

    This prevents a broad moving centroid from joining several similar speakers
    into one cluster. A profile needs at least two confident windows before it
    can collect less-certain windows from the same recording.
    """
    signatures = store._profile_signatures(expected_speakers, excluded_sources)
    if not signatures:
        return None
    matched = []
    core_counts: dict[str, int] = {}
    for observation in observations:
        candidates = store._match_signatures(observation[2], signatures)
        if not candidates:
            matched.append((*observation, None, None, None, False))
            continue
        name, score = candidates[0]
        margin = score - candidates[1][1] if len(candidates) > 1 else 1.0
        is_core = score >= PROFILE_MATCH_THRESHOLD and margin >= PROFILE_MATCH_MARGIN
        if is_core:
            core_counts[name] = core_counts.get(name, 0) + 1
        matched.append((*observation, name, score, margin, is_core))
    credible = {name for name, count in core_counts.items() if count >= PROFILE_GUIDED_MIN_CORE_SAMPLES}
    if not credible:
        return None
    grouped: dict[str, list[tuple[float, float, np.ndarray, float, float, float]]] = {name: [] for name in credible}
    unresolved = []
    for start, end, embedding, quality, name, score, margin, is_core in matched:
        if name in credible and score is not None and (is_core or score >= PROFILE_GUIDED_ASSIGN_THRESHOLD):
            grouped[name].append((start, end, embedding, quality, score, margin or 0.0))
        else:
            unresolved.append((start, end, embedding, quality))
    clusters = []
    for name, items in grouped.items():
        if not items:
            continue
        embeddings = [item[2] for item in items]
        average = np.mean(np.stack(embeddings), axis=0)
        centroid = average / max(float(np.linalg.norm(average)), 1e-8)
        clusters.append({
            "centroid": centroid,
            "embeddings": embeddings,
            "intervals": [(item[0], item[1]) for item in items],
            "qualities": [item[3] for item in items],
            "review_scores": [item[3] + max(0.0, item[5]) for item in items],
            "profile_name": name,
            "profile_score": float(np.median([item[4] for item in items])),
        })
    clusters.extend(_acoustic_clusters(unresolved))
    return sorted(clusters, key=lambda cluster: min(start for start, _end in cluster["intervals"]))


def _cluster_observations(observations: list[tuple[float, float, np.ndarray, float]], store: SpeakerProfileStore | None = None, expected_speakers: list[str] | None = None, excluded_sources: list[str | Path] | None = None) -> list[dict]:
    if store is not None:
        guided = _profile_guided_clusters(observations, store, expected_speakers, excluded_sources)
        if guided is not None:
            return guided
    return _acoustic_clusters(observations)


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


def analyze_speakers(samples: np.ndarray, rate: int, cancel=None, log=None, progress=None, expected_speakers: list[str] | None = None, source: str | Path | None = None) -> SpeakerAnalysis:
    cancel = cancel or _NeverCancel()
    log = log or (lambda _: None)
    progress = progress or (lambda _: None)
    if rate != 16000:
        raise ValueError("Speaker analysis expects decoded 16 kHz audio")
    ranges = _sample_ranges(_voice_intervals(samples, rate))
    if not ranges:
        return SpeakerAnalysis([], [])
    encoder = _load_encoder()
    observations: list[tuple[float, float, np.ndarray, float]] = []
    for index, (start, end) in enumerate(ranges):
        if cancel.is_set():
            raise InterruptedError("Speaker analysis cancelled")
        quality = _interval_quality(samples, rate, start, end)
        if quality < MIN_REVIEW_QUALITY:
            log(f"Skipped a quiet or low-quality voice interval at {start:.2f}s-{end:.2f}s")
            progress((index + 1) / len(ranges))
            continue
        waveform = samples[int(start * rate):int(end * rate)]
        embedding = np.asarray(encoder.embed_utterance(waveform), dtype=np.float32)
        if embedding.size == 0:
            continue
        observations.append((start, end, embedding, quality))
        progress((index + 1) / len(ranges))
    store = SpeakerProfileStore()
    excluded_sources = [source] if source else None
    clusters = _cluster_observations(observations, store, expected_speakers, excluded_sources)
    output: list[SpeakerCluster] = []
    interval_labels: list[tuple[float, float, str]] = []
    for number, cluster in enumerate(clusters, start=1):
        identifier = f"SPEAKER_{number:02d}"
        items = sorted(zip(cluster["intervals"], cluster["embeddings"], cluster["qualities"], cluster["review_scores"]), key=lambda item: item[0])
        intervals = [item[0] for item in items]
        embeddings = [item[1] for item in items]
        quality_values = [item[2] for item in items]
        ranked = sorted(items, key=lambda item: item[3], reverse=True)[:3]
        samples_for_review = [item[0] for item in ranked]
        sample_embeddings = [item[1].astype(float).tolist() for item in ranked]
        vector = cluster["centroid"].astype(float).tolist()
        if cluster.get("profile_name"):
            suggested, score = cluster["profile_name"], cluster.get("profile_score")
        else:
            suggested, score, _margin = store.best_match_with_margin(vector, allowed_names=expected_speakers, minimum_margin=PROFILE_MATCH_MARGIN, excluded_sources=excluded_sources)
        training = [item.astype(float).tolist() for item in embeddings]
        training_qualities = quality_values
        output.append(SpeakerCluster(identifier, vector, intervals, samples_for_review, suggested, score, sample_embeddings, training, training_qualities))
        interval_labels.extend((start, end, identifier) for start, end in intervals)
        log(f"Detected {identifier} with {len(intervals)} voice samples")
    return SpeakerAnalysis(output, sorted(interval_labels))


def save_confirmed_profiles(analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None, metadata: dict | None = None, learn: dict[str, bool] | None = None) -> SpeakerProfileStore:
    store = store or SpeakerProfileStore()
    for cluster in analysis.clusters:
        name = " ".join(names.get(cluster.identifier, "").strip().split())
        if name and not (learn is not None and learn.get(cluster.identifier, True) is False):
            # A cluster label confirms the clips the user heard and kept, not
            # every hidden window assigned to that cluster. Enrolling only the
            # reviewed clips prevents a mixed cluster from poisoning a profile.
            embeddings = cluster.sample_embeddings or ([cluster.embedding] if cluster.samples and cluster.embedding else [])
            for index, embedding in enumerate(embeddings):
                details = dict(metadata or {})
                details["reviewed"] = True
                details["cluster_id"] = cluster.identifier
                if cluster.training_embeddings and cluster.training_qualities:
                    nearest = max(range(len(cluster.training_embeddings)), key=lambda item: cosine_similarity(embedding, cluster.training_embeddings[item]))
                    if nearest < len(cluster.training_qualities):
                        details["quality"] = cluster.training_qualities[nearest]
                if index < len(cluster.samples):
                    start, end = cluster.samples[index]
                    details["start"] = start
                    details["end"] = end
                    details["duration"] = max(0.0, end - start)
                store.add_confirmed_embedding(name, embedding, metadata=details)
    if names:
        store.rebuild_active_indices()
        store.save()
    return store


def refine_unresolved_clusters(analysis: SpeakerAnalysis, names: dict[str, str], store: SpeakerProfileStore | None = None, expected_speakers: list[str] | None = None) -> tuple[dict[str, str], list[SpeakerCluster], SpeakerProfileStore]:
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
        suggested, score, margin = store.best_match_with_margin(cluster.embedding, threshold=0.0, allowed_names=expected_speakers, minimum_margin=PROFILE_MATCH_MARGIN)
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
