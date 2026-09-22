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
if not exist "%PACKAGE%" (
    echo The private configuration package was not found:
    echo %PACKAGE%
    echo.
    echo Copy it from the source PC, or run Create_Example_Configuration.bat on that PC first.
    pause
    exit /b 1
)

echo Importing TranscriptForge preferences and voice-learning data...
py -3 -m transcriptforge.cli config import "%PACKAGE%"
if errorlevel 1 (
    echo.
    echo Configuration import failed. Run Setup_TranscriptForge.bat first and try again.
    pause
    exit /b 1
)

echo.
echo Configuration imported. Recording and output folders remain local to this PC.
pause
exit /b 0
