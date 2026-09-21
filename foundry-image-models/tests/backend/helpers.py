from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.auth import AuthConfig, OIDCAuthManager
from app.main import create_app
from app.service import FoundryService


class RecordingCredential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str):
        self.scopes.append(scope)
        return SimpleNamespace(token="test-token")


def make_service(responder, credential: RecordingCredential | None = None) -> tuple[FoundryService, RecordingCredential]:
    cred = credential or RecordingCredential()
    transport = httpx.MockTransport(responder)
    client = httpx.AsyncClient(transport=transport, base_url="https://example.invalid")
    service = FoundryService(credential=cred, http_client=client)
    return service, cred


def make_client(service: FoundryService, auth_manager: OIDCAuthManager | None = None):
    from fastapi.testclient import TestClient

    app = create_app(
        service=service,
        auth_manager=auth_manager
        or OIDCAuthManager(AuthConfig(enabled=False, public_base_url="https://testserver")),
    )
    return TestClient(app, base_url="https://testserver")
