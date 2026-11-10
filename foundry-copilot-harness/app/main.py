from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import secrets
import time

from azure.core.exceptions import AzureError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from itsdangerous import BadData, URLSafeTimedSerializer
from openai import APIError

from auth import reader_authorized
from config import Settings, boolean
from prefix_store import PrefixBlobStore
from publisher import create_app as publisher_app
from scenario import OFFERS, PROMPT, REFERENCE
from service import HarnessService

logger = logging.getLogger("workshop")
STATIC = Path(__file__).resolve().parent.parent / "static"
RUN_TIMEOUT_SECONDS = 300


def event_line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def create_app(*, settings: Settings | None = None, service=None, storage_factory=PrefixBlobStore) -> FastAPI:
    production = os.getenv("APP_ENV") == "production"
    local = boolean(os.environ, "LOCAL_DEV")
    live = boolean(os.environ, "LIVE_DEMO_ENABLED")
    if production and local:
        raise ValueError("Production cannot enable LOCAL_DEV")

    if not live:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.get("/healthz")
        def health():
            return {"status": "ok"}

        @app.api_route("/_publish/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
        def publishing_disabled(path: str):
            raise HTTPException(404)

        if not local:
            @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "DELETE"])
            def locked(path: str):
                return JSONResponse({"detail": "Demo is locked pending configuration."}, 503)
            return app

        @app.get("/api/config")
        def config():
            return {"live": False, "prompt": PROMPT, "offers_csv": OFFERS.decode(), "reference": REFERENCE}

        @app.get("/{path:path}")
        def static(path: str):
            if path not in {"", "index.html", "app.mjs", "style.css", "tokens.css", "baseline.css"}:
                raise HTTPException(404)
            return FileResponse(STATIC / (path or "index.html"))
        return app

    if local:
        raise ValueError("Live Foundry calls require managed identity on Azure, not LOCAL_DEV")
    settings = settings or Settings.from_env()
    if settings.provider != "entra" or not settings.allowed_users:
        raise ValueError("Live demo requires Entra and a nonempty explicit allowlist")
    app = publisher_app(settings, storage_factory)
    site_route = app.router.routes.pop()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            runner = service or HarnessService(
                os.environ["FOUNDRY_PROJECT_URL"], settings.azure_client_id,
                os.environ.get("FOUNDRY_AGENT_NAME", "workshop-planner-demo"),
                os.environ["FOUNDRY_AGENT_VERSION"],
            )
            application.state.runner = runner
            try:
                yield
            finally:
                if service is None:
                    await runner.close()

    app.router.lifespan_context = lifespan
    signer = URLSafeTimedSerializer(settings.session_secret, salt="workshop-file-v1")
    busy = False
    next_run = 0.0

    def authorize(request):
        if not reader_authorized(request, settings):
            raise HTTPException(401, "Authentication required")
        return request.session["identity"]["id"]

    def same_origin(request):
        if request.headers.get("origin") != settings.public_base_url:
            raise HTTPException(403, "Same-origin request required")
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(415, "Use application/json")

    @app.get("/api/config")
    async def config(request: Request):
        authorize(request)
        csrf = request.session.setdefault("csrf", secrets.token_urlsafe(32))
        return {"live": True, "prompt": PROMPT, "offers_csv": OFFERS.decode(), "csrf": csrf}

    @app.post("/api/run")
    async def run(request: Request):
        nonlocal busy, next_run
        owner = authorize(request)
        same_origin(request)
        expected = request.session.get("csrf", "")
        if not expected or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), expected):
            raise HTTPException(403, "Invalid CSRF token")
        # The endpoint accepts no user prompt or other variable workload input.
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2:
                raise HTTPException(400, "Only the fixed demo prompt is supported")
            body.extend(chunk)
        if bytes(body) not in {b"", b"{}"}:
            raise HTTPException(400, "Only the fixed demo prompt is supported")
        if busy:
            raise HTTPException(409, "A workshop run is already active")
        if time.monotonic() < next_run:
            raise HTTPException(429, "Wait before starting another run", headers={"Retry-After": "30"})
        busy = True
        next_run = time.monotonic() + 30

        async def events():
            nonlocal busy
            try:
                async with asyncio.timeout(RUN_TIMEOUT_SECONDS):
                    async for event in request.app.state.runner.run():
                        if event["type"] == "result":
                            for file in event["files"]:
                                token = signer.dumps({"owner": owner, **file})
                                file["url"] = "/api/files/" + token
                        yield event_line(event)
            except TimeoutError:
                logger.warning("workshop_timeout cleanup_requested=true")
                yield event_line({
                    "type": "error",
                    "message": "Vypršel limit 5 minut. Byl vyžádán úklid conversation; vzdálené zastavení není zaručeno.",
                })
            except (APIError, AzureError, ValueError, KeyError) as exc:
                logger.warning("workshop_failed type=%s status=%s", type(exc).__name__, getattr(exc, "status_code", None))
                yield event_line({
                    "type": "error",
                    "message": "Běh selhal. Zkontrolujte oprávnění, konfiguraci a Foundry trace. Automatický retry neproběhl.",
                })
            finally:
                busy = False
        return StreamingResponse(
            events(), media_type="application/x-ndjson",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    @app.get("/api/files/{token}")
    async def download(request: Request, token: str):
        owner = authorize(request)
        if len(token) > 2048:
            raise HTTPException(400, "Invalid file link")
        try:
            file = signer.loads(token, max_age=3600)
            if file["owner"] != owner:
                raise HTTPException(403, "This report belongs to another reader")
            content = await request.app.state.runner.read_file(file["file_id"])
        except BadData as exc:
            raise HTTPException(410, "File link expired or invalid") from exc
        except (APIError, AzureError, TimeoutError, ValueError) as exc:
            logger.warning("file_download_failed type=%s", type(exc).__name__)
            raise HTTPException(502, "Foundry report unavailable") from exc
        return Response(
            content, media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{file["filename"]}"'},
        )

    app.router.routes.append(site_route)
    return app
