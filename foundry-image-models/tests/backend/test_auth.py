from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import AuthConfig, OIDCAuthManager
from app.main import create_app
from tests.backend.helpers import make_service


@pytest.fixture()
def oidc_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = "test-kid"
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, jwk


def build_auth_bundle(oidc_keys, *, token_tid: str | None = None, nonce_mode: str = "match"):
    private_key, jwk = oidc_keys
    tenant_id = "22222222-2222-2222-2222-222222222222"
    client_id = "11111111-1111-1111-1111-111111111111"
    base_url = "https://testserver"
    discovery_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    login_state: dict[str, str] = {}

    def auth_responder(request: httpx.Request) -> httpx.Response:
        if str(request.url) == discovery_url:
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize",
                    "token_endpoint": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                    "jwks_uri": f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
                },
            )
        if str(request.url) == f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys":
            return httpx.Response(200, json={"keys": [jwk]})
        if str(request.url) == f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token":
            form = dict(parse_qs(request.content.decode("utf-8")))
            assert form["client_id"][0] == client_id
            assert form["client_secret"][0] == "super-secret"
            nonce = login_state["nonce"]
            if nonce_mode != "match":
                nonce = nonce + "-mismatch"
            now = int(datetime.now(tz=timezone.utc).timestamp())
            token = jwt.encode(
                {
                    "iss": issuer,
                    "aud": client_id,
                    "tid": token_tid or tenant_id,
                    "sub": "user-subject",
                    "oid": "user-object-id",
                    "nonce": nonce,
                    "name": "Test User",
                    "preferred_username": "test.user@example.com",
                    "iat": now,
                    "exp": now + 3600,
                },
                private_key,
                algorithm="RS256",
                headers={"kid": "test-kid"},
            )
            return httpx.Response(200, json={"id_token": token, "token_type": "Bearer", "expires_in": 3600})
        raise AssertionError(f"unexpected auth request: {request.method} {request.url}")

    auth_client = httpx.AsyncClient(transport=httpx.MockTransport(auth_responder))
    config = AuthConfig(
        enabled=True,
        public_base_url=base_url,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret="super-secret",
        session_secret="session-secret",
    )
    auth = OIDCAuthManager(config=config, http_client=auth_client)
    auth._owns_client = True  # test-only: ensure the injected client is closed with the manager
    return auth, login_state


@pytest.fixture()
def auth_setup(oidc_keys):
    return build_auth_bundle(oidc_keys)


def test_authentication_protects_app_and_allows_callback_flow(auth_setup):
    auth, login_state = auth_setup

    def service_responder(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"name": "gpt-image-2.5-sunburst", "capabilities": {"imageEdits": True}},
                        {"name": "MAI-Image-2.6-Flash", "capabilities": {"imageEdits": False}},
                        {"name": "MAI-Image-2.6", "capabilities": {"imageEdits": True}},
                        {"name": "MAI-Image-2.5", "capabilities": {"imageEdits": True}},
                        {"name": "gpt-image-2", "capabilities": {"imageEdits": False}},
                    ]
                },
            )
        return httpx.Response(200, json={"data": [{"b64_json": "Zg=="}]})

    service, _ = make_service(service_responder)
    app = create_app(service=service, auth_manager=auth)

    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/healthz").status_code == 200

        root = client.get("/", follow_redirects=False)
        assert root.status_code == 307
        assert root.headers["location"].startswith("/login?return_to=%2F")

        api_unauth = client.get("/api/models")
        assert api_unauth.status_code == 401

        login = client.get("/login?return_to=/workbench", follow_redirects=False)
        assert login.status_code == 302
        auth_url = urlparse(login.headers["location"])
        query = parse_qs(auth_url.query)
        assert query["client_id"] == [auth.config.client_id]
        assert query["redirect_uri"] == [auth.config.callback_url]
        assert query["response_type"] == ["code"]
        assert query["scope"] == ["openid profile email"]
        login_state["nonce"] = query["nonce"][0]

        callback = client.get(f"/oauth/entra/callback?code=auth-code&state={query['state'][0]}", follow_redirects=False)
        assert callback.status_code == 302
        assert callback.headers["location"] == "/workbench"
        assert auth.load_session(client.cookies.get("__Host-foundry-session"))["preferred_username"] == "test.user@example.com"

        api_auth = client.get("/api/models")
        assert api_auth.status_code == 200
        assert [model["name"] for model in api_auth.json()["models"]][0] == "gpt-image-2.5-sunburst"

        logout = client.get("/logout", follow_redirects=False)
        assert logout.status_code == 302
        assert logout.headers["location"] == "/login"

        api_after_logout = client.get("/api/models")
        assert api_after_logout.status_code == 401


