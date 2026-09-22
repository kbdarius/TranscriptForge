@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher was not found. Run Setup_TranscriptForge.bat first.
    pause
    exit /b 1
)

set "PACKAGE=%~dp0TranscriptForge_Example.tfconfig"
echo Creating the private TranscriptForge configuration package...
py -3 -m transcriptforge.cli config export "%PACKAGE%"
if errorlevel 1 (
    echo.
    echo Configuration export failed. Run Setup_TranscriptForge.bat first and try again.
    pause
    exit /b 1
)

echo.
echo Created: %PACKAGE%
echo This file contains sensitive voice-learning data. Do not commit it to GitHub.
pause
exit /b 0
