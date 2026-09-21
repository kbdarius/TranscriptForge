# Speaker Recognition Current State

This document records the current implementation, evidence, safeguards, and known limitations. It is not a validated future solution. Candidate changes are evaluated in [Speaker Recognition Feasibility Plan](SPEAKER_RECOGNITION_FEASIBILITY_PLAN.md) before production implementation.

## Purpose

Improve TranscriptForge so a meeting with a small number of known speakers produces a small, accurate review list and becomes more reliable as users confirm identities over time. Preserve all confirmed learning data without allowing short, noisy, overlapping, or repetitive samples to degrade active recognition.

## Implementation status

TranscriptForge v0.20.0 implements the core protection and recognition improvements in this plan:

- schema-3 archive/active profile storage with automatic version-2 backup on save;
- unlimited reviewed-sample archive with quality, diversity, and per-recording active-set limits;
- robust centroid/medoid/prototype matching and consistent confidence margins;
- profile-guided interval grouping plus conservative acoustic fallback clustering;
- enrollment of only the representative clips the user heard and kept;
- same-source exclusion during reruns and recoverable source quarantine with a timestamped backup;
- optional expected-speaker filtering in the GUI and CLI;
- per-cluster learning opt-out during speaker review;
- read-only `diagnose` CLI reporting;
- profile-management counts showing archived versus active samples;
- portable configuration transfer of the profile archive and preferences.

The remaining follow-up work is formal held-out evaluation and finer overlap detection. The implementation should continue through those items before being treated as fully validated for all meeting types.

## Evidence from the September 4 regression

The 35-minute `SW Daily Standup-20260904_084546-Meeting Recording.mp4` recording contained Keivan Darius, Prabhu Sannachi, Brian Lelacheur, and Dario Galdamez.

- Voice activity detection produced 402 usable intervals.
- The v0.19.1 acoustic pass incorrectly placed 392 intervals into one moving-centroid cluster.
- That mixed cluster scored `0.918` as Prabhu, `0.916` as Keivan, and `0.907` as Brian. The confidence-margin rule correctly left the name blank, but it could not undo the earlier over-merge.
- The user's review of the failed grouping subsequently archived 394 same-source embeddings under Keivan. The active-source limit restricted immediate impact to 12 active embeddings, but the source still required quarantine.
- Matching the individual intervals against profiles while excluding this recording produced strong recurring-speaker cores for all four expected participants. This evidence motivated profile-guided grouping before acoustic fallback.
- Future cluster confirmation enrolls at most the kept review clips, not hundreds of unseen members. This changes the learning unit from an assumed-clean cluster to a sample the user actually verified.

## Evidence from the August 31 diagnostic

The 78-minute `BMS Time-Series MTU Compliance and Charger Gateway` recording contained three known speakers: Keivan Darius, Prabhu Sannachi, and Garrett Moore.

- The current analyzer split 851 voiced windows into 29 clusters.
- Three clusters represented most of the meeting: Garrett with 543 windows, Prabhu with 194, and Keivan with 43.
- The other 26 clusters were mostly isolated clips lasting 1.5 to 3.2 seconds.
- Reconstructing the profiles from before this meeting showed that 21 of 29 clusters did not clear the current `0.78` matching threshold.
- Garrett's primary cluster scored `0.834` against Garrett but `0.858` against an unrelated saved speaker because matching can be won by one outlying stored embedding.
- Labeling the meeting added approximately 590 Garrett, 195 Prabhu, and 57 Keivan embeddings. The current design enrolls nearly every kept window, which creates imbalance and can overfit recognition to one recording.

## Goals

1. Reduce false speaker fragmentation before the user sees the labeling window.
2. Match known speakers using robust voice signatures instead of the closest individual sample.
3. Keep all confirmed embeddings as an archive while using only a quality-controlled active set for recognition.
4. Prevent a single meeting from dominating a person's voice signature.
5. Make uncertain, overlapping, and low-quality clips explicit rather than learning from them automatically.
6. Preserve compatibility with existing profiles and portable `.tfconfig` packages.

## Non-goals

- Do not retain raw voice audio by default.
- Do not upload recordings, embeddings, or transcripts.
- Do not silently assign a speaker when confidence is ambiguous.
- Do not discard historical embeddings during migration.

