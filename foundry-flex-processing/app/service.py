from __future__ import annotations

import json
import logging
import random
import time
from typing import Any

import anyio
import httpx
from azure.core.exceptions import ClientAuthenticationError
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.identity import CredentialUnavailableError

from .config import DATA_SCOPE, Settings
from .pricing import PricingCatalog, calculate_cost


logger = logging.getLogger(__name__)
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class BenchmarkRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class FlexBenchmarkService:
    def __init__(
        self,
        settings: Settings,
        credential: object | None = None,
        http_client: httpx.AsyncClient | None = None,
        pricing: PricingCatalog | None = None,
    ) -> None:
        self.settings = settings
        self.credential = credential or self._credential()
        self.http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        self.pricing = pricing or PricingCatalog(self.http, settings.pricing_currency)
        self._owns_http = http_client is None

    def _credential(self) -> object:
        import os

        if os.getenv("APP_ENV", "development").lower() == "production":
            return ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)
        return AzureCliCredential()

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def _access_token(self) -> str:
        token = await anyio.to_thread.run_sync(self.credential.get_token, DATA_SCOPE)
        return token.token

    def _responses_url(self) -> str:
        return f"{self.settings.endpoint}/openai/v1/responses"

    @staticmethod
    def _extract_output_text(response: dict[str, Any]) -> str:
        parts: list[str] = []
        output = response.get("output")
        if not isinstance(output, list):
            return ""
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for entry in content:
                if isinstance(entry, dict) and entry.get("type") == "output_text":
                    text = entry.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts)

    @staticmethod
    def _error_detail(payload: Any, status_code: int) -> str:
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                return error["message"]
            if isinstance(payload.get("detail"), str):
                return payload["detail"]
        return f"Foundry request failed with HTTP {status_code}."

    async def run_tier(
        self,
        prompt: str,
        service_tier: str,
        max_output_tokens: int,
        pricing: dict[str, Any],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        token = await self._access_token()
        authenticated = time.perf_counter()
        body = {
            "model": self.settings.deployment,
            "input": prompt,
            "service_tier": service_tier,
            "max_output_tokens": max_output_tokens,
            "stream": True,
        }
        final_response: dict[str, Any] | None = None
        text_parts: list[str] = []
        first_token_at: float | None = None
        headers_at: float | None = None
        try:
            async with self.http.stream(
                "POST",
                self._responses_url(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response:
                headers_at = time.perf_counter()
                if response.status_code >= 400:
                    raw = await response.aread()
                    try:
                        payload = json.loads(raw)
                    except (ValueError, TypeError):
                        payload = None
                    raise BenchmarkRequestError(
                        self._error_detail(payload, response.status_code),
                        status_code=response.status_code,
                        retry_after=response.headers.get("retry-after"),
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw_event = line[5:].strip()
                    if not raw_event or raw_event == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw_event)
                    except ValueError as exc:
                        raise BenchmarkRequestError("Foundry returned an invalid streaming event.") from exc
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("type")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            text_parts.append(delta)
                    elif event_type in {"response.completed", "response.incomplete"} and isinstance(
                        event.get("response"), dict
                    ):
                        final_response = event["response"]
                    elif event_type == "response.failed":
                        candidate = event.get("response")
                        message = "The model did not complete the response."
                        status_code = None
                        if isinstance(candidate, dict):
                            error = candidate.get("error")
                            if isinstance(error, dict) and isinstance(error.get("message"), str):
                                message = error["message"]
                                error_code = str(error.get("code") or "").lower()
                                if error_code in {"server_error", "service_unavailable", "overloaded"}:
                                    status_code = 503
                        if "overloaded or not ready" in message.lower():
                            status_code = 503
                        raise BenchmarkRequestError(message, status_code=status_code)
        except httpx.TimeoutException as exc:
            raise BenchmarkRequestError(
                f"The {service_tier} request exceeded the {self.settings.request_timeout_seconds:g}-second timeout.",
                status_code=408,
            ) from exc
        except httpx.HTTPError as exc:
            raise BenchmarkRequestError(f"The {service_tier} connection failed: {exc}") from exc

        completed = time.perf_counter()
        if final_response is None:
            raise BenchmarkRequestError("Foundry closed the stream before the response completed.")
        output_text = "".join(text_parts) or self._extract_output_text(final_response)
        if first_token_at is None and output_text:
            first_token_at = completed
        usage = final_response.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        processed_tier = final_response.get("service_tier")
        price_key = "flex" if processed_tier == "flex" else "standard"
        tier_prices = pricing[price_key]
        latency = {
            "authenticationMs": round((authenticated - started) * 1000, 1),
            "requestToHeadersMs": round(((headers_at or authenticated) - authenticated) * 1000, 1),
            "headersToFirstTokenMs": (
                round((first_token_at - (headers_at or authenticated)) * 1000, 1)
                if first_token_at is not None
                else None
            ),
            "timeToFirstTokenMs": (
                round((first_token_at - started) * 1000, 1) if first_token_at is not None else None
            ),
            "generationMs": (
                round((completed - first_token_at) * 1000, 1) if first_token_at is not None else None
            ),
            "totalMs": round((completed - started) * 1000, 1),
        }
        return {
            "ok": True,
            "requestedTier": service_tier,
            "processedTier": processed_tier,
            "responseId": final_response.get("id"),
            "status": final_response.get("status"),
            "incompleteReason": (
                final_response.get("incomplete_details", {}).get("reason")
                if isinstance(final_response.get("incomplete_details"), dict)
                else None
            ),
            "outputText": output_text,
            "latency": latency,
            "usage": usage,
            "cost": calculate_cost(usage, tier_prices),
        }

    async def safe_run_tier(
        self,
        prompt: str,
        service_tier: str,
        max_output_tokens: int,
        pricing: dict[str, Any],
    ) -> dict[str, Any]:
        delays: list[float] = []
        for attempt in range(1, self.settings.max_transient_attempts + 1):
            try:
                result = await self.run_tier(prompt, service_tier, max_output_tokens, pricing)
                result["attempts"] = attempt
                result["retryDelaysMs"] = [round(delay * 1000) for delay in delays]
                return result
            except (ClientAuthenticationError, CredentialUnavailableError):
                logger.exception("Azure model authentication failed")
                return {
                    "ok": False,
                    "requestedTier": service_tier,
                    "error": "Model authentication failed. Check the Azure CLI session or managed identity role assignment.",
                    "statusCode": 401,
                    "retryAfter": None,
                    "attempts": attempt,
                    "retryDelaysMs": [round(delay * 1000) for delay in delays],
                }
            except BenchmarkRequestError as exc:
                transient = exc.status_code in TRANSIENT_STATUS_CODES
                if not transient or attempt >= self.settings.max_transient_attempts:
                    logger.warning(
                        "%s benchmark request failed after %s attempt(s), HTTP %s: %s",
                        service_tier,
                        attempt,
                        exc.status_code,
                        exc,
                    )
                    return {
                        "ok": False,
                        "requestedTier": service_tier,
                        "error": str(exc),
                        "statusCode": exc.status_code,
                        "retryAfter": exc.retry_after,
                        "attempts": attempt,
                        "retryDelaysMs": [round(delay * 1000) for delay in delays],
                    }
                retry_after = None
                if exc.retry_after:
                    try:
                        retry_after = float(exc.retry_after)
                    except ValueError:
                        retry_after = None
                delay = min(retry_after if retry_after is not None else 0.75 * (2 ** (attempt - 1)), 20)
                delay += random.uniform(0.05, 0.35)
                delays.append(delay)
                logger.info(
                    "Retrying %s after transient HTTP %s in %.2fs (attempt %s/%s)",
                    service_tier,
                    exc.status_code,
                    delay,
                    attempt + 1,
                    self.settings.max_transient_attempts,
                )
                await anyio.sleep(delay)
