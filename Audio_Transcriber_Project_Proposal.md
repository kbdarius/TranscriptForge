# Project Proposal: Local Audio Transcriber

**Date:** 2026-08-24  
**Status:** Implementation specification for an AI coding agent  
**Goal:** Build a simple Windows desktop Python application that transcribes a user-selected local audio or video file to a timestamped Markdown transcript.

## 1. Product Summary

Create a local-first Python desktop tool with a graphical interface. The user selects a recording, selects or confirms an output location and filename, then starts transcription. The application produces a `.md` transcript with timestamps, a run summary, and any sections that could not be confidently resolved.

The primary design requirement is transcript quality. The tool must avoid the failure mode observed in the reference meeting recording, where Whisper repeated a phrase over quiet or unclear audio and later emitted repeated `R0.` segments. It must detect suspicious repeated output, isolate only the affected audio range, and retry that range without allowing prior hallucinated text to affect the result.

The tool processes user media locally. It must not upload audio, transcripts, or model data.

## 2. Intended User Workflow

1. User launches the application by double-clicking a packaged executable or running the Python entry point.
2. A GUI opens with an input-file browse button.
3. User selects an audio or video recording.
4. The application proposes an output path in the same folder using the input stem and `.md` extension. Example: `meeting.mp4` becomes `meeting.md`.
5. User may edit the output filename and browse to a different output folder.
6. User chooses a locally available Whisper model, defaulting to `small.en` for English technical meetings.
7. User clicks **Transcribe**.
8. The UI shows progress, elapsed time, current processing stage, and a cancel button.
9. The application writes the final Markdown transcript and opens or reveals it when finished.

## 3. Required GUI

Use `tkinter` with `ttk` unless an existing project already has a preferred desktop UI framework. Keep the first version simple and Windows-friendly.

Required controls:

- Input file path: read-only text field plus a **Browse** button.
- Output folder: editable text field plus a **Browse** button.
- Output filename: editable text field, automatically initialized to `<input-file-stem>.md`.
- Model selector: `tiny.en`, `base.en`, `small.en`, with `small.en` as the default.
- Optional advanced section, collapsed by default:
  - language selector, default `en`;
  - retain intermediate WAV checkbox, default off;
  - include timestamped segments checkbox, default on;
  - open transcript after completion checkbox, default on.
- **Transcribe** button, disabled until the input and output paths are valid.
- **Cancel** button, enabled only while work is active.
- Progress bar and concise status text.
- A scrollable event log that shows actions, warnings, retry ranges, and final file path. Do not expose raw stack traces unless the user selects a details action.

Validation rules:

- Input must exist and have a supported extension.
- Output directory must exist or be creatable.
- Output filename must end in `.md`; append it when omitted.
- Do not overwrite an existing output without explicit confirmation.
- Do not allow input and output to resolve to the same path.

## 4. Supported Inputs and Local Dependencies

Support common audio and video containers, including `.wav`, `.mp3`, `.m4a`, `.aac`, `.mp4`, `.mov`, and `.mkv`.

Use these Python dependencies:

- `openai-whisper` for speech recognition.
- `torch`, installed according to the target CPU or GPU environment.
- `numpy` for audio sample manipulation.
- `imageio-ffmpeg` to obtain a bundled FFmpeg executable without requiring `ffmpeg` on `PATH`.
- Standard-library `wave`, `pathlib`, `subprocess`, `threading`, `queue`, `json`, `logging`, and `tkinter`.
- Optional: `webrtcvad` or `silero-vad` for voice-activity detection. The initial release may use RMS energy plus Whisper's speech confidence if adding VAD makes packaging unreliable.

Do not require the external `ffmpeg`, `ffprobe`, or `whisper` commands to be installed on `PATH`.

Use `imageio_ffmpeg.get_ffmpeg_exe()` to find the bundled executable, then invoke it with `subprocess.run()` to decode any supported input to temporary PCM WAV:

```text
mono, 16 kHz, signed 16-bit PCM WAV
```

Read the decoded WAV through `wave` and pass a NumPy float array directly to Whisper. Do not pass a filename to Whisper, because its filename path may invoke `ffmpeg` by name and fail on restricted Windows systems.

## 5. Model Management

Store models in an application-owned local cache, for example:

```text
%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models
```

At startup, list locally available models. If the user selects an unavailable model, clearly state that a download is required and offer a separate download action. If the environment blocks the download because of corporate TLS interception or a remote service error, preserve the error in the log and allow the user to select an already cached model.

The default English model is `small.en`. It produced materially better technical terminology than `tiny.en` in the reference recording. Provide smaller models for speed, but explain through the model selector text that they may reduce technical accuracy.

## 6. Transcription Architecture

Implement a pipeline with explicit stages:

