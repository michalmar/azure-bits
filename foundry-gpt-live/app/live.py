from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import re
from urllib.parse import urlsplit

from azure.identity import AzureCliCredential, ManagedIdentityCredential
from websockets.asyncio.client import connect


TOKEN_SCOPE = "https://ai.azure.com/.default"
MAX_AUDIO_FRAME_BYTES = 24_000 * 2
DELEGATION_REPLY = (
    "This demo only supports a live conversation. I cannot look things up or "
    "take actions outside this conversation."
)
INSTRUCTIONS = (
    "Have a natural, concise voice conversation. Listen even while speaking, "
    "and let the user interrupt or change direction. Do not claim to have "
    "searched, used tools, or completed external actions. Delegate requests "
    "that need a lookup, a tool, or deeper reasoning to the client."
)


@dataclass(frozen=True, slots=True)
class LiveSettings:
    endpoint: str
    deployment: str = "gpt-live-1"
    max_session_seconds: int = 300
    max_concurrent_sessions: int = 3

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".openai.azure.com")
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("AZURE_OPENAI_ENDPOINT must be an Azure OpenAI HTTPS origin")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.deployment):
            raise ValueError("LIVE_DEPLOYMENT must be a valid deployment name")
        if not 1 <= self.max_session_seconds <= 600:
            raise ValueError("MAX_SESSION_SECONDS must be between 1 and 600")
        if not 1 <= self.max_concurrent_sessions <= 10:
            raise ValueError("MAX_CONCURRENT_SESSIONS must be between 1 and 10")

    @classmethod
    def from_env(cls) -> LiveSettings:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT is required")
        return cls(
            endpoint=endpoint,
            deployment=os.getenv("LIVE_DEPLOYMENT", "gpt-live-1").strip(),
            max_session_seconds=int(os.getenv("MAX_SESSION_SECONDS", "300")),
            max_concurrent_sessions=int(os.getenv("MAX_CONCURRENT_SESSIONS", "3")),
        )

    @property
    def websocket_url(self) -> str:
        return self.endpoint.rstrip("/").replace("https://", "wss://", 1) + "/openai/v1/live/sessions"

    def start_event(self) -> dict[str, object]:
        return {
            "type": "session.start",
            "session": {
                "model": self.deployment,
                "instructions": INSTRUCTIONS,
                "audio": {"output": {"voice": "marin"}},
                "delegation": {"type": "client"},
            },
        }


class LiveService:
    def __init__(self, settings: LiveSettings, credential: object | None = None) -> None:
        self.settings = settings
        if credential is not None:
            self.credential = credential
            self._owns_credential = False
        elif os.getenv("APP_ENV", "development").lower() == "production":
            client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
            if not client_id:
                raise ValueError("AZURE_CLIENT_ID is required in production")
            self.credential = ManagedIdentityCredential(client_id=client_id)
            self._owns_credential = True
        else:
            self.credential = AzureCliCredential()
            self._owns_credential = True

    async def open_connection(self):
        token = await asyncio.to_thread(self.credential.get_token, TOKEN_SCOPE)
        return connect(
            self.settings.websocket_url,
            additional_headers={"Authorization": f"Bearer {token.token}"},
            open_timeout=15,
            close_timeout=5,
            max_size=1024 * 1024,
            max_queue=8,
        )

    async def close(self) -> None:
        if self._owns_credential:
            await asyncio.to_thread(self.credential.close)
