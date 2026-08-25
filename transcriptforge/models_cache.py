import os
from pathlib import Path

MODEL_NAMES = ("tiny.en", "base.en", "small.en")

def cache_dir() -> Path:
    root = Path(__import__("os").environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / "LocalAudioTranscriber" / "whisper-models"; path.mkdir(parents=True, exist_ok=True); return path

def search_dirs(cache: Path | None = None) -> list[Path]:
    """Return app and standard Whisper cache locations, without duplicates."""
    locations = [cache or cache_dir()]
    standard = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"
    locations.append(standard)
    result = []
    for location in locations:
        if location not in result:
            result.append(location)
    return result

def find_model_cache(name: str, cache: Path | None = None) -> Path | None:
    filename = f"{name}.pt"
    for location in search_dirs(cache):
        if (location / filename).is_file():
            return location
    return None

def model_available(name: str, cache: Path | None = None) -> bool:
    return find_model_cache(name, cache) is not None

def load_model(name: str, cache: Path | None = None):
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("openai-whisper is not installed") from exc
    source_cache = find_model_cache(name, cache)
    if source_cache is None:
        raise RuntimeError(f"Model {name} is not cached. Use Download model first.")
    return whisper.load_model(name, download_root=str(source_cache), device="cpu")

def download_model(name: str, cache: Path | None = None):
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("openai-whisper is not installed") from exc
    return whisper.load_model(name, download_root=str(cache or cache_dir()), device="cpu")