1. Validate GUI selections.
2. Decode source media to a temporary 16 kHz mono WAV.
3. Read PCM samples into a NumPy `float32` array scaled to `[-1, 1]`.
4. Load the selected local Whisper model with `fp16=False` for CPU compatibility.
5. Divide the audio into independently transcribed windows.
6. Transcribe every window with anti-hallucination defaults.
7. Analyze emitted segments for suspicious output.
8. Retry only suspicious time ranges using stricter settings and padded audio context.
9. Merge verified segments in chronological order.
10. Remove only confirmed contiguous duplicate hallucinations.
11. Write the Markdown transcript atomically.
12. Delete temporary audio unless the user selected retention.

Use fixed transcription windows of approximately 5 minutes with 2 seconds of overlap. Retain the absolute offset for every window and segment. Deduplicate only overlapping boundary segments after comparing their timestamps and normalized text.

Do not transcribe the entire recording in one call with `condition_on_previous_text=True`. This was the root cause of sustained repetition in the reference case.

## 7. First-Pass Whisper Settings

Use these settings for every independent window unless the user deliberately changes advanced settings:

```python
result = model.transcribe(
    audio_window,
    language="en",
    fp16=False,
    verbose=False,
    condition_on_previous_text=False,
    temperature=0,
    no_speech_threshold=0.6,
    logprob_threshold=-1.0,
    compression_ratio_threshold=2.4,
)
```

Reasons:

- `condition_on_previous_text=False` prevents a prior phrase from propagating through pauses or unclear audio.
- `no_speech_threshold=0.6` reduces text emitted during likely silence.
- `logprob_threshold` and `compression_ratio_threshold` expose low-confidence and repetitive decoding for review.
- `fp16=False` supports CPU-only systems.

Keep the model's returned fields required for diagnosis, including segment start and end, text, `avg_logprob`, `no_speech_prob`, `compression_ratio`, and `temperature` when available.

## 8. Pause and Hallucination Detection Algorithm

The tool must distinguish ordinary repeated dialogue from likely hallucination. It must never delete a repeated phrase solely because the same words occur twice somewhere in the meeting.

### 8.1 Normalize text for comparison

For duplicate analysis, normalize each segment's text by:

- trimming leading and trailing whitespace;
- converting to lowercase;
- collapsing internal whitespace;
- removing surrounding punctuation for comparison only.

Keep the original text unchanged for output.

### 8.2 Identify likely pauses

For each segment and a short audio interval around it, compute RMS energy in dBFS. Mark an interval as likely quiet when it remains below a configurable threshold, initially `-45 dBFS`, for at least 1.5 seconds. Do not use this alone to delete speech because meetings can contain quiet speakers and background noise.

Combine energy with Whisper confidence:

- probable pause: low energy and `no_speech_prob >= no_speech_threshold`;
- uncertain audio: low energy or poor `avg_logprob`, but not both;
- likely speech: energy above threshold or confident Whisper result.

### 8.3 Identify a likely hallucination run

Flag a consecutive run when all of the following are true:

- the same normalized text appears at least 3 consecutive times;
- the run spans at least 3 seconds;
- the segment text is short or has a high repetition/compression signal;
- at least one segment has low confidence, high no-speech probability, or falls inside a likely pause.

Also flag a run when a nonsensical short token such as `R0.` or another identical token repeats at least 4 times over advancing timestamps, even if the audio energy is not low. This covers unclear technical audio that Whisper repeatedly misdecodes.

Do not flag isolated valid repetitions such as two speakers saying “Okay,” a repeated part number in separate conversation turns, or a phrase that reappears after more than 30 seconds without a continuous run.

### 8.4 Isolate and retry only the suspect range

For every flagged run:

1. Define the suspect range from the start of the first repeated segment to the end of the last repeated segment.
2. Add 5 seconds of audio padding before and after the range, bounded by the source duration.
3. Transcribe that isolated slice with `condition_on_previous_text=False`, `temperature=0`, and `no_speech_threshold=0.6`.
4. Compare the retry output to the original flagged run.
5. If the retry is not itself suspicious, replace only the original suspect range with the retry segments, clipping segments back to the original unpadded range.
6. If the retry remains suspicious, retry once with a smaller slice, 15 to 30 seconds, and a stricter `no_speech_threshold` such as `0.7`.
7. If the second retry is still suspicious, omit the repeated hallucinated output. Write a Markdown note at that timestamp stating `[Unclear or silent audio omitted after retry]` only when the audio is classified as likely quiet. For non-quiet unclear audio, write `[Unclear speech]` rather than inventing text.

Limit automated retries to two per suspect range. This prevents endless loops and makes behavior predictable.

### 8.5 Final contiguous duplicate cleanup

After retries, make one final pass. Within each contiguous duplicate run that passed the hallucination criteria, keep the first segment and remove subsequent identical segments. Do not apply a global “keep only one occurrence” rule to all text in the recording.

This final cleanup must be scoped to identified runs. The reference transcript had one phrase repeated 93 times, while normal short dialogue also contained legitimate repeats such as “Yeah” and “Okay.”

## 9. Markdown Output Specification

