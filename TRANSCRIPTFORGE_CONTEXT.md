# TranscriptForge project context

Last reviewed for TranscriptForge v0.25.0.

## Purpose and architecture

TranscriptForge is a local-first Windows desktop application that turns audio and video recordings into timestamped Markdown transcripts. The GUI uses Tkinter, Whisper runs locally, FFmpeg decodes media locally, and speaker embeddings are stored on the user's PC. Audio, voice profiles, and transcripts are not uploaded by the application.

The main workflow is coordinated by `transcriptforge/app.py` and `transcriptforge/controller.py`. `transcriptforge/outlook_calendar.py` reads the default Outlook Classic calendar through the local Outlook COM interface. `transcriptforge/speakers.py` handles local voice analysis, clustering, matching, profile storage, and confirmed-speaker learning. `transcriptforge/speaker_names.py` provides name matching and speaker-name dropdown helpers.

## Meeting-aware speaker workflow

- The scheduled-recording prompt provides an optional Outlook meeting selector. Its default is **No meeting selected - use current workflow**. Leaving it selected preserves the existing speaker preferences and does not apply a calendar roster.
- When a meeting is selected, Outlook appointments are queried for the recording date. TranscriptForge reads a timestamp in the recording filename when available and otherwise uses the file's modified time.
- The selected meeting's organizer and invitees are used as a per-recording shortlist. The shortlist does not replace the user's general Expected speakers preference. Selecting a meeting enables speaker identification for that recording.
- Only saved profiles for roster names are candidates for automatic speaker naming. Voices without a matching profile, guests, and uncertain clusters remain reviewable. Users can type a guest's name or choose Unknown.
- Similar Outlook and saved-profile names require user confirmation. A confirmed identity merges profile embeddings under Outlook's spelling and stores the previous spelling as an alias. A declined match is remembered so it is not repeatedly suggested.
- The invitee count is an editable soft speaker limit in the scheduled-recording prompt. Strong profile matches and better-supported voice groups are prioritized. Extra distinct groups remain in the review window and are not merged or discarded just to satisfy the limit.
- Meeting-name aliases and declined name matches are saved with `speaker-profiles.json` and included in portable configuration transfers. Deleting a speaker profile also removes its associated name decisions.

## Speaker-identification behavior

Speaker identification is local and optional unless a meeting or speaker limit is selected for a recording. Known profiles can help group samples from recurring speakers. The invite list contains names, not voiceprints, so a person without a previously confirmed profile still requires user review before the app can learn that voice.

The review UI uses roster names as suggestions for a meeting-selected job and permits manual guest names. Confirmed profile learning uses only representative samples the user kept. Uncertain samples should remain unknown rather than being force-assigned.

## Versioning and verification

- `transcriptforge/version.py` is the single source of truth for the application version.
- Every code change increments the version: patch for fixes, minor for backward-compatible features, and major for breaking changes.
- The main Tkinter title displays `TranscriptForge v<version>`.
- Run `py -3 -m compileall -q transcriptforge tests` and `py -3 -m unittest discover -s tests -v` after code changes.
- Update `README.md` for user-visible behavior, dependencies, storage, or workflow changes.
- Update this context file in the same change whenever a feature or user-facing workflow is added or changed.
- Do not commit generated recordings, decoded WAV files, models, voice profiles, or temporary output.
