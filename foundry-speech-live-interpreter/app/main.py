from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import os
from pathlib import Path
import threading
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .auth import AuthManager, SESSION_COOKIE, STATE_COOKIE, load_auth_config, safe_return_to
from .speech import (
    ConfigurationError,
    create_translation_config,
    format_cancellation,
    load_speech_sdk,
    pcm_to_wav,
    settings_from_values,
    synthesis_chunk_format,
    translations,
)


STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MAX_SESSION_SECONDS = int(os.getenv("MAX_SESSION_SECONDS", "120"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.auth = AuthManager(load_auth_config())
    try:
        yield
    finally:
        await app.state.auth.close()


app = FastAPI(title="Azure Speech Live Interpreter", lifespan=lifespan)


@app.middleware("http")
async def require_reader(request: Request, call_next):
    auth: AuthManager = request.app.state.auth
    if not auth.config.enabled or request.url.path in {"/healthz", "/login", "/logout", "/oauth/entra/callback"}:
        return await call_next(request)
    identity = auth.session(request.cookies.get(SESSION_COOKIE))
    if identity:
        request.state.identity = identity
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?return_to={quote(safe_return_to(target), safe='')}", status_code=307)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/login", include_in_schema=False)
async def login(request: Request, return_to: str | None = None):
    auth: AuthManager = request.app.state.auth
    if not auth.config.enabled:
        return RedirectResponse("/")
    url, state_cookie = await auth.begin_login(return_to)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(STATE_COOKIE, state_cookie, secure=True, httponly=True, samesite="lax", path="/", max_age=600)
    return response


@app.get("/oauth/entra/callback", include_in_schema=False)
async def callback(request: Request, code: str = "", state: str = ""):
    auth: AuthManager = request.app.state.auth
    try:
        _, session = await auth.exchange(code, state, request.cookies.get(STATE_COOKIE, ""))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}") from exc
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(SESSION_COOKIE, session, secure=True, httponly=True, samesite="lax", path="/", max_age=60 * 60 * 8)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@app.get("/logout", include_in_schema=False)
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/config")
async def api_config(request: Request) -> dict[str, object]:
    auth: AuthManager = request.app.state.auth
    identity = getattr(request.state, "identity", None)
    return {
        "personalVoiceAvailable": os.getenv("PERSONAL_VOICE_ENABLED", "").lower() == "true",
        "maxSessionSeconds": MAX_SESSION_SECONDS,
        "authenticated": bool(identity),
        "user": {"name": identity.get("name", "")} if identity else None,
    }


@app.websocket("/api/interpret")
async def interpret(websocket: WebSocket):
    auth: AuthManager = websocket.app.state.auth
    if auth.config.enabled and not auth.session(websocket.cookies.get(SESSION_COOKIE)):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    speechsdk = None
    recognizer = None
    push_stream = None
    audio_chunks: list[bytes] = []
    stopped = threading.Event()
    event_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(payload: dict[str, object]) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, payload)

    try:
        start = await asyncio.wait_for(websocket.receive_json(), timeout=15)
        settings = settings_from_values(
            str(start.get("targetLanguage", "fr")),
            str(start.get("voice", "") or "") or None,
        )
        speechsdk = load_speech_sdk()
        translation_config, auto_detect = create_translation_config(settings, speechsdk)
        audio_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=translation_config,
            auto_detect_source_language_config=auto_detect,
            audio_config=speechsdk.audio.AudioConfig(stream=push_stream),
        )

        recognizer.recognizing.connect(
            lambda event: emit(
                {
                    "type": "recognizing",
                    "source": getattr(event.result, "text", ""),
                    "translations": translations(event.result),
                }
            )
        )
        recognizer.recognized.connect(
            lambda event: emit(
                {
                    "type": "recognized",
                    "source": getattr(event.result, "text", ""),
                    "translations": translations(event.result),
                }
            )
        )

        def on_synthesizing(event) -> None:
            audio = bytes(getattr(event.result, "audio", b"") or b"")
            if audio:
                audio_chunks.append(audio)
                emit(
                    {
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio).decode("ascii"),
                        "format": synthesis_chunk_format(audio),
                    }
                )

        recognizer.synthesizing.connect(on_synthesizing)
        recognizer.canceled.connect(
            lambda event: (
                emit({"type": "error", "message": format_cancellation(event, settings.voice_name)}),
                stopped.set(),
            )
        )
        recognizer.session_stopped.connect(lambda _: stopped.set())
        recognizer.start_continuous_recognition()
        await websocket.send_json({"type": "ready", "voice": settings.voice_name})

        async def receive_audio() -> None:
            deadline = loop.time() + MAX_SESSION_SECONDS
            while loop.time() < deadline:
                message = await websocket.receive()
                if message.get("bytes"):
                    push_stream.write(message["bytes"])
                elif message.get("text") == "stop":
                    break
            push_stream.close()

        receiver = asyncio.create_task(receive_audio())
        while not receiver.done():
            try:
                payload = await asyncio.wait_for(event_queue.get(), timeout=0.2)
                await websocket.send_json(payload)
            except asyncio.TimeoutError:
                if stopped.is_set():
                    receiver.cancel()
                    break
        try:
            await receiver
        except asyncio.CancelledError:
            pass
        if not stopped.is_set():
            await asyncio.to_thread(stopped.wait, 8)
        recognizer.stop_continuous_recognition()
        await asyncio.sleep(0.2)
        while not event_queue.empty():
            await websocket.send_json(event_queue.get_nowait())
        if audio_chunks:
            audio = base64.b64encode(pcm_to_wav(audio_chunks)).decode("ascii")
            await websocket.send_json({"type": "audio", "data": audio})
        await websocket.send_json({"type": "stopped"})
    except WebSocketDisconnect:
        pass
    except (ConfigurationError, RuntimeError, ValueError, asyncio.TimeoutError) as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except RuntimeError:
            pass
    finally:
        if push_stream is not None:
            try:
                push_stream.close()
            except RuntimeError:
                pass
        if recognizer is not None:
            try:
                recognizer.stop_continuous_recognition()
            except RuntimeError:
                pass
        try:
            await websocket.close()
        except RuntimeError:
            pass


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_ROOT / "index.html", media_type="text/html")


@app.get("/static/{file_path:path}", include_in_schema=False)
async def static(file_path: str):
    candidate = (STATIC_ROOT / file_path).resolve()
    if STATIC_ROOT.resolve() not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(candidate)
