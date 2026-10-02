"""Bounded MAI calls; managed identity is the only workload credential."""

from __future__ import annotations

import asyncio
import base64
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit
from typing import Literal, Protocol
from xml.sax.saxutils import escape

from azure.core.exceptions import AzureError
from azure.identity.aio import ManagedIdentityCredential
from fastapi import HTTPException, WebSocketDisconnect
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.types import Message
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

logger = logging.getLogger("mai_audio")
MODELS = ("MAI-Voice-2.1", "MAI-Voice-2.1-Flash")
VOICES = {
    "en-US-Harper": ("English", ("neutral", "narrator", "educational", "happy", "whispering")),
    "en-US-Grant": ("English", ("neutral", "narrator", "educational", "agent")),
    "cs-CZ-Harper": ("Czech", ("neutral", "narrator", "educational", "agent")),
    "de-DE-Harper": ("German", ("neutral", "narrator", "educational", "agent")),
    "fr-FR-Harper": ("French", ("neutral", "narrator", "educational", "agent")),
    "es-MX-Harper": ("Spanish", ("neutral", "narrator", "educational", "agent")),
}
PREFIX = "conversation.item.input_audio_transcription."
MAX_AUDIO_BYTES = 16_000 * 2 * 60
MIN_COMMIT_BYTES = 16_000 * 2 // 10
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def transcription_error(event: dict, stage: str) -> HTTPException:
    error = event.get("error", {})
    code = re.sub(r"[^A-Za-z0-9_.-]", "", str(error.get("code") or "unknown"))[:100]
    parameter = re.sub(r"[^A-Za-z0-9_.-]", "", str(error.get("param") or ""))[:100]
    logger.warning("transcription_failed stage=%s code=%s parameter=%s", stage, code, parameter)
    return HTTPException(502, f"MAI transcription {stage} failed ({code}; {parameter}). Check deployment availability and retry.")


class AudioStream(Protocol):
    async def receive(self) -> Message: ...
    async def send_json(self, data: dict) -> None: ...


class SynthesisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    voice: str = "en-US-Harper"
    style: str = "neutral"
    text: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def supported(self):
        if self.model not in MODELS or self.voice not in VOICES:
            raise ValueError("Choose a supported MAI model and curated voice")
        if self.style not in VOICES[self.voice][1]:
            raise ValueError("This style is not documented for the selected voice")
        if not self.text.strip() or any(ord(c) < 32 and c not in "\n\r\t" for c in self.text):
            raise ValueError("Text must contain speech and no control characters")
        return self


def ssml(value: SynthesisInput) -> str:
    locale = value.voice[:5]
    text = escape(value.text)
    if value.style != "neutral":
        text = f'<mstts:express-as style="{value.style}">{text}</mstts:express-as>'
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{locale}">'
        f'<voice name="{value.voice}:{value.model}">{text}</voice></speak>'
    )


@dataclass(frozen=True)
class AudioSettings:
    resource: str
    deployment: str
    client_id: str
    live_enabled: bool
    speech_resource_id: str = ""

    @classmethod
    def from_env(cls):
        project = os.getenv("FOUNDRY_PROJECT_URL", "")
        endpoint = os.getenv("AZURE_MAI_ENDPOINT", "")
        if not endpoint and project:
            parsed = urlsplit(project)
            endpoint = f"https://{parsed.hostname}" if parsed.hostname else ""
        live = os.getenv("LIVE_AUDIO_ENABLED", "false").lower() == "true"
        parsed = urlsplit(endpoint)
        if live and (
            parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".services.ai.azure.com")
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is not None
        ):
            raise ValueError("Configure an HTTPS Azure MAI resource root or FOUNDRY_PROJECT_URL")
        speech_resource_id = os.getenv("FOUNDRY_ACCOUNT_ID", "")
        if live and not re.fullmatch(
            r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/#]+/providers/Microsoft\.CognitiveServices/accounts/[^/#]+",
            speech_resource_id,
        ):
            raise ValueError("Configure FOUNDRY_ACCOUNT_ID for Speech Entra authentication")
        resource = parsed.hostname.split(".")[0] if parsed.hostname else ""
        return cls(resource, os.getenv("TRANSCRIBE_DEPLOYMENT", "MAI-Transcribe-2-Streaming"),
                   os.getenv("AZURE_CLIENT_ID", ""), live, speech_resource_id)


