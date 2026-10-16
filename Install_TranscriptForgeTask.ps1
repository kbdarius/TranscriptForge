param(
    [string]$RecordingFolder,
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "TranscriptForge - Check Recordings"
$python = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "Python Launcher (py.exe) was not found. Install Python, then run this script again."
}
if (-not (Test-Path -LiteralPath $projectRoot)) {
    throw "TranscriptForge folder was not found: $projectRoot"
}

$arguments = "-3 -m transcriptforge --scheduled-scan"
if (-not [string]::IsNullOrWhiteSpace($RecordingFolder)) {
    $arguments += " --folder `"$RecordingFolder`""
}
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Created: $taskName"
if ([string]::IsNullOrWhiteSpace($RecordingFolder)) {
    Write-Host "Folder:  reads the saved TranscriptForge recording-folder setting at each scan"
} else {
    Write-Host "Folder:  saved setting takes precedence; fallback argument is $RecordingFolder"
}
Write-Host "Project: $projectRoot"
Write-Host "Checks:  every $IntervalMinutes minutes while you are logged in"
Write-Host "Manage it in Windows Task Scheduler under Task Scheduler Library."
