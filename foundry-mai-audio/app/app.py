"""Extend the canonical private Blob publisher with a small audio playground."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import uuid

from azure.core.exceptions import AzureError, ResourceNotFoundError
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect

from audio import AudioService, AudioSettings, MODELS, SynthesisInput, VOICES, logger
from auth import reader_authorized
from config import Settings
from publisher import create_app as create_publisher
from probe import StreamingProbe
from storage import AzureBlobStore, BlobInfo, storage_error, upload


class LocalStore:
    """Read-only local static mode. No Azure identity fallback."""

    def __init__(self, settings):
        self.root = Path(__file__).resolve().parents[1] / "static"

    def file(self, path):
        value = (self.root / path).resolve()
        if not value.is_relative_to(self.root) or not value.is_file():
            raise ResourceNotFoundError("Local asset not found", status_code=404)
        return value

    async def stat(self, path):
        data = self.file(path).read_bytes()
        return BlobInfo(path, len(data), mimetypes.guess_type(path)[0] or "application/octet-stream",
                        '"' + hashlib.sha256(data).hexdigest() + '"')

    async def download(self, path, offset, length, etag):
        async def chunks():
            yield self.file(path).read_bytes()[offset:offset + length]
        return chunks()

    async def close(self):
        pass


def create_app(settings=None, storage_factory=None, audio_factory=AudioService):
    settings = settings or Settings.from_env()
    if settings.provider == "none" and not settings.local_dev:
        # Empty bootstrap has no reader content and cannot make paid calls.
        audio_settings = AudioSettings.from_env()
        if audio_settings.live_enabled:
            raise ValueError("Live audio cannot be enabled in an anonymous bootstrap")
    application = create_publisher(settings, storage_factory or (LocalStore if settings.local_dev else AzureBlobStore))
    original_lifespan = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original_lifespan(app):
            app.state.audio = audio_factory(AudioSettings.from_env())
            try:
                yield
            finally:
                await app.state.audio.close()

    application.router.lifespan_context = lifespan
    router = APIRouter()

    def authorize(request, mutate=False):
        if not reader_authorized(request, settings):
            raise HTTPException(401, "Reader sign-in required")
        if mutate and request.headers.get("origin") != settings.public_base_url:
            raise HTTPException(403, "Same-origin request required")
        return request.session.get("identity", {}).get("id", "local")

    @router.get("/api/config")
    async def config(request: Request):
        authorize(request)
        return {"live_enabled": request.app.state.audio.settings.live_enabled, "models": MODELS,
                "voices": [{"id": key, "language": val[0], "styles": val[1]} for key, val in VOICES.items()],
                "max_characters": 600, "max_seconds": 60, "authenticated": settings.provider != "none"}

    @router.post("/api/synthesize")
    async def synthesize(request: Request):
        identity = authorize(request, True)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                raise HTTPException(413, "Speech request exceeds 8 KiB")
        try:
            value = SynthesisInput.model_validate_json(body)
        except ValueError:
            raise HTTPException(422, "Choose a supported model, voice and style; enter 1-600 characters of text.") from None
        async with request.app.state.audio.slot(identity):
            audio, elapsed = await request.app.state.audio.synthesize(value)
        return Response(audio, media_type="audio/mpeg", headers={
            "X-Generation-Ms": str(elapsed), "X-Characters": str(len(value.text)),
            "Content-Disposition": f'inline; filename="{value.model}.mp3"',
        })

    @router.websocket("/api/transcribe")
    async def transcribe(browser: WebSocket):
        if not reader_authorized(browser, settings) or browser.headers.get("origin") != settings.public_base_url:
            await browser.close(code=1008)
            return
        await browser.accept()
        try:
            identity = browser.session.get("identity", {}).get("id", "local")
            async with browser.app.state.audio.slot(identity):
                await browser.app.state.audio.transcribe(browser)
        except WebSocketDisconnect:
            logger.info("transcription_closed reason=browser_disconnect")
            return
        except HTTPException as exc:
            await browser.send_json({"type": "error", "message": exc.detail})
        await browser.close()

    @router.post("/_publish/generate-samples")
    async def generate_samples(request: Request):
        # RequestBoundary enforces the temporary publishing digest before this route.
        service = request.app.state.audio
        if not service.settings.live_enabled:
            raise HTTPException(503, "Enable managed-identity audio before generating samples")
        recipes = [
            ("compare", "Same text, same voice", "en-US-Harper", "neutral",
             "Your table is ready. I have moved your reservation to seven thirty, and sent the confirmation. Is there anything else I can help you with?"),
            ("expression", "A warmer welcome", "en-US-Harper", "happy",
             "You did it! That was a wonderful first lesson. Let's try the next one together."),
            ("czech", "Harper in Czech", "cs-CZ-Harper", "educational",
             "Vítejte. Dnes si ukážeme, jak mohou nové hlasové modely pomáhat při učení a v každodenních rozhovorech."),
            ("german", "Harper in German", "de-DE-Harper", "educational",
             "Willkommen. Heute zeigen wir, wie neue Sprachmodelle beim Lernen und in alltäglichen Gesprächen helfen können."),
        ]
        generation = uuid.uuid4().hex[:12]
        manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "samples": []}

        async def save(path, data, mime):
            async def chunks():
                yield data
            await upload(request.app.state.store, path, chunks(), mime, 8 * 1024 * 1024, len(data), {})

        try:
            for key, title, voice, style, text in recipes:
                for model in MODELS:
                    value = SynthesisInput(model=model, voice=voice, style=style, text=text)
                    async with service.slot("publisher"):
                        data, elapsed = await service.synthesize(value)
                    path = f"media/{generation}-{key}-{model}.mp3"
                    await save(path, data, "audio/mpeg")
                    manifest["samples"].append({"scenario": key, "title": title, "model": model,
                                                "voice": voice, "style": style, "text": text,
                                                "path": path, "generation_ms": elapsed,
                                                "sha256": hashlib.sha256(data).hexdigest()})
            await save("samples.json", json.dumps(manifest, ensure_ascii=False).encode(), "application/json")
        except AzureError as exc:
            raise storage_error(exc, "generate_samples") from None
        return {"samples": len(manifest["samples"]), "generated_at": manifest["generated_at"]}

    @router.post("/_publish/verify-streaming")
    async def verify_streaming(request: Request):
        service = request.app.state.audio
        value = SynthesisInput(
            model=MODELS[1],
            text="This is a short audio model demonstration. Streaming captions arrive as I speak, and stopping produces a final transcript.",
        )
        async with service.slot("publisher"):
            pcm, _ = await service.synthesize(value, output_format="raw-16khz-16bit-mono-pcm")
        probe = StreamingProbe(pcm)
        async with service.slot("publisher"):
            await service.transcribe(probe)
        return probe.result()

    # Keep APIs ahead of the publisher's catch-all reader route.
    application.router.routes[0:0] = router.routes
    return application
