# TranscriptForge agent instructions

## Versioning

- The single source of truth for the application version is `transcriptforge/version.py`.
- Every code change must bump `__version__` before the change is considered complete.
- Use patch increments for fixes and small improvements, minor increments for new backward-compatible features, and major increments for breaking changes.
- Include the version bump in the same task change and commit as its code change; never publish changed code without its corresponding version bump.
- Keep the version visible in the main Tkinter window title as `TranscriptForge v<version>`.

## Verification

- Run `py -3 -m compileall -q transcriptforge tests`.
- Run `py -3 -m unittest discover -s tests -v`.
- Update `README.md` when user-visible behavior, dependencies, storage, or workflows change.
- Do not commit generated recordings, decoded WAV files, models, voice profiles, or temporary output.

## GitHub publishing

- The user requires every code change and its matching version bump to be committed and pushed to GitHub after verification. Treat this as standing authorization to publish task-related repository changes unless the user opts out for a task.
- Stage only files belonging to the current task. Do not include unrelated or pre-existing user changes, generated files, or user-supplied assets.
- Follow the repository's commit-message convention and include the required `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer.
- Never amend an existing commit, force-push, or skip hooks or signing. If the upstream is unavailable, the push is rejected, or a conflict or repository policy blocks publishing, stop and report the blocker without claiming success.
- After pushing, verify that the task commit is on the configured GitHub upstream and report its commit hash.

## Project context

- Use `TRANSCRIPTFORGE_CONTEXT_v1.1.1.yaml` as the current versioned project context map.
- Update the context file in the same change whenever adding a feature or changing an existing feature or user-facing workflow.
- Bump the context file's semantic version for context updates and update this reference in the same change whenever its versioned filename changes.
- Sanitize the desktop GUI's generated and user-entered output filename field before creating a file. Replace `/` and other Windows-invalid filename characters with `-`; do not alter directory paths.
