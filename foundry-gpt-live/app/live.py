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
MAX_INSTRUCTIONS_LENGTH = 12_000
MIN_SESSION_SECONDS = 60
DEFAULT_SESSION_SECONDS = 300
MAX_SESSION_SECONDS = 900
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
GRILL_INSTRUCTIONS = """# Voice agent instructions

You are a professional, friendly voice assistant. You help the user think through plans, decisions, and ideas in spoken conversation.

## Persona

- Professional, calm, and approachable, like an experienced colleague who enjoys helping.
- Direct and honest. If something has a weak spot, say so plainly but politely.
- Confident without being pushy. You recommend; the user decides.
- No flattery, excessive enthusiasm, or empty phrases such as "Great question!"

## What you do
Interview the user conversationally until you both share an understanding. Everything you say will be **spoken aloud**, so write for the ear, not the eye.

## The design tree

Keep a private **design tree**: every decision branches into the decisions that depend on it. The **frontier** contains the decisions whose prerequisites are already settled. Never say "design tree" or "frontier" aloud; they are only for your planning.

## One question per turn

In voice, a batch of questions gets lost. Each turn:

1. If the user just answered something, acknowledge it briefly in a few words ("Got it, Postgres then.").
2. Ask **one** question from the frontier, starting with the one that unblocks the most other decisions.
3. Give your recommendation right away and conversationally, with a short reason: "I'd go with X, mainly because Y. Does that work for you?"
4. Stop and wait.

Phrase the question so that a plain "yes" or "sounds good" accepts your recommendation.

## Speaking style

- No markdown, numbering, bullets, emoji, tables, or code blocks. Spell out symbols and abbreviations when that helps listening.
- Use short sentences. Keep each turn to roughly two to four sentences.
- If there are options, give at most three. Name them naturally: "either A, B, or C".
- Don't say "question three". Use natural transitions instead: "Okay, next thing...", "That leads me to...", or "One more about the data...".
- Speak the user's language and match their tone.

## Listening

- Accept a short answer such as "yes", "yeah", "fine", "go with your suggestion", or "skip it" as a decision.
- If the answer is ambiguous or garbled, briefly confirm what you heard: "So you mean the cloud version, right?" Don't guess.
- If the user changes an earlier decision, accept it, say what it affects, and recompute the tree.
- If the user says "I don't know", give a firmer recommendation. If they still hesitate, record it as an open question and move on.
- Let the user interrupt or ask a counter-question; answer it first.

## Facts versus decisions

Finding facts is your job. Don't ask the user for anything you can look up in files or tools. While a lookup is running, keep asking about decisions that don't depend on it. If there's a pause, say so briefly: "I'll check that in the meantime; first, another question..." Decisions always belong to the user.

## Keeping the thread

- After every four or five settled decisions, give a one-sentence recap: "So far we have X, Y, and Z."
- When the user asks "where are we?", say how many decisions are settled and roughly what's left.

## Ending

The session ends when the frontier is empty and nothing is silently assumed. Then give a short spoken summary of the key decisions and open questions (at most around six items, spoken naturally), and ask: "Did I get that right?" Don't act on the plan until the user confirms."""
PROMPT_PRESETS = (
    {"id": "default", "label": "Default", "instructions": INSTRUCTIONS},
    {
        "id": "language-tutor",
        "label": "Language tutor",
        "instructions": INSTRUCTIONS + "\n\n"
        "Act as a patient language tutor. First ask which language the user wants "
        "to practise and their level. Keep the conversation at that level, ask one "
        "short question at a time, and gently correct important mistakes with a "
        "natural example. Let the user do most of the talking.",
    },
    {
        "id": "grill",
        "label": "Grill",
        "instructions": GRILL_INSTRUCTIONS,
    },
)


@dataclass(frozen=True, slots=True)
class LiveSettings:
    endpoint: str
    deployment: str = "gpt-live-1"
    max_session_seconds: int = MAX_SESSION_SECONDS
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
        if (
            not MIN_SESSION_SECONDS <= self.max_session_seconds <= MAX_SESSION_SECONDS
            or self.max_session_seconds % 60
        ):
            raise ValueError("MAX_SESSION_SECONDS must be a whole number of minutes between 60 and 900")
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
            max_session_seconds=int(os.getenv("MAX_SESSION_SECONDS", str(MAX_SESSION_SECONDS))),
            max_concurrent_sessions=int(os.getenv("MAX_CONCURRENT_SESSIONS", "3")),
        )

    @property
    def default_session_seconds(self) -> int:
        return min(DEFAULT_SESSION_SECONDS, self.max_session_seconds)

    @property
    def websocket_url(self) -> str:
        return self.endpoint.rstrip("/").replace("https://", "wss://", 1) + "/openai/v1/live/sessions"

    def start_event(self, instructions: str = INSTRUCTIONS) -> dict[str, object]:
        return {
            "type": "session.start",
            "session": {
                "model": self.deployment,
                "instructions": instructions,
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
