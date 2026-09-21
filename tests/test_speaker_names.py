import unittest

from transcriptforge.speaker_names import (
    filter_speaker_name_choices,
    speaker_name_choices,
)


class SpeakerNameChoiceTests(unittest.TestCase):
    def test_recent_names_come_first_without_duplicates(self):
        choices = speaker_name_choices(
            ["Brian Lelacheur", "Keivan Darius", "Prabhu Sannachi"],
            ["Prabhu Sannachi", "KEIVAN DARIUS", "Prabhu Sannachi"],
        )
        self.assertEqual(
            choices,
            ["", "Prabhu Sannachi", "Keivan Darius", "Brian Lelacheur", "Unknown"],
        )

    def test_filter_is_case_insensitive_substring_and_keeps_recent_order(self):
        choices = filter_speaker_name_choices(
            ["Brian Lelacheur", "Dario Galdamez", "Keivan Darius", "Prabhu Sannachi"],
            "DAR",
            ["Keivan Darius", "Prabhu Sannachi"],
        )
        self.assertEqual(choices, ["Keivan Darius", "Dario Galdamez"])

    def test_recent_typed_name_is_available_for_later_rows(self):
        choices = filter_speaker_name_choices(
            ["Brian Lelacheur"], "new participant", ["New Participant"]
        )
        self.assertEqual(choices, ["New Participant"])


if __name__ == "__main__":
    unittest.main()
