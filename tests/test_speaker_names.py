import unittest

from transcriptforge.speaker_names import (
    commit_speaker_name_value,
    filter_speaker_name_choices,
    similar_speaker_names,
    speaker_name_suggestions,
    speaker_name_choices,
    speaker_name_similarity,
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

    def test_suggestions_are_limited_to_three_visible_matches(self):
        choices = speaker_name_suggestions(
            ["Alex Yu", "Alexandra King", "Alexis Lee", "Alex Moreno"], "alex"
        )
        self.assertEqual(choices, ["Alex Moreno", "Alex Yu", "Alexandra King"])

    def test_similar_names_include_expanded_first_names_and_reversed_order(self):
        self.assertGreaterEqual(speaker_name_similarity("Alex Yu", "Alexander Yu"), 0.72)
        self.assertEqual(speaker_name_similarity("Yu, Alex", "Alex Yu"), 1.0)
        self.assertGreaterEqual(speaker_name_similarity("Bob Smith", "Robert Smith"), 0.72)
        self.assertEqual(
            similar_speaker_names("Alex Yu", ["Alexander Yu", "Blair Moore"]),
            [("Alexander Yu", speaker_name_similarity("Alex Yu", "Alexander Yu"))],
        )

    def test_enter_preserves_free_form_name_instead_of_picking_first_suggestion(self):
        self.assertEqual(
            commit_speaker_name_value(
                "New Guest", ["New Guesthouse", "New Group"], -1
            ),
            "New Guest",
        )

    def test_enter_commits_only_an_explicitly_highlighted_suggestion(self):
        self.assertEqual(
            commit_speaker_name_value(
                "Search text", ["Alex Yu", "Alexander Yu"], 1
            ),
            "Alexander Yu",
        )
        self.assertEqual(
            commit_speaker_name_value(" Guest  Person ", ["Alex Yu"], 4),
            "Guest Person",
        )


if __name__ == "__main__":
    unittest.main()
