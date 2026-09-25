"""Portable TranscriptForge configuration packages."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path

from .settings import FilenameTemplateSettings, PreferencesSettings, SampleRejectionStore, settings_dir
from .speakers import SpeakerProfileStore

PACKAGE_VERSION = 1
_MANIFEST = "manifest.json"
_PREFERENCES = "preferences.json"
_TEMPLATES = "filename-templates.json"
_PROFILES = "speaker-profiles.json"
_REJECTIONS = "speaker-sample-rejections.json"


def _read_json(zipped: zipfile.ZipFile, member: str, default):
    try:
        value = json.loads(zipped.read(member).decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return default
    return value


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def export_configuration(path: Path, preferences: dict, filename_templates: list[str], profile_store: SpeakerProfileStore | None = None, rejection_store: SampleRejectionStore | None = None) -> Path:
    """Write a portable package without machine-specific paths or histories."""
    profiles = profile_store or SpeakerProfileStore()
    rejections = rejection_store or SampleRejectionStore()
    manifest = {
        "format": "TranscriptForge configuration",
        "version": PACKAGE_VERSION,
        "includes": ["preferences", "filename_templates", "speaker_profiles", "speaker_sample_rejections"],
        "excludes": ["recording_folder", "output_location_history", "meeting_output_settings", "recording_history", "whisper_models", "audio", "transcripts"],
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        package.writestr(_PREFERENCES, json.dumps(preferences, ensure_ascii=False, indent=2) + "\n")
        package.writestr(_TEMPLATES, json.dumps(list(filename_templates), ensure_ascii=False, indent=2) + "\n")
        package.writestr(_PROFILES, profiles.path.read_text(encoding="utf-8") if profiles.path.is_file() else "{}\n")
        package.writestr(_REJECTIONS, rejections.path.read_text(encoding="utf-8") if rejections.path.is_file() else "[]\n")
    return path


def import_configuration(path: Path, target_dir: Path | None = None) -> dict:
    """Import portable settings and merge speaker data into this PC's stores."""
    target = target_dir or settings_dir()
    with zipfile.ZipFile(path, "r") as package:
        manifest = _read_json(package, _MANIFEST, {})
        if manifest.get("format") != "TranscriptForge configuration" or manifest.get("version") != PACKAGE_VERSION:
            raise ValueError("This is not a supported TranscriptForge configuration package.")
        preferences = _read_json(package, _PREFERENCES, {})
        templates = _read_json(package, _TEMPLATES, [])
        profile_payload = _read_json(package, _PROFILES, {})
        rejection_payload = _read_json(package, _REJECTIONS, [])

    if not isinstance(preferences, dict):
        preferences = {}
    if preferences:
        PreferencesSettings(target / "preferences.json").save(preferences)
    if not isinstance(templates, list):
        templates = []
    template_store = FilenameTemplateSettings(target / "filename-templates.json")
    for name in reversed([value for value in templates if isinstance(value, str)]):
        template_store.remember(name)

    profile_store = SpeakerProfileStore(target / "speaker-profiles.json")
    imported_profiles = 0
    if isinstance(profile_payload, dict):
        profile_store.import_name_decisions(
            profile_payload.get("name_aliases", {}),
            profile_payload.get("rejected_name_matches", []),
        )
        source_profiles = profile_payload.get("profiles", {})
        source_metadata = profile_payload.get("embedding_metadata", {})
        if isinstance(source_profiles, dict):
            for name, vectors in source_profiles.items():
                if not isinstance(name, str) or not isinstance(vectors, list):
                    continue
                metadata = source_metadata.get(name, []) if isinstance(source_metadata, dict) else []
                for index, vector in enumerate(vectors):
                    if not isinstance(vector, list):
                        continue
                    details = metadata[index] if isinstance(metadata, list) and index < len(metadata) and isinstance(metadata[index], dict) else {}
                    if profile_store.add_confirmed_embedding(name, vector, metadata=details):
                        imported_profiles += 1
    if imported_profiles:
        profile_store.save()

    rejection_store = SampleRejectionStore(target / "speaker-sample-rejections.json")
    existing = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in rejection_store.records}
    imported_rejections = 0
    if isinstance(rejection_payload, list):
        for item in rejection_payload:
            if isinstance(item, dict):
                marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if marker not in existing:
                    rejection_store.records.append(item); existing.add(marker); imported_rejections += 1
    if imported_rejections:
        _write_json(rejection_store.path, rejection_store.records)
    return {"preferences": preferences, "templates": len([value for value in templates if isinstance(value, str)]), "profiles": imported_profiles, "rejections": imported_rejections}
