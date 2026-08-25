import os
import tempfile
from datetime import datetime
from pathlib import Path

from .models import Segment, ProcessingStats

def timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds); whole = int(seconds); fraction = int(round((seconds - whole) * 100))
    if fraction == 100: whole += 1; fraction = 0
    h, whole = divmod(whole, 3600); m, s = divmod(whole, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{fraction:02d}"

def render_markdown(source: Path, model: str, language: str, duration: float, segments: list[Segment], stats: ProcessingStats, cache: Path, include_timestamps: bool = True) -> str:
    lines = [f"# Transcript: {source.name}", "", f"**Generated:** {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}  ", f"**Source:** `{source}`  ", f"**Model:** `{model}`  ", f"**Language:** `{language}`  ", f"**Duration:** `{timestamp(duration)}`", "", "## Transcript", ""]
    lines.extend((f"[{timestamp(s.start)} - {timestamp(s.end)}] " if include_timestamps else "") + (f"{s.speaker}: " if s.speaker else "") + s.text.strip() for s in segments if s.text.strip())
    lines += ["", "## Processing Notes", "", f"- Windows retried for suspected repeated output: `{stats.retries}`.", f"- Unclear or silent intervals omitted after retry: `{stats.omitted}`.", f"- Model cache: `{cache}`."]
    if any(segment.speaker for segment in segments):
        lines.append("- Speaker labels were assigned locally from user-confirmed voice profiles.")
    if stats.warnings:
        lines.append("- Warnings: " + "; ".join(stats.warnings))
    return "\n".join(lines) + "\n"

def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try: os.unlink(temp_name)
        except OSError: pass
        raise
