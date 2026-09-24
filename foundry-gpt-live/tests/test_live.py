from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.auth import AuthConfig, OIDCAuthManager, SESSION_COOKIE_NAME
from app.live import LiveService, LiveSettings, MAX_AUDIO_FRAME_BYTES, TOKEN_SCOPE
from app.main import _from_browser, _outgoing_event, _relay, create_app


class FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.events: asyncio.Queue[str] = asyncio.Queue()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def send(self, value: str) -> None:
        event = json.loads(value)
        self.sent.append(event)
        if event["type"] == "session.start":
            await self.push({"type": "session.started", "session": {"model": "gpt-live-1"}})
        elif event["type"] == "session.input_audio.append":
            await self.push({
                "type": "session.input_transcript.delta",
                "delta": "Hello", "start_ms": 100, "end_ms": 300,
            })
            await self.push({
                "type": "session.output_audio.delta",
                "delta": base64.b64encode(b"\0\0").decode("ascii"),
                "start_ms": 200, "end_ms": 220,
            })
        elif event["type"] == "session.input_audio.mute":
            await self.push({"type": "session.input_audio.muted"})
        elif event["type"] == "session.close":
            await self.push({
                "type": "session.closed", "reason": "close_requested",
                "usage": {"seconds": 4},
            })

    async def push(self, event: dict[str, object]) -> None:
        await self.events.put(json.dumps(event))

    async def recv(self) -> str:
        return await self.events.get()

    async def __aiter__(self):
        while True:
            event = await self.recv()
            yield event
            if json.loads(event)["type"] == "session.closed":
                return


class FakeService:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.opened = 0

    async def open_connection(self):
        self.opened += 1
        return self.connection


@pytest.fixture()
def settings() -> LiveSettings:
    return LiveSettings(endpoint="https://demo-swe.openai.azure.com")


def test_live_settings_and_start_event(settings):
    assert settings.websocket_url == "wss://demo-swe.openai.azure.com/openai/v1/live/sessions"
    assert settings.start_event()["session"]["model"] == "gpt-live-1"
    assert settings.start_event()["session"]["audio"] == {"output": {"voice": "marin"}}
    assert settings.start_event()["session"]["delegation"] == {"type": "client"}
    assert settings.max_session_seconds == 300
    for endpoint in (
        "http://demo-swe.openai.azure.com",
        "https://attacker.example",
        "https://demo-swe.openai.azure.com/other",
    ):
        with pytest.raises(ValueError, match="HTTPS origin"):
            LiveSettings(endpoint=endpoint)
    with pytest.raises(ValueError, match="between 1 and 600"):
        LiveSettings(endpoint=settings.endpoint, max_session_seconds=601)


def test_live_connection_uses_azure_identity(settings, monkeypatch):
    class Credential:
        def get_token(self, scope):
            assert scope == TOKEN_SCOPE
            return SimpleNamespace(token="fake-token")

    observed = {}

    def fake_connect(url, *, additional_headers, **kwargs):
        observed["url"] = url
        observed["authorization"] = additional_headers["Authorization"]
        return object()

    monkeypatch.setattr("app.live.connect", fake_connect)
    asyncio.run(LiveService(settings, credential=Credential()).open_connection())
    assert observed == {
        "url": settings.websocket_url,
        "authorization": "Bearer fake-token",
    }


def test_pcm_frames_and_allowed_commands():
    frame = b"\x80\xff\x7f\x00" * 480
    assert _from_browser({"bytes": frame}) == {
        "type": "session.input_audio.append",
        "audio": base64.b64encode(frame).decode("ascii"),
    }
    assert _from_browser({"text": '{"type":"mute","muted":true}'}) == {"type": "session.input_audio.mute"}
    assert _from_browser({"text": '{"type":"mute","muted":false}'}) == {"type": "session.input_audio.unmute"}
    assert _from_browser({"text": '{"type":"stop"}'}) is None
    for invalid in (b"", b"\x01", b"\0" * (MAX_AUDIO_FRAME_BYTES + 2)):
        with pytest.raises(ValueError, match="PCM16"):
            _from_browser({"bytes": invalid})
    for invalid in ('{"type":"session.start"}', '{"type":"mute","muted":"true"}', "not json"):
        with pytest.raises(ValueError, match="Unsupported"):
            _from_browser({"text": invalid})


