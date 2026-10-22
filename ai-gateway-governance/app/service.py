from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

import anyio
import httpx
from azure.identity import AzureCliCredential, ManagedIdentityCredential

from .audit import AuditTrail
from .config import DATA_SCOPE, Profile, Settings
from .prompts import BURST_PROBE_PROMPT, PROMPT_PROFILES


logger = logging.getLogger(__name__)

# Gateway decisions that the summarizer survives by switching to the small tier.

# Response headers that carry governance evidence; everything else stays in the raw audit entry.
EVIDENCE_HEADERS = (
    "remaining-tokens",
    "consumed-tokens",
    "remaining-quota-tokens",
    "remaining-requests",
    "retry-after",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-remaining-requests",
    "x-correlation-id",
    "x-request-id",
    "apim-request-id",
    "x-ms-region",
)
_REDACTED_HEADERS = {"set-cookie", "api-key", "authorization"}


# Reasoning models spend completion tokens on thinking, so a tiny cap can return no text.
BURST_MAX_TOKENS = 64


def request_params(profile: Profile, max_out: int) -> dict[str, Any]:
    """Per-tier generation parameters. Reasoning models reject max_tokens and non-default temperature."""
    params: dict[str, Any] = {"max_completion_tokens": max_out}
    if profile.temperature is not None:
        params["temperature"] = profile.temperature
    if profile.reasoning_effort:
        params["reasoning_effort"] = profile.reasoning_effort
    return params


def classify_block(status: int | None, headers: dict[str, str], body: Any) -> str:
    """Map a non-2xx gateway answer to a stable, client-facing policy code."""
    if status is None:
        return "network_error"
    text = _body_text(body).lower()
    if status == 429:
        if "cost" in text or "budget" in text or "spend" in text:
            return "cost_limit_exceeded"
        if "token" in text or any(h in headers for h in ("remaining-tokens", "consumed-tokens")):
            return "token_limit_exceeded"
        return "request_rate_limited"
    if status == 403:
        return "ip_filter_blocked" if "ip" in text else "forbidden"
    if status == 400 and ("content" in text and ("safety" in text or "filter" in text)):
        return "content_safety_blocked"
    if status == 401:
        return "unauthorized"
    if status == 404:
        return "model_not_found"
    if status >= 500:
        return "backend_error"
    return "request_rejected"


def tier_for_model(model: str | None, profiles: tuple[Profile, ...]) -> str | None:
    if not model:
        return None
    value = model.lower()
    for profile in sorted(profiles, key=lambda p: len(p.model_id), reverse=True):
        model_id = profile.model_id.lower()
        if value == model_id or value.startswith(model_id + "-"):
            return profile.tier
    return None


def estimate_cost(usage: dict[str, Any] | None, profile: Profile) -> float | None:
    if not usage:
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    price = profile.price
    cost = (
        (prompt - cached) * price.input
        + cached * price.cached_input
        + completion * price.output
    ) / 1_000_000
    return round(cost, 8)


def _body_text(body: Any) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    return json.dumps(body, ensure_ascii=False)


def _error_message(body: Any) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if body.get("message"):
            return str(body["message"])
    text = _body_text(body)
    return text[:400] if text else "No response body."


