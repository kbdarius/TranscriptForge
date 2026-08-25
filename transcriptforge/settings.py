"""Small local settings stores for the desktop application."""

from __future__ import annotations

import json
import os
import tempfile
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

