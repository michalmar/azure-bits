from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
from urllib.parse import quote

from azure.core.exceptions import ClientAuthenticationError
from azure.identity import CredentialUnavailableError
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .auth import (
    OIDCAuthManager,
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    load_auth_config_from_env,
    sanitize_return_to,
)
from .live import DELEGATION_REPLY, MAX_AUDIO_FRAME_BYTES, LiveService, LiveSettings


STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
logger = logging.getLogger(__name__)


class LiveProtocolError(Exception):
    pass


def _event(raw: str | bytes) -> dict[str, object]:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise LiveProtocolError("The model sent an invalid event.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        raise LiveProtocolError("The model sent an invalid event.")
    return data


def _error_message(event: dict[str, object]) -> str:
    error = event.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) and message else "The model rejected the request."


async def _await_started(upstream, settings: LiveSettings) -> None:
    async def receive_start() -> None:
        for _ in range(5):
            event = _event(await upstream.recv())
            if event["type"] == "error":
                raise LiveProtocolError(_error_message(event))
            if event["type"] == "session.started":
                session = event.get("session")
                if not isinstance(session, dict) or session.get("model") != settings.deployment:
                    raise LiveProtocolError("The model started a different deployment.")
                return
        raise LiveProtocolError("The model did not confirm the session.")

    await asyncio.wait_for(receive_start(), timeout=20)


def _from_browser(frame: dict[str, object]) -> dict[str, object] | None:
    audio = frame.get("bytes")
    if isinstance(audio, bytes):
        if not audio or len(audio) > MAX_AUDIO_FRAME_BYTES or len(audio) % 2:
            raise ValueError("Audio must be nonempty, even-length PCM16 (at most one second per frame).")
        return {"type": "session.input_audio.append", "audio": base64.b64encode(audio).decode("ascii")}
    text = frame.get("text")
    if not isinstance(text, str) or len(text) > 1024:
        raise ValueError("Unsupported client message.")
    try:
        message = json.loads(text)
    except ValueError as exc:
        raise ValueError("Unsupported client message.") from exc
    if not isinstance(message, dict):
        raise ValueError("Unsupported client message.")
    if message == {"type": "stop"}:
        return None
    if message.get("type") == "mute" and isinstance(message.get("muted"), bool) and len(message) == 2:
        return {"type": "session.input_audio.mute" if message["muted"] else "session.input_audio.unmute"}
    raise ValueError("Unsupported client message.")


def _outgoing_event(event: dict[str, object]) -> dict[str, object] | None:
    kind = event["type"]
    if kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
        delta = event.get("delta")
        start = event.get("start_ms")
        end = event.get("end_ms")
        if (
            not isinstance(delta, str)
            or len(delta) > 4096
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
        ):
            raise LiveProtocolError("The model sent an invalid transcript.")
        return {
            "type": "transcript",
            "speaker": "you" if kind == "session.input_transcript.delta" else "assistant",
            "text": delta,
            "startMs": start,
            "endMs": end,
        }
    if kind == "session.output_audio.delta":
        delta = event.get("delta")
        if not isinstance(delta, str) or len(delta) > 512_000:
            raise LiveProtocolError("The model sent invalid audio.")
        return {"type": "audio", "data": delta}
    if kind == "session.input_audio.muted":
        return {"type": "muted", "muted": True}
    if kind == "session.input_audio.unmuted":
        return {"type": "muted", "muted": False}
    if kind == "session.usage.updated":
        usage = event.get("usage")
        seconds = usage.get("seconds") if isinstance(usage, dict) else None
        if isinstance(seconds, (int, float)) and seconds >= 0:
            return {"type": "usage", "seconds": seconds}
        raise LiveProtocolError("The model sent invalid usage.")
    if kind == "session.closed":
        usage = event.get("usage")
        seconds = usage.get("seconds") if isinstance(usage, dict) else None
        return {
            "type": "closed",
            "reason": event.get("reason", "unknown"),
            "seconds": seconds if isinstance(seconds, (int, float)) and seconds >= 0 else None,
        }
    if kind == "error":
        return {"type": "error", "message": _error_message(event)}
    return None


