from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


PRICING = {
    "currency": "USD",
    "unit": "1M tokens",
    "standard": {"input": 4.0, "cachedInput": 0.4, "cacheWrite": 5.0, "output": 20.0},
    "flex": {"input": 2.0, "cachedInput": 0.2, "cacheWrite": 2.5, "output": 10.0},
    "priority": {"input": 8.0, "cachedInput": 0.8, "cacheWrite": 10.0, "output": 40.0},
    "source": "test",
}


class FakePricing:
    async def get(self):
        return PRICING


class FakeService:
    pricing = FakePricing()

    async def safe_run_tier(self, prompt, service_tier, deployment, max_output_tokens, pricing):
        return {
            "ok": True,
            "requestedTier": service_tier,
            "processedTier": service_tier,
            "deployment": deployment,
            "outputText": prompt,
            "latency": {"totalMs": 10},
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "cost": {"amount": 0.00001},
        }


def test_compare_runs_both_tiers() -> None:
    settings = Settings(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.6-sol",
        priority_deployment="gpt-5.6-sol-priority",
        request_timeout_seconds=900,
        default_max_output_tokens=800,
        pricing_currency="USD",
        max_transient_attempts=3,
    )
    with TestClient(create_app(settings=settings, service=FakeService())) as client:
        response = client.post("/api/compare", json={"prompt": "Compare this", "max_output_tokens": 50})

    assert response.status_code == 200
    payload = response.json()
    assert payload["parallel"] is True
    assert payload["results"]["standard"]["requestedTier"] == "default"
    assert payload["results"]["flex"]["requestedTier"] == "flex"
    assert payload["results"]["priority"]["requestedTier"] == "priority"
    assert payload["results"]["priority"]["deployment"] == "gpt-5.6-sol-priority"


def test_compare_rejects_blank_prompt() -> None:
    settings = Settings(
        endpoint="https://example.openai.azure.com",
        deployment="gpt-5.6-sol",
        priority_deployment="gpt-5.6-sol-priority",
        request_timeout_seconds=900,
        default_max_output_tokens=800,
        pricing_currency="USD",
        max_transient_attempts=3,
    )
    with TestClient(create_app(settings=settings, service=FakeService())) as client:
        response = client.post("/api/compare", json={"prompt": "   ", "max_output_tokens": 50})

    assert response.status_code == 422
