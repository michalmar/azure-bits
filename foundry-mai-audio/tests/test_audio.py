import asyncio
import base64
import json
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app import create_app
from audio import AudioService, AudioSettings, MAX_AUDIO_BYTES, MODELS, PREFIX, SynthesisInput, ssml
from config import Settings
from probe import StreamingProbe
from tests.fakes import MemoryStore, environment


def test_ssml_escapes_text_and_selects_exact_model():
    value = SynthesisInput(model=MODELS[1], text='A < B & "C"', style="happy")
    xml = ssml(value)
    assert "en-US-Harper:MAI-Voice-2.1-Flash" in xml
    assert "A &lt; B &amp;" in xml
    assert 'style="happy"' in xml


@pytest.mark.parametrize("changes", [
    {"model": "other"}, {"voice": '"><audio src="evil"/>'}, {"text": " "},
    {"text": "x" * 601}, {"voice": "cs-CZ-Harper", "style": "happy"}, {"text": "\0hello"},
])
def test_invalid_synthesis_rejected(changes):
    with pytest.raises(ValueError):
        SynthesisInput(**({"model": MODELS[0], "text": "Hello"} | changes))


def test_live_is_disabled_without_managed_identity_host():
    async def run():
        service = AudioService(AudioSettings("", "", "", False))
        try:
            with pytest.raises(HTTPException, match="Static examples"):
                async with service.slot("local"):
                    pass
        finally:
            await service.close()
    asyncio.run(run())


def test_bounded_synthesis_and_error_surface():
    async def run():
        service = AudioService(AudioSettings("demo", "streaming", "", False, "/test-resource-id"))
        await service.http.aclose()
        service.token = AsyncMock(return_value="not-a-real-token")
        request_seen = []
        def handle(request):
            request_seen.append(request)
            return httpx.Response(200, content=b"ID3-real-test-audio")
        service.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        audio, elapsed = await service.synthesize(SynthesisInput(model=MODELS[1], text="Hello"))
        assert audio.startswith(b"ID3") and elapsed >= 0
        assert str(request_seen[0].url) == "https://demo.cognitiveservices.azure.com/tts/cognitiveservices/v1"
        assert request_seen[0].headers["Authorization"] == "Bearer aad#/test-resource-id#not-a-real-token"
        await service.http.aclose()
        service.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(403)))
        with pytest.raises(HTTPException, match="HTTP 403"):
            await service.synthesize(SynthesisInput(model=MODELS[0], text="Hello"))
        await service.close()
    asyncio.run(run())


def test_api_auth_origin_and_payload_boundaries():
    settings = Settings.from_env(environment(UPLOAD_API_ENABLED="false"))
    app = create_app(settings, lambda _: MemoryStore())
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 200
        assert client.post("/api/synthesize", json={}).status_code == 403
        headers = {"Origin": settings.public_base_url}
        assert client.post("/api/synthesize", headers=headers, content="x" * 9000).status_code == 413
        assert client.post("/api/synthesize", headers=headers, json={"model": MODELS[0], "text": "hello"}).status_code == 503
        assert client.post("/_publish/generate-samples").status_code == 404
        assert client.post("/_publish/verify-streaming").status_code == 404
        with client.websocket_connect("/api/transcribe", headers=headers) as socket:
            assert socket.receive_json()["type"] == "error"
    protected = Settings.from_env(environment(AUTH_PROVIDER="entra", ENTRA_TENANT_ID="12345678-1234-1234-1234-123456789012",
                                              ENTRA_CLIENT_ID="12345678-1234-1234-1234-123456789012", ENTRA_CLIENT_SECRET="reader-only"))
    with TestClient(create_app(protected, lambda _: MemoryStore())) as client:
        assert client.get("/api/config").status_code == 401
        assert client.post("/api/synthesize", json={}).status_code == 401