def test_model_events_map_to_conversation_without_leaking_session_data():
    assert _outgoing_event({
        "type": "session.input_transcript.delta",
        "delta": "Hello", "start_ms": 100, "end_ms": 250,
    }) == {"type": "transcript", "speaker": "you", "text": "Hello", "startMs": 100, "endMs": 250}
    assert _outgoing_event({"type": "session.output_audio.delta", "delta": "AQI="}) == {
        "type": "audio", "data": "AQI=",
    }
    assert _outgoing_event({"type": "session.started", "session": {"instructions": "private"}}) is None


def test_live_bridge_streams_audio_transcript_and_closes(settings):
    connection = FakeConnection()
    service = FakeService(connection)
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "healthy"}
        assert client.get("/api/config").json()["maxSessionSeconds"] == 300
        assert "Talk while it talks." in client.get("/").text
        assert client.get("/static/audio-worklet.js").status_code == 200
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            assert socket.receive_json() == {
                "type": "ready", "model": "gpt-live-1", "maxSessionSeconds": 300,
            }
            socket.send_bytes(b"\0\0" * 480)
            socket.send_json({"type": "mute", "muted": True})
            assert socket.receive_json()["speaker"] == "you"
            assert socket.receive_json()["type"] == "audio"
            assert socket.receive_json() == {"type": "muted", "muted": True}
            socket.send_json({"type": "stop"})
            assert socket.receive_json() == {
                "type": "closed", "reason": "close_requested", "seconds": 4,
            }
    assert [event["type"] for event in connection.sent] == [
        "session.start", "session.input_audio.append", "session.input_audio.mute", "session.close",
    ]
    assert service.opened == 1


def test_browser_disconnect_closes_upstream(settings):
    connection = FakeConnection()
    app = create_app(settings=settings, service=FakeService(connection))
    with TestClient(app) as client:
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            assert socket.receive_json()["type"] == "ready"
    assert connection.sent[-1]["type"] == "session.close"


def test_failed_browser_send_closes_upstream(settings):
    class DisconnectedBrowser:
        async def receive(self):
            await asyncio.Event().wait()

        async def send_json(self, message):
            raise WebSocketDisconnect(code=1006)

    connection = FakeConnection()

    async def run():
        await connection.push({
            "type": "session.input_transcript.delta",
            "delta": "Hello", "start_ms": 100, "end_ms": 300,
        })
        await asyncio.wait_for(_relay(DisconnectedBrowser(), connection, settings), timeout=2)

    asyncio.run(run())
    assert connection.sent[-1]["type"] == "session.close"


def test_session_limit_closes_at_the_configured_threshold():
    connection = FakeConnection()
    app = create_app(
        settings=LiveSettings(endpoint="https://demo-swe.openai.azure.com", max_session_seconds=1),
        service=FakeService(connection),
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            assert socket.receive_json()["type"] == "ready"
            assert socket.receive_json()["type"] == "limit"
            assert socket.receive_json()["type"] == "closed"
    assert connection.sent[-1]["type"] == "session.close"


def test_auth_origin_and_bootstrap_gate(settings):
    connection = FakeConnection()
    service = FakeService(connection)
    auth = OIDCAuthManager(AuthConfig(
        enabled=True,
        public_base_url="https://testserver",
        tenant_id="tenant", client_id="client", client_secret="secret",
        session_secret="cookie-key", allowed_users=("tenant:*",),
    ))
    app = create_app(settings=settings, service=service, auth_manager=auth)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/", follow_redirects=False).status_code == 307
        assert client.get("/api/config").status_code == 401
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/live", headers={"origin": "https://testserver"}):
                pass
        assert denied.value.code == 4401
        client.cookies.set(SESSION_COOKIE_NAME, auth.create_session_cookie({
            "tid": "tenant", "oid": "person-123", "name": "Test User",
        }))
        with pytest.raises(WebSocketDisconnect) as cross_site:
            with client.websocket_connect("/api/live", headers={"origin": "https://evil.example"}):
                pass
        assert cross_site.value.code == 4403
        with client.websocket_connect("/api/live", headers={"origin": "https://testserver"}) as socket:
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "stop"})
            assert socket.receive_json()["type"] == "closed"
        auth.config = AuthConfig(
            enabled=True, public_base_url="https://testserver",
            tenant_id="tenant", client_id="client", client_secret="secret",
            session_secret="cookie-key", allowed_users=("entra:another-user",),
        )
        assert client.get("/api/config").status_code == 401
    asyncio.run(auth.close())

    locked = create_app(settings=settings, service=FakeService(FakeConnection()), bootstrap_locked=True)
    with TestClient(locked) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 503
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/live"):
                pass
        assert denied.value.code == 4403