class AudioService:
    def __init__(self, settings: AudioSettings):
        self.settings = settings
        self.credential = ManagedIdentityCredential(client_id=settings.client_id) if settings.live_enabled else None
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15), follow_redirects=False)
        self.active = 0
        self.calls: dict[str, deque[float]] = {}

    async def close(self):
        await self.http.aclose()
        if self.credential:
            await self.credential.close()

    @asynccontextmanager
    async def slot(self, identity: str):
        if not self.settings.live_enabled:
            raise HTTPException(503, "Live audio requires an Azure host with managed identity. Static examples remain available.")
        now = time.monotonic()
        self.calls = {key: value for key, value in self.calls.items() if value and value[-1] > now - 60}
        recent = self.calls.setdefault(identity, deque())
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= 12 or self.active >= 3:
            raise HTTPException(429, "Demo limit reached. Wait one minute and try again.", headers={"Retry-After": "60"})
        recent.append(now)
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1

    async def token(self) -> str:
        if not self.credential:
            raise HTTPException(503, "Managed identity is not configured")
        try:
            return (await self.credential.get_token("https://cognitiveservices.azure.com/.default")).token
        except AzureError as exc:
            logger.warning("identity_failed type=%s", type(exc).__name__)
            raise HTTPException(503, "Managed identity could not authenticate. Check the host identity and Speech/Foundry roles.") from None

    async def synthesize(
        self, value: SynthesisInput,
        output_format: Literal["audio-24khz-160kbitrate-mono-mp3", "raw-16khz-16bit-mono-pcm"] = "audio-24khz-160kbitrate-mono-mp3",
    ) -> tuple[bytes, float]:
        token = await self.token()
        start = time.perf_counter()
        # Custom-subdomain Speech endpoint supports Entra authentication.
        url = f"https://{self.settings.resource}.cognitiveservices.azure.com/tts/cognitiveservices/v1"
        try:
            async with asyncio.timeout(70):
                async with self.http.stream("POST", url, content=ssml(value).encode(), headers={
                    "Authorization": f"Bearer aad#{self.settings.speech_resource_id}#{token}",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": output_format,
                    "User-Agent": "azure-bits-mai-audio",
                }) as response:
                    if response.status_code != 200:
                        logger.warning("synthesis_failed status=%s", response.status_code)
                        raise HTTPException(502, f"Azure Speech returned HTTP {response.status_code}. Check MAI voice availability and the identity's Speech User role.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_OUTPUT_BYTES:
                            raise HTTPException(502, "Audio response exceeded the demo's 8 MiB limit")
                    if not data:
                        raise HTTPException(502, "Azure Speech returned empty audio")
            return bytes(data), round((time.perf_counter() - start) * 1000, 1)
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("synthesis_unavailable type=%s", type(exc).__name__)
            raise HTTPException(504, "Azure Speech did not complete in time. Your text is preserved; retry a shorter passage.") from None

    async def transcribe(self, browser: AudioStream):
        token = await self.token()
        url = f"wss://{self.settings.resource}.services.ai.azure.com/mai/v1/realtime?intent=transcription"
        try:
            async with connect(url, additional_headers={"Authorization": f"Bearer {token}"},
                               max_size=2**20, open_timeout=20, close_timeout=5) as upstream:
                async def wait_for(kind):
                    async with asyncio.timeout(25):
                        while True:
                            event = json.loads(await upstream.recv())
                            if event.get("type") == "error":
                                raise transcription_error(event, "setup")
                            if event.get("type") == kind:
                                return

                await wait_for("session.created")
                await upstream.send(json.dumps({"type": "session.update", "session": {
                    "type": "transcription", "audio": {"input": {
                        "format": {"type": "audio/pcm", "rate": 16000},
                        "transcription": {"model": self.settings.deployment},
                        "turn_detection": None,
                    }},
                }}))
                await wait_for("session.updated")
                await browser.send_json({"type": "ready"})
                received = 0
                last_commit = 0
                pending = 0
                draining = False
                completed = asyncio.Event()
                first_audio = None
                first_text = False

                async def sender():
                    nonlocal received, last_commit, pending, draining, first_audio
                    async with asyncio.timeout(65):
                        while True:
                            message = await browser.receive()
                            if message["type"] == "websocket.disconnect":
                                raise WebSocketDisconnect()
                            chunk = message.get("bytes")
                            if chunk is not None:
                                if not chunk or len(chunk) % 2 or len(chunk) > 6400:
                                    raise HTTPException(400, "Send mono PCM16 audio in chunks of at most 200 ms")
                                received += len(chunk)
                                if received > MAX_AUDIO_BYTES:
                                    raise HTTPException(413, "Recording exceeds the 60-second demo limit")
                                if first_audio is None:
                                    first_audio = time.perf_counter()
                                await upstream.send(json.dumps({"type": "input_audio_buffer.append",
                                                               "audio": base64.b64encode(chunk).decode()}))
                                if received - last_commit >= 96000:
                                    pending += 1
                                    await upstream.send('{"type":"input_audio_buffer.commit"}')
                                    last_commit = received
                            elif message.get("text") == "stop":
                                if received > last_commit:
                                    # The preview rejects commits shorter than 100 ms; preserve short tails with silence.
                                    padding = MIN_COMMIT_BYTES - (received - last_commit)
                                    if padding > 0:
                                        await upstream.send(json.dumps({
                                            "type": "input_audio_buffer.append",
                                            "audio": base64.b64encode(b"\0" * padding).decode(),
                                        }))
                                    pending += 1
                                    await upstream.send('{"type":"input_audio_buffer.commit"}')
                                draining = True
                                if pending == 0:
                                    completed.set()
                                return
                            else:
                                raise HTTPException(400, "Unsupported audio control message")

                async def receiver():
                    nonlocal pending, first_text
                    async for raw in upstream:
                        event = json.loads(raw)
                        kind = event.get("type", "")
                        if kind == "error" or kind == PREFIX + "failed":
                            raise transcription_error(event, "stream")
                        if kind in {PREFIX + "delta", PREFIX + "intermediate", PREFIX + "completed"}:
                            payload = {key: event[key] for key in ("type", "item_id", "delta", "intermediate", "transcript") if key in event}
                            if not first_text and first_audio is not None and any(event.get(k) for k in ("delta", "intermediate", "transcript")):
                                payload["first_text_ms"] = round((time.perf_counter() - first_audio) * 1000, 1)
                                first_text = True
                            await browser.send_json(payload)
                        if kind == PREFIX + "completed":
                            pending -= 1
                            if draining and pending == 0:
                                completed.set()
                                return
                    raise HTTPException(502, "MAI closed the stream before the final transcript")

                send_task = asyncio.create_task(sender())
                receive_task = asyncio.create_task(receiver())
                try:
                    done, _ = await asyncio.wait({send_task, receive_task}, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    if receive_task in done and not send_task.done():
                        raise HTTPException(502, "MAI ended the stream unexpectedly")
                    async with asyncio.timeout(45):
                        wait_task = asyncio.create_task(completed.wait())
                        try:
                            done, _ = await asyncio.wait({wait_task, receive_task}, return_when=asyncio.FIRST_COMPLETED)
                            for task in done:
                                task.result()
                            if not completed.is_set():
                                raise HTTPException(502, "MAI did not finalize the transcript")
                        finally:
                            wait_task.cancel()
                            await asyncio.gather(wait_task, return_exceptions=True)
                    await browser.send_json({"type": "done", "audio_seconds": received / 32000})
                finally:
                    for task in (send_task, receive_task):
                        task.cancel()
                    await asyncio.gather(send_task, receive_task, return_exceptions=True)
        except (WebSocketException, TimeoutError, ValueError) as exc:
            logger.warning("transcription_unavailable type=%s", type(exc).__name__)
            raise HTTPException(502, "MAI streaming connection failed or timed out. Check the deployment and retry.") from None