## Proposed architecture

### 1. Profile archive and active recognition set

Introduce speaker-profile schema version 3 with two logical layers:

- **Archive:** every distinct user-confirmed embedding and its metadata. This remains the complete learning history.
- **Active set:** a bounded, quality-selected, diverse subset used for matching.

Each archived embedding should retain:

- speaker name;
- quality score;
- source recording identifier;
- enrollment date;
- duration;
- overlap/noise flags;
- whether it is eligible for the active set;
- exclusion reason when it is not eligible.

Active-set selection should:

- reject very short, low-volume, overlapping, or user-rejected windows;
- remove near-duplicates;
- remove statistical outliers far from the person's robust center;
- retain examples from different recordings and acoustic conditions;
- cap the contribution from one recording;
- keep approximately 30 to 60 diverse active embeddings per person while leaving the archive unlimited.

### 2. Robust speaker signatures

Replace the current “best individual embedding wins” decision with a robust signature containing:

- a quality-weighted centroid;
- one or more medoids representing natural voice variations;
- a small set of diverse prototypes selected from different recordings.

Matching should combine centroid and prototype similarity without allowing one outlier to dominate. A name should be suggested only when:

- the absolute score clears a calibrated threshold; and
- the score leads the second-best candidate by a calibrated confidence margin.

The same confidence policy must be used in both the first review pass and the refinement pass.

### 3. Separate diarization from identification

The current online clustering compares each new 1.5–6 second window against clusters created earlier in sequence. Replace this with a global two-stage process:

1. Generate embeddings for quality-qualified voiced windows.
2. Perform global/agglomerative clustering so later speech can merge with earlier speech.
3. Merge small clusters into a larger cluster only when similarity, temporal context, and profile evidence agree.
4. Match the resulting speaker clusters to active known-speaker signatures.
5. Keep unresolved or overlapping windows as uncertain instead of creating a new apparent speaker for each one.

Short fragments should not become standalone review rows unless they contain enough clean evidence to identify a genuinely new speaker.

### 4. Expected-speaker shortlist

Add an optional **Expected speakers** control before analysis. It should be an editable multi-select populated from known profiles.

When supplied:

- match against those profiles first;
- permit `New speaker` and `Unknown` so the shortlist is never forced;
- use other saved profiles only when evidence is substantially stronger;
- show the user when a result falls outside the expected list.

Recurring meeting templates may optionally remember an expected-speaker list, but users must be able to edit it for each recording.

### 5. Safer enrollment workflow

Confirming a cluster name should not automatically promote every interval in that cluster into active recognition.

- Archive confirmed eligible windows.
- Promote only quality-selected, diverse representatives.
- Add **Do not learn from this cluster** and **Do not learn from this sample** controls.
- Continue collecting removal reasons for overlap, rapid speaker changes, noise, silence, duplicates, and wrong clusters.
- Treat a user-confirmed name as identity feedback, not proof that every interval in the cluster is clean training material.

### 6. Post-label refinement

After the user labels the main clusters:

- rerun cluster-to-profile assignment using the confirmed identities;
- reassign small fragments through profile score, neighboring-speaker context, and temporal smoothing;
- show only genuinely unresolved audio in the second review;
- provide playback for every unresolved clip;
- never ask again about clips the user removed.

## Data migration and recovery

1. Back up `speaker-profiles.json` before the first schema migration.
2. Convert existing version 2 embeddings into the archive without deleting or rewriting their values.
3. Build the initial active set from quality metadata, source diversity, and robust outlier detection.
4. Mark embeddings with incomplete legacy metadata as archived and conservatively eligible until evaluated.
5. Update `.tfconfig` export/import to include both archive and active-signature data.
6. Preserve the ability to restore the pre-migration profile backup.

No migration should require the original audio samples.

## Development phases

### Phase 0: Reproducible diagnostics and evaluation

- Add a read-only diagnostic command that reports voiced-window count, cluster count, cluster duration, profile candidates, score margins, active/archive counts, and quality distribution.
- Create anonymizable evaluation fixtures from synthetic embeddings and local recordings without committing recordings to Git.
- Establish baseline measurements for the August 31 recording and several prior meetings.

