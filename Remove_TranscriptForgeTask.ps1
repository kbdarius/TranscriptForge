$ErrorActionPreference = "Stop"
$taskName = "TranscriptForge - Check Recordings"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
Write-Host "Removed: $taskName"
