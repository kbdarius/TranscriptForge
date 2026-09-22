# TranscriptForge installation guide

Current application version: `0.24.0`.

## Quick setup on a new Windows PC

1. Copy or clone the complete TranscriptForge folder to the PC.
2. Double-click `Setup_TranscriptForge.bat` in the project root.
3. If Python is missing, the script attempts a per-user Python 3.11 install through `winget`.
4. Wait for dependency installation, import checks, and model validation to finish.
5. Double-click `Run_TranscriptForge.bat` to launch the application.

The normal setup downloads the default `small.en` Whisper model and the local speaker encoder. To install all three models available in the GUI, run this from a Command Prompt in the project root:

```bat
Setup_TranscriptForge.bat all
```

That downloads `tiny.en`, `base.en`, and `small.en`, so allow additional disk space and download time. Setup is safe to rerun: packages and completed model files are checked and reused.

## Required Windows components

- Windows 10 or newer.
- Python 3.11 or newer. The standard Windows installer should include the Python Launcher (`py`) and Tkinter.
- `pip`, bootstrapped automatically when possible.
- PowerShell and Task Scheduler only if the optional scheduled recording scan is used; both are Windows components.
- Internet access during first setup for Python packages and model files, unless the organization provides an approved internal mirror.
- Enough disk space for Python packages, temporary decoded audio, and the selected models. `small.en` is approximately 461 MB; installing all three supported Whisper models is roughly 680 MB before temporary audio and package space.

The setup script uses per-user Python package installation and the CPU PyTorch build. Administrator rights are not normally required. NVIDIA/CUDA is not required for the supported default workflow.

## Direct Python dependencies

These are the direct runtime dependencies declared in `requirements.txt` and installed by setup:

| Package | Purpose |
| --- | --- |
| `openai-whisper` | Local speech-to-text models and transcription API |
| `torch` | CPU tensor/runtime backend used by Whisper and Resemblyzer |
| `numpy` | Audio sample arrays, RMS calculations, and embeddings |
| `imageio-ffmpeg` | Supplies a bundled FFmpeg executable |
| `resemblyzer` | Local voice embeddings for speaker clustering and profile matching |

No separate `ffmpeg`, `ffprobe`, or `whisper` command-line installation is required. TranscriptForge invokes the FFmpeg executable supplied by `imageio-ffmpeg` and passes decoded samples directly to Whisper.

## Transitive Python dependencies

`pip` resolves these packages from the direct dependencies. They are listed here so a restricted-PC software request has a complete dependency inventory; do not install them one by one unless an administrator requires an allow-list:

| Dependency area | Packages |
| --- | --- |
| Whisper | `more-itertools`, `numba`, `tiktoken`, `tqdm`, `llvmlite`, `regex`, `requests` |
| PyTorch | `filelock`, `typing-extensions`, `setuptools`, `sympy`, `networkx`, `jinja2`, `fsspec`, `mpmath`, `MarkupSafe` |
| Resemblyzer/audio | `librosa`, `webrtcvad`, `scipy`, `typing`, `audioread`, `scikit-learn`, `joblib`, `decorator`, `soundfile`, `pooch`, `soxr`, `lazy-loader`, `msgpack`, `platformdirs`, `threadpoolctl`, `narwhals` |
| Native audio support | `cffi`, `pycparser` |
| Shared HTTP support | `charset-normalizer`, `idna`, `urllib3`, `certifi` |
| Packaging support | `packaging` |

The test suite uses Python's standard-library `unittest`, `tempfile`, and related modules. The application uses standard-library `tkinter`, `wave`, `pathlib`, `subprocess`, `threading`, `queue`, `json`, `logging`, `zipfile`, and `sqlite`-free JSON stores; no additional test or database server installation is required.

## Models and local data

The setup script downloads and validates:

- Whisper `small.en` by default; optional `tiny.en` and `base.en` with the `all` argument.
- The Resemblyzer voice encoder used by optional local speaker identification.

Whisper models are stored under:

```text
%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models\
```

Speaker profiles are stored under:

```text
%LOCALAPPDATA%\LocalAudioTranscriber\speaker-profiles.json
```

The profile file contains confirmed voice embeddings and names, not permanent audio samples. Temporary decoded WAV files and speaker review clips are removed after processing. Other local settings include output-folder history, recording-folder settings, filename templates, transcription history, and removed-sample decisions under `%LOCALAPPDATA%\LocalAudioTranscriber\`.

## Restricted-PC troubleshooting

- Keep the final error text from `Setup_TranscriptForge.bat`; it identifies whether Python, pip, PyPI access, model access, or a local import failed.
- TLS interception, proxy rules, GitHub/PyPI allow-listing, or quota policies can block package/model downloads. The installer cannot bypass those policies.
- If `winget` is unavailable, install Python 3.11+ through the organization's approved software channel, ensure the Python Launcher and Tkinter are included, then rerun setup.
- If package installation encounters a corrupted local pip wheel, setup uses `--no-cache-dir` to force a fresh package fetch.
- If the model download is interrupted, rerun setup. Completed files are reused and incomplete downloads are handled by the Whisper loader.
- If the PC has no internet access, obtain approved offline wheels and model files from the administrator; do not copy model files or profiles into Git source control.
- A speaker profile is sensitive biometric data. Use TranscriptForge's profile management and configuration export/import features according to local policy.

## Manual recovery commands

From the TranscriptForge root folder:

```powershell
py -3 -m pip install --user --no-cache-dir -r requirements.txt
py -3 -m transcriptforge.cli models download small.en
py -3 -c "from resemblyzer import VoiceEncoder; VoiceEncoder(device='cpu')"
py -3 -m transcriptforge
```

All audio processing after setup is local. Audio and transcript content are not sent to a cloud transcription service.
