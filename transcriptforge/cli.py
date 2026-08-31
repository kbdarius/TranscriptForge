"""Command-line interface for automation and human review handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .audio import read_wav
from .media import SUPPORTED_EXTENSIONS, decode_to_wav, temporary_work_dir
from .models_cache import MODEL_NAMES, cache_dir, download_model, load_model, model_available
from .output import atomic_write, render_markdown
from .settings import OutputLocationHistory, settings_dir
from .speakers import SpeakerProfileStore, analyze_speakers, apply_speaker_names, fill_unknown_speakers_from_neighbors, refine_unresolved_clusters, save_confirmed_profiles, write_review_samples
from .transcription import transcribe_samples
from .version import __version__

REVIEW_REQUIRED = 2


def _emit(json_events: bool, event: str, **values) -> None:
    payload = {"event": event, **values}
    if json_events:
        print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
    else:
        message = values.get("message") or values.get("path") or ""
        print(f"[{event}] {message}", flush=True)


def _review_names(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("names"), dict):
        names = {str(key): str(value) for key, value in payload["names"].items()}
        for item in payload.get("clusters", []):
            if item.get("id") and item.get("name") is not None:
                names[str(item["id"])] = str(item["name"])
        return names
    if isinstance(payload, dict) and isinstance(payload.get("clusters"), list):
        return {str(item["id"]): str(item.get("name", "")) for item in payload["clusters"] if item.get("id")}
    if isinstance(payload, dict):
        return {str(key): str(value) for key, value in payload.items()}
    raise ValueError("Speaker review must contain a names object or cluster name fields")


def _review_path(args, output: Path) -> Path:
    return Path(args.review_out or args.speaker_review) if args.review_out or args.speaker_review else output.with_suffix(".speaker-review.json")


def _pending_dir(source: Path) -> Path:
    digest = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
    return settings_dir() / "pending-speaker-review" / digest


def _write_review(path: Path, source: Path, clusters, names: dict[str, str], existing_names: list[str], sample_files: dict[str, list[str]]) -> None:
    payload = {
        "version": 1,
        "source": str(source.resolve()),
        "created": datetime.now(timezone.utc).isoformat(),
        "instructions": "Edit the names values, then rerun the same CLI command. Leave a value blank or use Unknown when unresolved.",
        "existing_names": existing_names,
        "names": names,
        "clusters": [
            {
                "id": cluster.identifier,
                "name": names.get(cluster.identifier, cluster.suggested_name or ""),
                "suggestion": cluster.suggested_name,
                "confidence": cluster.suggestion_score,
                "samples": [{"start": start, "end": end} for start, end in cluster.samples],
                "sample_files": sample_files.get(cluster.identifier, []),
            }
            for cluster in clusters
        ],
    }
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _transcribe(args) -> int:
    source = Path(args.input).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Input must be an existing supported audio or video file")
    output = Path(args.output).expanduser().resolve() if args.output else source.with_suffix(".md")
    if output.resolve() == source.resolve():
        raise ValueError("Output must not be the same path as the input")
    if output.exists() and not args.force:
        raise ValueError(f"Output exists; pass --force to overwrite: {output}")
    if not model_available(args.model):
        raise ValueError(f"Model {args.model} is not cached; download it in the GUI or run: python -m transcriptforge.cli models download {args.model}")
    _emit(args.json_events, "started", version=__version__, path=str(source))
    review_dir = _pending_dir(source)
    try:
        with temporary_work_dir() as temporary:
            wav = decode_to_wav(source, Path(temporary)); samples, rate = read_wav(wav)
            analysis = None; names = {}
            if args.speakers:
                _emit(args.json_events, "stage", message="Analyzing speaker voices")
                analysis = analyze_speakers(samples, rate, log=lambda message: _emit(args.json_events, "log", message=message), progress=lambda value: _emit(args.json_events, "speaker_progress", value=value))
                if analysis.clusters:
                    profile_store = SpeakerProfileStore()
                    review_file = Path(args.speaker_review) if args.speaker_review else None
                    if review_file:
                        names = _review_names(review_file)
                    elif not args.accept_suggestions:
                        sample_files = write_review_samples(wav, analysis.clusters, review_dir)
                        review_path = _review_path(args, output); _write_review(review_path, source, analysis.clusters, {}, sorted(profile_store.profiles), sample_files)
                        _emit(args.json_events, "review_required", path=str(review_path), message="Edit the review JSON names and rerun")
                        return REVIEW_REQUIRED
                    if not names and args.accept_suggestions:
                        names = {cluster.identifier: cluster.suggested_name or "" for cluster in analysis.clusters}
                    profile_store = save_confirmed_profiles(analysis, names, profile_store, {"source": str(source)})
                    final_names, unresolved, profile_store = refine_unresolved_clusters(analysis, names, profile_store)
                    if unresolved and not args.accept_suggestions:
                        sample_files = write_review_samples(wav, unresolved, review_dir)
                        review_path = _review_path(args, output); _write_review(review_path, source, unresolved, final_names, sorted(profile_store.profiles), sample_files)
                        _emit(args.json_events, "review_required", path=str(review_path), unresolved=len(unresolved), message="Edit the remaining names and rerun")
                        return REVIEW_REQUIRED
                    names = final_names
                else:
                    _emit(args.json_events, "log", message="No distinct voice samples found")
            _emit(args.json_events, "stage", message="Loading local Whisper model")
            model = load_model(args.model, cache_dir())
            segments, stats = transcribe_samples(samples, rate, model, args.language, log=lambda message: _emit(args.json_events, "log", message=message), progress=lambda value: _emit(args.json_events, "progress", value=value))
            if analysis and analysis.clusters:
                apply_speaker_names(segments, analysis, names, save_profiles=False)
                inferred = fill_unknown_speakers_from_neighbors(segments)
                if inferred:
                    _emit(args.json_events, "log", message=f"Filled {inferred} short Unknown segment(s) from matching neighboring speakers.")
            atomic_write(output, render_markdown(source, args.model, args.language, len(samples) / rate, segments, stats, cache_dir(), not args.no_timestamps))
        OutputLocationHistory().remember(output.parent)
        if review_dir.exists():
            shutil.rmtree(review_dir)
        _emit(args.json_events, "completed", path=str(output))
        return 0
    except KeyboardInterrupt:
        _emit(args.json_events, "cancelled", message="Cancelled")
        return 130


def _models(args) -> int:
    if args.models_action == "list":
        for model in MODEL_NAMES:
            _emit(args.json_events, "model", name=model, available=model_available(model))
        return 0
    download_model(args.name)
    _emit(args.json_events, "completed", message=f"Model {args.name} is ready")
    return 0


def _profiles(args) -> int:
    from .speakers import SpeakerProfileStore
    store = SpeakerProfileStore()
    if args.profiles_action == "path":
        _emit(args.json_events, "profile_path", path=str(store.path)); return 0
    if args.profiles_action == "list":
        for name, vectors in sorted(store.profiles.items()): _emit(args.json_events, "profile", name=name, samples=len(vectors))
        return 0
    if args.name not in store.profiles:
        raise ValueError(f"Profile not found: {args.name}")
    del store.profiles[args.name]; store.save(); _emit(args.json_events, "completed", message=f"Deleted profile {args.name}"); return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m transcriptforge.cli", description="Local TranscriptForge command-line automation")
    parser.add_argument("--json-events", action="store_true", help="Emit newline-delimited JSON events for automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    transcribe = subparsers.add_parser("transcribe", help="Transcribe a local media file")
    transcribe.add_argument("input"); transcribe.add_argument("--output"); transcribe.add_argument("--model", choices=MODEL_NAMES, default="small.en"); transcribe.add_argument("--language", default="en"); transcribe.add_argument("--force", action="store_true"); transcribe.add_argument("--speakers", action="store_true"); transcribe.add_argument("--speaker-review", help="JSON review/map file from a previous run"); transcribe.add_argument("--review-out", help="Path for a generated speaker review JSON"); transcribe.add_argument("--accept-suggestions", action="store_true", help="Accept confident profile suggestions without a review checkpoint"); transcribe.add_argument("--no-timestamps", action="store_true")
    models = subparsers.add_parser("models", help="Inspect or download Whisper models"); models_sub = models.add_subparsers(dest="models_action", required=True); models_sub.add_parser("list"); download = models_sub.add_parser("download"); download.add_argument("name", choices=MODEL_NAMES)
    profiles = subparsers.add_parser("profiles", help="Inspect or manage local speaker profiles"); profiles_sub = profiles.add_subparsers(dest="profiles_action", required=True); profiles_sub.add_parser("list"); profiles_sub.add_parser("path"); remove = profiles_sub.add_parser("remove"); remove.add_argument("name")
    return parser


def main(argv=None) -> int:
    parser = build_parser(); args = parser.parse_args(argv)
    try:
        if args.command == "transcribe": return _transcribe(args)
        if args.command == "models": return _models(args)
        return _profiles(args)
    except Exception as exc:
        _emit(args.json_events, "error", message=str(exc)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
