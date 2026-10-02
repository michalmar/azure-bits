from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_ENDPOINT = "https://demo-swe.openai.azure.com"
DEFAULT_DEPLOYMENT = "gpt-5.6-sol"
DEFAULT_PRIORITY_DEPLOYMENT = "gpt-5.6-sol-priority"
MAX_PROMPT_LENGTH = 12_000
MAX_OUTPUT_TOKENS = 4_096
DATA_SCOPE = "https://cognitiveservices.azure.com/.default"
PRICING_API_URL = "https://prices.azure.com/api/retail/prices"
PRICING_PAGE_URL = "https://azure.microsoft.com/pricing/details/azure-openai/"
FLEX_GUIDE_URL = "https://learn.microsoft.com/azure/foundry/openai/how-to/flex-processing"
PRIORITY_GUIDE_URL = "https://learn.microsoft.com/azure/foundry/openai/concepts/priority-processing"

PRICE_SKUS = {
    "standard": {
        "input": "5.6 sol ShortCo Inp Std Gl",
        "cachedInput": "5.6 sol ShortCo Cd Inp Std Gl",
        "cacheWrite": "5.6 sol ShortCo Cd Wr Std Gl",
        "output": "5.6 sol ShortCo Opt Std Gl",
    },
    "priority": {
        "input": "5.6 sol ShortCo Inp PP Gl",
        "cachedInput": "5.6 sol ShortCo Cd Inp PP Gl",
        "cacheWrite": "5.6 sol ShortCo Cd Wr PP Gl",
        "output": "5.6 sol ShortCo Opt PP Gl",
    },
}

BUNDLED_STANDARD_PRICES = {
    "input": 4.0,
    "cachedInput": 0.4,
    "cacheWrite": 5.0,
    "output": 20.0,
}
BUNDLED_PRIORITY_PRICES = {
    "input": 8.0,
    "cachedInput": 0.8,
    "cacheWrite": 10.0,
    "output": 40.0,
}


@dataclass(frozen=True, slots=True)
class Settings:
    endpoint: str
    deployment: str
    priority_deployment: str
    request_timeout_seconds: float
    default_max_output_tokens: int
    pricing_currency: str
    max_transient_attempts: int

    @classmethod
    def from_env(cls) -> "Settings":
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
        if not endpoint.startswith("https://"):
            raise ValueError("AZURE_OPENAI_ENDPOINT must be an HTTPS URL.")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", DEFAULT_DEPLOYMENT).strip()
        if not deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT must not be empty.")
        priority_deployment = os.getenv(
            "AZURE_OPENAI_PRIORITY_DEPLOYMENT", DEFAULT_PRIORITY_DEPLOYMENT
        ).strip()
        if not priority_deployment:
            raise ValueError("AZURE_OPENAI_PRIORITY_DEPLOYMENT must not be empty.")
        timeout = float(os.getenv("FLEX_REQUEST_TIMEOUT_SECONDS", "900"))
        if timeout < 30 or timeout > 1800:
            raise ValueError("FLEX_REQUEST_TIMEOUT_SECONDS must be between 30 and 1800.")
        max_output_tokens = int(os.getenv("DEFAULT_MAX_OUTPUT_TOKENS", "800"))
        if not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"DEFAULT_MAX_OUTPUT_TOKENS must be between 1 and {MAX_OUTPUT_TOKENS}.")
        currency = os.getenv("PRICING_CURRENCY", "USD").upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("PRICING_CURRENCY must be a three-letter currency code.")
        max_transient_attempts = int(os.getenv("MAX_TRANSIENT_ATTEMPTS", "3"))
        if not 1 <= max_transient_attempts <= 5:
            raise ValueError("MAX_TRANSIENT_ATTEMPTS must be between 1 and 5.")
        return cls(
            endpoint=endpoint,
            deployment=deployment,
            priority_deployment=priority_deployment,
            request_timeout_seconds=timeout,
            default_max_output_tokens=max_output_tokens,
            pricing_currency=currency,
            max_transient_attempts=max_transient_attempts,
        )
