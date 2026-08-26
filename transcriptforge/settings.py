"""Small local settings stores for the desktop application."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MAX_OUTPUT_LOCATIONS = 5


def settings_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / "LocalAudioTranscriber"
    path.mkdir(parents=True, exist_ok=True)
    return path


class OutputLocationHistory:
    def __init__(self, path: Path | None = None):
        self.path = path or settings_dir() / "output-locations.json"
        self.locations: list[str] = []
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(values, list):
                self.locations = [str(value) for value in values if isinstance(value, str)][:MAX_OUTPUT_LOCATIONS]
        except (OSError, ValueError, TypeError):
            self.locations = []

    def remember(self, location: Path | str) -> None:
        value = str(Path(location).expanduser())
        normalized = os.path.normcase(os.path.abspath(value))
        self.locations = [item for item in self.locations if os.path.normcase(os.path.abspath(item)) != normalized]
        self.locations.insert(0, value)
        self.locations = self.locations[:MAX_OUTPUT_LOCATIONS]
        self.save()

    def save(self) -> None:
        fd, temporary = tempfile.mkstemp(prefix="output-locations-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.locations[:MAX_OUTPUT_LOCATIONS], handle, ensure_ascii=False, indent=2)
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


class RecordingFolderSettings:
    """Persist the user's recording folder independently on each PC."""

    def __init__(self, path: Path | None = None):
        self.path = path or settings_dir() / "recording-folder.json"
        self.folder: str | None = None
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("folder"), str):
                self.folder = value["folder"]
        except (OSError, ValueError, TypeError):
            self.folder = None

    def set(self, folder: Path | str) -> None:
        self.folder = str(Path(folder).expanduser().resolve())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="recording-folder-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"folder": self.folder}, handle, ensure_ascii=False, indent=2)
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


class RecordingHistory:
    """A small local ledger used by the scheduled recording scan."""

    def __init__(self, path: Path | None = None):
        self.path = path or settings_dir() / "recording-history.json"
        self.records: list[dict] = []
        self.load()

    @staticmethod
    def fingerprint(source: Path) -> str:
        stat = source.stat()
        return f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, list):
                self.records = [item for item in value if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            self.records = []

    def has_completed(self, source: Path) -> bool:
        try:
            key = self.fingerprint(source)
        except OSError:
            return False
        return any(item.get("fingerprint") == key and item.get("status") in {"pending", "completed"} for item in self.records)

    def latest_completed_source_mtime(self) -> float | None:
        values = [item.get("source_mtime") for item in self.records if item.get("status") == "completed" and isinstance(item.get("source_mtime"), (int, float))]
        return max(values) if values else None

    def update(self, source: Path, status: str, output: Path | None = None, final_media: Path | None = None) -> None:
        key = self.fingerprint(source) if source.exists() else str(source.resolve())
        record = next((item for item in self.records if item.get("fingerprint") == key), None)
        if record is None:
            record = {"fingerprint": key, "original_path": str(source.resolve())}
            self.records.append(record)
        record["status"] = status
        if source.exists():
            record["source_mtime"] = source.stat().st_mtime
        if output is not None:
            record["output_path"] = str(output.resolve())
        if final_media is not None:
            record["final_path"] = str(final_media.resolve())
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="recording-history-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.records, handle, ensure_ascii=False, indent=2)
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


def recording_history_path() -> Path:
    return settings_dir() / "recording-history.json"
