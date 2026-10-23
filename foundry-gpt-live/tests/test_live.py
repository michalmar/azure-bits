from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import json
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.auth import AuthConfig, OIDCAuthManager, SESSION_COOKIE_NAME
from app.live import (
    GRILL_INSTRUCTIONS,
    INSTRUCTIONS,
    MAX_AUDIO_FRAME_BYTES,
    MAX_INSTRUCTIONS_LENGTH,
    PROMPT_PRESETS,
    TOKEN_SCOPE,
    LiveService,
    LiveSettings,
)
from app.main import _from_browser, _outgoing_event, _relay, create_app
from scripts import configure_entra


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
    assert settings.start_event()["session"]["instructions"] == INSTRUCTIONS
    assert settings.start_event("Custom instructions")["session"]["instructions"] == "Custom instructions"
    assert settings.max_session_seconds == 900
    assert settings.default_session_seconds == 300
    for endpoint in (
        "http://demo-swe.openai.azure.com",
        "https://attacker.example",
        "https://demo-swe.openai.azure.com/other",
    ):
        with pytest.raises(ValueError, match="HTTPS origin"):
            LiveSettings(endpoint=endpoint)
    for seconds in (0, 1, 59, 61, 901, 960):
        with pytest.raises(ValueError, match="whole number of minutes"):
            LiveSettings(endpoint=settings.endpoint, max_session_seconds=seconds)


def test_duration_ceiling_from_environment_and_reduced_default(settings, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", settings.endpoint)
    monkeypatch.delenv("MAX_SESSION_SECONDS", raising=False)
    assert LiveSettings.from_env().max_session_seconds == 900
    monkeypatch.setenv("MAX_SESSION_SECONDS", "60")
    capped = LiveSettings.from_env()
    assert capped.max_session_seconds == 60
    assert capped.default_session_seconds == 60


def test_grill_replaces_interview_coach_without_changing_the_default():
    assert [(preset["id"], preset["label"]) for preset in PROMPT_PRESETS] == [
        ("default", "Default"),
        ("language-tutor", "Language tutor"),
        ("grill", "Grill"),
    ]
    assert PROMPT_PRESETS[0]["instructions"] == INSTRUCTIONS
    assert PROMPT_PRESETS[2]["instructions"] == GRILL_INSTRUCTIONS
    assert GRILL_INSTRUCTIONS.startswith("# Voice agent instructions\n\nYou are a professional")
    assert GRILL_INSTRUCTIONS.endswith("Don't act on the plan until the user confirms.")
    assert "4. Stop and wait." in GRILL_INSTRUCTIONS
    assert 0 < len(GRILL_INSTRUCTIONS) <= MAX_INSTRUCTIONS_LENGTH


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
        config = client.get("/api/config").json()
        assert config["maxSessionSeconds"] == 900
        assert config["minSessionSeconds"] == 60
        assert config["defaultSessionSeconds"] == 300
        assert config["promptPresets"] == list(PROMPT_PRESETS)
        assert config["defaultPromptId"] == "default"
        assert config["maxInstructionsLength"] == MAX_INSTRUCTIONS_LENGTH
        assert config["promptPresets"][0]["instructions"] == INSTRUCTIONS
        assert "Talk while it talks." in client.get("/").text
        assert client.get("/static/audio-worklet.js").status_code == 200
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS})
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
    assert connection.sent[0]["session"]["instructions"] == INSTRUCTIONS


def test_page_uses_versioned_assets_and_uncached_configuration(settings):
    app = create_app(settings=settings, service=FakeService(FakeConnection()))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.headers["cache-control"] == "no-store"
        assert client.get("/api/config").headers["cache-control"] == "no-store"
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
        assert len(assets) == 4
        assert len({url.split("/")[2] for url in assets}) == 1
        for url in assets:
            response = client.get(url)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "private, no-cache"
        prefix = assets[0].rsplit("/", 1)[0]
        assert client.get(prefix + "/format.mjs").status_code == 200
        assert client.get(prefix + "/audio-worklet.js").status_code == 200
        assert client.get("/static/app.js").headers["cache-control"] == "private, no-cache"
        assert client.get("/assets/old-version/app.js").status_code == 404
        assert client.get(prefix + "/%2e%2e/app/main.py").status_code == 404


