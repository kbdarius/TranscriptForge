import unittest

from transcriptforge.controller import TranscriptionController
from transcriptforge.models import Segment


class FailingSummaryClient:
    last_summary_used_excerpt = False

    def summarize(self, *_args, **_kwargs):
        raise RuntimeError("network unavailable")

    def cancel(self):
        pass


class SuccessfulSummaryClient:
    last_summary_used_excerpt = False

    def summarize(self, *_args, **_kwargs):
        return "- **DIU:** Verification planning"

    def cancel(self):
        pass


class ControllerSummaryTests(unittest.TestCase):
    def test_summary_failure_is_logged_and_does_not_raise(self):
        events = []
        controller = TranscriptionController(events.append, FailingSummaryClient)
        controller.callback = lambda kind, value=None: events.append((kind, value))

        summary = controller._generate_summary([Segment(0, 1, "Discussion")], "DIU", "Review")

        self.assertEqual(summary, "")
        self.assertTrue(any(kind == "log" and "skipped" in value for kind, value in events))
        self.assertIsNone(controller.summary_client)

    def test_successful_summary_is_returned(self):
        events = []
        controller = TranscriptionController(lambda kind, value=None: events.append((kind, value)), SuccessfulSummaryClient)
        summary = controller._generate_summary([Segment(0, 1, "Discussion")], "DIU", "Review")
        self.assertEqual(summary, "- **DIU:** Verification planning")
        self.assertTrue(any(kind == "log" and "Added" in value for kind, value in events))


if __name__ == "__main__":
    unittest.main()
