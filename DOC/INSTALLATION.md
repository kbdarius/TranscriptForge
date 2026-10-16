# TranscriptForge installation guide

Current application version: `0.27.0`.

## Quick setup on a new Windows PC

1. Copy or clone the complete TranscriptForge folder to the PC.
2. Double-click `Setup_TranscriptForge.bat` in the project root.
3. If Python is missing, the script attempts a per-user Python 3.11 install through `winget`.
4. The guided wizard checks Python, pip, Tkinter, and the available C++ build tools.
5. On the Dependencies stage, review the required and optional packages, then choose **Install missing packages**. Packages are attempted individually in the background; a failure does not stop unrelated packages from being attempted.
6. On the Models stage, download the default `small.en` model and speaker encoder, or select other models. These downloads can be retried independently.
7. Review the Summary stage. If a package or download failed, copy or save the IT report before closing the wizard. It names the executable used for downloads, affected packages, and any hosts found in the installer output.
8. Double-click `Run_TranscriptForge.bat` to launch the application. Core transcription remains available when only an optional feature dependency failed.

The normal setup selects the default `small.en` Whisper model and the local speaker encoder. To select all three models available in the GUI, run this from a Command Prompt in the project root:

```bat
Setup_TranscriptForge.bat all
```

That selects `tiny.en`, `base.en`, and `small.en`, so allow additional disk space and download time. Setup is safe to rerun: installed packages and completed model files are checked and reused. If Python is missing, its bootstrap runs before the wizard because Tkinter requires Python.

## Required Windows components

- Windows 10 or newer.
- Python 3.11 or newer. The standard Windows installer should include the Python Launcher (`py`) and Tkinter.
- `pip`, bootstrapped automatically when possible.
- Microsoft C++ Build Tools with MSVC 14 or newer and a Windows SDK may be needed if pip has to compile a native dependency from source. In particular, `resemblyzer` depends on `webrtcvad`; if a compatible wheel is unavailable, that build requires the C++ compiler. The wizard links to the official Build Tools installer and identifies this compiler error separately from network failures.
- Windows PowerShell is used by the optional Outlook Classic COM fallback and task installer; Task Scheduler is only needed for scheduled recording scans.
- Internet access during first setup for Python packages and model files, unless the organization provides an approved internal mirror.
- Enough disk space for Python packages, temporary decoded audio, and the selected models. `small.en` is approximately 461 MB; installing all three supported Whisper models is roughly 680 MB before temporary audio and package space.

The wizard uses per-user Python package installation outside a virtual environment and the CPU PyTorch build. Administrator rights are not normally required for Python packages. Installing Visual Studio C++ Build Tools may require IT approval or administrator rights. NVIDIA/CUDA is not required for the supported default workflow.

Live recording captures playback from the default Windows output device through WASAPI loopback. It does not capture microphone audio. Choose the local recording destination in **Setup > Live system audio recording**; this capture-folder setting is separate from the folder used by scheduled scans. Scheduled scans read the per-PC `recording-folder.json` setting each time, so changing that saved folder applies on the next scan. The task runs the scanner through windowless Python to avoid a console flash; the GUI still opens when a new recording needs a decision. The scheduled task's project working directory is set when the task is installed; rerun `Install_TranscriptForgeTask.ps1` after moving the project to another drive or folder.

## Direct Python dependencies

These are the direct runtime dependencies declared in `requirements.txt` and listed by the wizard. Required packages enable core transcription; optional packages enable the named feature:

| Package | Needed for | Purpose |
| --- | --- | --- |
| `openai-whisper` | Required | Local speech-to-text models and transcription API |
| `torch` | Required | CPU tensor/runtime backend used by Whisper |
| `numpy` | Required | Audio sample arrays, RMS calculations, and embeddings |
| `imageio-ffmpeg` | Required | Supplies a bundled FFmpeg executable |
| `resemblyzer` | Optional | Local voice embeddings for speaker clustering and profile matching |
| `pywin32` | Optional | Python COM client for Outlook Classic; a hidden PowerShell COM fallback is used if Python activation fails |
| `soundcard` | Optional | Windows WASAPI loopback capture for live system playback recording |

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

`webrtcvad` is a native extension installed as part of Resemblyzer's dependency tree, not a direct entry in `requirements.txt`. If pip reports that Microsoft Visual C++ 14.0 or later is required, install the C++ Build Tools. This is a compiler prerequisite, not a PyPI firewall error.

## Models and local data

The wizard can download and validate:

- Whisper `small.en` by default; `Setup_TranscriptForge.bat all` selects `tiny.en`, `base.en`, and `small.en`.
- The Resemblyzer voice encoder used by optional local speaker identification.

Whisper models are stored under:

```text
%LOCALAPPDATA%\LocalAudioTranscriber\whisper-models\
```

Speaker profiles are stored under:

```text
%LOCALAPPDATA%\LocalAudioTranscriber\speaker-profiles.json
```

The profile file contains confirmed voice embeddings and names, not permanent audio samples. Temporary decoded WAV files and speaker review clips are removed after processing. Other local settings include output-folder history, scheduled-scan folder settings, live-recording folder settings, the **Add content** provider history in `content-provider-history.json`, filename templates, transcription history, and removed-sample decisions under `%LOCALAPPDATA%\LocalAudioTranscriber\`.

## Restricted-PC troubleshooting

- At the Summary stage, use **Copy IT report** or **Save IT report**. The report identifies TranscriptForge, the Python executable that ran pip or the model downloader, failed package names, and any download hosts found in the error output. Give IT the exact Python executable path and request HTTPS access to the reported package/model hosts.
- If the report says `webrtcvad` needs Microsoft Visual C++ 14.0 or later, this is not a download block. Ask IT to install or approve Visual Studio Build Tools with the MSVC x64/x86 tools and a Windows SDK. The wizard's Welcome stage has a link to Microsoft's Build Tools page.
- A failed optional dependency does not block core transcription. The Summary stage lists missing optional features, and the wizard continues trying other packages and selected model downloads after individual failures.
- TLS interception, proxy rules, GitHub/PyPI allow-listing, or quota policies can block package/model downloads. The installer cannot bypass those policies.
- If `winget` is unavailable, install Python 3.11+ through the organization's approved software channel, ensure the Python Launcher and Tkinter are included, then rerun setup.
- Package installs use `--no-cache-dir` to force fresh package downloads. If one package fails, retry it from the Dependencies stage after the network or toolchain issue is addressed.
- If the model download is interrupted, rerun setup. Completed files are reused and incomplete downloads are handled by the Whisper loader.
- If the PC has no internet access, obtain approved offline wheels and model files from the administrator; do not copy model files or profiles into Git source control.
- A speaker profile is sensitive biometric data. Use TranscriptForge's profile management and configuration export/import features according to local policy.

## Manual recovery commands

From the TranscriptForge root folder, the guided wizard is the recommended setup route. These commands are available for manual recovery and do not provide the wizard's per-package continuation or IT report:

```powershell
py -3 -m pip install --user --no-cache-dir -r requirements.txt
py -3 -m transcriptforge.cli models download small.en
py -3 -c "from resemblyzer import VoiceEncoder; VoiceEncoder(device='cpu')"
py -3 -m transcriptforge
```

All audio processing after setup is local. Audio and transcript content are not sent to a cloud transcription service.
