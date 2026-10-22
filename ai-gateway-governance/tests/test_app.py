from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.audit import AuditTrail
from app.auth import AuthConfig, OIDCAuthManager, SESSION_COOKIE_NAME
from app.config import Settings
from app.main import create_app
from app.prompts import LARGE_SYSTEM_PROMPT, SMALL_SYSTEM_PROMPT
from app.service import SummarizerService, classify_block, estimate_cost, tier_for_model


APP_KEY = "app-secret-value-123"
BURST_KEY = "burst-secret-value-456"


class FakeCredential:
    def get_token(self, *scopes):
        return SimpleNamespace(token="entra-token", expires_on=9_999_999_999)


def settings(monkeypatch, **env) -> Settings:
    values = {
        "GATEWAY_ENDPOINT": "https://gw.example.com",
        "GATEWAY_APP_KEY": APP_KEY,
        "GATEWAY_BURST_KEY": BURST_KEY,
        "AUDIT_LOG_PATH": "",
        **env,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def completion(model: str, prompt_tokens=100, completion_tokens=50, content="Shrnutí."):
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def client_for(cfg: Settings, handler) -> tuple[TestClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(record))
    service = SummarizerService(cfg, AuditTrail(None), credential=FakeCredential(), http_client=http)
    return TestClient(create_app(cfg, service)), seen


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_direct_baseline_uses_entra_and_large_prompt(monkeypatch):
    cfg = settings(monkeypatch)
    client, seen = client_for(cfg, lambda r: httpx.Response(200, json=completion("gpt-4.1-2025-04-14")))
    with client:
        result = client.post("/api/summarize", json={"text": "notes", "path": "direct"}).json()
    assert seen[0].url.host == "aif-mma-eus.openai.azure.com"
    assert seen[0].headers["authorization"] == "Bearer entra-token"
    assert "api-key" not in seen[0].headers
    assert body_of(seen[0])["messages"][0]["content"] == LARGE_SYSTEM_PROMPT
    assert result["servedTier"] == "large"
    assert result["policy"] == "none (no gateway)"
    assert result["estimatedCostUsd"] == pytest.approx((100 * 2 + 50 * 8) / 1_000_000)


def test_gateway_pass_keeps_large_model(monkeypatch):
    cfg = settings(monkeypatch)
    client, seen = client_for(
        cfg,
        lambda r: httpx.Response(200, json=completion("gpt-4.1-2025-04-14"), headers={"remaining-tokens": "1500"}),
    )
    with client:
        result = client.post("/api/summarize", json={"text": "notes", "path": "gateway"}).json()
    assert str(seen[0].url) == "https://gw.example.com/default/models/openai/v1/chat/completions"
    assert seen[0].headers["api-key"] == APP_KEY
    assert body_of(seen[0])["model"] == "summarizer-large"
    assert result["policy"] == "pass"
    assert result["fallback"] is False
    assert result["gatewayEvidence"][0]["remaining-tokens"] == "1500"


def test_token_limit_429_falls_back_to_small_alias(monkeypatch):
    cfg = settings(monkeypatch)

    def handler(request):
        if body_of(request)["model"] == "summarizer-large":
            return httpx.Response(
                429,
                json={"statusCode": 429, "message": "Token limit exceeded. Try again in 42 seconds."},
                headers={"retry-after": "42", "remaining-tokens": "0"},
            )
        return httpx.Response(200, json=completion("gpt-4.1-nano-2025-04-14", 4000, 200))

    client, seen = client_for(cfg, handler)
    with client:
        result = client.post("/api/summarize", json={"text": "long", "path": "gateway"}).json()
        audit = client.get("/api/audit").json()["events"]
    assert [body_of(r)["model"] for r in seen] == ["summarizer-large", "summarizer-small"]
    assert body_of(seen[1])["messages"][0]["content"] == SMALL_SYSTEM_PROMPT
    assert result["status"] == "ok"
    assert result["servedTier"] == "small"
    assert result["policy"] == "token_limit_exceeded"
    assert result["action"] == "fallback"
    assert result["fallback"] is True
    assert result["decidedBy"] == "gateway"
    assert len(result["auditIds"]) == 2
    assert audit[1]["gatewayDecision"] == "token_limit_exceeded"
    assert audit[1]["errorBody"]["message"].startswith("Token limit")


def test_gateway_native_reroute_is_reported(monkeypatch):
    cfg = settings(monkeypatch)
    client, seen = client_for(cfg, lambda r: httpx.Response(200, json=completion("gpt-4.1-nano-2025-04-14")))
    with client:
        result = client.post("/api/summarize", json={"text": "notes", "path": "gateway"}).json()
    assert len(seen) == 1
    assert result["policy"] == "rerouted_by_gateway"
    assert result["switchedBy"] == "gateway"
    assert result["fallback"] is True


def test_rate_limit_returns_consistent_envelope_without_fallback(monkeypatch):
    cfg = settings(monkeypatch)
    client, seen = client_for(
        cfg, lambda r: httpx.Response(429, json={"statusCode": 429, "message": "Rate limit is exceeded."},
                                      headers={"retry-after": "30"}),
    )
    with client:
        response = client.post("/api/summarize", json={"text": "notes", "path": "gateway"})
    assert len(seen) == 1
    assert response.status_code == 429
    error = response.json()["error"]
    assert error == {
        "code": "request_rate_limited",
        "httpStatus": 429,
        "message": "Rate limit is exceeded.",
        "retryAfterSeconds": 30,
        "source": "ai-gateway",
        "correlationId": error["correlationId"],
    }


def test_rate_limit_falls_back_when_configured(monkeypatch):
    cfg = settings(monkeypatch, FALLBACK_ON="token_limit_exceeded,request_rate_limited")

    def handler(request):
        if body_of(request)["model"] == "summarizer-large":
            return httpx.Response(429, json={"statusCode": 429, "message": "Rate limit is exceeded."},
                                  headers={"retry-after": "15"})
        return httpx.Response(200, json=completion("gpt-4.1-nano-2025-04-14"))

    client, seen = client_for(cfg, handler)
    with client:
        result = client.post("/api/summarize", json={"text": "notes", "path": "gateway"}).json()
    assert [body_of(r)["model"] for r in seen] == ["summarizer-large", "summarizer-small"]
    assert result["policy"] == "request_rate_limited"
    assert result["action"] == "fallback"
    assert result["servedTier"] == "small"


def test_reasoning_tier_omits_temperature_and_uses_completion_cap(monkeypatch):
    cfg = settings(monkeypatch, LARGE_TEMPERATURE="", LARGE_REASONING_EFFORT="low",
                   LARGE_MAX_OUTPUT_TOKENS="2500", SMALL_TEMPERATURE="0.2")

    def handler(request):
        if body_of(request)["model"] == "summarizer-large":
            return httpx.Response(429, json={"message": "Token limit exceeded."}, headers={"remaining-tokens": "0"})
        return httpx.Response(200, json=completion("gpt-4.1-nano-2025-04-14"))

    client, seen = client_for(cfg, handler)
    with client:
        client.post("/api/summarize", json={"text": "notes", "path": "gateway"})
        audit = client.get("/api/audit").json()["events"]
    large, small = body_of(seen[0]), body_of(seen[1])
    assert large["max_completion_tokens"] == 2500
    assert large["reasoning_effort"] == "low"
    assert "temperature" not in large and "max_tokens" not in large
    assert small["temperature"] == 0.2
    assert "reasoning_effort" not in small
    assert {e["request"].get("reasoning_effort") for e in audit} == {"low", None}


def test_burst_rejects_after_limit_and_control_key_passes(monkeypatch):
    cfg = settings(monkeypatch)
    calls = {"burst": 0}

    def handler(request):
        if request.headers["api-key"] == BURST_KEY:
            calls["burst"] += 1
            if calls["burst"] > 3:
                return httpx.Response(429, json={"message": "Rate limit is exceeded."}, headers={"retry-after": "20"})
        return httpx.Response(200, json=completion("gpt-4.1-nano-2025-04-14", 20, 2, "OK"))

    client, seen = client_for(cfg, handler)
    with client:
        result = client.post("/api/burst", json={"count": 6}).json()
    assert {body_of(r)["model"] for r in seen} == {"summarizer-large"}
    assert result["model"] == "summarizer-large"
    assert result["accepted"] == 3
    assert result["rejected"] == 3
    assert result["control"]["httpStatus"] == 200
    assert result["control"]["keyName"] == "summarizer-app"
    codes = {r["error"]["code"] for r in result["requests"] if r["error"]}
    assert codes == {"request_rate_limited"}


def test_key_values_never_reach_audit_or_api(monkeypatch):
    cfg = settings(monkeypatch)
    client, _ = client_for(cfg, lambda r: httpx.Response(429, json={"message": "Rate limit is exceeded."}))
    with client:
        client.post("/api/summarize", json={"text": "notes", "path": "gateway"})
        client.post("/api/burst", json={"count": 2})
        dump = json.dumps(client.get("/api/audit").json()) + json.dumps(client.get("/api/config").json())
    assert APP_KEY not in dump
    assert BURST_KEY not in dump
    assert "summarizer-app" in dump


def test_gateway_not_configured(monkeypatch):
    cfg = settings(monkeypatch, GATEWAY_APP_KEY="", GATEWAY_BURST_KEY="")
    client, seen = client_for(cfg, lambda r: httpx.Response(500))
    with client:
        response = client.post("/api/summarize", json={"text": "notes", "path": "gateway"})
        burst = client.post("/api/burst", json={"count": 2})
    assert not seen
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "gateway_not_configured"
    assert burst.status_code == 503


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected"),
    [
        (429, {}, {"message": "Token limit exceeded"}, "token_limit_exceeded"),
        (429, {"remaining-tokens": "0"}, {"message": "Too many"}, "token_limit_exceeded"),
        (429, {}, {"message": "Cost limit exceeded for budget"}, "cost_limit_exceeded"),
        (429, {}, {"message": "Rate limit is exceeded."}, "request_rate_limited"),
        (403, {}, {"message": "Forbidden by IP filter"}, "ip_filter_blocked"),
        (401, {}, {"message": "Unauthorized"}, "unauthorized"),
        (404, {}, {"error": {"code": "model_not_found"}}, "model_not_found"),
        (503, {}, "upstream", "backend_error"),
        (None, {}, None, "network_error"),
    ],
)
def test_classify_block(status, headers, body, expected):
    assert classify_block(status, headers, body) == expected


