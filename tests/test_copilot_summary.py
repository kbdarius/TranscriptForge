import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from transcriptforge.copilot_summary import (
    CopilotSummaryClient,
    MAX_TRANSCRIPT_CHARACTERS,
    MODEL_ID,
    REASONING_EFFORT,
    format_copilot_service_error,
    normalize_summary,
    transcript_excerpt,
)
from transcriptforge.models import Segment


class FakeSession:
    def __init__(self, response_text="- **DIU:** Verification planning", started=None, wait=False, response_model=None):
        self.response_text = response_text
        self.started = started
        self.wait = wait
        self.response_model = response_model
        self.prompt = ""
        self.timeout = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def send_and_wait(self, prompt, *, timeout):
        self.prompt = prompt
        self.timeout = timeout
        if self.started:
            self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        return SimpleNamespace(data=SimpleNamespace(content=self.response_text, model=self.response_model))


class FakeClient:
    def __init__(self, authenticated=True, response_text=None, models=None, started=None, wait=False, response_model=None):
        self.auth_status = SimpleNamespace(
            isAuthenticated=authenticated,
            statusMessage="Not signed in" if not authenticated else "",
        )
        self.models = models if models is not None else [
            SimpleNamespace(id=MODEL_ID, name="Auto", supported_reasoning_efforts=[REASONING_EFFORT])
        ]
        self.session = FakeSession(response_text or "- **DIU:** Verification planning", started, wait, response_model)
        self.session_options = None
        self.session_creation_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get_auth_status(self):
        return self.auth_status

    async def list_models(self):
        return self.models

    async def create_session(self, **kwargs):
        self.session_options = kwargs
        self.session_creation_count += 1
        return self.session


