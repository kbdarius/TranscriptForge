@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo TranscriptForge guided setup
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
    %PYTHON% -c "import sys; raise SystemExit(0 if sys.prefix == sys.base_prefix else 1)" >nul 2>&1
    if errorlevel 1 (
        %PYTHON% -m ensurepip --upgrade
    ) else (
        %PYTHON% -m ensurepip --upgrade --user
    )
    if errorlevel 1 goto :pip_failed
)

%PYTHON% -c "import transcriptforge.setup_wizard" >nul 2>&1
if errorlevel 1 goto :wizard_failed

set "WIZARD_ARGS="
if /i "%~1"=="all" set "WIZARD_ARGS=--all-models"
set "PYTHON_EXE="
set "PYTHONW_EXE="
for /f "delims=" %%I in ('%PYTHON% -c "import sys; print(sys.executable)"') do set "PYTHON_EXE=%%I"
if not defined PYTHON_EXE goto :python_version_failed
for %%I in ("%PYTHON_EXE%") do set "PYTHONW_EXE=%%~dpIpythonw.exe"

echo Opening the guided setup wizard...
if exist "%PYTHONW_EXE%" (
    start "TranscriptForge Setup" "%PYTHONW_EXE%" -m transcriptforge.setup_wizard %WIZARD_ARGS%
    if errorlevel 1 goto :wizard_failed
    exit /b 0
)

%PYTHON% -m transcriptforge.setup_wizard %WIZARD_ARGS%
if errorlevel 1 goto :wizard_failed
exit /b 0

:python_missing
echo.
echo ERROR: Python 3.11 or newer was not found, and winget could not install it.
echo Install Python through your organization's approved software channel, including Tkinter and the Python Launcher.
goto :failed

:python_install_failed
echo.
echo ERROR: The winget Python installation failed or was blocked by policy.
goto :failed

:python_version_failed
echo.
echo ERROR: Python 3.11 or newer could not be started.
goto :failed

:tkinter_failed
echo.
echo ERROR: Tkinter is missing. Repair Python with the standard Tcl/Tk component enabled.
goto :failed

:pip_failed
echo.
echo ERROR: pip could not be installed. Ask IT to allow the approved Python installation or repair channel.
goto :failed

:wizard_failed
echo.
echo ERROR: The TranscriptForge setup wizard could not be started.
goto :failed

:failed
echo.
echo Setup could not open the guided wizard. No application transcription was started.
pause
exit /b 1
