import asyncio
import threading
import unittest
from types import SimpleNamespace

from transcriptforge.copilot_summary import (
    CopilotSummaryClient,
    MAX_TRANSCRIPT_CHARACTERS,
    MODEL_ID,
    REASONING_EFFORT,
    normalize_summary,
    transcript_excerpt,
)
from transcriptforge.models import Segment


class FakeSession:
    def __init__(self, response_text="- **DIU:** Verification planning", started=None, wait=False):
        self.response_text = response_text
        self.started = started
        self.wait = wait
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
        return SimpleNamespace(data=SimpleNamespace(content=self.response_text))


class FakeClient:
    def __init__(self, authenticated=True, response_text=None, models=None, started=None, wait=False):
        self.auth_status = SimpleNamespace(
            isAuthenticated=authenticated,
            statusMessage="Not signed in" if not authenticated else "",
        )
        self.models = models if models is not None else [
            SimpleNamespace(id=MODEL_ID, supported_reasoning_efforts=[REASONING_EFFORT])
        ]
        self.session = FakeSession(response_text or "- **DIU:** Verification planning", started, wait)
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
