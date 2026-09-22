# Example configuration transfer

This folder contains batch files for transferring a TranscriptForge setup to another Windows PC.

The private `TranscriptForge_Example.tfconfig` file is intentionally ignored by Git. A real package contains voice embeddings and rejected-sample embeddings, which are sensitive biometric data and must not be committed to GitHub.

## Source PC

Run `Create_Example_Configuration.bat`. It creates `TranscriptForge_Example.tfconfig` in this folder from the current user's preferences, recurring filename templates, confirmed voice-learning archive, and sample-rejection decisions.

Copy that private `.tfconfig` file to this same folder on the destination PC. Do not copy recording history, recording folders, output-location history, meeting output paths, audio, transcripts, or Whisper model files.

## Destination PC

1. Run the repository's `Setup_TranscriptForge.bat` once.
2. Copy the private `TranscriptForge_Example.tfconfig` into this folder.
3. Run `Setup_Example_Configuration.bat`.

The import merges voice learning with any profiles already on the destination PC. Computer-specific folders and histories remain local so the new PC can choose its own recording and transcript locations.
