# TranscriptForge

TranscriptForge is a local-first Windows desktop application for turning an audio or video file into a timestamped Markdown transcript. Audio is decoded locally with the FFmpeg executable supplied by `imageio-ffmpeg`, then passed to local Whisper as NumPy samples. No audio or transcript is uploaded.

Current version: `0.5.4`.

## Run

Install the dependencies in a CPU or GPU environment as appropriate:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m transcriptforge
```

The first use of a model requires a download. Models are cached under `%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models`. The GUI's **Download model** action is explicit; transcription only uses an already cached model.

The application remembers the recording folder for the current PC in `%LOCALAPPDATA%\LocalAudioTranscriber\recording-folder.json`. It starts with `C:\Users\dariusk\OneDrive - stryten.com\Recordings` when that default exists. If a saved folder is unavailable on another PC, TranscriptForge asks the user to choose a replacement folder at startup and stores that choice locally; no machine-specific path is shared with speaker profiles or the application code.

Speaker identification is optional and local. Enable **Identify speakers locally** to analyze voice clusters, play representative samples, confirm names, and reuse confirmed speaker profiles in future recordings. The workflow has two review passes: the first captures obvious names, then confirmed profiles are used to resolve easy blanks and a shorter second dialog asks about the remaining uncertain voices before Whisper transcription starts. Each sample has its own **X** button so mixed or poor clips can be removed before profile learning. Existing names appear in editable dropdowns; users can type new names or choose `Unknown`.

Speaker data is kept under `%LOCALAPPDATA%\LocalAudioTranscriber\`:

```text
speaker-profiles.json       # names and confirmed voice embeddings
speaker-samples\            # reserved for optional future persistent samples
whisper-models\             # downloaded Whisper model files
```

The current release stores only multiple confirmed voice embeddings per person in `speaker-profiles.json`. The decoded WAV and playable review clips are temporary files under `%TEMP%\transcriptforge-*` and are deleted when processing ends. Raw voice samples are not uploaded or retained by default. Profile embeddings are sensitive biometric data; use **Manage profiles** to delete saved names and samples, or remove the local profile file when a complete reset is required. The first speaker-analysis run may download the Resemblyzer encoder weights.

The five most recently used output folders are stored locally in `%LOCALAPPDATA%\LocalAudioTranscriber\output-locations.json`. The **Output folder** field is an editable dropdown, so a prior location can be selected without browsing; **Browse** remains available for a new location.

After a successful transcription, the default **Rename media to match output** option moves/renames the source media into the output folder before the Markdown is written and gives it the same base name as the Markdown file while preserving its original extension. This makes the Markdown title and source name match the final media filename. If the destination media name already exists, the GUI asks for confirmation before replacing it. Uncheck this option to leave the source media unchanged. After completion, **Transcribe** is disabled to prevent accidental reruns; use **New transcription** to clear the form and begin another job.

The main window keeps the core file, model, and transcription controls visible. Click the gear button (`⚙`) to open **TranscriptForge Setup** for optional settings such as speaker identification, timestamps, retaining the decoded WAV, opening the result automatically, language, and media renaming.

Setup also includes **View history**, which displays the locally stored transcription ledger with the recording filename prominently shown, status, update time, full paths, and horizontal scrolling for long locations. Select a row to see its paths, open the transcript, or open its output folder.

## Scheduled recording scan

`Install_TranscriptForgeTask.ps1` creates a Windows Task Scheduler task named **TranscriptForge - Check Recordings**. It checks the configured folder every 15 minutes while the user is logged in, exits quickly when there is no new stable media, and opens the normal GUI only when a recording needs review/transcription. A pending recording is not launched again while the GUI is handling it. The scanner uses the newest successful recording as a baseline, so older files are not unexpectedly picked up. It does not keep a watcher process or audio-processing process running between checks.

Run the installer from PowerShell in the project root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Install_TranscriptForgeTask.ps1
```

To use a different PC's recording folder:

```powershell
.\Install_TranscriptForgeTask.ps1 -RecordingFolder "D:\Recordings"
```

The scheduled task calls the same application entry point directly. To test one scan manually without installing a task:

```powershell
py -3 -m transcriptforge --scheduled-scan --folder "C:\path\to\recordings"
```

That command exits when there is no eligible recording. When it finds one, it launches the normal GUI with speaker review enabled; the user remains in control before transcription begins.

If that folder later does not exist, the launched GUI asks the user to choose a replacement and saves it in that PC's local settings. The scan ledger is `%LOCALAPPDATA%\LocalAudioTranscriber\recording-history.json`; it records the original path, status, final media path, and transcript path so completed recordings are not processed again. To remove the task, run `Remove_TranscriptForgeTask.ps1`, or open **Task Scheduler** (`taskschd.msc`), expand **Task Scheduler Library**, select **TranscriptForge - Check Recordings**, and choose **Disable** or **Delete**.

Run the tests with:

```powershell
py -3 -m unittest discover -s tests -v
```

## Command line use

The GUI remains the default entry point. For automation, use the CLI module:

```powershell
# Simple transcription; output defaults to <input-stem>.md
py -3 -m transcriptforge.cli transcribe "C:\path\meeting.mp4" --model small.en

# Machine-readable newline-delimited JSON events for an agent
py -3 -m transcriptforge.cli --json-events transcribe "C:\path\meeting.mp4" --output "C:\path\meeting.md" --force
```

Speaker identification has an explicit human-review handoff. The first command below analyzes voices and writes a review file without starting Whisper:

```powershell
py -3 -m transcriptforge.cli transcribe "C:\path\meeting.mp4" --speakers
```

The command exits with code `2` and creates `<input-stem>.speaker-review.json`. Edit the `name` values in that JSON (existing names can be reused, and new names can be typed), then rerun the command with `--speaker-review` pointing to that file:

```powershell
py -3 -m transcriptforge.cli transcribe "C:\path\meeting.mp4" --speakers --speaker-review "C:\path\meeting.speaker-review.json"
```

If uncertain voices remain, the command returns code `2` again with a shorter review list. Whisper starts only after the review is complete. Use `--accept-suggestions` to bypass the review checkpoint when an automated run is explicitly preferred. Review clips are kept temporarily under `%LOCALAPPDATA%\LocalAudioTranscriber\pending-speaker-review\` so a person can listen to them; they are removed after successful transcription.

Useful automation commands include `py -3 -m transcriptforge.cli --json-events models list`, `models download small.en`, `profiles list`, and `profiles path`. The CLI never opens the output file automatically.

Supported input extensions: `.wav`, `.mp3`, `.m4a`, `.aac`, `.mp4`, `.mov`, and `.mkv`.
