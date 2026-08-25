@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher was not found.
    echo Install Python 3.11 or newer, then run this file again.
    pause
    exit /b 1
)

where pyw >nul 2>&1
if errorlevel 1 (
    py -3 -m transcriptforge
    if errorlevel 1 pause
    exit /b %errorlevel%
)

start "TranscriptForge" pyw -3 -m transcriptforge
exit /b 0

