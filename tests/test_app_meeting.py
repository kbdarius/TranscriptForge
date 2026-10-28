import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

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
        self.configure_options = {}

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def configure(self, **options):
        self.configure_calls += 1
        self.configure_options.update(options)
        if "values" in options:
            self.values = list(options["values"])

    def focus_get(self):
        return self if self.focused else None

    def focus_set(self):
        self.focused = True

    def icursor(self, index):
        self.cursor = index


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

    def test_main_meeting_selection_survives_calendar_refresh(self):
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
        state = SimpleNamespace(
            outlook_loading=True,
            outlook_ready=False,
            outlook_meetings=[],
            outlook_meeting_date=datetime(2026, 9, 28).date(),
            selected_outlook_meeting=selected,
            _matching_scheduled_meeting=App._matching_scheduled_meeting,
            meeting_combo=_FakeCombo(),
            refresh_meetings_button=_FakeCombo(),
            outlook_date_button=_FakeCombo(),
            meeting_var=_FakeVariable(),
        )

        App._set_outlook_meetings(state, [refreshed])

        self.assertIs(state.selected_outlook_meeting, refreshed)
        self.assertEqual(state.meeting_var.get(), refreshed.display)

    def test_selecting_a_past_outlook_date_clears_old_meeting_choices(self):
        state = SimpleNamespace(
            outlook_meeting_date=date(2026, 9, 28),
            outlook_date_button=_FakeCombo(),
            outlook_meetings=[object()],
            selected_outlook_meeting=object(),
            outlook_ready=True,
            _outlook_fetch_started=True,
            meeting_combo=_FakeCombo(),
            meeting_var=_FakeVariable("Example Standup"),
        )
        state._outlook_date_button_text = MethodType(
            App._outlook_date_button_text,
            state,
        )
        selected_date = date(2026, 9, 23)

        App._set_outlook_meeting_date(state, selected_date)

        self.assertEqual(state.outlook_meeting_date, selected_date)
        self.assertEqual(state.outlook_date_button.configure_options["text"], "📅 2026-09-23")
        self.assertEqual(state.meeting_combo.values, [])
        self.assertEqual(state.meeting_combo.configure_options["state"], "disabled")
        self.assertEqual(state.meeting_var.get(), "Click Refresh to load meetings for 2026-09-23")
        self.assertEqual(state.outlook_meetings, [])
        self.assertIsNone(state.selected_outlook_meeting)
        self.assertFalse(state.outlook_ready)
        self.assertFalse(state._outlook_fetch_started)

    def test_refresh_queries_the_selected_outlook_date(self):
        selected_date = date(2026, 9, 23)
        events = []
        state = SimpleNamespace(
            _outlook_fetch_started=False,
            outlook_loading=False,
            outlook_meeting_date=selected_date,
            refresh_meetings_button=_FakeCombo(),
            outlook_date_button=_FakeCombo(),
            selected_outlook_meeting=None,
            meeting_var=_FakeVariable(),
            events=SimpleNamespace(put=events.append),
        )
        with (
            patch("transcriptforge.app.meetings_on", return_value=[]) as meetings_on,
            patch("transcriptforge.app.threading.Thread") as thread,
        ):
            App._load_outlook_meetings(state)
            thread.call_args.kwargs["target"]()

        meetings_on.assert_called_once_with(
            datetime.combine(selected_date, datetime.min.time())
        )
        self.assertEqual(events, [("outlook_meetings", [])])
        self.assertEqual(
            state.meeting_var.get(),
            "Loading Outlook meetings for 2026-09-23...",
        )

    def test_empty_outlook_result_names_the_selected_date(self):
        state = SimpleNamespace(
            outlook_loading=True,
            outlook_ready=False,
            outlook_meetings=[],
            outlook_meeting_date=date(2026, 9, 23),
            selected_outlook_meeting=None,
            _matching_scheduled_meeting=App._matching_scheduled_meeting,
            meeting_combo=_FakeCombo(),
            refresh_meetings_button=_FakeCombo(),
            outlook_date_button=_FakeCombo(),
            meeting_var=_FakeVariable(),
        )
        state._no_outlook_meetings_text = MethodType(
            App._no_outlook_meetings_text,
            state,
        )

        App._set_outlook_meetings(state, [])

        self.assertEqual(state.meeting_var.get(), "No Outlook meetings on 2026-09-23")

    def test_scheduled_meeting_override_updates_main_window_selection(self):
        selected = OutlookMeeting(
            "Example Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Sample Organizer",
            ("Guest One",),
        )
        state = SimpleNamespace(
            outlook_meetings=[selected],
            selected_outlook_meeting=None,
            meeting_var=_FakeVariable("Select a meeting (optional)"),
        )

        App._set_selected_meeting(state, selected)

        self.assertIs(state.selected_outlook_meeting, selected)
        self.assertEqual(state.meeting_var.get(), selected.display)

    def test_explicit_no_meeting_override_clears_main_selection(self):
        selected = OutlookMeeting(
            "Example Standup",
            datetime(2026, 9, 28, 8, 45),
            datetime(2026, 9, 28, 9, 0),
            "Sample Organizer",
            ("Guest One",),
        )
        state = SimpleNamespace(
            outlook_meetings=[selected],
            outlook_meeting_date=selected.start.date(),
            selected_outlook_meeting=selected,
            meeting_var=_FakeVariable(selected.display),
        )

        App._set_selected_meeting(state, None)

        self.assertIsNone(state.selected_outlook_meeting)
        self.assertEqual(state.meeting_var.get(), "Select a meeting (optional)")

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

    def test_speaker_name_typing_keeps_query_and_focus_while_filtering(self):
        current = _FakeCombo("Alex", values=["Alex Yu"], focused=True)
        names = ["Alex Yu", "Alexandra King"]
        shown = []
        app = SimpleNamespace(
            _show_speaker_name_suggestions=lambda *args: shown.append(args)
        )

        App._update_speaker_name_suggestions(
            app, SimpleNamespace(keysym="x"), current, names, [], [current]
        )

        self.assertEqual(current.get(), "Alex")
        self.assertEqual(current.values, ["Alex Yu"])
        self.assertEqual(current.configure_calls, 0)
        self.assertTrue(current.focused)
        self.assertEqual(current._tf_suggestions, ["Alex Yu", "Alexandra King"])
        self.assertEqual(shown, [(current, current._tf_suggestions, [current], names, [])])

    def test_refresh_rechecks_matches_and_returns_focus_to_the_name_field(self):
        current = _FakeCombo("Alex", focused=False)
        names = ["Alex Yu", "Blair Moore"]
        shown = []
        app = SimpleNamespace(
            _show_speaker_name_suggestions=lambda *args: shown.append(args)
        )

        App._refresh_speaker_name_suggestions(app, current, names, [], [current])

        self.assertEqual(current.get(), "Alex")
        self.assertTrue(current.focused)
        self.assertEqual(current._tf_suggestions, ["Alex Yu"])
        self.assertEqual(len(shown), 1)

    def test_mouse_suggestion_replaces_typed_text(self):
        current = _FakeCombo("Alex", focused=False)
        names = ["Alex Yu", "Alexander King"]
        recent_names = []
        app = SimpleNamespace(
            _hide_speaker_name_suggestions=lambda _combo: None,
            _remember_speaker_name=App._remember_speaker_name,
        )
        current._tf_suggestions = names

        App._select_speaker_name_suggestion(
            app, current, 1, [current], names, recent_names
        )

        self.assertEqual(current.get(), "Alexander King")
        self.assertEqual(current.cursor, "end")
        self.assertTrue(current.focused)
        self.assertEqual(recent_names, ["Alexander King"])

    def test_keyboard_navigation_keeps_search_text_until_enter(self):
        current = _FakeCombo("Alex", focused=True)
        names = ["Alex Yu", "Alexandra King"]
        recent_names = []
        current._tf_suggestions = ["Stale result"]
        current._tf_suggestion_index = -1
        app = SimpleNamespace(
            _show_speaker_name_suggestions=lambda *_args: None,
            _hide_speaker_name_suggestions=lambda _combo: None,
            _remember_speaker_name=App._remember_speaker_name,
        )

        result = App._navigate_speaker_name_suggestions(
            app, SimpleNamespace(keysym="Down"), current, names, recent_names, [current]
        )

        self.assertEqual(result, "break")
        self.assertEqual(current.get(), "Alex")
        self.assertEqual(current._tf_suggestion_index, 0)
        self.assertEqual(current._tf_suggestions, names)

        result = App._navigate_speaker_name_suggestions(
            app, SimpleNamespace(keysym="Return"), current, names, recent_names, [current]
        )

        self.assertEqual(result, "break")
        self.assertEqual(current.get(), "Alex Yu")
        self.assertEqual(recent_names, ["Alex Yu"])


if __name__ == "__main__":
    unittest.main()
