# Speaker Recognition Feasibility Plan

## Purpose

Determine which speaker-recognition improvements are worth adding to TranscriptForge before changing the production workflow or the user's active voice profiles.

The current concern is speaker identification, especially meetings with three known participants that produce dozens of apparent speakers. Whisper transcription quality is currently acceptable, so this feasibility effort keeps the transcription model fixed and concentrates on diarization, voice matching, profile learning, and review effort.

## Current evidence

The latest investigation provides the initial baseline:

- A meeting with three expected participants produced approximately 35 speaker clusters.
- Most extra clusters contained one short interval rather than a sustained speaker.
- The dominant groups contained most of the meeting and were generally associated with the correct people.
- Keivan's recent labeled samples were saved in the archive but several were not included in the active matching set.
- Resemblyzer preprocessing alone did not materially improve the difficult Keivan samples.
- The current application uses Resemblyzer embeddings on the CPU and profile matching is separate from Whisper transcription.

This means a larger Whisper model is not the first experiment. The first experiments must address fragmented clusters, profile selection, overlap, and the use of confirmed labels.

## SW Daily Standup study dataset

The recordings folder currently contains a particularly useful recurring-meeting dataset:

- 43 MP4 recordings;
- 42 distinct meeting dates;
- coverage from June 3, 2026 through September 10, 2026;
- one date with two MP4 files, June 3;
- one matching DOCX file from June 29, which is excluded from audio testing.

The repeated participant roster makes this suitable for testing future recognition on recordings that were not used to build the profiles. The roster from the supplied meeting screenshot should become an editable study roster. The study must not assume every saved profile name attended every standup; the user should be able to mark expected, absent, new, or uncertain participants for each recording.

The current inventory is:

```text
SW Daily Standup-20260603_084837-Meeting Recording.mp4
SW Daily Standup-20260603_084858-Meeting Recording.mp4
SW Daily Standup-20260604_084557-Meeting Recording.mp4
SW Daily Standup-20260615_084503-Meeting Recording.mp4
SW Daily Standup-20260702.mp4
SW Daily Standup-20260707_084645-Meeting Recording.mp4
SW Daily Standup-20260708_084540-Meeting Recording.mp4
SW Daily Standup-20260709_084547-Meeting Recording.mp4
SW Daily Standup-20260713_084626-Meeting Recording.mp4
SW Daily Standup-20260714_084629-Meeting Recording.mp4
SW Daily Standup-20260716_084537-Meeting Recording.mp4
SW Daily Standup-20260717_084527-Meeting Recording.mp4
SW Daily Standup-20260720_084522-Meeting Recording.mp4
SW Daily Standup-20260722_084540-Meeting Recording.mp4
SW Daily Standup-20260724_084511-Meeting Recording.mp4
SW Daily Standup-20260727_084608-Meeting Recording.mp4
SW Daily Standup-20260728_084535-Meeting Recording.mp4
SW Daily Standup-20260729_084521-Meeting Recording.mp4
SW Daily Standup-20260730_084617-Meeting Recording.mp4
SW Daily Standup-20260731_084725-Meeting Recording.mp4
SW Daily Standup-20260803_084521-Meeting Recording.mp4
SW Daily Standup-20260804_084750-Meeting Recording.mp4
SW Daily Standup-20260805_084617-Meeting Recording.mp4
SW Daily Standup-20260811_100100-Meeting Recording.mp4
SW Daily Standup-20260812_084626-Meeting Recording.mp4
SW Daily Standup-20260813_084607-Meeting Recording.mp4
SW Daily Standup-20260814_084534-Meeting Recording.mp4
SW Daily Standup-20260819_084903-Meeting Recording.mp4
SW Daily Standup-20260820_084620-Meeting Recording.mp4
SW Daily Standup-20260821_084542-Meeting Recording.mp4
SW Daily Standup-20260824_084604-Meeting Recording.mp4
SW Daily Standup-20260825.mp4
SW Daily Standup-20260826.mp4
SW Daily Standup-20260827_084531-Meeting Recording.mp4
SW Daily Standup-20260828.mp4
SW Daily Standup-20260831.mp4
SW Daily Standup-20260901.mp4
SW Daily Standup-20260902.mp4
SW Daily Standup-20260903.mp4
SW Daily Standup-20260904.mp4
SW Daily Standup-20260908.mp4
SW Daily Standup-20260909.mp4
SW Daily Standup-20260910.mp4
```

The DOCX file `SW Daily Standup-20260629_084657-Meeting Recording.docx` is not included because it is not an audio recording.

The initial chronological split should be:

