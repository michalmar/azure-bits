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


SESSION_COOKIE = "__Host-speech-interpreter-session"
STATE_COOKIE = "__Host-speech-interpreter-login"


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/"
    return urlunsplit(("", "", parsed.path or "/", parsed.query, ""))


@dataclass(frozen=True, slots=True)
class AuthConfig:
    enabled: bool
    public_base_url: str
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    session_secret: str = ""
    allowed_users: tuple[str, ...] = ()

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/oauth/entra/callback"


def load_auth_config() -> AuthConfig:
    enabled = _bool(os.getenv("AUTH_ENABLED"))
    base_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").strip()
    if not enabled:
        return AuthConfig(enabled=False, public_base_url=base_url)
    values = {
        name: os.getenv(name, "").strip()
        for name in (
            "ENTRA_TENANT_ID",
            "ENTRA_CLIENT_ID",
            "ENTRA_CLIENT_SECRET",
            "SESSION_SECRET",
            "ALLOWED_USERS",
        )
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError("Missing authentication configuration: " + ", ".join(missing))
    return AuthConfig(
        enabled=True,
        public_base_url=base_url,
        tenant_id=values["ENTRA_TENANT_ID"],
        client_id=values["ENTRA_CLIENT_ID"],
        client_secret=values["ENTRA_CLIENT_SECRET"],
        session_secret=values["SESSION_SECRET"],
        allowed_users=tuple(item.strip().lower() for item in values["ALLOWED_USERS"].split(",") if item.strip()),
    )


class AuthManager:
    def __init__(self, config: AuthConfig, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=20)
        self._owns_client = client is None
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._serializer = URLSafeTimedSerializer(config.session_secret or "disabled")

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def discovery(self) -> dict[str, Any]:
        if self._discovery is None:
            response = await self.client.get(f"{self.config.authority}/.well-known/openid-configuration")
            response.raise_for_status()
            self._discovery = response.json()
        return self._discovery

    async def jwks(self) -> dict[str, Any]:
        if self._jwks is None:
            response = await self.client.get((await self.discovery())["jwks_uri"])
            response.raise_for_status()
            self._jwks = response.json()
        return self._jwks

    async def begin_login(self, return_to: str | None) -> tuple[str, str]:
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        cookie = self._serializer.dumps(
            {"kind": "state", "state": state, "nonce": nonce, "return_to": safe_return_to(return_to)}
        )
        query = urlencode(
            {
                "client_id": self.config.client_id,
                "response_type": "code",
                "redirect_uri": self.config.callback_url,
                "response_mode": "query",
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{(await self.discovery())['authorization_endpoint']}?{query}", cookie

    async def exchange(self, code: str, state_query: str, state_cookie: str) -> tuple[dict[str, Any], str]:
        try:
            state = self._serializer.loads(state_cookie, max_age=600)
        except BadData as exc:
            raise RuntimeError("Login state is invalid or expired.") from exc
        if state.get("kind") != "state" or state.get("state") != state_query:
            raise RuntimeError("Login state did not match.")
        response = await self.client.post(
            (await self.discovery())["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "code": code,
                "redirect_uri": self.config.callback_url,
                "scope": "openid profile email",
            },
        )
        response.raise_for_status()
        token = response.json()["id_token"]
        header = jwt.get_unverified_header(token)
        key = next(item for item in (await self.jwks())["keys"] if item.get("kid") == header.get("kid"))
        claims = jwt.decode(
            token,
            jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
            algorithms=["RS256"],
            audience=self.config.client_id,
            issuer=(await self.discovery())["issuer"],
            options={"require": ["exp", "iat", "nonce", "aud", "iss", "sub", "tid"]},
        )
        if claims.get("nonce") != state["nonce"] or claims.get("tid") != self.config.tenant_id:
            raise RuntimeError("Identity token did not match this login.")
        candidates = {
            "tenant:*",
            f"entra:{claims.get('oid', '')}".lower(),
            f"email:{claims.get('preferred_username', '')}".lower(),
        }
        if not candidates.intersection(self.config.allowed_users):
            raise PermissionError("This identity is not in ALLOWED_USERS.")
        session = self._serializer.dumps({"kind": "session", "claims": claims})
        return claims, session

    def session(self, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        try:
            data = self._serializer.loads(value, max_age=60 * 60 * 8)
        except BadData:
            return None
        return data.get("claims") if data.get("kind") == "session" else None
