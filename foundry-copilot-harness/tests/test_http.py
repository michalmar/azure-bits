import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time
import threading

from fastapi import HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
import pytest

from config import Settings
from auth import identity_allowed, identity_from_claims
from main import create_app
from scenario import REFERENCE

SECRET = "test-only-random-session-key-not-a-real-credential"
USER = "11111111-1111-4111-8111-111111111111"
ORIGIN = "https://workshop.example.com"


class Store:
    def __init__(self, settings):
        pass

    async def close(self):
        pass


class Runner:
    calls = 0

    async def run(self):
        self.calls += 1
        yield {"type": "accepted", "agent": "workshop-planner-demo", "agent_version": "1", "conversation_id": "conv-1", "skills": []}
        yield {"type": "tool", "name": "skill", "status": "started"}
        yield {
            "type": "result", "text": "<script>unsafe</script>", "verified": True,
            "response_id": "resp-1", "conversation_id": "conv-1", "budget": REFERENCE,
            "warnings": [], "citations": [],
            "files": [{"file_id": "file-1", "filename": "budget.json"}],
        }

    async def read_file(self, identifier):
        assert identifier == "file-1"
        return b'{"test":true}'


@pytest.fixture
def live(monkeypatch):
    env = {
        "STORAGE_ACCOUNT_NAME": "teststorage", "BLOB_CONTAINER_NAME": "site",
        "AZURE_CLIENT_ID": USER, "PUBLIC_BASE_URL": ORIGIN, "AUTH_PROVIDER": "entra",
        "SESSION_SECRET": SECRET, "ENTRA_CLIENT_ID": USER, "ENTRA_CLIENT_SECRET": "reader-test-only",
        "ENTRA_TENANT_ID": USER, "ALLOWED_USERS": "entra:" + USER,
    }
    monkeypatch.setenv("LIVE_DEMO_ENABLED", "true")
    monkeypatch.setenv("LOCAL_DEV", "false")
    settings = Settings.from_env(env)
    runner = Runner()
    app = create_app(settings=settings, service=runner, storage_factory=Store)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, runner, env


def sign_in(client, user=USER):
    payload = {
        "identity": {"provider": "entra", "id": user, "name": ""},
        "expires": int(time.time()) + 3600,
    }
    value = TimestampSigner(SECRET).sign(base64.b64encode(json.dumps(payload).encode())).decode()
    client.cookies.clear()
    client.cookies.set("__Host-aca_session", value)


def headers(client):
    response = client.get("/api/config")
    return {"Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": response.json()["csrf"]}


def test_anonymous_and_denylisted_readers(live):
    client, runner, env = live
    assert client.get("/api/config").status_code == 401
    assert client.post("/api/run", json={}).status_code == 401
    assert client.get("/api/files/fake").status_code == 401
    sign_in(client, "22222222-2222-4222-8222-222222222222")
    assert client.get("/api/config").status_code == 401
    sign_in(client)
    assert client.get("/api/config").status_code == 200
    env["ALLOWED_USERS"] = ""
    assert client.get("/api/config").status_code == 401
    assert runner.calls == 0


def test_tenant_wildcard_allows_all_configured_tenant_users_without_sharing_reports(live):
    client, _, env = live
    env["ALLOWED_USERS"] = "tenant:*"
    assert client.get("/api/config").status_code == 401
    sign_in(client, "22222222-2222-4222-8222-222222222222")
    assert client.get("/api/config").status_code == 200
    events = client.post("/api/run", headers=headers(client), content="{}").text.splitlines()
    link = json.loads(events[-1])["files"][0]["url"]
    assert client.get(link).status_code == 200
    sign_in(client)
    assert client.get("/api/config").status_code == 200
    assert client.get(link).status_code == 403
    env["ALLOWED_USERS"] = ""
    assert client.get("/api/config").status_code == 401


def test_tenant_wildcard_requires_validated_entra_tenant(live):
    _, _, env = live
    env["ALLOWED_USERS"] = "tenant:*"
    settings = Settings.from_env(env)
    claims = {"tid": USER, "oid": "22222222-2222-4222-8222-222222222222"}
    identity = identity_from_claims("entra", claims, settings)
    assert identity_allowed(identity, settings)
    with pytest.raises(HTTPException) as error:
        identity_from_claims("entra", {**claims, "tid": "33333333-3333-4333-8333-333333333333"}, settings)
    assert error.value.status_code == 401
    assert not identity_allowed({"provider": "google", "id": "external", "name": ""}, settings)


