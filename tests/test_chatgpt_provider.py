import unittest

from transcriptforge.chatgpt_provider import ChatGPTSummaryClient
from transcriptforge.models import Segment


class ChatGPTProviderTests(unittest.TestCase):
    def test_model_scan_deduplicates_ids_and_uses_readable_names(self):
        calls = []

        def request(method, path, body, timeout):
            calls.append((method, path))
            return {"models": [{"slug": "gpt-test", "owned_by": "OpenAI"}, {"slug": "gpt-test", "name": "Duplicate"}, {"slug": "o3-mini", "display_name": "o3-mini"}]}

        models = ChatGPTSummaryClient("token", request=request).list_available_models()
        self.assertEqual([(item.id, item.name) for item in models], [("gpt-test", "OpenAI"), ("o3-mini", "o3-mini")])
        self.assertEqual(calls, [("GET", "/models")])

    def test_validate_connection_rejects_unavailable_selected_model(self):
        def request(method, path, body, timeout):
            return {"data": [{"id": "gpt-test"}]}

        success, message = ChatGPTSummaryClient("token", model_id="missing", request=request).validate_connection()
        self.assertFalse(success)
        self.assertIn("missing", message)

    def test_summary_uses_responses_api_and_records_actual_model(self):
        calls = []

        def request(method, path, body, timeout):
            calls.append((method, path, body))
            return {"model": "gpt-routed", "output": [{"content": [{"type": "output_text", "text": "- **DIU:** Verification planning"}]}]}

        client = ChatGPTSummaryClient("token", model_id="gpt-selected", request=request)
        summary = client.summarize([Segment(0, 1, "Discussion")], meeting_title="Review")
        self.assertEqual(summary, "- **DIU:** Verification planning")
        self.assertEqual(client.last_model_used, "gpt-routed")
        self.assertEqual(calls[0][0:2], ("POST", "/responses"))
        self.assertIn(b"gpt-selected", calls[0][2])
        self.assertIn(b"Discussion", calls[0][2])
        self.assertIn(b'"store": false', calls[0][2])
        self.assertIn(b'"stream": true', calls[0][2])
        self.assertIn(b'"instructions"', calls[0][2])

    def test_missing_token_is_reported_without_network_request(self):
        client = ChatGPTSummaryClient("")
        success, message = client.validate_connection()
        self.assertFalse(success)
        self.assertIn("Continue with ChatGPT", message)

    def test_cancel_prevents_request(self):
        called = False

        def request(method, path, body, timeout):
            nonlocal called
            called = True
            return {}

        client = ChatGPTSummaryClient("token", request=request)
        client.cancel()
        with self.assertRaises(InterruptedError):
            client.summarize([Segment(0, 1, "Discussion")])
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
