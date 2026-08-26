param(
    [string]$RecordingFolder = "C:\Users\dariusk\OneDrive - stryten.com\Recordings",
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

$action = New-ScheduledTaskAction -Execute $python -Argument "-3 -m transcriptforge --scheduled-scan --folder `"$RecordingFolder`"" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Created: $taskName"
Write-Host "Folder:  $RecordingFolder"
Write-Host "Checks:  every $IntervalMinutes minutes while you are logged in"
Write-Host "Manage it in Windows Task Scheduler under Task Scheduler Library."
