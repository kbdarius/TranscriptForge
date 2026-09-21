# TranscriptForge

TranscriptForge is a local-first Windows desktop application for turning an audio or video file into a timestamped Markdown transcript. Audio is decoded locally with the FFmpeg executable supplied by `imageio-ffmpeg`, then passed to local Whisper as NumPy samples. No audio or transcript is uploaded.

Current version: `0.21.0`.

For a new Windows PC, run [Setup_TranscriptForge.bat](Setup_TranscriptForge.bat) once before launching the application. See the [installation guide](DOC/INSTALLATION.md) for the complete dependency list, model setup, and restricted-PC troubleshooting. The [documentation index](DOC/README.md) links the project proposal, current speaker-recognition behavior, and feasibility plan.

Generated transcripts contain the transcript metadata and transcript content only; internal processing notes are kept out of the Markdown output.

## Run

Install the dependencies in a CPU or GPU environment as appropriate:

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m transcriptforge
```

The first use of a model requires a download. Models are cached under `%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models`. The GUI's **Download model** action is explicit; transcription only uses an already cached model.

The application remembers the recording folder for the current PC in `%LOCALAPPDATA%\LocalAudioTranscriber\recording-folder.json`. It starts with `C:\Users\dariusk\OneDrive - stryten.com\Recordings` when that default exists. If a saved folder is unavailable on another PC, TranscriptForge asks the user to choose a replacement folder at startup and stores that choice locally; no machine-specific path is shared with speaker profiles or the application code.

Speaker identification is optional and local. Enable **Identify speakers locally** to analyze voice clusters, play representative samples, confirm names, and reuse confirmed speaker profiles in future recordings. The workflow has two review passes: the first captures obvious names, then confirmed profiles are used to resolve easy blanks and a shorter second dialog asks about the remaining uncertain voices before Whisper transcription starts. Each sample has its own **X** button so mixed or poor clips can be removed before profile learning. Existing names appear in editable dropdowns: start typing to filter the choices, use the arrow keys and Enter to select, or type a new name. Names selected earlier in the same review are moved to the top of the later dropdowns. Each review row also has a **Learn** checkbox; clear it when the label is useful for this transcript but the cluster should not contribute training data.

The Setup dialog includes optional **Expected speakers**. Enter known profile names separated by commas, such as `Keivan Darius, Prabhu Sannachi, Garrett Moore`, to limit automatic suggestions to the expected participants while still allowing `Unknown` or a new speaker during review. The same restriction is available in the CLI with repeated `--expected-speaker` options.

Speaker data is kept under `%LOCALAPPDATA%\LocalAudioTranscriber\`:

```text
speaker-profiles.json       # names and confirmed voice embeddings
speaker-samples\            # reserved for optional future persistent samples
whisper-models\             # downloaded Whisper model files
```

The current release stores every distinct, user-reviewed voice embedding per person in `speaker-profiles.json`; it no longer drops older samples at a 20-sample limit. A confirmed cluster enrolls only the representative clips the user actually listened to and kept, rather than every unseen interval placed in that cluster. This prevents one incorrectly merged cluster from adding hundreds of mixed voices to a profile. The profile file is a schema-3 archive with a bounded active recognition set. Near-duplicate embeddings are ignored, all confirmed embeddings remain in the archive, and only quality-selected, diverse active embeddings are used for matching. Active selection limits the contribution from one recording so one long meeting cannot dominate a profile. Each new enrollment includes its quality, source, reviewed interval, cluster identifier, and date metadata.

Known profiles now seed the clustering of recurring meetings one interval at a time. A name must have multiple confident intervals before uncertain intervals can join its group; acoustic-only clustering uses stricter separation for speakers without a reliable profile match. When the same recording is diagnosed or reprocessed, embeddings previously learned from that source are excluded from its matching pass so a bad prior run cannot validate itself. Matching combines a robust centroid, medoid, and several top prototypes, and automatic reuse requires a confidence margin over the next-best speaker. The decoded WAV and playable review clips are temporary files under `%TEMP%\transcriptforge-*` and are deleted when processing ends. Raw voice samples are not uploaded or retained by default. Profile embeddings are sensitive biometric data; use **Manage profiles** to delete saved names and samples, or remove the local profile file when a complete reset is required. The first speaker-analysis run may download the Resemblyzer encoder weights.

The five most recently used output folders are stored locally in `%LOCALAPPDATA%\LocalAudioTranscriber\output-locations.json`. The **Output folder** field is an editable dropdown, so a prior location can be selected without browsing; **Browse** remains available for a new location.

After a successful transcription, the default **Rename media to match output** option renames the source media in its original folder before the Markdown is written and gives it the same base name as the Markdown file while preserving its original extension. The media is not moved to the output folder. If the renamed media name already exists, the GUI asks for confirmation before replacing it. The history ledger links the renamed media back to its original pending record. Uncheck this option to leave the source media unchanged. After completion, **Transcribe** is disabled to prevent accidental reruns; use **New transcription** to clear the form and begin another job.

Once transcription starts, the input file, output folder, and output filename fields are temporarily locked because the background job uses the paths captured at start time. They become editable again after completion, cancellation, or failure.

When local speaker identification is enabled, the two speaker-review dialogs are followed by a **Ready to transcribe** checkpoint. The output filename and output folder can be changed at that point, and the gear Setup dialog is available so a saved common filename can be selected. The analyzed input file remains locked so it cannot be changed after speaker analysis. Whisper starts only after the user clicks **Start transcription**. This ensures the final Markdown and renamed media use the user's final choices.

Clicking a sample's **X** now asks for a removal reason and optional note. The reason and embedding are stored locally in `%LOCALAPPDATA%\LocalAudioTranscriber\speaker-sample-rejections.json`; the audio itself is not retained. Removed samples are excluded from profile learning, and a cluster with all samples removed is not shown again in the second review. After transcription, short `Unknown` segments (up to three seconds) are filled only when the nearest labeled speakers on both sides agree, so ambiguous sections remain `Unknown` rather than receiving an unsafe guess.

The main window keeps the core file, model, and transcription controls visible. Click the gear button (`⚙`) to open **TranscriptForge Setup** for optional settings such as speaker identification, timestamps, retaining the decoded WAV, opening the result automatically, language, and media renaming.

Setup also includes **View history**, which displays the locally stored transcription ledger with the recording filename prominently shown, status, update time, full paths, and horizontal scrolling for long locations. Select a row to see its paths, open the transcript, or open its output folder.

Setup includes **Export configuration** and **Import configuration**. The portable `.tfconfig` package transfers the Setup preferences, selected Whisper model name, recurring filename templates, confirmed speaker embeddings, and removed-sample decisions. Import merges speaker data with profiles already on the destination PC, so it does not discard newer training. It intentionally excludes recording-folder settings, output-location dropdown history, transcription history, Whisper model files, audio, transcripts, and other computer-specific paths; those remain local to each PC.

When a scheduled scan finds a recording, TranscriptForge first asks whether to **Transcribe**, **Ignore**, or **Delete** it. **Ignore** keeps the audio in the recording folder and prevents future scans from selecting it. **Delete** asks for confirmation, removes the audio from that folder, and keeps a `deleted` history entry. History includes **Unignore / requeue**, which restores an ignored recording (or a pending recording left for later) to the next scan.

After a transcription finishes, use **Add content** to append messages or other manually supplied material. Choose an existing speaker from the editable **Provided by** dropdown or type a new name. The content is added under an `Additional content` section and is not used for voice-profile learning.

Setup also provides a saved **Common filename** list for recurring meetings. Add a name such as `SW Daily Standup`, select it, and choose **Use for output filename**. TranscriptForge constructs a dated Markdown filename such as `SW Daily Standup-20260826.md` using the input recording's modified date. The list is stored locally in `%LOCALAPPDATA%\LocalAudioTranscriber\filename-templates.json`; the normal output filename field remains available for one-off names.

The read-only CLI diagnostic command reports cluster counts, durations, profile archive/active counts, candidate scores, and margins without saving profiles:

```powershell
py -3 -m transcriptforge.cli diagnose "C:\path\meeting.mp4" --expected-speaker "Keivan Darius" --expected-speaker "Prabhu Sannachi" --expected-speaker "Garrett Moore"
```

If a known failed run enrolled a mixed cluster, quarantine that recording's embeddings from future matching without deleting them from the archive. The command creates a timestamped profile backup first; repeat `--name` to limit the change to specific profiles:

```powershell
py -3 -m transcriptforge.cli profiles quarantine-source "C:\path\meeting.mp4" --name "Keivan Darius" --reason "mixed speaker cluster"
```

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

The scheduled task calls the same application entry point directly. When it finds a recording, the GUI decision dialog appears before speaker labeling or transcription. The scanner marks the item `pending` before launching the GUI, so repeated 15-minute checks do not open duplicate windows while the user is working. Choosing Ignore changes the entry to `ignored`; choosing Delete removes the source after confirmation. A pending, ignored, or deleted entry is skipped until it is restored from History.

To test one scan manually without installing a task:

```powershell
py -3 -m transcriptforge --scheduled-scan --folder "C:\path\to\recordings"
```

That command exits when there is no eligible recording. When it finds one, it launches the normal GUI with speaker review enabled; the user remains in control before transcription begins.

If that folder later does not exist, the launched GUI asks the user to choose a replacement and saves it in that PC's local settings. The scan ledger is `%LOCALAPPDATA%\LocalAudioTranscriber\recording-history.json`; it records the original path, status, final media path, and transcript path so completed, ignored, and deleted recordings are not processed again. Deleted audio cannot be recovered by TranscriptForge. To remove the task, run `Remove_TranscriptForgeTask.ps1`, or open **Task Scheduler** (`taskschd.msc`), expand **Task Scheduler Library**, select **TranscriptForge - Check Recordings**, and choose **Disable** or **Delete**.

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
