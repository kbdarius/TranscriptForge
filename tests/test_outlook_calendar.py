import base64
import json
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch
import unittest
from datetime import datetime

from transcriptforge import outlook_calendar
from transcriptforge.outlook_calendar import meetings_on, today_meetings


def _reader(_day):
    return [{
        "subject": "SW Daily Standup",
        "start": datetime(2026, 9, 22, 8, 45),
        "end": datetime(2026, 9, 22, 9, 0),
        "organizer": "Keivan Darius",
        "attendees": ["Alex Yu", "Keivan Darius", "Prabhu Sannachi"],
    }]


class OutlookCalendarTests(unittest.TestCase):
    def test_meeting_preserves_people_once_and_displays_time(self):
        meetings = today_meetings(datetime(2026, 9, 22), reader=_reader)
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].display, "8:45 AM - SW Daily Standup")
        self.assertEqual(meetings[0].possible_speakers, ["Keivan Darius", "Alex Yu", "Prabhu Sannachi"])

    def test_meetings_on_queries_the_recording_day(self):
        requested_days = []

        def reader(day):
            requested_days.append(day)
            return _reader(day)

        requested = datetime(2026, 9, 22, 8, 46)
        meetings_on(requested, reader=reader)
        self.assertEqual(requested_days, [requested])

    def test_powershell_fallback_parses_classic_outlook_calendar_json(self):
        day = datetime(2026, 9, 22, 8, 46)
        payload = {
            "meetings": [{
                "subject": "SW Daily Standup",
                "start": "2026-09-22T08:45:00.000000",
                "end": "2026-09-22T09:00:00.000000",
                "organizer": "Keivan Darius",
                "attendees": ["Alex Yu"],
            }]
        }
        completed = subprocess.CompletedProcess(
            args=["powershell.exe"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        with (
            patch.object(outlook_calendar.shutil, "which", return_value="powershell.exe"),
            patch.object(outlook_calendar.subprocess, "run", return_value=completed) as run,
        ):
            meetings = outlook_calendar._read_day_with_powershell(day)

        self.assertEqual(meetings[0]["start"], datetime(2026, 9, 22, 8, 45))
        self.assertEqual(meetings[0]["attendees"], ["Alex Yu"])
        command = run.call_args.args[0]
        self.assertIn("-STA", command)
        self.assertEqual(
            run.call_args.kwargs["creationflags"],
            getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        encoded = command[command.index("-EncodedCommand") + 1]
        script = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn("New-Object -ComObject Outlook.Application", script)
        self.assertNotIn("Microsoft.Graph", script)

    def test_python_classic_com_failure_uses_powershell_fallback(self):
        class FakeComError(Exception):
            pass

        pythoncom = ModuleType("pythoncom")
        pythoncom.com_error = FakeComError
        win32com = ModuleType("win32com")
        win32com.__path__ = []
        client = ModuleType("win32com.client")
        win32com.client = client
        day = datetime(2026, 9, 22)
        expected = _reader(day)

        with (
            patch.dict(
                sys.modules,
                {
                    "pythoncom": pythoncom,
                    "win32com": win32com,
                    "win32com.client": client,
                },
            ),
            patch.object(
                outlook_calendar,
                "_read_day_with_pywin32",
                side_effect=FakeComError("Classic Outlook server activation failed"),
            ),
            patch.object(outlook_calendar, "_read_day_with_powershell", return_value=expected) as fallback,
        ):
            actual = outlook_calendar._read_day_with_outlook(day)

        self.assertEqual(actual, expected)
        fallback.assert_called_once_with(day)

    def test_missing_pywin32_uses_classic_powershell_fallback(self):
        day = datetime(2026, 9, 22)
        expected = _reader(day)
        with (
            patch.dict(sys.modules, {"pythoncom": None, "win32com": None, "win32com.client": None}),
            patch.object(outlook_calendar, "_read_day_with_powershell", return_value=expected) as fallback,
        ):
            actual = outlook_calendar._read_day_with_outlook(day)

        self.assertEqual(actual, expected)
        fallback.assert_called_once_with(day)