def test_tier_matching_prefers_longest_model_id(monkeypatch):
    cfg = settings(monkeypatch)
    profiles = (cfg.large, cfg.small)
    assert tier_for_model("gpt-4.1-nano-2025-04-14", profiles) == "small"
    assert tier_for_model("gpt-4.1-2025-04-14", profiles) == "large"
    assert tier_for_model("gpt-4.1", profiles) == "large"
    assert tier_for_model("gpt-5", profiles) is None


def test_estimate_cost_accounts_for_cached_tokens(monkeypatch):
    cfg = settings(monkeypatch)
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 400}}
    assert estimate_cost(usage, cfg.large) == pytest.approx((600 * 2 + 400 * 0.5 + 100 * 8) / 1_000_000)


def test_input_validation(monkeypatch):
    cfg = settings(monkeypatch)
    client, _ = client_for(cfg, lambda r: httpx.Response(500))
    with client:
        assert client.post("/api/summarize", json={"text": "  ", "path": "gateway"}).status_code == 422
        assert client.post("/api/summarize", json={"text": "x", "path": "other"}).status_code == 422
        assert client.post("/api/burst", json={"count": 99}).status_code == 422
        assert client.get("/static/../app/config.py").status_code == 404


def test_bootstrap_locked_serves_health_and_blocks_ui(monkeypatch):
    cfg = settings(monkeypatch)
    app = create_app(cfg, bootstrap_locked=True)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 503


