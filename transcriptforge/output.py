import os
import shutil
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


def append_markdown_content(path: Path, provider: str, content: str) -> None:
    """Append manually supplied, attributed content to an existing transcript."""
    clean_provider = " ".join(provider.strip().split()) or "Unknown"
    clean_content = content.strip()
    if not clean_content:
        raise ValueError("Additional content cannot be empty")
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    separator = "\n" if existing.endswith("\n") else "\n\n"
    addition = f"## Additional content\n\n**Provided by:** {clean_provider}\n\n{clean_content}\n"
    atomic_write(path, existing + separator + addition)


def rename_media_to_match_output(source: Path, output: Path, overwrite: bool = False) -> Path:
    """Rename the source media in its original folder using the transcript stem."""
    source = source.resolve(); target = source.with_name(output.stem + source.suffix).resolve()
    if source == target:
        return source
    if target.exists():
        if not overwrite:
            raise FileExistsError(f"Media destination already exists: {target}")
        if target.is_dir():
            raise IsADirectoryError(f"Media destination is a directory: {target}")
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target
