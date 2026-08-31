@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo TranscriptForge setup v0.17.0
echo ========================================
echo.

set "PYTHON="
py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3.11"

if not defined PYTHON (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo Python 3.11 or newer was not found. Attempting a per-user Python 3.11 install through winget...
    where winget >nul 2>&1
    if errorlevel 1 goto :python_missing
    winget install --id Python.Python.3.11 --scope user --accept-source-agreements --accept-package-agreements
    if errorlevel 1 goto :python_install_failed
    py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3.11"
)

if not defined PYTHON goto :python_missing

echo Using %PYTHON%
%PYTHON% --version
if errorlevel 1 goto :python_version_failed

echo Checking Tkinter...
%PYTHON% -c "import tkinter; print('Tkinter: ready')"
if errorlevel 1 goto :tkinter_failed

echo Checking pip...
%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip is missing. Bootstrapping pip...
    %PYTHON% -m ensurepip --upgrade --user
    if errorlevel 1 goto :pip_failed
)

echo Updating pip for this user...
%PYTHON% -m pip install --user --upgrade pip
if errorlevel 1 goto :pip_failed

echo Installing TranscriptForge dependencies without using the local pip cache...
%PYTHON% -m pip install --user --no-cache-dir -r requirements.txt
if errorlevel 1 goto :dependency_failed

echo Verifying installed packages and bundled FFmpeg...
%PYTHON% -c "import whisper, torch, numpy, imageio_ffmpeg, resemblyzer; print('Whisper:', whisper.__version__); print('Torch:', torch.__version__); print('NumPy:', numpy.__version__); print('FFmpeg:', imageio_ffmpeg.get_ffmpeg_exe()); print('Speaker encoder package: ready')"
if errorlevel 1 goto :verification_failed

if /i "%~1"=="all" goto :download_all

call :download_model small.en
if errorlevel 1 goto :model_failed
goto :speaker_encoder

:download_all
call :download_model tiny.en
if errorlevel 1 goto :model_failed
call :download_model base.en
if errorlevel 1 goto :model_failed
call :download_model small.en
if errorlevel 1 goto :model_failed

:speaker_encoder
echo Initializing the local Resemblyzer speaker encoder...
%PYTHON% -c "from resemblyzer import VoiceEncoder; VoiceEncoder(device='cpu'); print('Speaker encoder model: ready')"
if errorlevel 1 goto :speaker_failed

echo.
echo ========================================
echo Setup completed successfully.
echo You can now double-click Run_TranscriptForge.bat.
echo ========================================
pause
exit /b 0

:download_model
echo Checking Whisper model %~1...
%PYTHON% -m transcriptforge.cli models download %~1
exit /b %errorlevel%

:python_missing
echo.
echo ERROR: Python 3.11 or newer was not found, and winget could not install it.
echo Install Python through your organization's approved software channel, then run this file again.
goto :failed

:python_install_failed
echo.
echo ERROR: The winget Python installation failed or was blocked by policy.
goto :failed

:python_version_failed
echo.
echo ERROR: Python 3.11 or newer is required.
goto :failed

:tkinter_failed
echo.
echo ERROR: Tkinter is missing. Repair Python with the standard Tcl/Tk component enabled.
goto :failed

:pip_failed
echo.
echo ERROR: pip could not be installed or updated.
goto :failed

:dependency_failed
echo.
echo ERROR: One or more Python dependencies could not be installed.
echo Check the network, proxy, TLS, and package allow-list policy, then rerun setup.
goto :failed

:verification_failed
echo.
echo ERROR: Installed packages or bundled FFmpeg could not be imported successfully.
goto :failed

:model_failed
echo.
echo ERROR: A Whisper model download or validation failed.
echo Check the network, proxy, TLS, and model allow-list policy, then rerun setup.
goto :failed

:speaker_failed
echo.
echo ERROR: The Resemblyzer speaker encoder could not be downloaded or initialized.
goto :failed

:failed
echo.
echo Setup did not complete. No application transcription was started.
pause
exit /b 1

