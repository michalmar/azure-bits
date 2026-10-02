from __future__ import annotations

from datetime import UTC, datetime
import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from .config import (
    BUNDLED_STANDARD_PRICES,
    BUNDLED_PRIORITY_PRICES,
    FLEX_GUIDE_URL,
    PRIORITY_GUIDE_URL,
    PRICE_SKUS,
    PRICING_API_URL,
    PRICING_PAGE_URL,
)


logger = logging.getLogger(__name__)
FLEX_MULTIPLIER = 0.5
PRICE_CACHE_SECONDS = 24 * 60 * 60


class PricingCatalog:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        currency: str = "USD",
        cache_seconds: int = PRICE_CACHE_SECONDS,
    ) -> None:
        self.http = http_client
        self.currency = currency
        self.cache_seconds = cache_seconds
        self._cached_at = 0.0
        self._cached: dict[str, Any] | None = None

    def _url(self) -> str:
        sku_filter = " or ".join(
            f"skuName eq '{sku}'" for tier in PRICE_SKUS.values() for sku in tier.values()
        )
        query_filter = f"productName eq 'Azure OpenAI GPT5' and ({sku_filter})"
        encoded_filter = quote(query_filter, safe="()'$=,")
        return (
            f"{PRICING_API_URL}?api-version=2023-01-01-preview"
            f"&currencyCode={self.currency}&$filter={encoded_filter}"
        )

    def _parse(self, payload: dict[str, Any]) -> dict[str, dict[str, float]]:
        items = payload.get("Items")
        if not isinstance(items, list):
            raise ValueError("Azure Retail Prices response did not include Items.")
        prices: dict[str, dict[str, float]] = {}
        for tier, skus in PRICE_SKUS.items():
            prices[tier] = {}
            for key, sku in skus.items():
                values = {
                    float(item["unitPrice"])
                    for item in items
                    if isinstance(item, dict)
                    and item.get("skuName") == sku
                    and item.get("currencyCode") == self.currency
                    and isinstance(item.get("unitPrice"), (int, float))
                }
                if len(values) != 1:
                    raise ValueError(
                        f"Expected one unique {self.currency} price for {sku}; found {sorted(values)}."
                    )
                prices[tier][key] = values.pop()
        return prices

    def _payload(
        self,
        standard: dict[str, float],
        priority: dict[str, float],
        *,
        source: str,
        warning: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        flex = {key: round(value * FLEX_MULTIPLIER, 8) for key, value in standard.items()}
        payload: dict[str, Any] = {
            "currency": currency or self.currency,
            "unit": "1M tokens",
            "standard": standard,
            "flex": flex,
            "priority": priority,
            "flexMultiplier": FLEX_MULTIPLIER,
            "source": source,
            "retrievedAt": datetime.now(UTC).isoformat(),
            "retailApiUrl": PRICING_API_URL,
            "pricingPageUrl": PRICING_PAGE_URL,
            "flexGuideUrl": FLEX_GUIDE_URL,
            "priorityGuideUrl": PRIORITY_GUIDE_URL,
            "meters": PRICE_SKUS,
        }
        if warning:
            payload["warning"] = warning
        return payload

    async def get(self, refresh: bool = False) -> dict[str, Any]:
        if not refresh and self._cached and time.monotonic() - self._cached_at < self.cache_seconds:
            return self._cached
        try:
            response = await self.http.get(self._url(), timeout=30)
            response.raise_for_status()
            prices = self._parse(response.json())
            result = self._payload(
                prices["standard"],
                prices["priority"],
                source="Azure Retail Prices API",
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Azure Retail Prices lookup failed: %s", exc)
            warning = (
                "Live pricing lookup failed; using the bundled USD pricing snapshot. "
                "Verify current rates before making purchasing decisions."
            )
            result = self._payload(
                dict(BUNDLED_STANDARD_PRICES),
                dict(BUNDLED_PRIORITY_PRICES),
                source="Bundled 2026-09-29 pricing snapshot",
                warning=warning,
                currency="USD",
            )
        self._cached = result
        self._cached_at = time.monotonic()
        return result


def calculate_cost(usage: dict[str, Any], prices: dict[str, float]) -> dict[str, Any]:
    details = usage.get("input_tokens_details")
    if not isinstance(details, dict):
        details = {}
    input_tokens = max(int(usage.get("input_tokens") or 0), 0)
    cached_tokens = max(int(details.get("cached_tokens") or 0), 0)
    cache_write_tokens = max(int(details.get("cache_write_tokens") or 0), 0)
    regular_input_tokens = max(input_tokens - cached_tokens - cache_write_tokens, 0)
    output_tokens = max(int(usage.get("output_tokens") or 0), 0)
    components = {
        "input": regular_input_tokens * prices["input"] / 1_000_000,
        "cachedInput": cached_tokens * prices["cachedInput"] / 1_000_000,
        "cacheWrite": cache_write_tokens * prices["cacheWrite"] / 1_000_000,
        "output": output_tokens * prices["output"] / 1_000_000,
    }
    return {
        "amount": round(sum(components.values()), 10),
        "components": {key: round(value, 10) for key, value in components.items()},
        "billableTokens": {
            "input": regular_input_tokens,
            "cachedInput": cached_tokens,
            "cacheWrite": cache_write_tokens,
            "output": output_tokens,
        },
    }
