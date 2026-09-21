from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse

from .config import ALLOWED_MODELS
from .auth import (
    SESSION_COOKIE_NAME,
    STATE_COOKIE_NAME,
    OIDCAuthManager,
    load_auth_config_from_env,
    sanitize_return_to,
)
from .service import CapabilityLookupError, FoundryService, ImageResult
from .upload import parse_generate_upload


def get_service(request: Request) -> FoundryService:
    return request.app.state.service


def get_auth_manager(request: Request) -> OIDCAuthManager:
    return request.app.state.auth


def _is_inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False


def _httpx_http_exception(exc: httpx.HTTPStatusError, prefix: str) -> HTTPException:
    response = exc.response
    headers = {}
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if response is not None and response.status_code == 429:
        if retry_after:
            headers["Retry-After"] = retry_after
        return HTTPException(status_code=429, detail="upstream rate limited", headers=headers or None)
    return HTTPException(status_code=502, detail=f"{prefix}: {exc}")


def create_app(service: FoundryService | None = None, auth_manager: OIDCAuthManager | None = None) -> FastAPI:
    auth_config = None if auth_manager is not None else load_auth_config_from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        managed_service = service or FoundryService()
        managed_auth = auth_manager if auth_manager is not None else OIDCAuthManager(auth_config)
        app.state.service = managed_service
        app.state.auth = managed_auth
        try:
            yield
        finally:
            await managed_service.close()
            await managed_auth.close()

    app = FastAPI(title="Foundry image models demo", lifespan=lifespan)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        auth = request.app.state.auth
        if not auth.enabled:
            return await call_next(request)

        path = request.url.path
        if path in {"/healthz", "/login", "/logout", "/oauth/entra/callback"}:
            return await call_next(request)

        session = auth.load_session(request.cookies.get(SESSION_COOKIE_NAME))
        if session is not None:
            request.state.identity = session
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "authentication required"}, status_code=401)

        target = sanitize_return_to(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(url=f"/login?return_to={quote(target, safe='')}", status_code=307)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/login", include_in_schema=False)
    async def login(
        request: Request,
        return_to: str | None = None,
        auth: OIDCAuthManager = Depends(get_auth_manager),
    ):
        if not auth.enabled:
            return RedirectResponse(url=sanitize_return_to(return_to))
        if auth.load_session(request.cookies.get(SESSION_COOKIE_NAME)) is not None:
            return RedirectResponse(url=sanitize_return_to(return_to))
        try:
            auth_url, state_cookie = await auth.begin_login(return_to=return_to)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"login unavailable: {exc}") from exc
        response = RedirectResponse(url=auth_url, status_code=302)
        response.set_cookie(
            key=STATE_COOKIE_NAME,
            value=state_cookie,
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=600,
        )
        return response

    @app.get("/oauth/entra/callback", include_in_schema=False)
    async def entra_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        auth: OIDCAuthManager = Depends(get_auth_manager),
    ):
        if not auth.enabled:
            return RedirectResponse(url="/")
        if not code or not state:
            raise HTTPException(status_code=400, detail="missing authorization code or state")

        state_cookie = request.cookies.get(STATE_COOKIE_NAME)
        if not state_cookie:
            raise HTTPException(status_code=400, detail="missing login state")

        try:
            session_data = await auth.exchange_code(code=code, state_cookie=state_cookie, state_query=state)
        except httpx.HTTPStatusError as exc:
            raise _httpx_http_exception(exc, "token exchange failed") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"token exchange request failed: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"authentication failed: {exc}") from exc

        response = RedirectResponse(url=session_data["return_to"], status_code=302)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=auth.create_session_cookie(session_data["session"]),
            secure=True,
            httponly=True,
            samesite="lax",
            path="/",
            max_age=60 * 60 * 8,
        )
        response.delete_cookie(key=STATE_COOKIE_NAME, path="/")
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout(auth: OIDCAuthManager = Depends(get_auth_manager)):
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(key=STATE_COOKIE_NAME, path="/")
        return response

    @app.get("/api/models")
    async def api_models(service: FoundryService = Depends(get_service)) -> dict[str, object]:
        capabilities = await service.model_capabilities()
        return service.list_models_payload(capabilities)

    @app.get("/api/session")
    async def api_session(request: Request, auth: OIDCAuthManager = Depends(get_auth_manager)) -> dict[str, object]:
        if not auth.enabled:
            return {"authenticated": False, "user": None}
        identity = getattr(request.state, "identity", None)
        if not identity:
            return {"authenticated": False, "user": None}
        return {
            "authenticated": True,
            "user": {
                "name": identity.get("name", ""),
                "username": identity.get("preferred_username") or identity.get("upn") or "",
            },
        }

    @app.get("/api/gallery")
    async def api_gallery(service: FoundryService = Depends(get_service)) -> dict[str, object]:
        return service.read_gallery_manifest()

    @app.post("/api/generate")
    async def api_generate(request: Request, service: FoundryService = Depends(get_service)) -> dict[str, object]:
        payload = await parse_generate_upload(request)
        if payload.model not in ALLOWED_MODELS:
            raise HTTPException(status_code=400, detail="unsupported model")

        try:
            result: ImageResult = await service.generate_image(
                model=payload.model,
                prompt=payload.prompt,
                image=payload.image,
                image_filename=payload.image_filename,
                image_content_type=payload.image_content_type,
            )
        except CapabilityLookupError as exc:
            raise HTTPException(status_code=503, detail=f"capability lookup failed: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise _httpx_http_exception(exc, "generation request failed") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"generation request error: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return result.as_dict()

    static_root = Path("static")

    @app.get("/", include_in_schema=False)
    async def root() -> object:
        index = static_root / "index.html"
        if index.exists():
            return FileResponse(index, media_type="text/html")
        return PlainTextResponse("Static frontend is not present yet.", status_code=404)

    @app.get("/static/{file_path:path}", include_in_schema=False)
    async def static_files(file_path: str) -> object:
        path = (static_root / file_path).resolve()
        if not _is_inside(static_root, path) or not path.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path)

    return app


app = create_app()
