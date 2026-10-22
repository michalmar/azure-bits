from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

from .audit import AuditTrail
from .auth import (
    OIDCAuthManager,
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    load_auth_config_from_env,
    sanitize_return_to,
)
from .config import MAX_BURST_REQUESTS, MAX_INPUT_CHARS, Settings
from .prompts import PROMPT_PROFILES
from .samples import SAMPLES
from .service import SummarizerService


STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class SummarizeRequest(BaseModel):
    text: str = Field(max_length=MAX_INPUT_CHARS)
    path: Literal["direct", "gateway"] = "gateway"

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must not be empty.")
        return value


class BurstRequest(BaseModel):
    count: int = Field(default=10, ge=2, le=MAX_BURST_REQUESTS)


def create_app(
    settings: Settings | None = None,
    service: SummarizerService | None = None,
    auth_manager: OIDCAuthManager | None = None,
    bootstrap_locked: bool | None = None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    locked = (
        os.getenv("BOOTSTRAP_LOCKED", "false").lower() == "true"
        if bootstrap_locked is None
        else bootstrap_locked
    )
    auth_config = None if locked or auth_manager is not None else load_auth_config_from_env()
    if os.getenv("APP_ENV", "development").lower() == "production" and not locked:
        if auth_manager is None and not auth_config.enabled:
            raise RuntimeError("Production requires AUTH_ENABLED=true.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or SummarizerService(resolved, AuditTrail(resolved.audit_log_path))
        app.state.auth = None if locked else (auth_manager or OIDCAuthManager(auth_config))
        try:
            yield
        finally:
            if service is None:
                await app.state.service.close()
            if auth_manager is None and app.state.auth is not None:
                await app.state.auth.close()

    app = FastAPI(
        title="AI Gateway governance demo",
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

    def svc(request: Request) -> SummarizerService:
        return request.app.state.service

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
            STATE_COOKIE_NAME,
            state_cookie,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=600,
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
            SESSION_COOKIE_NAME,
            auth.create_session_cookie(result["session"]),
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=60 * 60 * 8,
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
        def profile(p):
            return {
                "modelId": p.model_id,
                "maxOutputTokens": p.max_output_tokens,
                "promptProfile": PROMPT_PROFILES[p.tier]["name"],
                "systemPrompt": PROMPT_PROFILES[p.tier]["system"],
                "pricePer1M": {"input": p.price.input, "cachedInput": p.price.cached_input, "output": p.price.output},
                "temperature": p.temperature,
                "reasoningEffort": p.reasoning_effort,
            }

        return {
            "direct": {"endpoint": resolved.foundry_endpoint, "deployment": resolved.direct_large_deployment},
            "gateway": {
                "endpoint": resolved.gateway_endpoint or None,
                "configured": resolved.gateway_configured,
                "burstConfigured": resolved.burst_key_configured,
                "primaryModel": resolved.gateway_primary_model,
                "fallbackModel": resolved.gateway_fallback_model,
                "appKeyName": resolved.gateway_app_key_name,
                "burstKeyName": resolved.gateway_burst_key_name,
                "burstModel": resolved.burst_model,
                "fallbackOn": sorted(resolved.fallback_on),
            },
            "large": profile(resolved.large),
            "small": profile(resolved.small),
            "samples": SAMPLES,
            "maxBurst": MAX_BURST_REQUESTS,
            "user": (
                getattr(request.state, "identity", {}).get("name")
                if getattr(request.state, "identity", None)
                else None
            ),
        }

    @app.post("/api/summarize")
    async def summarize(payload: SummarizeRequest, request: Request):
        result = await svc(request).summarize(payload.text, payload.path)
        if result["status"] == "ok":
            return result
        status = result["error"]["httpStatus"] or 503
        return JSONResponse(result, status_code=status if 400 <= status < 600 else 502)

    @app.post("/api/burst")
    async def burst(payload: BurstRequest, request: Request):
        result = await svc(request).burst(payload.count)
        return JSONResponse(result, status_code=503 if result.get("error") else 200)

    @app.get("/api/audit")
    async def audit(request: Request, limit: int = 100) -> dict[str, object]:
        return {"events": svc(request).audit.list(max(1, min(limit, 300)))}

    @app.get("/api/audit/{event_id}")
    async def audit_event(event_id: str, request: Request):
        event = svc(request).audit.get(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Audit event not found.")
        return event

    @app.delete("/api/audit")
    async def clear_audit(request: Request) -> dict[str, str]:
        svc(request).audit.clear()
        return {"status": "cleared"}

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