Write output using UTF-8. Create the file in a temporary sibling path, then atomically rename it to the requested `.md` path after successful completion.

Use this structure:

```markdown
# Transcript: <source filename>

**Generated:** <local date and time>  
**Source:** `<absolute or user-visible source path>`  
**Model:** `<selected model>`  
**Language:** `<language>`  
**Duration:** `<HH:MM:SS>`

## Transcript

[00:00:00.00 - 00:00:07.92] Transcript text.
[00:00:07.92 - 00:00:09.64] Transcript text.

## Processing Notes

- Windows retried for suspected repeated output: `<count>`.
- Unclear or silent intervals omitted after retry: `<count>`.
- Model cache: `<local cache path>`.
```

Format timestamps as `HH:MM:SS.ss`, not raw seconds. Preserve chronological order. Include only transcript lines and short machine-generated processing notes. Do not add a speculative meeting summary.

Optional future enhancement: write a companion `.json` file with raw Whisper metadata and retry decisions for diagnostic review. Do not put raw model diagnostics in the primary `.md` transcript.

## 10. Error Handling and Cancellation

Run long transcription work on a worker thread. Send progress and log events to the UI through a thread-safe queue. Do not update tkinter controls directly from the worker thread.

Cancellation requirements:

- The user can request cancellation while decoding or transcribing.
- Check a cancellation event between decode completion, each transcription window, each retry, and output writing.
- Do not present a partial transcript as final.
- Optionally save an explicitly named partial diagnostic file only after user confirmation.

Handle and explain these errors:

- source file cannot be decoded;
- no audio stream is present;
- insufficient disk space for temporary WAV;
- selected model is absent and cannot be downloaded;
- output directory cannot be written;
- source audio is longer than the available memory budget;
- unexpected model or decode exception.

For source files longer than a configurable threshold, decode and process in sequential chunks rather than holding the full recording in memory. The first release may initially load a complete 35-minute WAV if memory use is acceptable, but the architecture must make chunked processing straightforward.

## 11. File and Module Layout

Use a small, testable structure:

```text
audio_transcriber/
  app.py                 # tkinter entry point and UI state
  controller.py          # background-job orchestration and cancellation
  media.py               # bundled FFmpeg discovery and WAV decoding
  audio.py               # WAV reading, slicing, energy measurements
  transcription.py       # Whisper model loading and window transcription
  quality.py              # pause, duplicate, and hallucination detection
  retry.py                # suspect-range retry logic and replacement
  output.py               # Markdown rendering and atomic output writing
  models.py               # dataclasses for segments, ranges, diagnostics
  tests/
    test_quality.py
    test_retry.py
    test_output.py
    fixtures/
```

Keep GUI code out of the transcription and quality modules. The core pipeline should be callable from automated tests without opening a window.

## 12. Acceptance Criteria

The implementation is complete only when all of these are demonstrated:

- A user can choose a local recording through the GUI.
- The default output path is the input file's folder and stem with `.md` extension.
- The user can change both output folder and output filename.
- The program decodes media without relying on `ffmpeg` being on `PATH`.
- The program transcribes through local Whisper sample arrays rather than asking Whisper to open the filename.
- A CPU-only Windows run succeeds with `fp16=False`.
- A normal meeting transcript includes chronological timestamped Markdown segments.
- A synthetic or captured repeated-text fixture is detected as a hallucination run.
- The application retries only the suspect range and does not rerun the entire recording.
- The repeated phrase run is removed or replaced, while nonconsecutive valid repeated dialogue remains.
- The reference pattern of repeated `R0.` output is treated as a suspect run and retried.
- The transcript records any unresolved quiet or unclear range rather than fabricating text.
- The application remains responsive during transcription and supports cancellation.
- Intermediate WAV files are deleted by default after success or cancellation.

## 13. Reference Case to Use During Development

Use the completed reference meeting only as a local development and validation fixture if authorized. It demonstrated these facts:

- An MP4 with a valid AAC audio track was successfully decoded through bundled FFmpeg.
- `small.en` recognized technical terms better than `tiny.en`.
- Passing a decoded WAV sample array directly to Whisper bypassed the missing `ffmpeg` command lookup.
- A full transcription with `condition_on_previous_text=True` generated a 93-line repeated phrase run and later repeated `R0.` output.
- Re-transcribing a suspect range independently with `condition_on_previous_text=False` and `no_speech_threshold=0.6` removed the repeated `R0.` behavior and recovered useful dialogue.

The AI implementing this project should keep the reference audio and generated transcripts out of source control unless the owner explicitly authorizes them.

## 14. Implementation Boundaries

Build the tool described here, not a cloud transcription service and not a meeting-summary product. Keep the first release focused on dependable local transcription, transparent retry behavior, and a straightforward GUI.

Do not silently delete uncertain content outside a confirmed hallucination run. Favor timestamped `[Unclear speech]` or `[Unclear or silent audio omitted after retry]` markers over invented wording.