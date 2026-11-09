"""Local Sign in with ChatGPT OAuth support for the desktop application.

This is the public-client flow documented by OpenAI for open-source local
applications.  The browser handles the user's password and consent; the app
only receives OAuth tokens on the loopback callback and protects them with
Windows DPAPI before saving them locally.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from .settings import settings_dir

AUTH_BASE_URL = "https://auth.openai.com"
AUTHORIZE_URL = f"{AUTH_BASE_URL}/api/accounts/authorize"
TOKEN_URL = f"{AUTH_BASE_URL}/api/accounts/oauth/token"
JWKS_URL = f"{AUTH_BASE_URL}/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
APP_NAME = "TranscriptForge"
HOST_ID_FILENAME = "chatgpt-host-id.txt"
CREDENTIAL_FILENAME = "chatgpt-credentials.json"
AUTH_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ChatGPTAccount:
    email: str
    client_id: str
    scopes: tuple[str, ...]


class ChatGPTAuthStore:
    """Persist one protected ChatGPT registration for this Windows user."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or settings_dir()
        self.host_id_path = self.directory / HOST_ID_FILENAME
        self.credentials_path = self.directory / CREDENTIAL_FILENAME

    def host_id(self) -> str:
        if self.host_id_path.is_file():
            value = self.host_id_path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = f"urn:uuid:{uuid.uuid4()}"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.host_id_path.write_text(value + "\n", encoding="utf-8")
        return value

    @staticmethod
    def _protect(value: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:
            raise RuntimeError("ChatGPT sign-in storage requires Windows DPAPI (pywin32).") from exc
        return win32crypt.CryptProtectData(value, "TranscriptForge ChatGPT credentials", None, None, None, 0)[1]

    @staticmethod
    def _unprotect(value: bytes) -> bytes:
        try:
            import win32crypt
        except ImportError as exc:
            raise RuntimeError("ChatGPT sign-in storage requires Windows DPAPI (pywin32).") from exc
        return win32crypt.CryptUnprotectData(value, None, None, None, 0)[1]

    def load(self) -> dict[str, Any] | None:
        if not self.credentials_path.is_file():
            return None
        try:
            encoded = json.loads(self.credentials_path.read_text(encoding="utf-8"))
            encrypted = base64.b64decode(encoded["protected"], validate=True)
            value = json.loads(self._unprotect(encrypted).decode("utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, credentials: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        protected = self._protect(json.dumps(credentials, ensure_ascii=False).encode("utf-8"))
        temporary = self.credentials_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"protected": base64.b64encode(protected).decode("ascii")}) + "\n", encoding="utf-8")
        temporary.replace(self.credentials_path)

    def clear(self) -> None:
        try:
            self.credentials_path.unlink()
        except FileNotFoundError:
            pass


