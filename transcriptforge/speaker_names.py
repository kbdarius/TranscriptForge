"""Helpers for searchable speaker-name choices in review dialogs."""


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