def test_missing_deployed_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
    monkeypatch.delenv("ENTRA_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)

    service, _ = make_service(lambda request: httpx.Response(200, json={"value": []}))

    with pytest.raises(RuntimeError, match="required auth configuration is missing"):
        create_app(service=service)


def test_callback_rejects_state_mismatch(oidc_keys):
    auth, login_state = build_auth_bundle(oidc_keys)

    def service_responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": "Zg=="}]})

    service, _ = make_service(service_responder)
    app = create_app(service=service, auth_manager=auth)

    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as client:
        login = client.get("/login?return_to=/workbench", follow_redirects=False)
        auth_url = urlparse(login.headers["location"])
        query = parse_qs(auth_url.query)
        login_state["nonce"] = query["nonce"][0]
        response = client.get(
            f"/oauth/entra/callback?code=auth-code&state=wrong-state",
            follow_redirects=False,
        )

    assert response.status_code == 401


def test_callback_rejects_nonce_mismatch(oidc_keys):
    auth, login_state = build_auth_bundle(oidc_keys, nonce_mode="mismatch")

    def service_responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": "Zg=="}]})

    service, _ = make_service(service_responder)
    app = create_app(service=service, auth_manager=auth)

    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as client:
        login = client.get("/login?return_to=/workbench", follow_redirects=False)
        auth_url = urlparse(login.headers["location"])
        query = parse_qs(auth_url.query)
        login_state["nonce"] = query["nonce"][0]
        response = client.get(
            f"/oauth/entra/callback?code=auth-code&state={query['state'][0]}",
            follow_redirects=False,
        )

    assert response.status_code == 401


def test_callback_rejects_tenant_claim_mismatch(oidc_keys):
    auth, login_state = build_auth_bundle(oidc_keys, token_tid="00000000-0000-0000-0000-000000000000")

    def service_responder(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": "Zg=="}]})

    service, _ = make_service(service_responder)
    app = create_app(service=service, auth_manager=auth)

    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as client:
        login = client.get("/login?return_to=/workbench", follow_redirects=False)
        auth_url = urlparse(login.headers["location"])
        query = parse_qs(auth_url.query)
        login_state["nonce"] = query["nonce"][0]
        response = client.get(
            f"/oauth/entra/callback?code=auth-code&state={query['state'][0]}",
            follow_redirects=False,
        )

    assert response.status_code == 401


def build_signed_token(private_key, *, kid: str, issuer: str, client_id: str, tenant_id: str) -> str:
    now = int(datetime.now(tz=timezone.utc).timestamp())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": client_id,
            "tid": tenant_id,
            "sub": "user-subject",
            "nonce": "expected-nonce",
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def test_unknown_kid_refreshes_jwks_once():
    tenant_id = "22222222-2222-2222-2222-222222222222"
    client_id = "11111111-1111-1111-1111-111111111111"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    jwks_uri = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    old_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    old_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(old_private_key.public_key()))
    new_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(new_private_key.public_key()))
    old_jwk["kid"] = "old-kid"
    new_jwk["kid"] = "new-kid"
    jwks_requests = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_requests
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": issuer, "jwks_uri": jwks_uri})
        if str(request.url) == jwks_uri:
            jwks_requests += 1
            return httpx.Response(200, json={"keys": [old_jwk if jwks_requests == 1 else new_jwk]})
        raise AssertionError(f"unexpected auth request: {request.method} {request.url}")

    auth = OIDCAuthManager(
        config=AuthConfig(
            enabled=True,
            public_base_url="https://testserver",
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret="super-secret",
            session_secret="session-secret",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(responder)),
    )
    token = build_signed_token(
        new_private_key,
        kid="new-kid",
        issuer=issuer,
        client_id=client_id,
        tenant_id=tenant_id,
    )

    claims = asyncio.run(auth._validate_id_token(token, "expected-nonce"))
    asyncio.run(auth.http.aclose())

    assert claims["sub"] == "user-subject"
    assert jwks_requests == 2


def test_unknown_kid_fails_after_one_jwks_refresh():
    tenant_id = "22222222-2222-2222-2222-222222222222"
    client_id = "11111111-1111-1111-1111-111111111111"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    jwks_uri = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    known_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unknown_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    known_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(known_private_key.public_key()))
    known_jwk["kid"] = "known-kid"
    jwks_requests = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal jwks_requests
        if str(request.url).endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": issuer, "jwks_uri": jwks_uri})
        if str(request.url) == jwks_uri:
            jwks_requests += 1
            return httpx.Response(200, json={"keys": [known_jwk]})
        raise AssertionError(f"unexpected auth request: {request.method} {request.url}")

    auth = OIDCAuthManager(
        config=AuthConfig(
            enabled=True,
            public_base_url="https://testserver",
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret="super-secret",
            session_secret="session-secret",
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(responder)),
    )
    token = build_signed_token(
        unknown_private_key,
        kid="unknown-kid",
        issuer=issuer,
        client_id=client_id,
        tenant_id=tenant_id,
    )

    with pytest.raises(RuntimeError, match="matching jwk not found"):
        asyncio.run(auth._validate_id_token(token, "expected-nonce"))
    asyncio.run(auth.http.aclose())

    assert jwks_requests == 2