class CopilotSummaryTests(unittest.TestCase):
    def test_blocked_service_error_is_actionable_and_does_not_include_html(self):
        error = RuntimeError(
            "JSON-RPC Error -32603 status 503 Service Unavailable body: "
            "<html><h1>Page Blocked</h1>company policy</html>"
        )

        message = format_copilot_service_error("Could not scan GitHub Copilot models", error)

        self.assertIn("network or company web filter blocked", message)
        self.assertIn("api.individual.githubcopilot.com", message)
        self.assertNotIn("<html>", message)

    def test_summary_uses_isolated_tool_free_session_and_project_context(self):
        client = FakeClient()
        summary = CopilotSummaryClient(lambda: client).summarize(
            [Segment(0, 2, "Reviewed the DIU verification procedure", speaker="Alex")],
            meeting_title="DIU review",
            project_context="DIU; BESS",
        )

        self.assertEqual(summary, "- **DIU:** Verification planning")
        self.assertEqual(client.session_options["model"], MODEL_ID)
        self.assertNotIn("reasoning_effort", client.session_options)
        self.assertEqual(client.session_options["available_tools"], [])
        self.assertFalse(client.session_options["enable_config_discovery"])
        self.assertFalse(client.session_options["enable_session_store"])
        self.assertFalse(client.session_options["enable_skills"])
        self.assertTrue(client.session_options["skip_custom_instructions"])
        self.assertIn("Meeting title: DIU review", client.session.prompt)
        self.assertIn("Known weekly-report projects and aliases: DIU; BESS", client.session.prompt)
        self.assertIn("Alex: Reviewed the DIU verification procedure", client.session.prompt)

    @patch("copilot.CopilotClient")
    def test_selected_account_token_is_passed_explicitly(self, copilot_client):
        summary_client = CopilotSummaryClient(
            model_id="gpt-selected",
            github_token="gho_selected",
            github_account="second",
        )

        summary_client._create_client()

        copilot_client.assert_called_once_with(
            github_token="gho_selected",
            use_logged_in_user=False,
        )

    def test_selected_model_is_sent_and_reported_model_is_recorded(self):
        client = FakeClient(response_model="gpt-routed")
        summary_client = CopilotSummaryClient(lambda: client, model_id="gpt-selected")

        summary_client.summarize([Segment(0, 1, "Discussion")])

        self.assertEqual(client.session_options["model"], "gpt-selected")
        self.assertEqual(summary_client.last_model_used, "gpt-routed")

    def test_model_scan_returns_ids_and_names_without_creating_a_session(self):
        client = FakeClient(models=[
            SimpleNamespace(id="auto", name="Auto"),
            SimpleNamespace(id="", name="Malformed"),
            SimpleNamespace(id="gpt-test", name="GPT Test"),
            SimpleNamespace(id="gpt-test", name="Duplicate"),
        ])

        models = CopilotSummaryClient(lambda: client).list_available_models()

        self.assertEqual([(model.id, model.name) for model in models], [("auto", "Auto"), ("gpt-test", "GPT Test")])
        self.assertEqual(models[1].display_name, "GPT Test (gpt-test)")
        self.assertEqual(client.session_creation_count, 0)

    def test_model_scan_rejects_an_empty_model_list(self):
        with self.assertRaisesRegex(RuntimeError, "no available models"):
            CopilotSummaryClient(lambda: FakeClient(models=[])).list_available_models()

    def test_connection_check_sends_no_model_request(self):
        client = FakeClient()
        success, message = CopilotSummaryClient(lambda: client).validate_connection()
        self.assertTrue(success)
        self.assertIn("No transcript was sent", message)
        self.assertEqual(client.session_creation_count, 0)

    def test_connection_check_reports_missing_authentication(self):
        success, message = CopilotSummaryClient(lambda: FakeClient(authenticated=False)).validate_connection()
        self.assertFalse(success)
        self.assertIn("Sign in", message)
        self.assertIn("copilot", message.lower())

    def test_connection_check_reports_when_selected_model_is_unavailable(self):
        client = FakeClient(models=[SimpleNamespace(id="auto", name="Auto")])
        success, message = CopilotSummaryClient(lambda: client, model_id="missing-model").validate_connection()
        self.assertFalse(success)
        self.assertIn("missing-model", message)
        self.assertIn("Scan", message)

    def test_cancel_interrupts_active_summary(self):
        started = threading.Event()
        client = FakeClient(started=started, wait=True)
        summary_client = CopilotSummaryClient(lambda: client)
        result = {}
        worker = threading.Thread(
            target=lambda: result.setdefault(
                "error",
                self._capture_error(
                    lambda: summary_client.summarize([Segment(0, 1, "Discussion")])
                ),
            ),
            daemon=True,
        )
        worker.start()
        self.assertTrue(started.wait(timeout=5))
        summary_client.cancel()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(result["error"], InterruptedError)

    def test_cancel_before_request_prevents_session_creation(self):
        client = FakeClient()
        summary_client = CopilotSummaryClient(lambda: client)
        summary_client.cancel()

        with self.assertRaises(InterruptedError):
            summary_client.summarize([Segment(0, 1, "Discussion")])

        self.assertEqual(client.session_creation_count, 0)

    @staticmethod
    def _capture_error(operation):
        try:
            operation()
        except BaseException as exc:
            return exc
        return None

    def test_long_transcript_excerpt_preserves_start_middle_and_end(self):
        segments = [Segment(index, index + 1, f"topic-{index}-" + ("x" * 80)) for index in range(3000)]
        excerpt = transcript_excerpt(segments, 900)
        self.assertLessEqual(len(excerpt), 900)
        self.assertIn("topic-0-", excerpt)
        self.assertIn("topic-1500-", excerpt)
        self.assertIn("topic-2999-", excerpt)
        self.assertLess(MAX_TRANSCRIPT_CHARACTERS, len("\n".join(segment.text for segment in segments)))

    def test_summary_normalization_removes_heading_and_limits_bullets(self):
        response = "# Summary\n" + "\n".join(f"{index}. Item {index}" for index in range(1, 9))
        summary = normalize_summary(response)
        self.assertNotIn("# Summary", summary)
        self.assertEqual(len(summary.splitlines()), 6)
        self.assertTrue(all(line.startswith("- ") for line in summary.splitlines()))


if __name__ == "__main__":
    unittest.main()
