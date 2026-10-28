"""Read Outlook Classic appointments without Graph access."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class OutlookMeeting:
    subject: str
    start: datetime
    end: datetime
    organizer: str
    attendees: tuple[str, ...]

    @property
    def display(self) -> str:
        return f"{self.start.strftime('%I:%M %p').lstrip('0')} - {self.subject}"

    @property
    def possible_speakers(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for name in (self.organizer, *self.attendees):
            clean = " ".join(name.split())
            if clean and clean.casefold() not in seen:
                values.append(clean)
                seen.add(clean.casefold())
        return values


def _read_day_with_outlook(day: datetime) -> list[dict]:
    """Read Outlook Classic through Python COM, with a hidden PowerShell fallback."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return _read_day_with_powershell(day)

    try:
        return _read_day_with_pywin32(day, pythoncom, win32com.client)
    except pythoncom.com_error as python_error:
        try:
            return _read_day_with_powershell(day)
        except RuntimeError as fallback_error:
            raise RuntimeError(
                "Python could not access Outlook Classic over COM, and the hidden PowerShell COM "
                f"fallback also failed. Python error: {python_error}; fallback error: {fallback_error}"
            ) from fallback_error


def _read_day_with_pywin32(day: datetime, pythoncom, client) -> list[dict]:
    pythoncom.CoInitialize()
    try:
        outlook = client.GetActiveObject("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)  # olFolderCalendar
        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        restriction = f"[Start] < '{day_end.strftime('%m/%d/%Y %I:%M %p')}' AND [End] > '{day_start.strftime('%m/%d/%Y %I:%M %p')}'"
        results: list[dict] = []
        for meeting in items.Restrict(restriction):
            if meeting.Class != 26:  # olAppointment
                continue
            attendees = []
            for index in range(1, meeting.Recipients.Count + 1):
                recipient = meeting.Recipients.Item(index)
                if recipient.Type in (1, 2):  # required or optional
                    attendees.append(str(recipient.Name))
            results.append({
                "subject": str(meeting.Subject),
                "start": meeting.Start,
                "end": meeting.End,
                "organizer": str(meeting.Organizer),
                "attendees": attendees,
            })
        return results
    finally:
        pythoncom.CoUninitialize()


def _read_day_with_powershell(day: datetime) -> list[dict]:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise RuntimeError("Windows PowerShell was not found for the Outlook Classic COM fallback.")

    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    lower_bound = day_start.strftime("%m/%d/%Y %I:%M %p")
    upper_bound = day_end.strftime("%m/%d/%Y %I:%M %p")
    script = "\n".join((
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
        "for ($attempt = 1; $attempt -le 4; $attempt++) {",
        "  try {",
        "    $app = New-Object -ComObject Outlook.Application",
        "    $namespace = $app.GetNamespace('MAPI')",
        "    $items = $namespace.GetDefaultFolder(9).Items",
        "    $items.Sort('[Start]')",
        "    $items.IncludeRecurrences = $true",
        f'    $restriction = "[Start] < \'{upper_bound}\' AND [End] > \'{lower_bound}\'"',
        "    $selected = $items.Restrict($restriction)",
        "    $meetings = @(",
        "      foreach ($item in $selected) {",
        "        if ($item.Class -eq 26) {",
        "          $attendees = @()",
        "          for ($i = 1; $i -le $item.Recipients.Count; $i++) {",
        "            $recipient = $item.Recipients.Item($i)",
        "            if ($recipient.Type -in 1, 2) { $attendees += [string]$recipient.Name }",
        "          }",
        "          [PSCustomObject]@{",
        "            subject = [string]$item.Subject",
        "            start = $item.Start.ToString('yyyy-MM-ddTHH:mm:ss.ffffff')",
        "            end = $item.End.ToString('yyyy-MM-ddTHH:mm:ss.ffffff')",
        "            organizer = [string]$item.Organizer",
        "            attendees = @($attendees)",
        "          }",
        "        }",
        "      }",
        "    )",
        "    $output = [PSCustomObject]@{ meetings = [object[]]$meetings }",
        "    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $output -Compress -Depth 4))",
        "    break",
        "  } catch {",
        "    $hresult = $_.Exception.HResult",
        "    $isOutlookBusy = $hresult -in @(-2147418111, -2147417846)",
        "    if ($isOutlookBusy -and $attempt -lt 4) {",
        "      Start-Sleep -Milliseconds (300 * $attempt)",
        "      continue",
        "    }",
        "    if ($isOutlookBusy) {",
        "      [Console]::Error.WriteLine(\"Outlook Classic remained busy after $attempt attempts: \" + $_.Exception.Message)",
        "    } else {",
        "      [Console]::Error.WriteLine($_.Exception.Message)",
        "    }",
        "    exit 1",
        "  }",
        "}",
    ))
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-STA",
                "-NonInteractive",
                "-EncodedCommand",
                encoded_script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Outlook Classic calendar lookup through PowerShell timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start the Outlook Classic PowerShell fallback: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "No diagnostic output."
        raise RuntimeError(
            f"Outlook Classic PowerShell COM fallback failed with exit code "
            f"{completed.returncode}: {detail}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Outlook Classic PowerShell COM fallback returned invalid JSON.") from exc
    meetings = payload.get("meetings") if isinstance(payload, dict) else None
    if not isinstance(meetings, list):
        raise RuntimeError("Outlook Classic PowerShell COM fallback returned an unexpected response.")

    results = []
    for item in meetings:
        if not isinstance(item, dict):
            raise RuntimeError("Outlook Classic PowerShell COM fallback returned an invalid meeting.")
        try:
            start = datetime.fromisoformat(item["start"])
            end = datetime.fromisoformat(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Outlook Classic PowerShell COM fallback returned invalid meeting times.") from exc
        attendees = item.get("attendees", [])
        if attendees is None:
            attendees = []
        if not isinstance(attendees, list):
            raise RuntimeError("Outlook Classic PowerShell COM fallback returned invalid attendees.")
        results.append({
            "subject": item.get("subject"),
            "start": start,
            "end": end,
            "organizer": item.get("organizer", ""),
            "attendees": attendees,
        })
    return results


def meetings_on(day: datetime, reader=None) -> list[OutlookMeeting]:
    """Return the default Outlook Classic calendar's appointments for the given day."""
    payload = (reader or _read_day_with_outlook)(day)
    meetings: list[OutlookMeeting] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("subject"), str):
            continue
        attendees = item.get("attendees", [])
        if not isinstance(attendees, list):
            attendees = []
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        meetings.append(OutlookMeeting(
            subject=" ".join(item["subject"].split()),
            start=start,
            end=end,
            organizer=" ".join(str(item.get("organizer", "")).split()),
            attendees=tuple(" ".join(str(name).split()) for name in attendees if str(name).strip()),
        ))
    return sorted(meetings, key=lambda meeting: meeting.start)


def today_meetings(today: datetime | None = None, reader=None) -> list[OutlookMeeting]:
    """Return today's appointments, or appointments for the supplied date."""
    return meetings_on(today or datetime.now(), reader)
