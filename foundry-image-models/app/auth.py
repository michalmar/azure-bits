from __future__ import annotations

from dataclasses import dataclass
import json
import os
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
import jwt
from itsdangerous import BadData, URLSafeTimedSerializer
from jwt import PyJWTError


AUTH_SCOPES = "openid profile email"
SESSION_COOKIE_NAME = "__Host-foundry-session"
STATE_COOKIE_NAME = "__Host-foundry-login"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 8
STATE_MAX_AGE_SECONDS = 60 * 10


@dataclass(frozen=True, slots=True)
class AuthConfig:
    enabled: bool
    public_base_url: str
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    session_secret: str | None = None

    @property
    def authority(self) -> str:
        if not self.tenant_id:
            raise RuntimeError("tenant id is missing")
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def discovery_url(self) -> str:
        return f"{self.authority}/.well-known/openid-configuration"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/oauth/entra/callback"


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def sanitize_return_to(value: str | None) -> str:
    if not value:
        return "/"
    candidate = value.strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))


def load_auth_config_from_env() -> AuthConfig:
    enabled = parse_bool(os.getenv("AUTH_ENABLED"), default=False)
    public_base_url = (os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").strip()

    if not enabled:
        return AuthConfig(enabled=False, public_base_url=public_base_url)

    required = {
        "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL"),
        "ENTRA_TENANT_ID": os.getenv("ENTRA_TENANT_ID"),
        "ENTRA_CLIENT_ID": os.getenv("ENTRA_CLIENT_ID"),
        "ENTRA_CLIENT_SECRET": os.getenv("ENTRA_CLIENT_SECRET"),
        "SESSION_SECRET": os.getenv("SESSION_SECRET"),
    }
    missing = [name for name, value in required.items() if not (value or "").strip()]
    if missing:
        raise RuntimeError(
            "AUTH_ENABLED is true but required auth configuration is missing: " + ", ".join(missing)
        )

    return AuthConfig(
        enabled=True,
        public_base_url=required["PUBLIC_BASE_URL"].strip(),
        tenant_id=required["ENTRA_TENANT_ID"].strip(),
        client_id=required["ENTRA_CLIENT_ID"].strip(),
        client_secret=required["ENTRA_CLIENT_SECRET"].strip(),
        session_secret=required["SESSION_SECRET"].strip(),
    )