def test_asset_version_changes_when_a_frontend_dependency_changes(settings, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text('<script src="/static/app.js"></script>')
    (tmp_path / "app.js").write_text('import "./format.mjs";')
    (tmp_path / "format.mjs").write_text("export const version = 1;")
    monkeypatch.setattr("app.main.STATIC_ROOT", tmp_path)
    app = create_app(settings=settings, service=FakeService(FakeConnection()))
    with TestClient(app) as client:
        old_url = re.search(r'src="([^"]+)"', client.get("/").text).group(1)
    (tmp_path / "format.mjs").write_text("export const version = 2;")
    updated = create_app(settings=settings, service=FakeService(FakeConnection()))
    with TestClient(updated) as client:
        new_url = re.search(r'src="([^"]+)"', client.get("/").text).group(1)
        assert new_url != old_url
        assert client.get(old_url).status_code == 404
        assert client.get(new_url).status_code == 200


@pytest.mark.parametrize("instructions", [
    preset["instructions"] for preset in PROMPT_PRESETS
] + [
    "  Odpovídej česky.\nAsk only one question at a time.  ",
    "🎙" * MAX_INSTRUCTIONS_LENGTH,
])
def test_selected_prompt_is_forwarded_verbatim(settings, instructions):
    connection = FakeConnection()
    app = create_app(settings=settings, service=FakeService(connection))
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            socket.send_json({"type": "start", "instructions": instructions})
            assert socket.receive_json()["type"] == "ready"
            assert connection.sent[0]["session"]["instructions"] == instructions
            socket.send_json({"type": "stop"})
            assert socket.receive_json()["type"] == "closed"


@pytest.mark.parametrize("message", [
    {"type": "start", "instructions": ""},
    {"type": "start", "instructions": " \n\t "},
    {"type": "start", "instructions": None},
    {"type": "start", "instructions": 123},
    {"type": "start", "instructions": ["prompt"]},
    {"type": "start", "instructions": "x" * (MAX_INSTRUCTIONS_LENGTH + 1)},
    {"type": "start"},
    {"type": "start", "instructions": "prompt", "extra": True},
    {"type": "mute", "muted": True},
    [],
])
def test_invalid_start_does_not_open_model_or_leak_session_slot(settings, message):
    service = FakeService(FakeConnection())
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            socket.send_json(message)
            assert socket.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert service.opened == 0
        assert app.state.active_sessions == 0


@pytest.mark.parametrize("frame", [
    {"text": "not json"},
    {"text": "x" * (MAX_INSTRUCTIONS_LENGTH * 12 + 1025)},
    {"bytes": b"\0\0"},
])
def test_invalid_start_frames_are_rejected_before_model_connection(settings, frame):
    service = FakeService(FakeConnection())
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            socket.send({"type": "websocket.receive", **frame})
            assert socket.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert service.opened == 0
        assert app.state.active_sessions == 0


def test_start_timeout_does_not_open_model(settings, monkeypatch):
    monkeypatch.setattr("app.main.START_TIMEOUT_SECONDS", 0.01)
    service = FakeService(FakeConnection())
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            assert socket.receive_json() == {
                "type": "error", "message": "The live connection failed or timed out.",
            }
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert service.opened == 0
        assert app.state.active_sessions == 0


def test_disconnect_before_start_does_not_open_model(settings):
    service = FakeService(FakeConnection())
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        with client.websocket_connect("/api/live"):
            pass
    assert service.opened == 0
    assert app.state.active_sessions == 0


def test_browser_disconnect_closes_upstream(settings):
    connection = FakeConnection()
    app = create_app(settings=settings, service=FakeService(connection))
    with TestClient(app) as client:
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS})
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
        await asyncio.wait_for(_relay(DisconnectedBrowser(), connection, 300), timeout=2)

    asyncio.run(run())
    assert connection.sent[-1]["type"] == "session.close"


@pytest.mark.parametrize("duration", [60, 300, 900])
def test_session_limit_closes_at_the_selected_threshold(settings, monkeypatch, duration):
    requested_delays = []
    real_sleep = asyncio.sleep

    async def expire_selected_duration(seconds):
        if seconds == duration:
            requested_delays.append(seconds)
            return
        await real_sleep(seconds)

    monkeypatch.setattr("app.main.asyncio.sleep", expire_selected_duration)
    connection = FakeConnection()
    app = create_app(settings=settings, service=FakeService(connection))
    with TestClient(app) as client:
        with client.websocket_connect("/api/live", headers={"origin": "http://testserver"}) as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS, "durationSeconds": duration})
            assert socket.receive_json() == {
                "type": "ready", "model": "gpt-live-1", "maxSessionSeconds": duration,
            }
            assert socket.receive_json()["type"] == "limit"
            assert socket.receive_json()["type"] == "closed"
    assert connection.sent[-1]["type"] == "session.close"
    assert requested_delays == [duration]
    assert "durationSeconds" not in connection.sent[0]["session"]


