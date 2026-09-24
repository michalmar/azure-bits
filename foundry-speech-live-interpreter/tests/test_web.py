from fastapi.testclient import TestClient

from app.main import app
from app.auth import AuthConfig, AuthManager


def test_health_and_frontend(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "healthy"}
        response = client.get("/")
        assert response.status_code == 200
        assert "Speak naturally. Hear the translation." in response.text


def test_config_hides_personal_voice_by_default(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.delenv("PERSONAL_VOICE_ENABLED", raising=False)
    with TestClient(app) as client:
        payload = client.get("/api/config").json()
        assert payload["personalVoiceAvailable"] is False
        assert payload["authenticated"] is False


def test_tenant_wildcard_is_a_supported_allowlist_value():
    manager = AuthManager(
        AuthConfig(
            enabled=True,
            public_base_url="https://example.invalid",
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            session_secret="session-secret",
            allowed_users=("tenant:*",),
        )
    )
    assert manager.config.allowed_users == ("tenant:*",)
