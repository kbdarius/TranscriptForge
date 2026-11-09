import tempfile
import unittest
from pathlib import Path

from transcriptforge.chatgpt_auth import ChatGPTAuthStore


class ChatGPTAuthStoreTests(unittest.TestCase):
    def test_host_id_is_created_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ChatGPTAuthStore(Path(directory))
            first = store.host_id()
            second = ChatGPTAuthStore(Path(directory)).host_id()

            self.assertTrue(first.startswith("urn:uuid:"))
            self.assertEqual(first, second)
            self.assertTrue((Path(directory) / "chatgpt-host-id.txt").is_file())

    def test_missing_credentials_are_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(ChatGPTAuthStore(Path(directory)).load())


if __name__ == "__main__":
    unittest.main()
