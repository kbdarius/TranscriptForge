import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from transcriptforge.app import App, NO_MEETING_SELECTION
from transcriptforge.controller import _review_speaker_names
from transcriptforge.outlook_calendar import OutlookMeeting
from transcriptforge.speakers import SpeakerProfileStore


class _FakeCombo:
    def __init__(self, value="", values=(), focused=False):
        self.value = value
        self.values = list(values)
        self.configure_calls = 0
        self.focused = focused

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def configure(self, **options):
        self.configure_calls += 1
        if "values" in options:
            self.values = list(options["values"])

    def focus_get(self):
        return self if self.focused else None


class _FakeVariable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _FakeDialog:
    def winfo_exists(self):
        return True


class ScheduledMeetingDialogTests(unittest.TestCase):
    def test_no_meeting_option_keeps_current_workflow_available(self):
        self.assertIn("No meeting selected", NO_MEETING_SELECTION)

    def test_speaker_limit_accepts_empty_and_positive_whole_numbers(self):
        self.assertIsNone(App._parse_speaker_limit(""))
        self.assertIsNone(App._parse_speaker_limit("  "))
        self.assertEqual(App._parse_speaker_limit("4"), 4)

    def test_speaker_limit_rejects_invalid_values(self):
        for value in ("0", "-1", "2.5", "many"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    App._parse_speaker_limit(value)

    def test_recording_timestamp_is_preferred_over_file_modified_time(self):
        source = Path("Standup-20260925_084638-Meeting Recording.mp4")
        self.assertEqual(
            App._recording_datetime(source),
            datetime(2026, 9, 25, 8, 46, 38),
        )

    def test_modified_time_is_fallback_when_filename_has_no_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "recording.mp4"
            source.write_bytes(b"audio")
            expected = datetime(2024, 1, 2, 3, 4, 5)
            timestamp = expected.timestamp()
            os.utime(source, (timestamp, timestamp))
            self.assertEqual(App._recording_datetime(source), expected)

    def test_meeting_review_suggestions_are_limited_but_empty_meeting_keeps_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SpeakerProfileStore(Path(directory) / "profiles.json")
            store.add_confirmed_embedding("Alex Yu", [1.0, 0.0])
            store.add_confirmed_embedding("Blair Moore", [0.0, 1.0])
            self.assertEqual(_review_speaker_names(store, None), ["Alex Yu", "Blair Moore"])
            self.assertEqual(_review_speaker_names(store, ["Alex Yu"]), ["Alex Yu"])

    def test_selected_meeting_is_carried_to_the_scheduled_recording_dialog(self):
        selected = OutlookMeeting(
            "Example Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Sample Organizer",
            ("Guest One", "Guest Two"),
        )
        recording_day_meetings = [
            OutlookMeeting(
                selected.subject,
                selected.start,
                selected.end,
                selected.organizer,
                selected.attendees,
            )
        ]
        self.assertIs(
            App._matching_scheduled_meeting(recording_day_meetings, selected),
            recording_day_meetings[0],
        )

    def test_scheduled_meeting_carryover_matches_same_appointment_after_attendee_refresh(self):
        selected = OutlookMeeting(
            "Example Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Sample Organizer",
            ("Guest One",),
        )
        refreshed = OutlookMeeting(
            " Example   Standup ",
            selected.start,
            selected.end,
            "Sample Organizer",
            ("Guest One", "Guest Two"),
        )
        self.assertIs(
            App._matching_scheduled_meeting([refreshed], selected),
            refreshed,
        )

    def test_scheduled_meeting_carryover_does_not_use_a_different_date(self):
        selected = OutlookMeeting(
            "Example Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Sample Organizer",
            ("Guest One",),
        )
        another_day = OutlookMeeting(
            selected.subject,
            datetime(2026, 9, 29, 8, 45),
            datetime(2026, 9, 29, 9, 0),
            selected.organizer,
            selected.attendees,
        )
        self.assertIsNone(App._matching_scheduled_meeting([another_day], selected))

    @staticmethod
    def _scheduled_dialog_state(selected_meeting, user_selected=False):
        dialog = _FakeDialog()
        state = SimpleNamespace(
            _scheduled_meeting_dialog=dialog,
            _scheduled_meeting_combo=_FakeCombo(),
            _scheduled_meeting_var=_FakeVariable(NO_MEETING_SELECTION),
            _scheduled_meeting_status=_FakeVariable(),
            _scheduled_speaker_limit_var=_FakeVariable(),
            _scheduled_meeting_user_selected=user_selected,
            _scheduled_meetings=[],
            selected_outlook_meeting=selected_meeting,
            _matching_scheduled_meeting=App._matching_scheduled_meeting,
        )
        return state, dialog

    def test_scheduled_dialog_preselects_matching_meeting_and_invitee_limit(self):
        selected = OutlookMeeting(
            "SW Daily Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Keivan Darius",
            ("Alex Yu", "Prabhu Sannachi"),
        )
        state, dialog = self._scheduled_dialog_state(selected)

        App._set_scheduled_meetings(state, dialog, [selected])

        self.assertEqual(state._scheduled_meeting_var.get(), selected.display)
        self.assertEqual(state._scheduled_speaker_limit_var.get(), "3")
        self.assertIn("carried over", state._scheduled_meeting_status.get())

    def test_scheduled_dialog_preserves_explicit_no_meeting_choice(self):
        selected = OutlookMeeting(
            "SW Daily Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Keivan Darius",
            ("Alex Yu",),
        )
        state, dialog = self._scheduled_dialog_state(selected, user_selected=True)

        App._set_scheduled_meetings(state, dialog, [selected])

        self.assertEqual(state._scheduled_meeting_var.get(), NO_MEETING_SELECTION)
        self.assertEqual(state._scheduled_speaker_limit_var.get(), "")

    def test_free_form_speaker_name_is_kept_when_recent_choices_update(self):
        current = _FakeCombo("  Guest   Speaker ", focused=True)
        another_focused_row = _FakeCombo(focused=True)
        another_row = _FakeCombo()
        recent_names = []

        App._remember_speaker_name(
            current,
            [current, another_focused_row, another_row],
            ["Alex Yu"],
            recent_names,
        )

        self.assertEqual(current.get(), "Guest Speaker")
        self.assertEqual(current.configure_calls, 0)
        self.assertEqual(another_focused_row.configure_calls, 0)
        self.assertIn("Guest Speaker", another_row.values)
        self.assertEqual(recent_names[0], "Guest Speaker")


if __name__ == "__main__":
    unittest.main()
