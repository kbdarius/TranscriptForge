# TranscriptForge

TranscriptForge is a local-first Windows desktop application for turning an audio or video file into a timestamped Markdown transcript. Audio is decoded locally with the FFmpeg executable supplied by `imageio-ffmpeg`, then passed to local Whisper as NumPy samples. No audio or transcript is uploaded.

Current version: `0.1.0`.

## Run

Install the dependencies in a CPU or GPU environment as appropriate:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m transcriptforge
```

The first use of a model requires a download. Models are cached under `%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models`. The GUI's **Download model** action is explicit; transcription only uses an already cached model.

Speaker identification is optional and local. Enable **Identify speakers locally** to analyze voice clusters, play representative samples, confirm names, and reuse confirmed speaker profiles in future recordings. The workflow has two review passes: the first captures obvious names, then confirmed profiles are used to resolve easy blanks and a shorter second dialog asks about the remaining uncertain voices before Whisper transcription starts. Existing names appear in editable dropdowns; users can type new names or choose `Unknown`.

Speaker data is kept under `%LOCALAPPDATA%\LocalAudioTranscriber\`:

```text
speaker-profiles.json       # names and confirmed voice embeddings
speaker-samples\            # reserved for optional future persistent samples
whisper-models\             # downloaded Whisper model files
```

The current release stores only multiple confirmed voice embeddings per person in `speaker-profiles.json`. The decoded WAV and playable review clips are temporary files under `%TEMP%\transcriptforge-*` and are deleted when processing ends. Raw voice samples are not uploaded or retained by default. Profile embeddings are sensitive biometric data; use **Manage profiles** to delete saved names and samples, or remove the local profile file when a complete reset is required. The first speaker-analysis run may download the Resemblyzer encoder weights.

The five most recently used output folders are stored locally in `%LOCALAPPDATA%\LocalAudioTranscriber\output-locations.json`. The **Output folder** field is an editable dropdown, so a prior location can be selected without browsing; **Browse** remains available for a new location.

Run the tests with:

```powershell
py -3 -m unittest discover -s tests -v
```

Supported input extensions: `.wav`, `.mp3`, `.m4a`, `.aac`, `.mp4`, `.mov`, and `.mkv`.