def _retry_after(headers: dict[str, str]) -> int | None:
    value = headers.get("retry-after")
    try:
        return max(0, int(float(value))) if value is not None else None
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SummarizerService:
    def __init__(
        self,
        settings: Settings,
        audit: AuditTrail,
        credential: object | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.audit = audit
        self.credential = credential or self._credential()
        self.http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
        )
        self._owns_http = http_client is None
        self._token: tuple[str, float] | None = None
        self._token_lock = asyncio.Lock()

    @staticmethod
    def _credential() -> object:
        if os.getenv("APP_ENV", "development").lower() == "production":
            return ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)
        return AzureCliCredential()

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def _entra_token(self) -> str:
        async with self._token_lock:
            if self._token and self._token[1] - 300 > time.time():
                return self._token[0]
            token = await anyio.to_thread.run_sync(self.credential.get_token, DATA_SCOPE)
            self._token = (token.token, float(token.expires_on))
            return token.token

    # ------------------------------------------------------------------ calls

    async def _call(
        self,
        *,
        run_id: str,
        seq: int,
        path: str,
        profile: Profile,
        model: str,
        text: str,
        key_name: str | None,
        api_key: str | None,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        purpose: str = "summarize",
    ) -> dict[str, Any]:
        system = system_prompt or PROMPT_PROFILES[profile.tier]["system"]
        max_out = max_tokens or profile.max_output_tokens
        params = request_params(profile, max_out)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            **params,
        }
        correlation_id = f"{run_id}-{seq}"
        headers = {"content-type": "application/json", "x-correlation-id": correlation_id}
        auth_ms = 0.0
        if path == "direct":
            url = f"{self.settings.foundry_endpoint}/openai/v1/chat/completions"
            auth_started = time.perf_counter()
            headers["authorization"] = f"Bearer {await self._entra_token()}"
            auth_ms = (time.perf_counter() - auth_started) * 1000
        else:
            url = f"{self.settings.gateway_endpoint}/default/models/openai/v1/chat/completions"
            headers["api-key"] = api_key or ""

        status: int | None = None
        response_headers: dict[str, str] = {}
        payload: Any = None
        started = time.perf_counter()
        try:
            response = await self.http.post(url, headers=headers, json=body)
            status = response.status_code
            response_headers = {
                k.lower(): v[:300] for k, v in response.headers.items() if k.lower() not in _REDACTED_HEADERS
            }
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:2000]
        except httpx.HTTPError as exc:
            payload = f"{type(exc).__name__}: {exc}"
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        ok = status is not None and 200 <= status < 300 and isinstance(payload, dict)
        served_model = payload.get("model") if ok else None
        usage = payload.get("usage") if ok else None
        served_tier = tier_for_model(served_model, (self.settings.large, self.settings.small))
        served_profile = self.settings.small if served_tier == "small" else self.settings.large
        if served_tier is None:
            served_profile = profile
        content = ""
        if ok:
            choices = payload.get("choices") or []
            if choices and isinstance(choices[0], dict):
                content = (choices[0].get("message") or {}).get("content") or ""

        if path == "direct":
            decision = "not_applicable" if ok else "backend_error"
        elif ok:
            decision = "pass" if served_tier in (None, profile.tier) else "rerouted"
        else:
            decision = classify_block(status, response_headers, payload)

        event = {
            "id": correlation_id,
            "runId": run_id,
            "timestamp": _now(),
            "purpose": purpose,
            "path": path,
            "endpointHost": urlsplit(url).netloc,
            "operation": "chat.completions",
            "keyName": key_name if path == "gateway" else "entra-id (no gateway)",
            "requestedModel": model,
            "requestedTier": profile.tier,
            "promptProfile": PROMPT_PROFILES[profile.tier]["name"] if purpose == "summarize" else "probe",
            "request": {
                "model": model,
                **params,
                "inputChars": len(text),
                "inputPreview": text[:160],
            },
            "httpStatus": status,
            "latencyMs": latency_ms,
            "authMs": round(auth_ms, 1),
            "servedModel": served_model,
            "servedTier": served_tier,
            "usage": usage,
            "estimatedCostUsd": estimate_cost(usage, served_profile) if ok else None,
            "gatewayDecision": decision,
            "evidenceHeaders": {h: response_headers[h] for h in EVIDENCE_HEADERS if h in response_headers},
            "responseHeaders": response_headers,
            "errorBody": None if ok else payload,
            "outputChars": len(content),
        }
        self.audit.record(event)
        return {"ok": ok, "event": event, "content": content}

    # ------------------------------------------------------------- summarize

    async def summarize(self, text: str, path: str) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:12]
        large, small = self.settings.large, self.settings.small
        if path == "direct":
            first = await self._call(
                run_id=run_id, seq=1, path="direct", profile=large,
                model=self.settings.direct_large_deployment, text=text, key_name=None, api_key=None,
            )
            return self._result(run_id, path, [first], final=first, policy="none (no gateway)",
                                action="none", decided_by="none")

        if not self.settings.gateway_configured:
            return self._error_result(run_id, path, "gateway_not_configured", None,
                                      "Set GATEWAY_ENDPOINT and GATEWAY_APP_KEY to call the AI Gateway.", [])

        first = await self._call(
            run_id=run_id, seq=1, path="gateway", profile=large,
            model=self.settings.gateway_primary_model, text=text,
            key_name=self.settings.gateway_app_key_name, api_key=self.settings.gateway_app_key,
        )
        decision = first["event"]["gatewayDecision"]
        if first["ok"]:
            if decision == "rerouted":
                return self._result(run_id, path, [first], final=first, policy="rerouted_by_gateway",
                                    action="fallback", decided_by="gateway", switched_by="gateway")
            return self._result(run_id, path, [first], final=first, policy="pass",
                                action="none", decided_by="gateway")

        if decision in self.settings.fallback_on:
            second = await self._call(
                run_id=run_id, seq=2, path="gateway", profile=small,
                model=self.settings.gateway_fallback_model, text=text,
                key_name=self.settings.gateway_app_key_name, api_key=self.settings.gateway_app_key,
            )
            if second["ok"]:
                return self._result(run_id, path, [first, second], final=second, policy=decision,
                                    action="fallback", decided_by="gateway",
                                    switched_by="app (on gateway 429)")
            return self._error_from_call(run_id, path, second, [first, second])

        return self._error_from_call(run_id, path, first, [first])

    def _result(self, run_id, path, calls, *, final, policy, action, decided_by, switched_by=None):
        event = final["event"]
        usage = event.get("usage") or {}
        tier = event.get("servedTier") or event.get("requestedTier")
        return {
            "runId": run_id,
            "status": "ok",
            "path": path,
            "requestedModel": calls[0]["event"]["requestedModel"],
            "servedModel": event.get("servedModel"),
            "servedTier": tier,
            "fallback": action == "fallback",
            "policy": policy,
            "action": action,
            "decidedBy": decided_by,
            "switchedBy": switched_by,
            "promptProfile": PROMPT_PROFILES[event["requestedTier"]]["name"],
            "tokens": {
                "prompt": usage.get("prompt_tokens"),
                "completion": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            },
            "latencyMs": round(sum(c["event"]["latencyMs"] for c in calls), 1),
            "authMs": round(sum(c["event"]["authMs"] for c in calls), 1),
            "estimatedCostUsd": event.get("estimatedCostUsd"),
            "gatewayEvidence": [c["event"]["evidenceHeaders"] for c in calls],
            "auditIds": [c["event"]["id"] for c in calls],
            "summary": final["content"],
            "error": None,
        }

    def _error_from_call(self, run_id, path, call, calls):
        event = call["event"]
        return self._error_result(
            run_id, path, event["gatewayDecision"], event["httpStatus"],
            _error_message(event["errorBody"]), calls,
            retry_after=_retry_after(event["responseHeaders"]),
        )

    @staticmethod
    def _error_result(run_id, path, code, status, message, calls, retry_after=None):
        return {
            "runId": run_id,
            "status": "error",
            "path": path,
            "requestedModel": calls[0]["event"]["requestedModel"] if calls else None,
            "servedModel": None,
            "servedTier": None,
            "fallback": False,
            "policy": code,
            "action": "reject",
            "decidedBy": "gateway" if path == "gateway" and status else "app",
            "switchedBy": None,
            "latencyMs": round(sum(c["event"]["latencyMs"] for c in calls), 1),
            "auditIds": [c["event"]["id"] for c in calls],
            "gatewayEvidence": [c["event"]["evidenceHeaders"] for c in calls],
            "summary": "",
            "error": error_envelope(code, status, message, retry_after, calls[-1]["event"]["id"] if calls else None),
        }

    # ----------------------------------------------------------------- burst

    async def burst(self, count: int) -> dict[str, Any]:
        run_id = "burst-" + uuid.uuid4().hex[:8]
        if not self.settings.burst_key_configured:
            return {"runId": run_id, "error": error_envelope(
                "gateway_not_configured", None, "Set GATEWAY_BURST_KEY to run the rate-limit test.", None, None)}
        model = self.settings.burst_model
        profile = self.settings.small if model == self.settings.gateway_fallback_model else self.settings.large

        async def probe(seq: int, key_name: str, key: str):
            return await self._call(
                run_id=run_id, seq=seq, path="gateway", profile=profile,
                model=model, text=BURST_PROBE_PROMPT,
                key_name=key_name, api_key=key, system_prompt="Odpovídej co nejstručněji.",
                max_tokens=BURST_MAX_TOKENS, purpose="burst",
            )

        started = time.perf_counter()
        calls = await asyncio.gather(*[
            probe(i + 1, self.settings.gateway_burst_key_name, self.settings.gateway_burst_key)
            for i in range(count)
        ])
        control = None
        if self.settings.gateway_app_key:
            control = await probe(count + 1, self.settings.gateway_app_key_name, self.settings.gateway_app_key)

        def row(call):
            e = call["event"]
            code = e["gatewayDecision"]
            return {
                "id": e["id"],
                "keyName": e["keyName"],
                "httpStatus": e["httpStatus"],
                "decision": code,
                "latencyMs": e["latencyMs"],
                "error": None if call["ok"] else error_envelope(
                    code, e["httpStatus"], _error_message(e["errorBody"]),
                    _retry_after(e["responseHeaders"]), e["id"]),
            }

        rows = [row(c) for c in calls]
        return {
            "runId": run_id,
            "keyName": self.settings.gateway_burst_key_name,
            "model": model,
            "wallClockMs": round((time.perf_counter() - started) * 1000, 1),
            "accepted": sum(1 for r in rows if r["httpStatus"] and r["httpStatus"] < 300),
            "rejected": sum(1 for r in rows if not r["httpStatus"] or r["httpStatus"] >= 300),
            "requests": rows,
            "control": row(control) if control else None,
            "error": None,
        }


def error_envelope(code, status, message, retry_after, correlation_id):
    """The one error shape the app returns, whatever the gateway rejected."""
    return {
        "code": code,
        "httpStatus": status,
        "message": message,
        "retryAfterSeconds": retry_after,
        "source": "ai-gateway" if status else "app",
        "correlationId": correlation_id,
    }