Deliverable: repeatable baseline report and regression tests.

### Phase 1: Profile schema version 3

- Add archive and active-set metadata.
- Implement atomic migration and automatic backup.
- Implement quality, duplicate, source-diversity, and outlier selection.
- Update profile management and portable configuration import/export.

Deliverable: no-loss migration with deterministic active signatures.

### Phase 2: Robust matching

- Implement weighted centroid, medoid, and diverse prototype generation.
- Replace max-sample matching.
- Apply threshold and margin checks consistently.
- Add expected-speaker filtering at the matching layer.

Deliverable: known-speaker matching that is resistant to isolated bad samples.

### Phase 3: Global clustering and fragment merging

- Replace sequential clustering with global/agglomerative clustering.
- Add small-cluster reassignment and temporal smoothing.
- Detect or conservatively flag likely overlap and poor-quality windows.
- Keep uncertain fragments out of profile learning.

Deliverable: review rows approximate real speakers rather than short acoustic variations.

### Phase 4: User workflow

- Add expected-speaker selection to the pre-analysis UI and CLI.
- Add per-cluster and per-sample learning controls.
- Improve the second-pass review to show only unresolved retained clips.
- Add profile diagnostics showing archive count, active count, recordings represented, and excluded samples.

Deliverable: understandable user control over recognition and learning.

### Phase 5: Validation and rollout

- Run migration against a copy of the current profile database.
- Compare old and new algorithms on held-out recordings that were not used to construct active signatures.
- Verify configuration export/import on a clean settings directory.
- Document rollback and profile-backup recovery.
- Bump the version, update README documentation, run compile/tests, and publish only after acceptance criteria pass.

## Testing strategy

### Unit tests

- schema migration and rollback;
- active-set selection and per-recording contribution limits;
- duplicate and outlier handling;
- centroid/medoid/prototype calculations;
- confidence threshold and margin behavior;
- expected-speaker filtering;
- short-fragment merging;
- enrollment exclusion and archive retention;
- configuration package round trips.

### Integration tests

- three known speakers with changing microphone conditions;
- one known speaker plus one new speaker;
- overlapping speakers and rapid handoffs;
- long meeting with hundreds of windows;
- recurring meeting with an expected-speaker shortlist;
- import of a legacy profile followed by recognition on a new PC.

### Performance tests

- analysis time and memory for a 90-minute recording;
- matching time with thousands of archived embeddings;
- package export/import size and duration;
- proof that matching uses the bounded active set rather than scanning the full archive.

## Acceptance criteria

For the August 31 three-speaker diagnostic recording:

- identify the three dominant speaker groups correctly;
- present no more than six review rows unless genuine unresolved/overlapping speech requires more;
- do not confidently suggest unrelated saved speakers for the three dominant groups;
- reduce the 26 one-off speaker clusters to uncertain fragments or assignments to the three confirmed speakers;
- add no low-quality or removed samples to the active recognition set;
- prevent any one recording from supplying more than the configured share of an active signature.

Across held-out recordings:

- improve known-speaker top-1 accuracy over the current implementation;
- reduce wrong confident suggestions to zero in the evaluation set;
- reduce the number of manual review decisions without increasing incorrect automatic labels;
- preserve every archived confirmed embedding through migration and configuration transfer.

## Risks and mitigations

- **Over-merging distinct speakers:** require combined profile, acoustic, and temporal evidence; keep uncertain results reviewable.
- **Legacy contamination:** archive everything but rebuild active sets with robust outlier filtering.
- **Thresholds tuned to one meeting:** calibrate on multiple held-out meetings and keep thresholds configurable internally.
- **Migration failure:** use atomic writes, timestamped backup, schema validation, and rollback.
- **Profile growth:** keep archive unlimited while bounding active matching cost.

## Recommended implementation order

Implement Phase 0 and Phase 1 first. The archive/active separation stops additional profile pollution and provides reliable measurements. Then implement robust matching before replacing clustering, allowing each improvement to be measured independently. Add the expected-speaker UI after the matching layer supports it, and finish with global clustering and workflow refinements.