| Set | Dates | Recordings | Use |
|---|---|---:|---|
| Enrollment | June 3 through August 18 | 27 | Build a clean study profile snapshot from reviewed clips |
| Validation | August 19 through August 31 | 9 | Tune clustering and profile-selection rules |
| Final holdout | September 1 through September 10 | 7 | Measure performance on recordings not used for tuning |

The final holdout must remain untouched until the candidate approach is fixed. A recording belongs to one set as a whole; clips from a recording must never be split between enrollment and testing.

## Study labeling UI

The existing transcription review window is designed to label one recording while preparing a transcript. The study needs a separate **Speaker Recognition Study** window so labels can be saved as repeatable ground truth without starting Whisper or changing the production profile database.

The first screen should:

1. Show the discovered SW Daily Standup recordings with date, duration, size, and study status.
2. Let the user assign recordings to Enrollment, Validation, Final holdout, or Exclude.
3. Show the editable daily participant roster from the supplied list, with checkboxes for expected and absent participants.
4. Let the user resume a partially labeled recording.
5. Keep the final holdout locked from labeling until the study is ready for scoring.

The labeling screen should analyze one selected recording and present a manageable set of candidate samples. Each row should include:

- recording date and start/end time;
- a Play button and a short waveform or level indicator;
- the proposed cluster or speaker identifier;
- a searchable name dropdown containing the study roster;
- `Unknown`, `New speaker`, and `Mixed/overlap` choices;
- a Keep for study checkbox;
- an optional Learn for profile checkbox, disabled by default;
- an exclusion reason such as overlap, unclear, noise, silence, duplicate, or wrong cluster;
- a notes field for observations.

The UI should offer `Play`, `Play again`, `Keep and next`, `Exclude and next`, `Save`, and `Finish later`. A user correction should immediately update the study annotation, but it should not update `speaker-profiles.json` unless the user explicitly enables profile learning for that clean sample.

The study UI should not require the user to label every short interval in every meeting. It should first select representative samples from the beginning, middle, and end of a recording, include samples from each proposed cluster, and oversample uncertain or conflicting clusters. The final scoring set should include both clean speech and difficult cases so the results measure real performance.

Study annotations should be stored separately from production data, for example under `%LOCALAPPDATA%\\LocalAudioTranscriber\\speaker-study\\`, with one manifest per recording and a study-level manifest. The records should contain paths, timestamps, labels, decisions, and metrics references; raw audio remains in the recordings folder and is never copied into the repository or a configuration package.

## Study workflow using the daily recordings

The user-facing workflow should be:

1. Scan and list the 43 recordings.
2. Confirm or edit the participant roster.
3. Label clean representative samples from the Enrollment recordings.
4. Run the current algorithm against the Validation recordings using a copied profile snapshot.
5. Label only the validation disagreements and difficult samples.
6. Test each candidate change against the same Validation set.
7. Freeze the selected candidate and run it against the Final holdout recordings.
8. Review the holdout score and resource report before any production integration.

The same clean enrollment labels may later be offered for profile learning, but study accuracy must always be calculated from recordings excluded from enrollment. This prevents a profile from appearing accurate merely because it was tested on the audio that created it.

## Feasibility principles

1. Test each phase outside the production pipeline first.
2. Never train or rewrite the live profile database during an experiment.
3. Keep the original recording and current profile archive unchanged.
4. Compare every experiment with the current TranscriptForge result on the same recording.
5. Save metrics and machine-resource measurements, but do not commit recordings, decoded audio, embeddings, or profile copies to Git.
6. Do not accept a lower error rate if it creates unsafe confident names or increases the user's review burden.

## Isolated test code

Create a separate feasibility package rather than placing experimental code in the production modules at the beginning. A proposed layout is:

```text
feasibility/
    README.md                 # setup and repeatable commands
    run_experiment.py         # one entry point for all phases
    audio_manifest.py         # local recording metadata; no audio in Git
    baselines.py              # current pipeline measurements
    profile_snapshot.py       # read-only copied profile data
    metrics.py                # accuracy, fragmentation, purity, and review metrics
    resource_metrics.py       # wall time, RAM, VRAM, and CPU measurements
    phase1_current_pipeline.py
    phase2_profile_selection.py
    phase3_diarization_model.py
    phase4_name_assignment.py
    results/                   # local results; ignored by Git
```

The test code should call production functions read-only where practical. Experimental algorithms and model adapters should remain in the feasibility package until they pass their phase gate. A test run should write a JSON result containing the recording identifier, profile snapshot identifier, software version, model name, settings, metrics, and resource usage.

The harness should support these modes:

```powershell
py -3 -m feasibility.run_experiment baseline --recording "C:\path\meeting.mp4"
py -3 -m feasibility.run_experiment phase1 --recording "C:\path\meeting.mp4" --expected-speaker "Keivan Darius" --expected-speaker "Prabhu Sannachi" --expected-speaker "Garrett Moore"
py -3 -m feasibility.run_experiment compare --recording "C:\path\meeting.mp4" --runs baseline,phase1,phase2,phase3
```