class ChatGPTAuthenticator:
    """Complete OAuth browser flow and token refresh for one local account."""

    def __init__(
        self,
        store: ChatGPTAuthStore | None = None,
        *,
        open_browser: Callable[[str], bool] = webbrowser.open,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ):
        self.store = store or ChatGPTAuthStore()
        self.open_browser = open_browser
        self.urlopen = urlopen

    def account(self) -> ChatGPTAccount | None:
        credentials = self.store.load()
        if not credentials:
            return None
        return ChatGPTAccount(
            email=str(credentials.get("email", "ChatGPT account")),
            client_id=str(credentials.get("client_id", "")),
            scopes=tuple(str(item) for item in credentials.get("scopes", []) if str(item).strip()),
        )

    def access_token(self) -> str:
        credentials = self.store.load()
        if not credentials:
            raise RuntimeError("ChatGPT is not connected. Use Continue with ChatGPT in Settings to sign in.")
        expires_at = float(credentials.get("expires_at", 0) or 0)
        if expires_at > time.time() + 60 and credentials.get("access_token"):
            return str(credentials["access_token"])
        refresh_token = str(credentials.get("refresh_token", ""))
        if not refresh_token:
            raise RuntimeError("ChatGPT sign-in expired. Use Continue with ChatGPT to reconnect.")
        payload = self._post_form({
            "grant_type": "refresh_token",
            "client_id": str(credentials["client_id"]),
            "refresh_token": refresh_token,
            "resource": RESOURCE,
        })
        credentials.update(self._token_fields(payload))
        self.store.save(credentials)
        return str(credentials["access_token"])

    def sign_in(self) -> ChatGPTAccount:
        host_id = self.store.host_id()
        existing = self.store.load() or {}
        client_id = str(existing.get("client_id") or "dynamic_agent_client")
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        result: dict[str, str] = {}
        ready = threading.Event()

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_error(404)
                    return
                result.update({key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items() if values})
                body = b"<html><body><h2>TranscriptForge is connected.</h2><p>You can close this window.</p></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                ready.set()

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        redirect_uri = f"http://127.0.0.1:{server.server_port}/auth/callback"
        query = {
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        if client_id == "dynamic_agent_client":
            query["agent_name_hint"] = APP_NAME
        elif existing.get("id_token"):
            query["id_token_hint"] = str(existing["id_token"])
        url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(query)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        self.open_browser(url)
        if not ready.wait(AUTH_TIMEOUT_SECONDS):
            server.server_close()
            raise RuntimeError("Timed out waiting for ChatGPT sign-in.")
        server.server_close()
        if result.get("state") != state:
            raise RuntimeError("ChatGPT sign-in returned an invalid state.")
        if result.get("error"):
            raise RuntimeError(f"ChatGPT sign-in was not completed: {result['error']}.")
        issued_client_id = result.get("client_id") or client_id
        if issued_client_id == "dynamic_agent_client" or not result.get("code"):
            raise RuntimeError("ChatGPT sign-in did not return a usable authorization code.")
        token_payload = self._post_form({
            "grant_type": "authorization_code",
            "client_id": issued_client_id,
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        })
        scopes = tuple(str(token_payload.get("scope", "")).split())
        if "chatgpt.tokens.use.direct" not in scopes:
            raise RuntimeError("ChatGPT plan usage was not authorized. Try again and allow plan usage.")
        claims = self._validate_id_token(str(token_payload.get("id_token", "")), nonce, issued_client_id)
        credentials = {
            "email": str(claims.get("email") or "ChatGPT account"),
            "subject": str(claims["sub"]),
            "client_id": issued_client_id,
            "ext_agent_host_id": host_id,
            "id_token": str(token_payload["id_token"]),
            **self._token_fields(token_payload),
            "scopes": list(scopes),
        }
        self.store.save(credentials)
        return self.account() or ChatGPTAccount(credentials["email"], issued_client_id, scopes)

    def _post_form(self, fields: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        try:
            with self.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("ChatGPT token exchange failed.") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RuntimeError("ChatGPT token exchange did not return an access token.")
        return payload

    @staticmethod
    def _token_fields(payload: dict[str, Any]) -> dict[str, Any]:
        expires = int(payload.get("expires_in", 3600) or 3600)
        return {"access_token": str(payload["access_token"]), "refresh_token": str(payload.get("refresh_token", "")), "token_type": str(payload.get("token_type", "Bearer")), "expires_at": time.time() + expires}

    def _validate_id_token(self, id_token: str, nonce: str, client_id: str) -> dict[str, Any]:
        try:
            import jwt
            from jwt import PyJWKClient
            key = PyJWKClient(JWKS_URL, cache_jwk_set=True, lifespan=600).get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(id_token, key, algorithms=["RS256"], issuer=AUTH_BASE_URL, audience=client_id, options={"require": ["sub", "exp", "iat"]})
        except Exception as exc:
            raise RuntimeError("ChatGPT sign-in returned an invalid identity token.") from exc
        if claims.get("nonce") != nonce or not str(claims.get("sub", "")):
            raise RuntimeError("ChatGPT sign-in identity validation failed.")
        return claims