class OIDCAuthManager:
    def __init__(self, config: AuthConfig, http_client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._owns_client = http_client is None
        self._discovery_cache: dict[str, Any] | None = None
        self._jwks_cache: dict[str, Any] | None = None
        self._session_serializer = URLSafeTimedSerializer(
            config.session_secret or "",
            salt="foundry-image-models.session",
        )
        self._state_serializer = URLSafeTimedSerializer(
            config.session_secret or "",
            salt="foundry-image-models.state",
        )

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def close(self) -> None:
        if self._owns_client:
            await self.http.aclose()

    def _sign_session(self, payload: dict[str, Any]) -> str:
        return self._session_serializer.dumps(payload)

    def _unsign_session(self, value: str) -> dict[str, Any] | None:
        try:
            data = self._session_serializer.loads(value, max_age=SESSION_MAX_AGE_SECONDS)
        except BadData:
            return None
        return data if isinstance(data, dict) else None

    def _sign_state(self, payload: dict[str, Any]) -> str:
        return self._state_serializer.dumps(payload)

    def _unsign_state(self, value: str) -> dict[str, Any] | None:
        try:
            data = self._state_serializer.loads(value, max_age=STATE_MAX_AGE_SECONDS)
        except BadData:
            return None
        return data if isinstance(data, dict) else None

    async def _discovery(self) -> dict[str, Any]:
        if self._discovery_cache is not None:
            return self._discovery_cache
        response = await self.http.get(self.config.discovery_url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("openid configuration was not an object")
        self._discovery_cache = payload
        return payload

    async def _jwks(self, *, refresh: bool = False) -> dict[str, Any]:
        if self._jwks_cache is not None and not refresh:
            return self._jwks_cache
        discovery = await self._discovery()
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise RuntimeError("openid configuration missing jwks_uri")
        response = await self.http.get(jwks_uri)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise RuntimeError("jwks payload was not valid")
        self._jwks_cache = payload
        return payload

    async def _validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        discovery = await self._discovery()
        expected_issuer = discovery.get("issuer")
        if not isinstance(expected_issuer, str) or not expected_issuer:
            raise RuntimeError("openid configuration missing issuer")

        header = jwt.get_unverified_header(id_token)
        if header.get("alg") != "RS256":
            raise RuntimeError("unsupported id token algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise RuntimeError("id token missing kid")

        key = None
        for refresh in (False, True):
            jwks = await self._jwks(refresh=refresh)
            key = next(
                (
                    candidate
                    for candidate in jwks["keys"]
                    if isinstance(candidate, dict) and candidate.get("kid") == kid
                ),
                None,
            )
            if isinstance(key, dict):
                break
        if not isinstance(key, dict):
            raise RuntimeError("matching jwk not found")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        try:
            claims = jwt.decode(
                id_token,
                key=public_key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=expected_issuer,
                options={
                    "require": ["exp", "iat", "nonce", "aud", "iss", "sub", "tid"],
                },
            )
        except PyJWTError as exc:
            raise RuntimeError(f"id token validation failed: {exc}") from exc

        if claims.get("tid") != self.config.tenant_id:
            raise RuntimeError("tenant id claim did not match configuration")
        if claims.get("nonce") != nonce:
            raise RuntimeError("nonce claim did not match state")
        return claims

    async def begin_login(self, return_to: str | None = None) -> tuple[str, str]:
        discovery = await self._discovery()
        auth_url = discovery.get("authorization_endpoint")
        if not isinstance(auth_url, str) or not auth_url:
            raise RuntimeError("openid configuration missing authorization_endpoint")

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        state_cookie = self._sign_state(
            {
                "state": state,
                "nonce": nonce,
                "return_to": sanitize_return_to(return_to),
            }
        )
        query = urlencode(
            {
                "client_id": self.config.client_id or "",
                "response_type": "code",
                "redirect_uri": self.config.callback_url,
                "response_mode": "query",
                "scope": AUTH_SCOPES,
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{auth_url}?{query}", state_cookie

    async def exchange_code(self, code: str, state_cookie: str, state_query: str) -> dict[str, Any]:
        state_payload = self._unsign_state(state_cookie)
        if not state_payload:
            raise RuntimeError("state cookie is invalid or expired")
        if state_payload.get("state") != state_query:
            raise RuntimeError("state parameter did not match cookie")

        discovery = await self._discovery()
        token_url = discovery.get("token_endpoint")
        if not isinstance(token_url, str) or not token_url:
            raise RuntimeError("openid configuration missing token_endpoint")

        response = await self.http.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.config.client_id or "",
                "client_secret": self.config.client_secret or "",
                "code": code,
                "redirect_uri": self.config.callback_url,
                "scope": AUTH_SCOPES,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("token endpoint returned invalid payload")
        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise RuntimeError("token endpoint did not return id_token")

        claims = await self._validate_id_token(id_token, state_payload["nonce"])
        return {
            "session": {
                "sub": claims.get("sub"),
                "tid": claims.get("tid"),
                "oid": claims.get("oid"),
                "name": claims.get("name"),
                "preferred_username": claims.get("preferred_username"),
                "upn": claims.get("upn"),
                "iat": claims.get("iat"),
                "exp": claims.get("exp"),
            },
            "return_to": sanitize_return_to(state_payload.get("return_to")),
        }

    def load_session(self, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        return self._unsign_session(value)

    def create_session_cookie(self, payload: dict[str, Any]) -> str:
        return self._sign_session(payload)

    def create_state_cookie(self, payload: str) -> str:
        return payload
