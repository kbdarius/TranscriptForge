import unittest
from datetime import datetime

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