def test_entra_reader_auth_protects_ui_and_api(monkeypatch):
    cfg = settings(monkeypatch)
    auth = OIDCAuthManager(
        AuthConfig(
            enabled=True,
            public_base_url="https://demo.example.com",
            tenant_id="tenant-1",
            client_id="client-1",
            client_secret="secret-1",
            session_secret="session-secret-1",
            allowed_users=("entra:allowed-oid",),
        )
    )
    service = SummarizerService(cfg, AuditTrail(None), credential=FakeCredential())
    app = create_app(cfg, service, auth_manager=auth, bootstrap_locked=False)
    with TestClient(app, base_url="https://demo.example.com") as client:
        assert client.get("/healthz").status_code == 200
        redir = client.get("/", follow_redirects=False)
        assert redir.status_code == 307
        assert redir.headers["location"].startswith("/login?return_to=")
        assert client.get("/api/config").status_code == 401

        denied_cookie = auth.create_session_cookie({"sub": "s", "tid": "tenant-1", "oid": "other-oid", "name": "No"})
        client.cookies.set(SESSION_COOKIE_NAME, denied_cookie)
        assert client.get("/api/config").status_code == 401

        allowed_cookie = auth.create_session_cookie(
            {"sub": "s", "tid": "tenant-1", "oid": "allowed-oid", "name": "Alice"}
        )
        client.cookies.set(SESSION_COOKIE_NAME, allowed_cookie)
        config_res = client.get("/api/config")
        assert config_res.status_code == 200
        assert config_res.json()["user"] == "Alice"