def test_fixed_prompt_csrf_rate_limit_and_downloads(live):
    client, runner, _ = live
    sign_in(client)
    good = headers(client)
    assert client.post("/api/run", headers={**good, "Origin": "https://evil.example.com"}, json={}).status_code == 403
    assert client.post("/api/run", headers={**good, "X-CSRF-Token": "bad"}, json={}).status_code == 403
    assert client.post("/api/run", headers=good, json={"prompt": "not allowed"}).status_code == 400
    response = client.post("/api/run", headers=good, content="{}")
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["verified"] is True
    link = events[-1]["files"][0]["url"]
    assert client.get(link).content == b'{"test":true}'
    assert client.get("/api/files/tampered").status_code == 410
    assert client.post("/api/run", headers=good, content="{}").status_code == 429
    assert runner.calls == 1
    sign_in(client, "22222222-2222-4222-8222-222222222222")
    assert client.get(link).status_code == 401


def test_disabled_publisher_precedes_auth_and_method_dispatch(live):
    client, _, _ = live
    for method in ["GET", "HEAD", "POST", "PUT", "DELETE"]:
        assert client.request(method, "/_publish/blobs/index.html").status_code == 404


def test_local_preview_never_calls_azure(monkeypatch):
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("LIVE_DEMO_ENABLED", "false")
    monkeypatch.setenv("APP_ENV", "development")
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/app.mjs").status_code == 200
        assert client.get("/api/config").json()["live"] is False
        assert client.post("/api/run", json={}).status_code == 405
        assert client.get("/../requirements.lock").status_code == 404
        for method in ["GET", "HEAD", "POST", "PUT", "DELETE"]:
            assert client.request(method, "/_publish/blobs/index.html").status_code == 404


def test_production_cannot_enable_local_preview(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOCAL_DEV", "true")
    with pytest.raises(ValueError, match="LOCAL_DEV"):
        create_app()


def test_bootstrap_is_locked(monkeypatch):
    monkeypatch.setenv("LOCAL_DEV", "false")
    monkeypatch.setenv("LIVE_DEMO_ENABLED", "false")
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 503
        assert client.post("/api/run", json={}).status_code == 503
        for method in ["GET", "HEAD", "POST", "PUT", "DELETE"]:
            assert client.request(method, "/_publish/blobs/index.html").status_code == 404


def test_parallel_run_rejected(live):
    client, _, _ = live
    sign_in(client)
    good = headers(client)
    entered = threading.Event()

    class SlowRunner(Runner):
        async def run(self):
            entered.set()
            await asyncio.sleep(0.3)
            async for event in super().run():
                yield event

    client.app.state.runner = SlowRunner()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/api/run", headers=good, content="{}")
        assert entered.wait(5)
        assert client.post("/api/run", headers=good, content="{}").status_code == 409
        assert first.result().status_code == 200


def test_timeout_surfaces_uncertain_remote_state(live, monkeypatch):
    client, _, _ = live
    sign_in(client)
    good = headers(client)

    class SlowRunner(Runner):
        async def run(self):
            await asyncio.sleep(1)
            yield {"type": "result"}

    client.app.state.runner = SlowRunner()
    monkeypatch.setattr("main.RUN_TIMEOUT_SECONDS", 0.01)
    response = client.post("/api/run", headers=good, content="{}")
    event = json.loads(response.text.strip())
    assert event["type"] == "error"
    assert "není zaručeno" in event["message"]


def test_reports_are_bound_to_the_reader(live):
    client, _, env = live
    sign_in(client)
    good = headers(client)
    events = client.post("/api/run", headers=good, content="{}").text.splitlines()
    link = json.loads(events[-1])["files"][0]["url"]
    second = "22222222-2222-4222-8222-222222222222"
    env["ALLOWED_USERS"] += ",entra:" + second
    sign_in(client, second)
    assert client.get("/api/config").status_code == 200
    assert client.get(link).status_code == 403