@pytest.mark.parametrize("duration", list(range(60, 901, 60)))
def test_every_whole_minute_duration_is_accepted(settings, duration):
    connection = FakeConnection()
    app = create_app(settings=settings, service=FakeService(connection))
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS, "durationSeconds": duration})
            assert socket.receive_json()["maxSessionSeconds"] == duration
            socket.send_json({"type": "stop"})
            assert socket.receive_json()["type"] == "closed"
    assert settings.max_session_seconds == 900


@pytest.mark.parametrize("duration", [None, True, False, "60", 60.0, [], 0, -60, 59, 61, 901, 960])
def test_invalid_duration_is_rejected_before_opening_a_model(settings, duration):
    service = FakeService(FakeConnection())
    app = create_app(settings=settings, service=service)
    with TestClient(app) as client:
        with client.websocket_connect("/api/live") as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS, "durationSeconds": duration})
            error = socket.receive_json()
            assert error["type"] == "error"
            assert "Duration" in error["message"]
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert service.opened == 0
        assert app.state.active_sessions == 0


def test_configured_ceiling_cannot_be_exceeded(settings):
    service = FakeService(FakeConnection())
    app = create_app(
        settings=LiveSettings(endpoint=settings.endpoint, max_session_seconds=300),
        service=service,
    )
    with TestClient(app) as client:
        assert client.get("/api/config").json()["maxSessionSeconds"] == 300
        with client.websocket_connect("/api/live") as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS, "durationSeconds": 360})
            assert socket.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert service.opened == 0


def test_existing_image_update_applies_duration_ceiling_and_preserves_auth(monkeypatch):
    snapshot = {
        "properties": {
            "configuration": {"secrets": []},
            "template": {"containers": [{
                "image": "old-image",
                "env": [
                    {"name": "MAX_SESSION_SECONDS", "value": "300"},
                    {"name": "AUTH_ENABLED", "value": "true"},
                    {"name": "SESSION_SECRET", "secretRef": "existing-secret"},
                ],
            }]},
        },
    }
    monkeypatch.setattr(configure_entra, "_arm_json", lambda app_id: deepcopy(snapshot))
    monkeypatch.setattr(configure_entra, "_apply_container_app_snapshot", lambda current: current)
    updated = configure_entra._update_container_image(
        "app-id", container_image="new-image", max_session_seconds=900, snapshot=snapshot,
    )
    container = updated["properties"]["template"]["containers"][0]
    assert container["image"] == "new-image"
    assert container["env"] == [
        {"name": "AUTH_ENABLED", "value": "true"},
        {"name": "SESSION_SECRET", "secretRef": "existing-secret"},
        {"name": "MAX_SESSION_SECONDS", "value": "900"},
    ]
    assert updated["properties"]["configuration"] == snapshot["properties"]["configuration"]


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
        page = client.get("/")
        script_url = re.search(r'src="(/assets/[^"]+/app\.js)"', page.text).group(1)
        assert client.get(script_url).status_code == 200
        assert client.get("/api/config").json()["promptPresets"] == list(PROMPT_PRESETS)
        with pytest.raises(WebSocketDisconnect) as cross_site:
            with client.websocket_connect("/api/live", headers={"origin": "https://evil.example"}):
                pass
        assert cross_site.value.code == 4403
        with client.websocket_connect("/api/live", headers={"origin": "https://testserver"}) as socket:
            socket.send_json({"type": "start", "instructions": INSTRUCTIONS})
            assert socket.receive_json()["type"] == "ready"
            socket.send_json({"type": "stop"})
            assert socket.receive_json()["type"] == "closed"
        auth.config = AuthConfig(
            enabled=True, public_base_url="https://testserver",
            tenant_id="tenant", client_id="client", client_secret="secret",
            session_secret="cookie-key", allowed_users=("entra:another-user",),
        )
        assert client.get("/api/config").status_code == 401
        assert client.get(script_url, follow_redirects=False).status_code == 307
    asyncio.run(auth.close())

    locked = create_app(settings=settings, service=FakeService(FakeConnection()), bootstrap_locked=True)
    with TestClient(locked) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 503
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/live"):
                pass
        assert denied.value.code == 4403
