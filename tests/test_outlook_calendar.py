import unittest
from datetime import datetime

from transcriptforge.outlook_calendar import today_meetings


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
        self.assertEqual(meetings[0].display, "8:45 AM — SW Daily Standup")
        self.assertEqual(meetings[0].possible_speakers, ["Keivan Darius", "Alex Yu", "Prabhu Sannachi"])
