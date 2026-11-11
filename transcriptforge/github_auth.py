"""Read GitHub CLI accounts for explicit Copilot account selection."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass


DEFAULT_GITHUB_HOST = "github.com"
GH_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class GitHubAccountOption:
    """One successfully authenticated GitHub CLI account."""

    login: str
    host: str = DEFAULT_GITHUB_HOST
    active: bool = False
    token_source: str = ""

    @property
    def display_name(self) -> str:
        suffix = " (active)" if self.active else ""
        return f"{self.login}{suffix}"


def _gh_executable() -> str:
    return shutil.which("gh") or "gh"


def _run_gh(arguments: list[str]) -> str:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [_gh_executable(), *arguments],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "GitHub account selection requires the GitHub CLI (`gh`). "
            "Install it from https://cli.github.com/ and sign in with `gh auth login`."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The GitHub CLI did not respond while checking signed-in accounts.") from exc
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())
        raise RuntimeError(detail or f"GitHub CLI exited with status {result.returncode}.")
    return result.stdout


def list_github_accounts(host: str = DEFAULT_GITHUB_HOST) -> list[GitHubAccountOption]:
    """Return successful GitHub CLI accounts without exposing their tokens."""
    raw = _run_gh(["auth", "status", "--hostname", host, "--json", "hosts"])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned an unreadable account list.") from exc
    hosts = payload.get("hosts", {}) if isinstance(payload, dict) else {}
    entries = hosts.get(host, []) if isinstance(hosts, dict) else []
    accounts = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("state") != "success":
            continue
        login = str(entry.get("login", "")).strip()
        if not login:
            continue
        accounts.append(
            GitHubAccountOption(
                login=login,
                host=host,
                active=bool(entry.get("active")),
                token_source=str(entry.get("tokenSource", "")).strip(),
            )
        )
    if not accounts:
        raise RuntimeError(
            "No working GitHub CLI accounts were found. Sign in with `gh auth login`, "
            "then refresh the account list."
        )
    return accounts


def github_token_for_account(account: GitHubAccountOption | str, host: str = DEFAULT_GITHUB_HOST) -> str:
    """Read one account's token only for the in-memory Copilot request."""
    if isinstance(account, GitHubAccountOption):
        login = account.login
        host = account.host
    else:
        login = str(account).strip()
    if not login:
        raise ValueError("A GitHub account login is required.")
    token = _run_gh(["auth", "token", "--hostname", host, "--user", login]).strip()
    if not token:
        raise RuntimeError(f"GitHub CLI returned no token for the selected account '{login}'.")
    if token.startswith("ghp_"):
        raise RuntimeError(
            "The selected GitHub account uses an unsupported classic `ghp_` token. "
            "Run `gh auth logout -u " + login + "` and sign in again with `gh auth login`."
        )
    return token
