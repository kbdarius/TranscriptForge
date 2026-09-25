# TranscriptForge agent instructions

## Versioning

- The single source of truth for the application version is `transcriptforge/version.py`.
- Every code change must bump `__version__` before the change is considered complete.
- Use patch increments for fixes and small improvements, minor increments for new backward-compatible features, and major increments for breaking changes.
- Keep the version visible in the main Tkinter window title as `TranscriptForge v<version>`.

## Verification

- Run `py -3 -m compileall -q transcriptforge tests`.
- Run `py -3 -m unittest discover -s tests -v`.
- Update `README.md` when user-visible behavior, dependencies, storage, or workflows change.
- Do not commit generated recordings, decoded WAV files, models, voice profiles, or temporary output.

## Project context

- Keep `TRANSCRIPTFORGE_CONTEXT.md` aligned with the current architecture, features, and workflows.
- Update the context file in the same change whenever adding a feature or changing an existing feature or user-facing workflow.