The exact commands may change when the harness is implemented. The important boundary is that the harness reads a copied profile database and never enrolls samples into the user's live database.

## Test data and ground truth

Use a small held-out set of real meetings supplied by the user, including:

- the latest three-person meeting;
- at least two additional three-person meetings with recurring participants;
- one meeting with four or more participants;
- one recording containing overlap or rapid speaker changes;
- one recording with a new participant who is not in the profiles.

For each evaluation recording, create a local annotation manifest containing reviewed time ranges and the correct speaker name. The manifest may reference the original audio path but must not include audio or biometric data in Git.

The first manifest can be lightweight: a set of reviewed intervals and speaker names rather than a fully labeled transcript. It should be sufficient to measure whether the system assigned the right person, made an unsafe confident assignment, or left a segment unresolved.

## Measurements

Every phase should report the same measurements so results remain comparable.

### Recognition quality

- Known-speaker top-1 accuracy on reviewed intervals.
- Keivan top-1 accuracy as a separate tracked metric.
- False confident assignments to the wrong saved person.
- Unknown rate for speech that cannot be safely identified.
- Accuracy on short intervals and longer intervals separately.
- Accuracy when the expected-speaker list is supplied.

### Diarization quality

- Number of review clusters shown to the user.
- Number and percentage of speech seconds in the dominant clusters.
- Orphan-cluster count and duration.
- Mixed-cluster rate based on reviewed samples.
- Number of likely overlap or rapid-handoff intervals.
- Whether adjacent intervals from the same person were incorrectly split.

### Learning quality

- Archived samples before and after the run.
- Active samples before and after the run.
- Number of recordings represented in each active profile.
- Maximum contribution from one recording.
- Number of removed, rejected, duplicate, and outlier samples.
- Whether the user's corrected samples become eligible for future matching.

### User effort

- Number of samples requiring playback.
- Number of names the user must enter or select.
- Number of second-pass questions.
- Number of samples removed by the user.
- Whether removed samples are asked about again.

### Resource usage

- Total processing time.
- Peak system RAM.
- Peak GPU memory and whether CUDA was used.
- CPU utilization.
- Model download size and local cache size.

The current test PC has approximately 32 GB of RAM and an RTX 4000 Ada Laptop GPU with 12 GB VRAM. The installed PyTorch build is currently CPU-only, so GPU measurements must distinguish the existing CPU path from any future CUDA-enabled test environment.

## Phase 0: Baseline and reproducibility

Run the current production algorithm against the held-out recordings using a copied profile archive. Record cluster counts, candidate names, confidence margins, active/archive counts, and the measurements above.

Deliverables:

- repeatable baseline command;
- JSON result files;
- a short baseline report for each recording;
- regression fixtures using synthetic embeddings for deterministic tests.

Gate to continue: the same input and copied profiles produce stable results across repeated runs, and the baseline report clearly identifies the current failure modes.

## Phase 1: Improve the current pipeline

Test changes that do not require a new speaker model:

1. Use the expected participant list as a matching constraint while retaining `Unknown` and `New speaker` escape paths.
2. Replace sequence-only grouping with global grouping over the full recording.
3. Merge short fragments only when voice similarity, timing, and neighboring context agree.
4. Keep likely overlap, silence, and rapid handoff samples out of training.
5. Make the active profile selector retain recent confirmed samples while preserving recording diversity.
6. Compare profile decisions using centroid, medoid, and diverse prototypes rather than one winning sample.

The test harness should run each change independently and then as a combined candidate. This will show which change actually helps instead of hiding regressions in a large rewrite.

Gate to continue: on the three-person baseline, the system should reduce one-off review rows substantially, avoid confident wrong names, and make Keivan's held-out accuracy equal to or better than the current baseline. The provisional target is no more than six meaningful review groups for a clean three-person meeting, with unresolved fragments reported separately.

## Phase 2: Test a stronger diarization model

