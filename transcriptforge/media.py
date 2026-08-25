import subprocess
import tempfile
import wave
from pathlib import Path

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".mp4", ".mov", ".mkv"}

def ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError("imageio-ffmpeg is required to decode media") from exc

def decode_to_wav(source: Path, work_dir: Path) -> Path:
    target = work_dir / "decoded.wav"
    command = [ffmpeg_executable(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "unknown FFmpeg error"
        raise RuntimeError(f"Could not decode source media: {detail}")
    if not target.exists() or target.stat().st_size < 44:
        raise RuntimeError("The source contains no usable audio stream")
    with wave.open(str(target), "rb") as wav:
        if wav.getnframes() == 0:
            raise RuntimeError("The source contains no audio frames")
    return target

def temporary_work_dir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="transcriptforge-")

