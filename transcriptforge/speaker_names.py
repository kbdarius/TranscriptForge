"""Helpers for searchable speaker-name choices in review dialogs."""

import re
from difflib import SequenceMatcher


_NAME_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_speaker_name(name: str) -> str:
    """Return a punctuation-insensitive, case-folded form for name comparisons."""
    return " ".join(_NAME_TOKEN.findall(str(name).casefold()))


def speaker_name_similarity(left: str, right: str) -> float:
    left_tokens = normalize_speaker_name(left).split()
    right_tokens = normalize_speaker_name(right).split()
    if not left_tokens or not right_tokens:
        return 0.0
    if sorted(left_tokens) == sorted(right_tokens):
        return 1.0

    left_text = " ".join(left_tokens)
    right_text = " ".join(right_tokens)
    score = max(
        SequenceMatcher(None, left_text, right_text).ratio(),
        SequenceMatcher(None, sorted(left_tokens), sorted(right_tokens)).ratio(),
    )
    if len(left_tokens) >= 2 and len(right_tokens) >= 2 and left_tokens[-1] == right_tokens[-1]:
        left_first, right_first = left_tokens[0], right_tokens[0]
        if left_first.startswith(right_first) or right_first.startswith(left_first):
            score = max(score, 0.9 if min(len(left_first), len(right_first)) > 1 else 0.82)
        else:
            first_score = SequenceMatcher(None, left_first, right_first).ratio()
            if first_score >= 0.7:
                score = max(score, 0.65 + 0.25 * first_score)
            elif left_first[0] == right_first[0]:
                score = max(score, 0.74)
    return min(1.0, score)


def similar_speaker_names(
    name: str, candidates: list[str], threshold: float = 0.72
) -> list[tuple[str, float]]:
    matches = []
    clean_name = " ".join(str(name).split())
    for candidate in candidates:
        if " ".join(str(candidate).split()) == clean_name:
            continue
        score = speaker_name_similarity(name, candidate)
        if score >= threshold:
            matches.append((candidate, score))
    return sorted(matches, key=lambda item: (-item[1], item[0].casefold()))


def speaker_name_choices(names: list[str], recent_names: list[str] | None = None) -> list[str]:
    """Put names selected in this review first, then sort the remaining names."""
    canonical: dict[str, str] = {}
    for name in names:
        clean = " ".join(str(name).split())
        if clean and clean.casefold() != "unknown":
            canonical.setdefault(clean.casefold(), clean)

    recent: list[str] = []
    seen: set[str] = set()
    for name in recent_names or []:
        clean = " ".join(str(name).split())
        key = clean.casefold()
        if clean and key != "unknown" and key not in seen:
            recent.append(canonical.setdefault(key, clean))
            seen.add(key)

    remaining = sorted(
        (name for key, name in canonical.items() if key not in seen),
        key=str.casefold,
    )
    return ["", *recent, *remaining, "Unknown"]


def filter_speaker_name_choices(
    names: list[str], query: str, recent_names: list[str] | None = None
) -> list[str]:
    """Filter choices by case-insensitive substring while preserving recent order."""
    choices = speaker_name_choices(names, recent_names)
    normalized_query = " ".join(str(query).split()).casefold()
    if not normalized_query:
        return choices
    return [
        choice
        for choice in choices
        if choice and normalized_query in choice.casefold()
    ]


def speaker_name_suggestions(
    names: list[str], query: str, recent_names: list[str] | None = None, limit: int = 3
) -> list[str]:
    """Return the small visible type-ahead list used by the review UI."""
    return filter_speaker_name_choices(names, query, recent_names)[:max(1, limit)]
