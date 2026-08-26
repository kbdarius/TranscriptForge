"""One-shot recording-folder scan used by Windows Task Scheduler."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .media import SUPPORTED_EXTENSIONS
from .settings import RecordingHistory


def find_new_recording(folder: Path, history: RecordingHistory | None = None, minimum_age_minutes: int = 2) -> Path | None:
    if not folder.is_dir():
        return None
    history = history or RecordingHistory()
    cutoff = datetime.now().timestamp() - minimum_age_minutes * 60
    baseline = history.latest_completed_source_mtime()
    candidates = []
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                modified = path.stat().st_mtime
                if modified <= cutoff and (baseline is None or modified > baseline) and not history.has_completed(path):
                    candidates.append(path)
            except OSError:
                continue
    return min(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def scan_and_launch(folder: Path, python_executable: str | None = None) -> int:
    history = RecordingHistory()
    if not folder.is_dir():
        _launch_gui(["--prompt-recording-folder"] , python_executable)
        return 0
    source = find_new_recording(folder, history)
    if source is None:
        return 0
    history.update(source, "pending")
    _launch_gui(["--input", str(source), "--auto-start", "--identify-speakers", "--recording-folder", str(folder)], python_executable)
    return 0


def _launch_gui(arguments: list[str], python_executable: str | None = None) -> None:
    executable = python_executable or sys.executable
    if executable.lower().endswith("python.exe"):
        candidate = str(Path(executable).with_name("pythonw.exe"))
        if Path(candidate).is_file():
            executable = candidate
    subprocess.Popen([executable, "-m", "transcriptforge", *arguments], close_fds=True)
