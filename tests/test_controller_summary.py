import unittest

from transcriptforge.controller import TranscriptionController
from transcriptforge.models import Segment


class FailingSummaryClient:
    last_summary_used_excerpt = False
    last_model_used = ""

    def __init__(self, *, model_id):
        self.model_id = model_id

    def summarize(self, *_args, **_kwargs):
        raise RuntimeError("network unavailable")

    def cancel(self):
        pass


class SuccessfulSummaryClient:
    last_summary_used_excerpt = False
    last_model_used = "gpt-test"

    def __init__(self, *, model_id):
        self.model_id = model_id

    def summarize(self, *_args, **_kwargs):
        return "- **DIU:** Verification planning"

    def cancel(self):
        pass


class FailingSummaryClientFactory:
    def __new__(cls, *, model_id):
        raise RuntimeError(f"could not create {model_id}")


class ControllerSummaryTests(unittest.TestCase):
    def test_summary_failure_is_logged_and_does_not_raise(self):
        events = []
        controller = TranscriptionController(events.append, FailingSummaryClient)
        controller.callback = lambda kind, value=None: events.append((kind, value))

        summary = controller._generate_summary([Segment(0, 1, "Discussion")], "DIU", "Review", "gpt-test")

        self.assertEqual(summary, "")
        self.assertTrue(any(kind == "log" and "skipped" in value for kind, value in events))
        self.assertIsNone(controller.summary_client)

    def test_successful_summary_is_returned(self):
        events = []
        controller = TranscriptionController(lambda kind, value=None: events.append((kind, value)), SuccessfulSummaryClient)
        summary = controller._generate_summary([Segment(0, 1, "Discussion")], "DIU", "Review", "gpt-test")
        self.assertEqual(summary, "- **DIU:** Verification planning")
        self.assertTrue(any(kind == "log" and "gpt-test" in value for kind, value in events))

    def test_summary_client_creation_failure_is_non_blocking(self):
        events = []
        controller = TranscriptionController(lambda kind, value=None: events.append((kind, value)), FailingSummaryClientFactory)

        summary = controller._generate_summary([Segment(0, 1, "Discussion")], "DIU", "Review", "gpt-test")

        self.assertEqual(summary, "")
        self.assertTrue(any(kind == "log" and "could not create" in value for kind, value in events))
        self.assertIsNone(controller.summary_client)


if __name__ == "__main__":
    unittest.main()