async def _relay(websocket: WebSocket, upstream, settings: LiveSettings) -> None:
    browser_connected = True
    browser_disconnected = asyncio.Event()

    async def receive_browser() -> str:
        nonlocal browser_connected
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                browser_connected = False
                browser_disconnected.set()
                return "disconnect"
            outgoing = _from_browser(frame)
            if outgoing is None:
                return "stop"
            await upstream.send(json.dumps(outgoing))

    async def send_to_browser(message: dict[str, object]) -> None:
        nonlocal browser_connected
        if browser_connected:
            try:
                await websocket.send_json(message)
            except WebSocketDisconnect:
                browser_connected = False
                browser_disconnected.set()

    async def receive_model() -> str:
        async for raw in upstream:
            event = _event(raw)
            if event["type"] == "session.delegation.created":
                delegation = event.get("delegation")
                if isinstance(delegation, dict) and delegation.get("target") == "client":
                    delegation_id = delegation.get("id")
                    if not isinstance(delegation_id, str) or not delegation_id:
                        raise LiveProtocolError("The model sent an invalid delegation.")
                    await upstream.send(json.dumps({
                        "type": "session.commentary.append",
                        "delegation_id": delegation_id,
                        "content": DELEGATION_REPLY,
                    }))
                    await send_to_browser({"type": "notice", "message": "No external tools are connected."})
                continue
            outgoing = _outgoing_event(event)
            if outgoing:
                await send_to_browser(outgoing)
            if event["type"] in {"session.closed", "error"}:
                return str(event["type"])
        return "disconnected"

    browser_task = asyncio.create_task(receive_browser())
    model_task = asyncio.create_task(receive_model())
    limit_task = asyncio.create_task(asyncio.sleep(settings.max_session_seconds))
    disconnect_task = asyncio.create_task(browser_disconnected.wait())
    try:
        done, _ = await asyncio.wait(
            {browser_task, model_task, limit_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if model_task in done:
            result = model_task.result()
            if result == "disconnected" and browser_connected:
                raise LiveProtocolError("The model connection closed without confirming the session.")
            return
        if browser_task in done:
            browser_task.result()
        elif disconnect_task not in done:
            browser_task.cancel()
            await send_to_browser({
                "type": "limit", "message": "Session time limit reached. Closing the conversation."
            })

        await upstream.send(json.dumps({"type": "session.close"}))
        try:
            outcome = await asyncio.wait_for(model_task, timeout=10)
        except asyncio.TimeoutError as exc:
            raise LiveProtocolError("The model did not confirm that the session closed.") from exc
        if outcome == "disconnected" and browser_connected:
            raise LiveProtocolError("The model disconnected before confirming the session closed.")
    finally:
        for task in (browser_task, model_task, limit_task, disconnect_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(browser_task, model_task, limit_task, disconnect_task, return_exceptions=True)


async def _send_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message})
    except WebSocketDisconnect:
        pass


def create_app(
    settings: LiveSettings | None = None,
    service: LiveService | None = None,
    auth_manager: OIDCAuthManager | None = None,
    bootstrap_locked: bool | None = None,
) -> FastAPI:
    locked = (
        os.getenv("BOOTSTRAP_LOCKED", "false").lower() == "true"
        if bootstrap_locked is None else bootstrap_locked
    )
    auth_config = None if locked or auth_manager is not None else load_auth_config_from_env()
    if os.getenv("APP_ENV", "development").lower() == "production" and not locked:
        if auth_manager is None and not auth_config.enabled:
            raise RuntimeError("Production requires AUTH_ENABLED=true")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.auth = None if locked else (auth_manager or OIDCAuthManager(auth_config))
        app.state.settings = settings or LiveSettings.from_env()
        app.state.service = service or LiveService(app.state.settings)
        app.state.active_sessions = 0
        try:
            yield
        finally:
            if service is None:
                await app.state.service.close()
            if auth_manager is None and app.state.auth is not None:
                await app.state.auth.close()

    app = FastAPI(
        title="Foundry GPT-Live demo",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def reader_auth(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if locked:
            return JSONResponse({"detail": "Demo sign-in is being configured."}, status_code=503)
        auth: OIDCAuthManager = request.app.state.auth
        if not auth.enabled or request.url.path in {"/login", "/logout", "/oauth/entra/callback"}:
            return await call_next(request)
        identity = auth.load_session(request.cookies.get(SESSION_COOKIE_NAME))
        if identity:
            request.state.identity = identity
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required."}, status_code=401)
        target = sanitize_return_to(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(f"/login?return_to={quote(target, safe='')}", status_code=307)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/login", include_in_schema=False)
    async def login(request: Request, return_to: str | None = None):
        auth: OIDCAuthManager = request.app.state.auth
        if not auth.enabled:
            return RedirectResponse(sanitize_return_to(return_to))
        try:
            url, state_cookie = await auth.begin_login(return_to)
        except Exception as exc:
            logger.exception("Entra sign-in unavailable")
            raise HTTPException(status_code=503, detail="Sign-in is currently unavailable.") from exc
        response = RedirectResponse(url, status_code=302)
        response.set_cookie(
            STATE_COOKIE_NAME, state_cookie, secure=True, httponly=True,
            samesite="lax", path="/", max_age=600,
        )
        return response

    @app.get("/oauth/entra/callback", include_in_schema=False)
    async def callback(request: Request, code: str = "", state: str = ""):
        auth: OIDCAuthManager = request.app.state.auth
        if not code or not state or not request.cookies.get(STATE_COOKIE_NAME):
            raise HTTPException(status_code=400, detail="Missing Entra sign-in state.")
        try:
            result = await auth.exchange_code(code, request.cookies[STATE_COOKIE_NAME], state)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Entra sign-in failed")
            raise HTTPException(status_code=401, detail="Sign-in failed; start again.") from exc
        response = RedirectResponse(result["return_to"], status_code=302)
        response.set_cookie(
            SESSION_COOKIE_NAME, auth.create_session_cookie(result["session"]),
            secure=True, httponly=True, samesite="lax", path="/", max_age=60 * 60 * 8,
        )
        response.delete_cookie(STATE_COOKIE_NAME, path="/")
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout():
        response = RedirectResponse("/login", status_code=302)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return response

    @app.get("/api/config")
    async def config(request: Request) -> dict[str, object]:
        live: LiveSettings = request.app.state.settings
        identity = getattr(request.state, "identity", None)
        return {
            "model": live.deployment,
            "maxSessionSeconds": live.max_session_seconds,
            "maxConcurrentSessions": live.max_concurrent_sessions,
            "voice": "marin",
            "user": identity.get("name") if identity else None,
        }

    @app.websocket("/api/live")
    async def live(websocket: WebSocket) -> None:
        if locked:
            await websocket.close(code=4403)
            return
        auth: OIDCAuthManager = websocket.app.state.auth
        if auth.enabled and not auth.load_session(websocket.cookies.get(SESSION_COOKIE_NAME)):
            await websocket.close(code=4401)
            return
        origin = websocket.headers.get("origin")
        expected = (
            auth.config.public_base_url.rstrip("/")
            if auth.enabled else f"{'https' if websocket.url.scheme == 'wss' else 'http'}://{websocket.headers.get('host')}"
        )
        if origin != expected and (origin is not None or auth.enabled):
            await websocket.close(code=4403)
            return
        live_settings: LiveSettings = websocket.app.state.settings
        if websocket.app.state.active_sessions >= live_settings.max_concurrent_sessions:
            await websocket.close(code=4429)
            return
        websocket.app.state.active_sessions += 1
        try:
            await websocket.accept()
            service: LiveService = websocket.app.state.service
            connection = await service.open_connection()
            async with connection as upstream:
                await upstream.send(json.dumps(live_settings.start_event()))
                await _await_started(upstream, live_settings)
                await websocket.send_json({
                    "type": "ready",
                    "model": live_settings.deployment,
                    "maxSessionSeconds": live_settings.max_session_seconds,
                })
                await _relay(websocket, upstream, live_settings)
        except WebSocketDisconnect:
            pass
        except (ClientAuthenticationError, CredentialUnavailableError):
            logger.exception("Managed identity or Azure CLI model authentication failed")
            await _send_error(websocket, "Model authentication failed. Check the Foundry role assignment.")
        except InvalidStatus as exc:
            status = exc.response.status_code
            logger.warning("Foundry rejected WebSocket connection: HTTP %s", status)
            await _send_error(
                websocket, f"Foundry refused the connection (HTTP {status}). Check model access and capacity."
            )
        except (LiveProtocolError, ValueError) as exc:
            await _send_error(websocket, str(exc))
        except (OSError, asyncio.TimeoutError, ConnectionClosed) as exc:
            logger.warning("Live connection failed: %s", type(exc).__name__)
            await _send_error(websocket, "The live connection failed or timed out.")
        finally:
            websocket.app.state.active_sessions -= 1
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(STATIC_ROOT / "index.html", media_type="text/html")

    @app.get("/static/{file_path:path}", include_in_schema=False)
    async def static(file_path: str):
        target = (STATIC_ROOT / file_path).resolve()
        if not target.is_relative_to(STATIC_ROOT.resolve()) or not target.is_file():
            raise HTTPException(status_code=404, detail="Not found.")
        return FileResponse(target)

    return app


app = create_app()
