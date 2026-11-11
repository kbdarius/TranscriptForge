import json
import unittest
from unittest.mock import patch

from transcriptforge.github_auth import (
    GitHubAccountOption,
    github_token_for_account,
    list_github_accounts,
)


class GitHubAuthTests(unittest.TestCase):
    @patch("transcriptforge.github_auth._run_gh")
    def test_lists_successful_accounts_and_active_state(self, run_gh):
        run_gh.return_value = json.dumps(
            {
                "hosts": {
                    "github.com": [
                        {"state": "success", "active": False, "login": "first", "tokenSource": "keyring"},
                        {"state": "error", "active": False, "login": "broken"},
                        {"state": "success", "active": True, "login": "second", "tokenSource": "keyring"},
                    ]
                }
            }
        )

        accounts = list_github_accounts()

        self.assertEqual([account.login for account in accounts], ["first", "second"])
        self.assertFalse(accounts[0].active)
        self.assertTrue(accounts[1].active)
        self.assertEqual(accounts[1].display_name, "second (active)")
        run_gh.assert_called_once_with(["auth", "status", "--hostname", "github.com", "--json", "hosts"])

    @patch("transcriptforge.github_auth._run_gh", return_value="gho_secret-token\n")
    def test_reads_selected_account_token_without_logging_it(self, run_gh):
        token = github_token_for_account(GitHubAccountOption("second"))

        self.assertEqual(token, "gho_secret-token")
        run_gh.assert_called_once_with(["auth", "token", "--hostname", "github.com", "--user", "second"])

    @patch("transcriptforge.github_auth._run_gh", return_value="ghp_classic-token\n")
    def test_rejects_classic_tokens(self, _run_gh):
        with self.assertRaisesRegex(RuntimeError, "classic"):
            github_token_for_account("second")


if __name__ == "__main__":
    unittest.main()