Evaluate `pyannote/speaker-diarization-community-1` as an experimental diarization backend. Its official model card describes improved speaker assignment and counting, supports a known `num_speakers` value, supports speaker-count bounds, and provides exclusive diarization output for reconciling turns with transcription timestamps. It can run locally, although model access requires accepting the model conditions and using a Hugging Face token. See the [official model card](https://huggingface.co/pyannote/speaker-diarization-community-1).

Run three tests against each baseline recording:

- automatic speaker count;
- the known participant count, such as `num_speakers=3`;
- a bounded range when the participant count is uncertain.

Keep pyannote output separate from name assignment at first. The first question is whether it produces cleaner speaker turns and fewer fragments. The second question is whether those turns can be matched reliably to the existing names.

Resource testing must include CPU and CUDA paths when available. The existing application cannot currently use the installed NVIDIA GPU because its PyTorch package is CPU-only.

Gate to continue: the model must reduce fragmentation and mixed clusters on held-out recordings without creating a material increase in processing time, memory use, or unsafe name assignments. If it improves diarization but not name matching, keep it as a turn-generation backend and continue with Phase 3.

## Phase 3: Match diarized turns to known names

Use the output turns from the best Phase 1 or Phase 2 candidate and match them to the existing confirmed profiles.

Test:

- profile matching with no expected-speaker list;
- matching with the expected participant list;
- robust per-person signatures built from recent and historical confirmed samples;
- an explicit low-confidence result instead of a forced name;
- handling for a new speaker and a speaker whose samples were removed.

This phase must verify that a better diarization result does not simply move the error into the name-matching layer. It should also confirm that corrected labels from one meeting improve a later held-out meeting without allowing one noisy recording to dominate the profile.

Gate to continue: known-speaker accuracy improves across multiple meetings, Keivan's recognition improves on recordings not used for enrollment, and active profiles retain samples from multiple recordings.

## Phase 4: User workflow trial

After the algorithm passes offline tests, integrate the smallest useful workflow changes behind settings or an experimental mode:

- expected participant selection before analysis;
- clear distinction between mixed, unclear, wrong-cluster, and valid samples;
- a second-pass list containing only retained unresolved samples;
- playback for every item still requiring a decision;
- per-sample and per-cluster learning controls;
- profile diagnostics showing archive count, active count, source diversity, and excluded samples.

The user should be able to complete the same recordings using the current workflow and the experimental workflow. Record review time and corrections rather than relying only on model scores.

Gate to continue: the experimental workflow reduces review effort without hiding uncertainty and does not ask the user to label samples that were already removed.

## Phase 5: Production rollout

Only after the earlier gates pass:

1. Add the selected algorithm behind a setting with the current path available as a fallback.
2. Migrate profiles atomically and create a recoverable backup.
3. Preserve the full archive and rebuild only the bounded active set.
4. Add a diagnostic report so future failures can be compared with the baseline.
5. Update the README and installation documentation with model, storage, and resource requirements.
6. Bump the application version for the code change.
7. Run compile checks, unit tests, and held-out regression tests before release.

The live profile database should never be changed by a feasibility run. A production rollout should provide a profile backup and a setting that allows the user to return to the previous speaker backend.

## Feasibility decision matrix

| Candidate | Main benefit | Main cost | Decision condition |
|---|---|---|---|
| Improve current clustering and profile selection | Lowest integration cost; directly addresses fragmentation and learning | Requires careful tuning and evaluation | First implementation candidate if held-out tests improve |
| Add expected participant count/list | Can prevent implausible speaker proliferation in recurring meetings | User must provide or maintain the list | Use when the known roster improves precision without hiding new speakers |
| pyannote Community-1 | Stronger diarization, speaker counting, overlap-aware turn output | Larger dependency/model footprint and additional setup | Adopt only if it materially improves held-out diarization and resource tests |
| Replace the current voice embedding model | Potentially better identity matching | Existing profiles cannot be reused directly; requires profile re-enrollment or dual storage | Consider only after the current profile-learning test is complete |
| Upgrade Whisper | May improve words or timestamps | Does not directly solve speaker identity; adds compute and memory | Defer until transcription quality becomes the limiting issue |

## Risks and mitigations

**Over-merging speakers:** require a confidence margin and retain `Unknown` when evidence conflicts.

**Over-fragmenting one speaker:** use global clustering and temporal context, but do not merge solely because two clips are close in time.

**Learning from mixed audio:** detect overlap and let the user remove the sample; removed or unclear samples never enter the active set.

**One meeting dominating a profile:** cap active enrollment per recording and retain all other confirmed data in the archive.

**Changing embedding models:** store model identity with each profile set and keep separate profile namespaces until the new model is proven.

**Resource exhaustion:** measure peak RAM and VRAM before enabling a backend by default; keep CPU fallback and allow the user to cancel analysis.

**Privacy and portability:** process locally, keep experiment artifacts outside Git, and do not export recordings or raw audio as part of a profile package.

## Recommended order

Start with Phase 0 and Phase 1 using the current Resemblyzer profiles. That will answer whether the main failure is caused by clustering and active-profile selection. Then run the pyannote comparison in Phase 2 without changing names or profiles. Only the strongest turn-generation approach should proceed to profile matching and user-interface integration.

This order gives us a measurable answer at each step and protects the existing training data while the experiments are underway.
