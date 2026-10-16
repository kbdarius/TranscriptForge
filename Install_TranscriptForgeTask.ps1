param(
    [string]$RecordingFolder,
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "TranscriptForge - Check Recordings"
$pythonLauncher = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonLauncher) {
    throw "Python Launcher (py.exe) was not found. Install Python, then run this script again."
}
$pythonw = & $pythonLauncher -3 -c "import sys; from pathlib import Path; print(Path(sys.executable).with_name('pythonw.exe'))"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3 could not be resolved. Install Python, then run this script again."
}
$pythonw = $pythonw.Trim()
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "Windowless Python (pythonw.exe) was not found for the selected Python 3 installation: $pythonw"
}
$windowlessLauncher = (Get-Command pyw.exe -ErrorAction SilentlyContinue).Source
if ($windowlessLauncher) {
    $python = $windowlessLauncher
    $pythonArguments = "-3"
} else {
    $python = $pythonw
    $pythonArguments = ""
}
if (-not (Test-Path -LiteralPath $projectRoot)) {
    throw "TranscriptForge folder was not found: $projectRoot"
}

$arguments = "$pythonArguments -m transcriptforge --scheduled-scan".Trim()
if (-not [string]::IsNullOrWhiteSpace($RecordingFolder)) {
    $arguments += " --folder `"$RecordingFolder`""
}
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Created: $taskName"
Write-Host "Scanner: $python (windowless)"
if ([string]::IsNullOrWhiteSpace($RecordingFolder)) {
    Write-Host "Folder:  reads the saved TranscriptForge recording-folder setting at each scan"
} else {
    Write-Host "Folder:  saved setting takes precedence; fallback argument is $RecordingFolder"
}
Write-Host "Project: $projectRoot"
Write-Host "Checks:  every $IntervalMinutes minutes while you are logged in"
Write-Host "Manage it in Windows Task Scheduler under Task Scheduler Library."
