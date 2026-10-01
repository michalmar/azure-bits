from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import time
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

from .auth import (
    OIDCAuthManager,
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    load_auth_config_from_env,
    sanitize_return_to,
)
from .config import MAX_OUTPUT_TOKENS, MAX_PROMPT_LENGTH, Settings
from .service import FlexBenchmarkService


STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
logger = logging.getLogger(__name__)


class CompareRequest(BaseModel):
    prompt: str = Field(max_length=MAX_PROMPT_LENGTH)
    max_output_tokens: int = Field(default=800, ge=1, le=MAX_OUTPUT_TOKENS)

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Prompt must not be empty.")
        return value


def create_app(
    settings: Settings | None = None,
    service: FlexBenchmarkService | None = None,
    auth_manager: OIDCAuthManager | None = None,
    bootstrap_locked: bool | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
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
        app.state.settings = resolved_settings
        app.state.service = service or FlexBenchmarkService(resolved_settings)
        app.state.auth = None if locked else (auth_manager or OIDCAuthManager(auth_config))
        try:
            yield
        finally:
            if service is None:
                await app.state.service.close()
            if auth_manager is None and app.state.auth is not None:
                await app.state.auth.close()

    app = FastAPI(
        title="Foundry Flex processing comparison",
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
        benchmark: FlexBenchmarkService = request.app.state.service
        pricing = await benchmark.pricing.get()
        return {
            "model": resolved_settings.deployment,
            "defaultMaxOutputTokens": resolved_settings.default_max_output_tokens,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "maxPromptLength": MAX_PROMPT_LENGTH,
            "pricing": pricing,
            "user": (
                getattr(request.state, "identity", {}).get("name")
                if getattr(request.state, "identity", None)
                else None
            ),
        }

    @app.post("/api/compare")
    async def compare(payload: CompareRequest, request: Request) -> dict[str, object]:
        benchmark: FlexBenchmarkService = request.app.state.service
        pricing = await benchmark.pricing.get()
        started = time.perf_counter()
        standard, flex = await asyncio.gather(
            benchmark.safe_run_tier(payload.prompt, "default", payload.max_output_tokens, pricing),
            benchmark.safe_run_tier(payload.prompt, "flex", payload.max_output_tokens, pricing),
        )
        return {
            "model": resolved_settings.deployment,
            "parallel": True,
            "wallClockMs": round((time.perf_counter() - started) * 1000, 1),
            "pricing": pricing,
            "results": {"standard": standard, "flex": flex},
        }

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
