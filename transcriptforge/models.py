from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class Segment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    temperature: float | None = None
    source_window: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

@dataclass(frozen=True)
class SuspectRange:
    start: float
    end: float
    reason: str

@dataclass
class ProcessingStats:
    retries: int = 0
    omitted: int = 0
    warnings: list[str] = field(default_factory=list)

@dataclass
class TranscriptionResult:
    segments: list[Segment]
    duration: float
    stats: ProcessingStats
    model_cache: Path