@pytest.mark.parametrize("setup_error", [False, True])
@pytest.mark.parametrize("sizes", [[640], [2560], [3200], [640] * 150 + [640], []])
def test_stream_configures_before_audio_and_drains_final(setup_error, sizes):
    class Upstream:
        def __init__(self):
            self.events = asyncio.Queue()
            self.events.put_nowait({"type": "session.created"})
            self.sent = []
        async def send(self, raw):
            event = json.loads(raw)
            self.sent.append(event)
            if event["type"] == "session.update":
                self.events.put_nowait(
                    {"type": "error", "error": {"code": "invalid_model", "param": "session.audio.input.transcription.model"}}
                    if setup_error else {"type": "session.updated"}
                )
            if event["type"] == "input_audio_buffer.commit":
                self.events.put_nowait({"type": PREFIX + "intermediate", "item_id": "one", "intermediate": "Hello"})
                self.events.put_nowait({"type": PREFIX + "completed", "item_id": "one", "transcript": "Hello."})
        async def recv(self):
            return json.dumps(await self.events.get())
        def __aiter__(self):
            return self
        async def __anext__(self):
            return await self.recv()
    class Connection:
        async def __aenter__(self):
            return upstream
        async def __aexit__(self, *args):
            pass
    class Browser:
        def __init__(self):
            self.sent = []
            self.inputs = iter([{"type": "websocket.receive", "bytes": b"\0" * size} for size in sizes]
                               + [{"type": "websocket.receive", "text": "stop"}])
        async def send_json(self, value):
            self.sent.append(value)
        async def receive(self):
            return next(self.inputs)
    async def run():
        nonlocal upstream
        upstream = Upstream()
        browser = Browser()
        service = AudioService(AudioSettings("demo", "exact-deployment", "", False))
        service.token = AsyncMock(return_value="test")
        try:
            with patch("audio.connect", return_value=Connection()):
                if setup_error:
                    with pytest.raises(HTTPException, match="invalid_model"):
                        await service.transcribe(browser)
                    assert browser.sent == []
                    assert len(upstream.sent) == 1
                    return
                await service.transcribe(browser)
            assert upstream.sent[0]["type"] == "session.update"
            config = upstream.sent[0]["session"]["audio"]["input"]
            assert config["transcription"]["model"] == "exact-deployment"
            assert config["turn_detection"] is None
            assert "language" not in config["transcription"]
            assert "noise_reduction" not in config
            assert browser.sent[0]["type"] == "ready"
            assert browser.sent[-1]["type"] == "done"
            actual_bytes = sum(sizes)
            assert browser.sent[-1]["audio_seconds"] == actual_bytes / 32000
            remainder = actual_bytes % 96000
            padding = max(0, 3200 - remainder) if remainder else 0
            appends = [base64.b64decode(event["audio"]) for event in upstream.sent if event["type"] == "input_audio_buffer.append"]
            assert b"".join(appends) == b"\0" * (actual_bytes + padding)
            if actual_bytes:
                assert any(v.get("transcript") == "Hello." for v in browser.sent)
        finally:
            await service.close()
    upstream = None
    asyncio.run(run())


def test_streaming_probe_requires_completed_real_audio_and_preserves_chunks():
    async def run():
        pcm = b"\x01\x02" * 321
        probe = StreamingProbe(pcm)
        with pytest.raises(HTTPException, match="nonempty final transcript"):
            probe.result()
        chunks = [await probe.receive(), await probe.receive()]
        assert b"".join(chunk["bytes"] for chunk in chunks) == pcm
        assert (await probe.receive())["text"] == "stop"
        await probe.send_json({"type": PREFIX + "completed", "transcript": "Audio demonstration."})
        await probe.send_json({"type": "done"})
        assert probe.result()["transcript"] == "Audio demonstration."
        assert probe.result()["audio_seconds"] == len(pcm) / 32000
        with pytest.raises(HTTPException, match="valid PCM16"):
            StreamingProbe(b"\0")
    asyncio.run(run())
