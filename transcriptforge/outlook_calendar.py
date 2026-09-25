"""Read Outlook Classic appointments without Graph access."""

from __future__ import annotations

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
    """Use the installed Outlook Classic COM interface in the calling thread."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("Outlook calendar support requires pywin32. Run Setup_TranscriptForge.bat again.") from exc

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
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
